# Gromozeka — Service Integration Patterns

> **Audience:** LLM agents  
> **Purpose:** Complete reference for using CacheService, QueueService, LLMService, StorageService, RateLimiterManager, ProxyService, and STTService  
> **Self-contained:** Everything needed for service integration is here

---

## Table of Contents

1. [CacheService](#1-cacheservice)
2. [QueueService](#2-queueservice)
3. [LLMService](#3-llmservice)
4. [StorageService](#4-storageservice)
5. [RateLimiterManager](#5-ratelimitermanager)
6. [ProxyService](#6-proxyservice)
7. [STTService](#7-sttservice)
8. [Service Singleton Pattern](#8-service-singleton-pattern)
9. [StatsAggregationService](#9-statsaggregationservice)

---

## 1. CacheService

**File:** [`internal/services/cache/service.py:195`](../../internal/services/cache/service.py:195)  
**Import:** `from internal.services.cache import CacheService`

```python
# Get singleton instance
cache = CacheService.getInstance()

# MUST inject database before use (done by HandlersManager)
cache.injectDatabase(dbWrapper)

# Chat settings
chatSettings: ChatSettingsDict = await cache.getCachedChatSettings(chatId, ttl=3600)
cache.cacheChatSettings(chatId, settings)
cache.setChatSetting(chatId, key, value, userId=user.id)
cache.unsetChatSetting(chatId=chatId, key=key)

# Chat info
chatInfo: Optional[ChatInfoDict] = await cache.getChatInfo(chatId)
await cache.setChatInfo(chatId, chatInfo)

# Chat admins (synchronous methods with TTL parameter)
admins: Optional[Dict[int, Tuple[str, str]]] = cache.getChatAdmins(chatId, ttl=3600)
cache.setChatAdmins(chatId, admins)

# Permanent user memories (async, write-through cache; injected at message-arrival
# time by MessagePreprocessorHandler.injectMemories into EnsuredMessage.metadata.memories
# as compact IDs + warmed into the MEMORIES by-id cache)
permanentMemories: list[SingleMemoryDict] = await cache.getChatUserPermanentMemories(
    chatId=chatId, userId=userId, threadId=threadId
)
await cache.invalidateChatUserPermanentMemories(chatId=chatId, userId=userId, threadId=threadId)

# chat_users row + metadata (async, write-through; see ADR-015)
userInfo: Optional[ChatUserDict] = await cache.getChatUser(chatId=chatId, userId=userId)
# Accurate messages_count: callers needing a fresh count usually want the
# conditional-refresh helper (see ADR-015) rather than an unconditional refresh.
# spam handlers use SpamHandler._getUserInfoFreshIfMessagesLessThan(chatId, userId, threshold),
# which refreshes ONLY when the cached count is below the threshold (monotonic
# value at/above the threshold stays valid). A direct unconditional refresh is
# still available when truly required:
userInfo = await cache.getChatUser(chatId=chatId, userId=userId, refresh=True)
await cache.updateChatUser(chatId=chatId, userId=userId, username="@user", fullName="Name")
metadata: UserMetadataDict = await cache.getUserMetadata(chatId=chatId, userId=userId)
await cache.updateUserMetadata(chatId=chatId, userId=userId, metadata=metadata)  # full-dict replace, NO merge
cache.invalidateChatUser(chatId=chatId, userId=userId)  # sync; pops userInfo only, preserves permanentMemories

# Chat accessibility (cache-aside via getChatInfo; see "Chat accessibility tracking" below)
if await cache.isChatInaccessible(chatId):           # async, cache-aside (cheap on a hit)
    await cache.markChatActive(chatId)               # async; reads getChatInfo, writes via setChatInfo
await cache.markChatInaccessible(otherChatId)        # async; reads getChatInfo, writes via setChatInfo

# Default chat settings are handled by config/database, not CacheService
# Use config files in configs/ for defaults, or set per-chat via setChatSetting()
```

**`chat_users` row cache (ADR-015):** the `CHAT_USERS` namespace (keyed `f"{chatId}:{userId}"`, `MEMORY_ONLY`) holds both the `user_data` blob (`data` field) and the `chat_users` row (`userInfo` field, lazily loaded). `getChatUser` is an LRU read with DB fallback on miss; `updateChatUser`/`updateUserMetadata` are write-through. Single-row `(chatId, userId)` reads/writes in handlers MUST go through `self.cache.*` — not `self.db.chatUsers.*` — so the cache stays consistent.

**`messages_count` is best-effort stale** on a cached row: the column is incremented by a raw SQL `UPDATE` inside `ChatMessagesRepository.saveChatMessage` (`internal/database/repositories/chat_messages.py:158`), bypassing this cache. Callers needing an accurate count SHOULD prefer the conditional-refresh helper `SpamHandler._getUserInfoFreshIfMessagesLessThan(chatId, userId, threshold)` over a blanket `refresh=True` — it refreshes only when the cached count is strictly below the threshold (a monotonic at-or-above value stays valid), so established users don't pay a per-message DB hit. The two spam gates use it with gate-direction-appropriate thresholds (`checkSpam` `>=` passes the threshold unchanged; `markAsSpam` strict `>` passes `threshold + 1` to refresh the boundary case). A direct `getChatUser(..., refresh=True)` is still available when an unconditional refresh is genuinely required. `updateChatUser` skips the DB upsert when `username`/`full_name` are unchanged, so `updated_at` no longer refreshes on a no-op call; on a cache miss it leaves the cache cold (no warming re-read). `updateUserMetadata` performs a **full-dict replace with NO merge** — callers writing a nested sub-dict (e.g. `memoryRefinement`) must read-modify-write the whole metadata dict. See [`architecture.md`](architecture.md) ADR-015 for the full decision and the nested-write safety invariant.

**Key types from** [`internal/services/cache/types.py`](../../internal/services/cache/types.py):
- `HCChatCacheDict` — per-chat cache
- `HCChatUserCacheDict` — per-user-in-chat cache
- `UserDataType` / `UserDataValueType` — user data structures

### Chat accessibility tracking (cache-aside via `getChatInfo`)

CacheService exposes three async accessors that read/write the `chat_info.bot_status` column. There is **no** dedicated in-memory set and **no** dedicated repository method for accessibility any more — `bot_status` is read through the normal `getChatInfo` cache-aside path (in-memory `self.chats` cache first, DB on miss) and persisted through `setChatInfo`, which routes to `ChatInfoRepository.updateChatInfo(botStatus=...)`. The DB column remains the source of truth; the in-memory chat-info cache is the hot-path optimisation. Full design (binding decisions, recovery semantics, restart edge cases) and the divergence note for this cache-aside shape live in [`docs/design/chat-accessibility-tracking.md`](../design/chat-accessibility-tracking.md#implementation-divergence-2026-08-12).

| Member | Kind | Purpose |
|---|---|---|
| `async isChatInaccessible(chatId: int) -> bool` | async | Cache-aside check via `getChatInfo`. Returns `True` if the chat is unknown to the bot (fail-closed — treats a missing row as inaccessible) or its `bot_status == ChatBotStatus.INACCESSIBLE`; `False` otherwise. A cache hit is cheap (no DB I/O, no API call); a miss reads the DB through the normal `getChatInfo` path. Awaited at the top of `TheBot.getChatAdmins` to short-circuit the platform API call, and in the preprocessor recovery hook. |
| `async markChatInaccessible(chatId: int) -> bool` | async | Record that the bot is inaccessible in `chatId`. Reads `getChatInfo`; if the chat is not found, logs an error and returns `False`. Otherwise sets `bot_status = ChatBotStatus.INACCESSIBLE` and persists via `setChatInfo` (updates the in-memory cache + writes the DB through `updateChatInfo(botStatus=...)`). Called from the `getChatAdmins` failure catch sites. |
| `async markChatActive(chatId: int) -> bool` | async | Recover `chatId` to `ACTIVE`. Reads `getChatInfo`; if the chat is not found, logs an error and returns `False`. Otherwise sets `bot_status = ChatBotStatus.ACTIVE` and persists via `setChatInfo` (in-memory cache + DB). The return value is a best-effort signal; callers keep recovery logic idempotent. |

**No startup seeding hook.** Because accessibility is looked up cache-aside through the same `getChatInfo` path the rest of the chat cache uses, there is no separate `injectDatabase` warm-up step and no `getInactiveChatIds()`/`setChatBotStatus()` repository method — those were removed when the in-memory `_inaccessibleChats` set was dropped. The first `isChatInaccessible(chatId)` for a chat that is not yet in the in-memory cache simply falls through to a DB read, same as any other `getChatInfo` miss.

**Post-refresh nuance:** after the periodic (~12 h) chat-info cache refresh, a cache entry may briefly lack a `bot_status` field, in which case `isChatInaccessible` returns `False` for a chat that is actually `INACCESSIBLE` until the next `getChatAdmins` call re-marks it. This is self-healing — the DB value stays correct and chat-list queries filter on the DB column, so the only effect is a single redundant `getChatAdmins` probe. See the design doc divergence section linked above.

**IMPORTANT:** `CacheService.injectDatabase(db)` MUST be called before any cache operations. This is done automatically by `HandlersManager`, so only call it manually in tests

---

## 2. QueueService

**File:** [`internal/services/queue_service/service.py:56`](../../internal/services/queue_service/service.py:56)  
**Import:** `from internal.services.queue_service import QueueService, makeEmptyAsyncTask`

```python
queue = QueueService.getInstance()

# Add background task (fire-and-forget)
parseTask = asyncio.create_task(some_coroutine())
await queue.addBackgroundTask(parseTask)

# Add delayed task (runs at specific time)
await queue.addDelayedTask(
    delayedUntil=time.time() + 3600,
    function=DelayedTaskFunction.SEND_MESSAGE,
    kwargs={"chat_id": 123, "text": "Hello"}
)

# Register a handler for delayed tasks
queue.registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, my_handler_fn)

# Create empty/no-op task
emptyTask: asyncio.Task = makeEmptyAsyncTask()
```

**`DelayedTaskFunction` enum** (from `internal/services/queue_service/types.py`):
- `SEND_MESSAGE` — scheduled message sending
- `DELETE_MESSAGE` — scheduled message deletion
- `CRON_JOB` — periodic cron tasks
- `DO_EXIT` — cleanup on exit
- `STATS_PAGES_CLEANUP` — one-shot per-page deletion of a generated stats page: `StatsHandler` registers the handler (and schedules one such task per successful page generation) when `[stats.pages] enabled = true`; `kwargs` carry `pageId` + the resolved delete argv; single attempt, no reschedule. A pending task with no registered handler (stats disabled) hits the queue's no-handler path and is re-delayed 60 s in memory for the process lifetime, but the DB row is marked done on first firing — after restart the task is gone; orphaned page file is the accepted R13 outcome.

---

## 3. LLMService

**File:** [`internal/services/llm/service.py:144`](../../internal/services/llm/service.py:144)  
**Import:** `from internal.services.llm import LLMService`
**Optional import:** `from lib.stats.stats_storage import StatsStorage, NullStatsStorage` (for tool call statistics, gated by `[stats]` enabled)

```python
llmService = LLMService.getInstance()

# Generate text response
result: ModelRunResult = await llmService.generateText(
    messages,                    # List[ModelMessage]
    chatId=chatId,               # mandatory int: stats consumerId + rate limiting
    chatSettings=chatSettings,
    modelKey=ChatSettingsKey.CHAT_MODEL,
    fallbackKey=ChatSettingsKey.CHAT_FALLBACK_MODEL,
    doRateLimit=True,            # optional; False = skip limiter, keep attribution
)

if result.status == ModelResultStatus.FINAL:
    responseText = result.resultText

# Condense long conversation context.
# ALWAYS returns a (messages, coverageMap) tuple. The first element is the
# condensed message list (head + summaries + tail); the second is a
# Dict[int, CondensingDict] keyed by body-index -> fully-populated
# CondensingDict (coverage metadata computed inside via generateCondensingDict
# reading ModelMessage.source). Empty dict when no condensing occurs.
condensed, coverageMap = await llmService.condenseContext(
    messages,
    model=llmModel,
    keepFirstN=1,
    keepLastN=1,
    maxTokens=maxTokens,
    condensingModel=condensingModel,
    condensingPrompt=condensingPrompt,
    condensingSystemPrompt=condensingSystemPrompt,
)
# coverageMap values are the CondensingDicts to persist (Path A extends its
# condensedThread list; Path B merges them via mergeCondensingDicts).

# Path C (generateTextViaLLM) unpacks the tuple and ignores coverage:
#   _messages, _ = await self.condenseContext(...)

# Register LLM tool — always use ToolName.XXX (never raw string)
llmService.registerTool(
    name=ToolName.EXAMPLE,
    description="Search the web",
    parameters=[
        LLMFunctionParameter("query", "Search query", LLMParameterType.STRING, required=True),
    ],
    handler=mySearchHandler,  # async def mySearchHandler(param1, ...) -> dict
)

# Inject stats storage for tool call statistics (optional, gated by [stats] enabled)
llmService.injectStatsStorage(toolStatsStorage)  # or None for NullStatsStorage default
```

**Rule:** Always use a `ToolName` member (from `internal.bot.constants`) for the `name=` argument. See the [add-handler skill](../../.agents/skills/add-handler/SKILL.md) Step 5 for the full registration workflow.

**`chatId` / `doRateLimit` semantics (all generation methods):** `chatId` is a **mandatory `int`** on `generateText` / `generateStructured` / `generateImage` / `generateEmbedding` / `generateTextViaLLM`. It always threads `consumerId=str(chatId)` into the model call for `llm_request` stats attribution (merged into `labels["consumer"]` by `StatsStorage`; chats are never conflated into `__global__`). Rate limiting is controlled independently by the keyword-only `doRateLimit: bool = True` flag: background/system-initiated work (embedding backfill, memory refinement) passes the **real** chat id with `doRateLimit=False` — the per-chat hot-path limiter is skipped while attribution is preserved. `condenseContext` takes a stats-only keyword-only `consumerId: Optional[str]` (the condensing path never rate-limits); `generateTextViaLLM` threads it automatically for every per-round condense.

**`generateTextViaLLM` — tool-execution loop:**

The multi-turn variant of `generateText` that executes tool calls requested by the LLM until a final text response is produced. Resolves primary/fallback models, condenses context, detects tool calls (including text-embedded ones), executes them, and feeds results back. Supports an optional streaming `callback` for intermediate results.

```python
result: ModelRunResult = await llmService.generateTextViaLLM(
    messages,                    # Sequence[ModelMessage]
    chatId=chatId,
    chatSettings=chatSettings,
    modelKey=ChatSettingsKey.CHAT_MODEL,
    fallbackModelKey=ChatSettingsKey.FALLBACK_MODEL,
    useTools=True,               # all tools; see per-tool dict form below
    extraData=extraData,         # passed to tool handlers and callback
    callback=processIntermediateMessages,  # optional async callback
)
```

**`useTools` parameter — per-tool enable/disable** (type `UseToolsType`, re-exported from [`internal.services.llm`](../../internal/services/llm/__init__.py)):

- `True` — enable **all** registered tools.
- `False` — disable all tools (default).
- `dict[str, bool]` — enable/disable individual tools by name. The special key defined by `TOOLS_DEFAULT_DICT_KEY` (defined in [`internal/services/llm/constants.py`](../../internal/services/llm/constants.py) and re-exported from [`internal.services.llm`](../../internal/services/llm/__init__.py)) controls every tool not explicitly listed (defaults to `False` when absent). Unknown tool names are logged as warnings (`logger.warning`) and ignored.

**Tool names** should be specified via members of the `ToolName` StrEnum ([`internal.bot.constants.ToolName`](../../internal/bot/constants.py)) — one member per registered tool (e.g. `ToolName.RUN_PYTHON`, `ToolName.WEB_SEARCH`). Because `ToolName` is a `StrEnum`, members serialize to the exact string `registerTool(name=...)` expects, so raw string literals (e.g. `"run_python"`) also work; the enum is recommended for type safety and greppability.

```python
from internal.bot.constants import ToolName
from internal.services.llm import TOOLS_DEFAULT_DICT_KEY

# Enable only the sandbox tools; disable everything else:
useTools={TOOLS_DEFAULT_DICT_KEY: False, ToolName.RUN_PYTHON: True, ToolName.SANDBOX_LIST_FILES: True}

# Enable all tools except one:
useTools={TOOLS_DEFAULT_DICT_KEY: True, ToolName.SANDBOX_SEND_FILE: False}
```

Resolution happens in the private `_resolveTools(useTools)` method, which returns the filtered `List[LLMToolFunction]` sent to the model. The execution guard also uses this filtered set: if the LLM requests a dict-disabled tool, the loop returns an error listing only the **actually available** tool names (not the full registry), so the model is not tempted to retry a disabled tool.

**Tool call statistics:** When `injectStatsStorage` is called with a `StatsStorage` instance (constructed in `main.py` gated by `[stats] enabled`), each tool dispatch in the `generateTextViaLLM` loop records an `llm_tool_call` event with stats `tool_call_count=1` (every dispatch), `tool_exec_count=1` (**executed-only** — present only when the tool actually executed, not merely was requested), `elapsed_time` (seconds, float), and `is_error` (0/1; `1` when the dict result has `done is False` **or** a truthy `error`/`errorMessage` field). Labels are `user_id` (from `extraData["ensuredMessage"].sender.id`) and `toolName`. The `consumerId` is the chat ID from `ensuredMessage.recipient.id`. Recording is skipped when `ensuredMessage` is absent. Tools that raise exceptions propagate unrecorded (per the never-raise contract).

**`maxRounds` — tool-calling round budget** (`Optional[int]`, default `DEFAULT_MAX_ROUNDS` = 32, defined in [`internal/services/llm/constants.py`](../../internal/services/llm/constants.py) and re-exported from [`internal.services.llm`](../../internal/services/llm/__init__.py)): bounds the number of rounds the model may call tools before the budget is considered exhausted. Must be a non-negative integer or `None` (negative raises `ValueError`). Once `roundN >= maxRounds`: tool schemas are dropped (`tools=[]`), the `filteredToolNames` execution allowlist is cleared (so even healed tool calls cannot execute), tool-call healing is disabled, a steering directive is folded into the leading system message (or a `user` message when none exists), and the loop is hard-bounded to a single additional round — terminating regardless of the model's response. On any post-budget termination `ModelRunResult.roundLimitHit` is set to `True` and a service-level `logger.warning` fires, so callers can detect that the result may be incomplete. A fallback answer is synthesized **only** when the model returned no usable text and the status is `FINAL` or a post-budget `TOOL_CALLS` (a glitching model that ignored the empty `tools=[]`); genuine error statuses (`ERROR` / `CONTENT_FILTER` / `UNKNOWN`) propagate with their original status and empty text so callers can detect the failure. Pass `maxRounds=None` to disable the limit (unlimited rounds, legacy behavior); `maxRounds=0` drops tools on the very first call.

**Generate structured (JSON-Schema) output:**
```python
result: ModelStructuredResult = await llmService.generateStructured(
    prompt,                      # Sequence[ModelMessage]
    schema,                      # Dict[str, Any] — JSON Schema
    chatId=chatId,
    chatSettings=chatSettings,
    modelKey=ChatSettingsKey.CHAT_MODEL,
    fallbackKey=ChatSettingsKey.CHAT_FALLBACK_MODEL,
    schemaName="response",       # optional; identifies schema to provider
    strict=True,                 # optional; request strict schema enforcement
    doDebugLogging=True,         # optional
)

if result.status == ModelResultStatus.FINAL:
    parsedDict = result.data     # Optional[Dict[str, Any]]
```

**`generateStructured` full signature:**
```python
async def generateStructured(
    self,
    prompt: Sequence[ModelMessage],
    schema: Dict[str, Any],
    *,
    chatId: int,
    chatSettings: ChatSettingsDict,
    modelKey: Union[ChatSettingsKey, AbstractModel, None],
    fallbackKey: Union[ChatSettingsKey, AbstractModel, None],
    schemaName: str = "response",
    strict: bool = True,
    doDebugLogging: bool = True,
    doRateLimit: bool = True,
) -> ModelStructuredResult
```

`generateStructured` mirrors `generateText` end-to-end: it resolves
the primary and fallback models from `chatSettings`, applies rate
limiting unless `doRateLimit=False`, then delegates to
  `AbstractModel.generateStructured` (with `fallbackModels` parameter). Key differences:

- Raises `NotImplementedError` if **neither** the primary nor the
  fallback model has `support_structured_output = true` in its config.
- Auto-swaps primary↔fallback when only the fallback supports the
  capability, avoiding a guaranteed `NotImplementedError` on the
  primary call.
- No auto-injected JSON hint: callers should include a system message
  hinting at JSON output; this wrapper will not inject one.

**Import** `ModelStructuredResult` from `lib.ai`:
```python
from lib.ai import ModelStructuredResult
```

**`ModelResultStatus` values** (from [`lib/ai/models.py`](../../lib/ai/models.py); see `ERROR_STATUSES` frozenset there for the failure subset):
- `FINAL` — complete, final response (the success case callers usually check)
- `TRUNCATED_FINAL` — truncated but still considered final (text usable)
- `TOOL_CALLS` — model is requesting tool calls (handled inside `generateTextViaLLM`'s loop)
- `ERROR` — execution error
- `CONTENT_FILTER` — response filtered by provider content policy
- `UNSPECIFIED` / `PARTIAL` / `UNKNOWN` — other non-final / failure states

There is no `TIMEOUT` and no `EMPTY` status. Callers wanting "did we get usable text?" should check `status == ModelResultStatus.FINAL` (or also accept `TRUNCATED_FINAL`); callers wanting "did it fail?" should check `status in ERROR_STATUSES`.

**IMPORTANT:** `LLMService` has an `initialized` guard (singleton init runs once). Never check `initialized` directly in new code

**Proxy config flow:** Proxy configuration flows from `ConfigManager.getProxyConfig()` → `ProxyHelper.getInstance().setGlobalProxyConfig()` in `main.py`. Services create `ProxyConfig` via `ProxyConfig.fromServiceConfig()` with their service-level config, then call `ProxyConfig.getCombined()` to merge with the global config, and `ProxyConfig.toKwargs()` to get `httpx2.AsyncClient` kwargs (httpx2 is aliased as `httpx` process-wide via `httpx2.alias_httpx()` — see [`architecture.md`](architecture.md) ADR-021; source reads `httpx.AsyncClient`). `LLMManager` stores a `proxyConfig` attribute. `BasicOpenAIProvider._initClient()` creates a custom `httpx2.AsyncClient` for the OpenAI SDK. Image download and OpenRouter `listRemoteModels()` also resolve proxy.

### Message reconstruction: `ModelMessage.fromDictList`

There is no `internal/services/llm/utils.py` and no standalone `reconstructMessages` helper — message reconstruction from serialised request data is a classmethod on `ModelMessage` itself:

- `ModelMessage.fromDictList(dictList: List[Dict[str, Any]]) -> List[ModelMessage]` (defined in [`lib/ai/models.py`](../../lib/ai/models.py)). Accepts dicts with `role`, `content`, optional `tool_calls` and `tool_call_id`. Used by:
  - `scripts/run_llm_debug_query.py` — CLI debug replay (`entry["request"]` → `ModelMessage.fromDictList`).
  - `DevCommandsHandler.llmReplayCommand` — the `/llm_replay` bot command.
  - `LLMMessageHandler` and `ResenderHandler` for the same purpose on the hot path.

---

## 4. StorageService

**File:** [`internal/services/storage/service.py:24`](../../internal/services/storage/service.py:24)  
**Import:** `from internal.services.storage import StorageService`

```python
storage = StorageService.getInstance()

# MUST inject config before use (done by HandlersManager)
storage.injectConfig(configManager)

# Store binary data
storage.store("my/key.png", imageBytes)

# Retrieve data
data: Optional[bytes] = storage.get("my/key.png")

# Check existence
exists: bool = storage.exists("my/key.png")

# Delete
storage.delete("my/key.png")

# List keys
keys: List[str] = storage.list(prefix="attachments/", limit=100)
```

**Backends:** `null` (no-op), `fs` (filesystem), `s3` (AWS S3/compatible)

**IMPORTANT:** `StorageService.injectConfig(configManager)` MUST be called before any storage operations. This is done automatically by `HandlersManager`

---

## 5. RateLimiterManager

**File:** [`lib/rate_limiter/manager.py:57`](../../lib/rate_limiter/manager.py:57)  
**Import:** `from lib.rate_limiter import RateLimiterManager`

```python
manager = RateLimiterManager.getInstance()

# Apply rate limit for a named queue
# Blocks if over limit; returns True when applied
applied: bool = await manager.applyLimit("yandex-search")

# Bounded waiting: returns False instead of sleeping when the required
# wait exceeds `timeout` seconds (slot not consumed); also False on
# internal failure (no limiter registered, limiter error)
applied = await manager.applyLimit("yandex-search", timeout=30)
if not applied:
    ...  # limit saturated — degrade gracefully

# Get stats
stats = manager.getStats("yandex-search")
# Returns: {"requestsInWindow": N, "maxRequests": N, "utilizationPercent": N, ...}
```

**Config in TOML:**
```toml
[ratelimiter.ratelimiters.<name>]
type = "SlidingWindow"
[ratelimiter.ratelimiters.<name>.config]
windowSeconds = 5
maxRequests = 5

[ratelimiter.queues]
yandex-search = "<limiter-name>"
openweathermap = "<limiter-name>"
```

**Diagnostics:** `manager.dumpAllStats()` iterates every registered limiter and queue, **returning** a `List[RateLimiterStatsEntry]` (one entry per queue with keys `limiter`, `queue`, `requestsInWindow`, `maxRequests`, `windowSeconds`, `utilizationPercent`). It does not log the results itself — the caller logs them. Failures are isolated per queue (a single bad queue is logged as a warning and skipped). `HandlersManager._dumpAllState()` calls this during shutdown and logs each returned entry at INFO via `utils.jsonDumps(entry, indent=2)` (see [handlers.md §5](handlers.md#shutdown-state-dump)).

---

## 6. ProxyService

**File:** [`internal/services/proxy/service.py:23`](../../internal/services/proxy/service.py:23)
**Import:** `from internal.services.proxy import ProxyService`

```python
proxyService = ProxyService.getInstance()

# Initialize (called once from main.py; this calls setGlobalProxyConfig internally)
proxyService.initialize(configManager.getProxyConfig(), loop=loop)

# Resolve proxy for a service (replaces direct ProxyConfig.fromServiceConfig)
proxyConfig = proxyService.resolveProxy(serviceConfig, "my-service")
```

**Key methods:**

| Method | Returns | Purpose |
|---|---|---|
| `initialize(proxyConfigDict, loop)` | `None` | Idempotent init. Calls `ProxyHelper.setGlobalProxyConfig()` with the supplied dict, creates `ProxyLifecycle` for the global proxy if a lifecycle section is present, registers CRON_JOB/DO_EXIT handlers. Global proxy start command runs immediately via the shared event loop (`loop.run_until_complete()`). |
| `resolveProxy(serviceConfig, serviceLabel)` | `ProxyConfig` | Wraps `ProxyConfig.fromServiceConfig()`. Creates a `ProxyLifecycle` if the service config has a `proxy.lifecycle` sub-section. Deduplicates by `serviceLabel`. |

**`ProxyLifecycle`** (non-singleton, one per proxy config):

| Method | Returns | Purpose |
|---|---|---|
| `start()` | `None` | Execute the `start-command` via `asyncio.create_subprocess_exec` (fire-and-forget). Sets `_started` flag. |
| `stop()` | `None` | Execute the `stop-command`. |
| `restart()` | `None` | Execute `restart-command` if present, else `stop()` + `start()` sequentially. |
| `healthCheck()` | `bool` | Run health check (URL GET or command). Returns `True` if healthy. |
| `onCronTick()` | `None` | Called by CRON_JOB handler. Runs health check at configured interval; triggers restart on failure. |
| `onExit()` | `None` | Called by DO_EXIT handler. Stops the proxy process gracefully. |
| `started` | `bool` | Read-only property. `True` if the proxy process has been started. |

**Singleton reset in tests:**
```python
@pytest.fixture(autouse=True)
def resetProxyServiceSingleton():
    """Reset ProxyService singleton for clean test state"""
    from internal.services.proxy import ProxyService
    ProxyService._instance = None
    yield
    ProxyService._instance = None
```

---

## 7. STTService

**File:** [`internal/services/stt/service.py`](../../internal/services/stt/service.py)  
**Import:** `from internal.services.stt import STTService, STTOutcome`

`STTService` is a **stateless** singleton that owns the STT provider lifecycle (construction, proxy resolution, `aclose()`) and the never-raise transcription entry. It mirrors `ProxyService` exactly: class-level `_instance` / `_lock`, `getInstance()`, `hasattr(self, 'initialized')` guard, separate `initialize(...)`. **It does NOT touch the database** — no row read, insert, cache, claim, persist, or reclaim. The full `media_attachments` row lifecycle (read / cache-hit short-circuit / claim / persist the outcome via plain `updateMediaAttachment` / terminalize) is owned by the **`BaseBotHandler._processMediaV2` STT branch + its `_transcribeMedia` background task** in [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py) (see [`docs/archive/design/stt-next-steps.md`](../archive/design/stt-next-steps.md) §2). Single attachments have no concurrent writes, so last-write semantics via `updateMediaAttachment` are sufficient — there is no CAS.

**Status (2026-08-03):** implemented, tested, and **wired into `BaseBotHandler._processMediaV2`** — the `_transcribeMedia` background task consumes `STTService.getInstance().transcribeMedia(data, chatId=...)` (the bytes are downloaded synchronously inside `_processMediaV2` and passed in as `data`) and terminalizes the row via `updateMediaAttachment`. The feature remains **DEFAULT-OFF** — all four gates (`[stt] enabled = false` config default + eligible media type + the per-chat `PARSE_ATTACHMENTS` and `TRANSCRIBE_MEDIA` settings, both default `false`) must be satisfied before any media is transcribed.

> **v1.1 (gate-3 Object-Storage routing + gate-4 statistics) — implemented.** See [`docs/design/stt-v1.1.md`](../design/stt-v1.1.md) for the authoritative design. gate-3: the Yandex provider now routes clips whose extracted payload ≥ `[stt].max-inline-bytes` through a co-located `lib/stt/providers/yandex_object_storage.py` helper (boto3, hard import) and submits via the `uri` field; over-threshold + Object-Storage-disabled → `SOURCE_TOO_LARGE`, upload failure → the new `OBJECT_STORAGE_ERROR`. gate-4: per-transcription stats are recorded best-effort in the base `AbstractSTTProvider._recordStats` (template-method refactor — timing + recording in the base `transcribe`, hoisted from the Yandex provider; mirrors `lib/ai`'s `_recordAttemptStats`; reuses `DatabaseStatsStorage` with `eventType="stt_request"`, no new table/migration), gated by the global `[stats].enabled` flag. STT stats use a separate `[stats].stt-stats-data-source` config key (independent from `llm-stats-data-source`). The `lib/stt` dependency firewall (zero `internal.*` imports) is intact — boto3 is an external dependency. No service-layer Object-Storage client and no sweep task; leaked-object reclamation is delegated to a Yandex bucket lifecycle rule.

> **Yandex mono speaker attribution — implemented.** `[stt].force-mono = false` is provider-owned and forwarded generically as `forceMono`. Enabling it makes Yandex advertise mono-only input formats, so compatible multi-channel input is downmixed/re-encoded; compatible mono input still passes through. Regardless of that option, final mono `ExtractedAudio` causes both inline and Object-Storage submissions to request speaker labeling. The service preserves the provider result: generic opaque, recording-local `attributionTag` values render as `[Speaker#<tag>]` for `SPEAKER` results, while `CHANNEL` results render `[Ch#<tag>]` only for multiple tags. See the authoritative [`lib-stt-v1.md`](../design/lib-stt-v1.md).

```python
from internal.services.stt import STTService, STTOutcome

# Initialize (called once from main.py AFTER proxy + rate-limiter init,
# BEFORE the bot application). NO database argument:
STTService.getInstance().initialize(configManager)

# Cheap gate check before any per-message work (handlers call this):
if not STTService.getInstance().isEnabled():
    return HandlerResultStatus.NEXT

# Stateless transcription entry (NEVER raises except asyncio.CancelledError).
# The handler supplies the already-downloaded raw bytes:
outcome: STTOutcome = await STTService.getInstance().transcribeMedia(
    audioBytes, chatId=chatId
)
# outcome.success is True when a transcript was produced.
# outcome.description: the formatted transcript when success is True ("" when
#   NO_SPEECH — the thin formatter uses the result attribution role: [Speaker#<tag>]
#   for SPEAKER, [Ch#<tag>] only for multi-tag CHANNEL); None on failure.
# outcome.errorCode: an STTErrorCode when success is False; None otherwise.

# Shutdown (main.py Step 2.5, best-effort try/except, after LLM close,
# before DB close):
await STTService.getInstance().aclose()
```

### `transcribeMedia` — the stateless pipeline

**Signature:** `async def transcribeMedia(self, data: bytes, *, chatId: int) -> STTOutcome` (since 2026-08-23 `chatId` is a mandatory `int` — the old `Optional[int]` branch that skipped the per-chat limiter and dropped stats attribution on `None` was removed; every transcription is attributed to its chat).

This is a **thin, stateless** entry (ADR-020 decision 1). It performs no DB I/O. Admission is **unbounded** — there is no `asyncio.timeout` around the semaphore; the **handler bounds the originating turn** (via its pipeline timeout).

**Never-raise boundary:** `transcribeMedia` is the FINAL never-raise boundary for the STT feature. Every failure path returns an `STTOutcome(FAILED, …)` + a structured log; only `asyncio.CancelledError` propagates. `provider.stt(data)` (the `lib/stt` never-raise entry) never raises either, so `STTService` is the layer that converts every outcome into a typed `STTOutcome` for the handler to persist.

**Pipeline:**

1. **`STT_DISABLED`** — early return when `not self._enabled` (i.e. `[stt] enabled = false`).
2. **`SOURCE_TOO_LARGE`** — early return when `len(data) > self._maxSourceBytes` (source bytes are caller-supplied — bounding is post-download; `max-source-bytes` default is 1 GiB).
3. **Rate limiters** — per-chat (`chat-ratelimiter-queue`, keyed by `str(chatId)`) then global (`global-ratelimiter-queue`), applied when configured. (Duration bounding is the handler's job — see ADR-020 decision 3.)
4. **`async with self._semaphore`** — concurrency limiter (`max-concurrency` size). **No `asyncio.timeout`** (admission is unbounded; the handler bounds the turn).
5. **`await self._provider.stt(data)`** — the `lib/stt` provider's extract + transcribe never-raise entry (ADR-020 decision 2). Yandex requests speaker labeling for final mono extracted audio; an unexpected raise is caught defense-in-depth → `FAILED` + `PROVIDER_ERROR`.
6. **`_mapOutcome`** — `FINAL`/`NO_SPEECH` → `success=True` + `formatTranscript(result)` (the thin formatter uses generic tags plus the result role: `[Speaker#<tag>]` for `SPEAKER`, `[Ch#<tag>]` only for multi-tag `CHANNEL`; equal timestamps render once; `NO_SPEECH` yields `success=True` with `description=""`); `ERROR` → `success=False` + the provider's `errorCode`.
7. Return the `STTOutcome`.

A broad outer `except Exception` (never-raise boundary) catches anything else → `FAILED` + `PROVIDER_ERROR` (the service's catch-all fallback; structured logs distinguish service-caught vs provider-returned `PROVIDER_ERROR`).

### `STTErrorCode` ownership

The shared [`STTErrorCode`](../../lib/stt/models.py) enum (9 members as of v1.1 — `OBJECT_STORAGE_ERROR` was added) is the stable failure vocabulary, but its members are produced at different layers:

- **Service-produced** (produced ONLY by `STTService`): `STT_DISABLED`. `SOURCE_TOO_LARGE` is produced by the service (source-byte cap, `len(data) > maxSourceBytes`) **and** as of v1.1 also surfaced by the Yandex provider when the *extracted* payload ≥ `max-inline-bytes` and Object Storage is disabled (see [`docs/design/stt-v1.1.md`](../design/stt-v1.1.md) §4.2/§4.5). (`PROVIDER_ERROR` is also produced by the service as the catch-all fallback for unexpected exceptions — structured logs distinguish a service-caught fallback from a provider-returned `PROVIDER_ERROR`.)
- **Provider-produced** (returned inside a `TranscriptionResult(ERROR, …)` from `provider.stt()`): `NO_AUDIO`, `PROVIDER_ERROR`, `PROTOCOL_ERROR`, and as of v1.1 `SOURCE_TOO_LARGE` (over inline threshold without Object Storage) + `OBJECT_STORAGE_ERROR` (Object-Storage upload failure before submit).
- **Reserved / partially-produced at the handler layer** (not produced by the service or provider): `SOURCE_SIZE_UNKNOWN`, `DOWNLOAD_ERROR`, `DURATION_EXCEEDED`. The bounded-download platform extension that would have produced `SOURCE_SIZE_UNKNOWN` was **dropped** (user decision 2026-08-03 — the wired `_transcribeMedia` task uses the existing unbounded `downloadAttachment`); `DOWNLOAD_ERROR` is emitted only as a structured log label by `_transcribeMedia` when `downloadAttachment` returns `None` (it is not persisted — there is no `errorCode` column); `DURATION_EXCEEDED` remains vocabulary-only (no duration gating in v1). These codes stay reserved on the enum as the stable failure vocabulary.

See [ADR-020](architecture.md#adr-020-sttservice--synchronous-stateless-stt-service-and-dependency-firewall) and [`docs/design/lib-stt-v1.md`](../design/lib-stt-v1.md) §4 for the full raise/return contract.

### Lifecycle & proxy injection

- **`initialize(configManager, statsStorage=None)`** (NO `database` arg) — reads `[stt]`; when `enabled = false` (the default) the provider stays `None` and the service is a no-op. When `enabled = true`, the service validates ONLY the provider name via `STT_PROVIDERS_MAP`; the chosen provider's constructor (e.g. `YandexSpeechKitProvider.__init__`) owns cred / unresolved `${...}`-placeholder / cap-positivity / cross-field (`maxPollIntervalSeconds ≥ pollIntervalSeconds`) validation and may raise `ValueError` (propagated). `ProxyService.resolveProxy(sttConfig, "stt")` `ValueError`s are also propagated. Idempotent. The optional `statsStorage` (v1.1 gate-4) is forwarded to the provider constructor; a `DatabaseStatsStorage(eventType="stt_request", dataSource=<from [stats].stt-stats-data-source>)` is constructed via the `StatsAggregationService` factory when `[stats].enabled = true` (the global stats flag; `main.py` wires it) and `None` is passed otherwise → provider defaults to `NullStatsStorage` (no-op). STT stats use their own `[stats].stt-stats-data-source` config key (independent from `llm-stats-data-source`); the enabled gate is the global `[stats].enabled` flag (no STT-specific flag).
- **Proxy firewall (ADR-020 decision 4):** `STTService` resolves the proxy and **injects** it into the provider; it never resolves a proxy itself inside `lib/stt`, and `lib/stt` never imports `internal.*`.
- **Construction order in `main.py`:** `STTService.getInstance().initialize(configManager)` runs AFTER proxy + rate-limiter init, BEFORE the bot application.
- **`aclose()`** — best-effort close of the provider's persistent HTTP client. Called from `main.py` shutdown Step 2.5 (after LLM close, before DB close), wrapped in `try/except`. Never raises.
- **`isEnabled()`** — cheap gate; returns `_enabled`. Handlers should call this before doing any per-message STT work.

### Integration-boundary dataclass

`STTOutcome` is a frozen, slot dataclass re-exported from [`internal.services.stt`](../../internal/services/stt/__init__.py). (`STTMediaRequest` was REMOVED in the 2026-08-02 simplification — `transcribeMedia` now takes raw `bytes` + a `chatId` keyword.)

| Dataclass | Field | Type | Notes |
|---|---|---|---|
| `STTOutcome` | `success` | `bool` | `True` when a transcript was produced |
| | `description` | `Optional[str]` | Formatted transcript when `success is True` (`""` for `NO_SPEECH`); `None` when `success is False` |
| | `errorCode` | `Optional[STTErrorCode]` | Present iff `success is False` |

**Database:** NO migration, and the service itself does NO DB I/O. The `BaseBotHandler._processMediaV2` STT branch + its `_transcribeMedia` background task own the `media_attachments` row lifecycle (download synchronously inside `_processMediaV2`, then read/cache/claim/persist/terminalize via plain `updateMediaAttachment` — single attachments have no concurrent writes, so last-write semantics suffice; there is no CAS); the service just returns an `STTOutcome`. See [`database.md`](database.md) (media attachments) and [ADR-020](architecture.md#adr-020-sttservice--synchronous-stateless-stt-service-and-dependency-firewall).

**See also:** [`docs/design/media-transcription-stt-v1.md`](../design/media-transcription-stt-v1.md) (parent product decisions D1–D8), [`docs/archive/design/stt-next-steps.md`](../archive/design/stt-next-steps.md) (integration roadmap), [`docs/design/lib-stt-v1.md`](../design/lib-stt-v1.md) (`lib/stt` library spec).

---

## 8. Service Singleton Pattern

All services use this pattern. When MODIFYING a service, preserve the singleton structure

```python
import threading
from typing import Optional


class MyService:
    """Singleton service"""

    _instance: Optional["MyService"] = None
    _lock: threading.RLock = threading.RLock()

    def __new__(cls) -> "MyService":
        """Create or return singleton instance

        Returns:
            The singleton MyService instance
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize service once"""
        if hasattr(self, "initialized"):
            return
        self.initialized: bool = True
        # ... actual init ...

    @classmethod
    def getInstance(cls) -> "MyService":
        """Get the singleton instance

        Returns:
            The singleton MyService instance
        """
        return cls()
```

**Rules for singletons:**
- Always use `getInstance()` — never `MyService()` directly
- Thread safety via `RLock`
- `hasattr(self, "initialized")` guard prevents double-init
- In tests, reset with `MyService._instance = None` (use autouse fixture)

---

## 9. StatsAggregationService

**File:** [`internal/services/stats/service.py`](../../internal/services/stats/service.py)  
**Import:** `from internal.services.stats import StatsAggregationService`

`StatsAggregationService` is a **singleton coordinator** for periodic stats aggregation and event retention. It owns the storage factory + registry — the single construction seam for stats storages — and registers a handler on the shared CRON_JOB 60-second tick, gated in-memory by a configurable interval. Mirrors `STTService` exactly: class-level `_instance` / `_lock`, `getInstance()`, `hasattr(self, 'initialized')` guard, separate `initialize(...)`.

**Status (2026-08-17):** implemented, tested, and **wired into `main.py`** — `StatsAggregationService.getInstance().initialize(configManager, database)` is called once (synchronous) before the first storage factory call. The factory `createStatsStorage(eventType, dataSource)` reads `[stats] enabled` itself: disabled returns an **unregistered** `NullStatsStorage` (registry stays empty, handler no-ops every tick); enabled constructs `DatabaseStatsStorage` and registers it in the registry keyed by eventType. `main.py` registers **all five storages** (llm_request, llm_tool_call, stt_request, message, command) synchronously, **registered synchronously during GromozekBot.__init__, before bot startup / before the first CRON tick in default deployments (no global proxy lifecycle)** — no storage is constructed lazily after startup.

**Initialization:** Reads and parses `[stats]` configuration once at startup, caching the values. Raises `ValueError` on malformed configuration values (startup fails loudly — user decision). Validation is **strict**: booleans, floats, and non-integral strings (e.g. `"3.5"`) are all rejected with a `ValueError` naming the offending key; integral strings (`"3600"`) are accepted, so `${VAR}` env substitution in TOML is safe. The service is not marked as initialized until config parse succeeds, and the handler is not registered until then — a failed initialize leaves the service retryable (config fixed → initialize again succeeds). Configuration changes after initialization have no effect (config frozen at init).

**Per-cycle behavior (runs on CRON_JOB tick, gated by elapsed time):**
1. **Gate check:** if registry is empty → immediate return (stats disabled). If `time.time() - _lastRunTime < intervalSeconds` → return (interval not elapsed).
2. For each storage in a **registry snapshot** — `list(_statsStorages.items())` (guards against `RuntimeError` if the registry is mutated mid-iteration, e.g. by a `createStatsStorage` call; insertion order: llm_request, llm_tool_call, stt_request, message, command):
   - **Drain loop:** call `aggregate(limit=self._batchLimit)` repeatedly until it returns 0 **or** a safety cap of `MAX_AGGREGATION_ROUNDS = 10` is hit (bounds a cycle at `MAX_AGGREGATION_ROUNDS × batch-limit` events per storage).
   - **Retention purge:** if `self._retentionDays > 0`, call `purgeProcessed(retentionDays=N)` **once per storage, every cycle** — the purge predicate is **event_type-scoped** (`event_type = :eventType`): each storage deletes its own event type's processed rows past the retention cutoff via its own data source. Deletes rows with `processed = 1 AND event_type = :eventType AND created_at < truncateToDay(now - N days)`. The cutoff is day-truncated: events are deleted only once they are beyond N **whole** days (UTC midnight comparison).
   - Per-storage try/except isolation — one storage's failure never blocks others.
3. One INFO summary line: per-storage processed/purged counts + errors (using registry keys as labels).
4. Set `_lastRunTime = cycleStart` (gate advanced to cycle-start timestamp).

**First tick after startup is an immediate catch-up run** (`_lastRunTime = 0.0` → the gate always passes).

**Configuration:**
- `[stats] enabled` (default `false`): master switch; when false, the factory returns unregistered `NullStatsStorage` and the registry stays empty — zero per-tick cost.
- `[stats] aggregation-interval-seconds` (default `3600`): cycle cadence in seconds; clamped to minimum 60 (the tick granularity). Cached at initialization; malformed values raise ValueError.
- `[stats] aggregation-batch-limit` (default `1000`): number of events to process per `aggregate()` call in the drain loop; clamped to minimum 1. Bounds a cycle at `MAX_AGGREGATION_ROUNDS × batch-limit` events per storage. Cached at initialization; malformed values raise ValueError.
- `[stats] events-retention-days` (default `30`): retention window; `0` = keep forever. Cached at initialization; malformed values raise ValueError.

**Public read accessor:** `getQueryStorage(eventType: str) -> StatsStorage` — returns the registered storage for that eventType (e.g., `llm_request`, `message`, `command`) or `NullStatsStorage()` if the registry is uninitialized, empty, or the eventType is unregistered. Enables handlers to reach storages for read queries without construction side effects. `query()` supports `limit` + `offset` paging (keyword-only args; defaults `limit=STATS_QUERY_ROW_LIMIT` = 10000, `offset=0`) for segmented reads of large aggregate sets.

```python
from internal.services.stats import StatsAggregationService

# Initialize (called once from main.py, synchronous, before first factory call):
StatsAggregationService.getInstance().initialize(configManager, database)

# Get stats config for data source resolution:
statsConfig = configManager.getStatsConfig()

# Construct storages via factory (reads [stats] enabled itself):
llmStatsStorage = StatsAggregationService.getInstance().createStatsStorage(
    "llm_request", statsConfig.get("llm-stats-data-source", database.manager.default)
)
toolStatsStorage = StatsAggregationService.getInstance().createStatsStorage(
    "llm_tool_call", statsConfig.get("tool-stats-data-source", database.manager.default)
)
sttStatsStorage = StatsAggregationService.getInstance().createStatsStorage(
    "stt_request", statsConfig.get("stt-stats-data-source", database.manager.default)
)
messageStatsStorage = StatsAggregationService.getInstance().createStatsStorage(
    "message", statsConfig.get("message-stats-data-source", database.manager.default)
)
commandStatsStorage = StatsAggregationService.getInstance().createStatsStorage(
    "command", statsConfig.get("command-stats-data-source", database.manager.default)
)

# Read accessor for query() calls (returns NullStatsStorage if unregistered):
storage = StatsAggregationService.getInstance().getQueryStorage("llm_request")
rows = await storage.query(eventType="llm_request", periodType="daily")

# Storages flow to consumers exactly as today (LLMService, STTService, bot applications).
```

**Factory semantics:**
- **Disabled config** (`[stats] enabled = false`): `createStatsStorage` returns `NullStatsStorage()` and does NOT register it in the registry. The registry stays empty, so the handler returns after one truthiness check per tick — zero per-tick cost.
- **Enabled config**: `createStatsStorage` constructs `DatabaseStatsStorage` ([`lib/stats/sql_storage.py`](../../lib/stats/sql_storage.py) — takes `DatabaseManager` directly, `manager=self._database.manager`; ADR-023), registers it in `_statsStorages[eventType]`, and returns it. Duplicate eventType calls overwrite last-wins.
- **DataSource resolution**: `dataSource=None` uses the database manager's default datasource; main.py passes `statsConfig.get("<key>-stats-data-source")` (which is `None` when the key is absent).

**Failure isolation:** Per-storage try/except means one broken datasource or missing table never prevents the other storages from being processed. Errors are logged at exception level with storage context, and the summary line names failing storages (using registry keys as labels).

**Stats-off silence:** When `[stats] enabled = false`, the factory hands out unregistered `NullStatsStorage`s, the registry stays empty, and the registered handler returns after one truthiness check per tick — equivalent to the old nothing-seeded state, with zero per-tick cost.

---

## See Also

- [`index.md`](index.md) — Project overview, singleton services quick reference
- [`architecture.md`](architecture.md) — ADR-001 (singleton services), ADR-020 (stateless STTService boundary), service initialization order
- [`handlers.md`](handlers.md) — Using services from handler methods
- [`database.md`](database.md) — CacheService for DB hot-path access
- [`libraries.md`](libraries.md) — Low-level lib/ai, lib/cache, lib/rate_limiter APIs
- [`configuration.md`](configuration.md) — Service TOML config sections
- [`testing.md`](testing.md) — Mocking services in tests, singleton reset fixtures

---

*This guide is auto-maintained and should be updated whenever service integration patterns change*  
*Last updated: 2026-08-02*
