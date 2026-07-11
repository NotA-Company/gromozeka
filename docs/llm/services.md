# Gromozeka — Service Integration Patterns

> **Audience:** LLM agents  
> **Purpose:** Complete reference for using CacheService, QueueService, LLMService, StorageService, and RateLimiterManager  
> **Self-contained:** Everything needed for service integration is here

---

## Table of Contents

1. [CacheService](#1-cacheservice)
2. [QueueService](#2-queueservice)
3. [LLMService](#3-llmservice)
4. [StorageService](#4-storageservice)
5. [RateLimiterManager](#5-ratelimitermanager)
6. [Service Singleton Pattern](#6-service-singleton-pattern)

---

## 1. CacheService

**File:** [`internal/services/cache/service.py:193`](../../internal/services/cache/service.py:193)  
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

# Default chat settings are handled by config/database, not CacheService
# Use config files in configs/ for defaults, or set per-chat via setChatSetting()
```

**`chat_users` row cache (ADR-015):** the `CHAT_USERS` namespace (keyed `f"{chatId}:{userId}"`, `MEMORY_ONLY`) holds both the `user_data` blob (`data` field) and the `chat_users` row (`userInfo` field, lazily loaded). `getChatUser` is an LRU read with DB fallback on miss; `updateChatUser`/`updateUserMetadata` are write-through. Single-row `(chatId, userId)` reads/writes in handlers MUST go through `self.cache.*` — not `self.db.chatUsers.*` — so the cache stays consistent.

**`messages_count` is best-effort stale** on a cached row: the column is incremented by a raw SQL `UPDATE` inside `ChatMessagesRepository.saveChatMessage` (`internal/database/repositories/chat_messages.py:154`), bypassing this cache. Callers needing an accurate count SHOULD prefer the conditional-refresh helper `SpamHandler._getUserInfoFreshIfMessagesLessThan(chatId, userId, threshold)` over a blanket `refresh=True` — it refreshes only when the cached count is strictly below the threshold (a monotonic at-or-above value stays valid), so established users don't pay a per-message DB hit. The two spam gates use it with gate-direction-appropriate thresholds (`checkSpam` `>=` passes the threshold unchanged; `markAsSpam` strict `>` passes `threshold + 1` to refresh the boundary case). A direct `getChatUser(..., refresh=True)` is still available when an unconditional refresh is genuinely required. `updateChatUser` skips the DB upsert when `username`/`full_name` are unchanged, so `updated_at` no longer refreshes on a no-op call; on a cache miss it leaves the cache cold (no warming re-read). `updateUserMetadata` performs a **full-dict replace with NO merge** — callers writing a nested sub-dict (e.g. `memoryRefinement`) must read-modify-write the whole metadata dict. See [`architecture.md`](architecture.md) ADR-015 for the full decision and the nested-write safety invariant.

**Key types from** [`internal/services/cache/types.py`](../../internal/services/cache/types.py):
- `HCChatCacheDict` — per-chat cache
- `HCChatUserCacheDict` — per-user-in-chat cache
- `UserDataType` / `UserDataValueType` — user data structures

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
- `CRON_JOB` — periodic cron tasks
- `DO_EXIT` — cleanup on exit
- `SEND_MESSAGE` — scheduled message sending

---

## 3. LLMService

**File:** [`internal/services/llm/service.py:52`](../../internal/services/llm/service.py:52)  
**Import:** `from internal.services.llm import LLMService`

```python
llmService = LLMService.getInstance()

# Generate text response
result: ModelRunResult = await llmService.generateText(
    messages,                    # List[ModelMessage]
    chatId=chatId,
    chatSettings=chatSettings,
    modelKey=ChatSettingsKey.CHAT_MODEL,
    fallbackKey=ChatSettingsKey.CHAT_FALLBACK_MODEL,
)

if result.status == ModelResultStatus.FINAL:
    responseText = result.resultText

# Condense long conversation context
condensed = await llmService.condenseContext(
    messages,
    model=llmModel,
    keepFirstN=1,
    keepLastN=1,
    maxTokens=maxTokens,
    condensingModel=condensingModel,
    condensingPrompt=condensingPrompt,
    condensingSystemPrompt=condensingSystemPrompt,
)

# Register LLM tool — always use ToolName.XXX (never raw string)
llmService.registerTool(
    name=ToolName.EXAMPLE,
    description="Search the web",
    parameters=[
        LLMFunctionParameter("query", "Search query", LLMParameterType.STRING, required=True),
    ],
    handler=mySearchHandler,  # async def mySearchHandler(param1, ...) -> dict
)
```

**Rule:** Always use a `ToolName` member (from `internal.bot.constants`) for the `name=` argument. See the [add-handler skill](../../.agents/skills/add-handler/SKILL.md) Step 5 for the full registration workflow.

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
- `dict[str, bool]` — enable/disable individual tools by name. The special key defined by `TOOLS_DEFAULT_DICT_KEY` (from [`internal.bot.constants`](../../internal/bot/constants.py)) controls every tool not explicitly listed (defaults to `False` when absent). Unknown tool names are logged as warnings (`logger.warning`) and ignored.

**Tool names** should be specified via members of the `ToolName` StrEnum ([`internal.bot.constants.ToolName`](../../internal/bot/constants.py)) — one member per registered tool (e.g. `ToolName.RUN_PYTHON`, `ToolName.WEB_SEARCH`). Because `ToolName` is a `StrEnum`, members serialize to the exact string `registerTool(name=...)` expects, so raw string literals (e.g. `"run_python"`) also work; the enum is recommended for type safety and greppability.

```python
from internal.bot.constants import TOOLS_DEFAULT_DICT_KEY, ToolName

# Enable only the sandbox tools; disable everything else:
useTools={TOOLS_DEFAULT_DICT_KEY: False, ToolName.RUN_PYTHON: True, ToolName.SANDBOX_LIST_FILES: True}

# Enable all tools except one:
useTools={TOOLS_DEFAULT_DICT_KEY: True, ToolName.SANDBOX_SEND_FILE: False}
```

Resolution happens in the private `_resolveTools(useTools)` method, which returns the filtered `List[LLMToolFunction]` sent to the model. The execution guard also uses this filtered set: if the LLM requests a dict-disabled tool, the loop returns an error listing only the **actually available** tool names (not the full registry), so the model is not tempted to retry a disabled tool.

**Generate structured (JSON-Schema) output:**
```python
result: ModelStructuredResult = await llmService.generateStructured(
    prompt,                      # Union[str, Sequence[ModelMessage]]
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
    prompt: Union[str, Sequence[ModelMessage]],
    schema: Dict[str, Any],
    *,
    chatId: Optional[int],
    chatSettings: ChatSettingsDict,
    modelKey: Union[ChatSettingsKey, AbstractModel, None],
    fallbackKey: Union[ChatSettingsKey, AbstractModel, None],
    schemaName: str = "response",
    strict: bool = True,
    doDebugLogging: bool = True,
) -> ModelStructuredResult
```

`generateStructured` mirrors `generateText` end-to-end: it resolves
the primary and fallback models from `chatSettings`, applies rate
limiting for non-`None` `chatId`, then delegates to
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

**`ModelResultStatus` values:**
- `FINAL` — successful response
- `ERROR` — LLM error
- `TIMEOUT` — request timed out
- `EMPTY` — empty response

**IMPORTANT:** `LLMService` has an `initialized` guard (singleton init runs once). Never check `initialized` directly in new code

**Proxy config flow:** Proxy configuration flows from `ConfigManager.getProxyConfig()` → `ProxyHelper.getInstance().setGlobalProxyConfig()` in `main.py`. Services create `ProxyConfig` via `ProxyConfig.fromServiceConfig()` with their service-level config, then call `ProxyConfig.getCombined()` to merge with the global config, and `ProxyConfig.toKwargs()` to get `httpx.AsyncClient` kwargs. `LLMManager` stores a `proxyConfig` attribute. `BasicOpenAIProvider._initClient()` creates a custom `httpx.AsyncClient` for the OpenAI SDK. Image download and OpenRouter `listRemoteModels()` also resolve proxy.

### `internal/services/llm/utils.py`

Shared LLM utility functions used by both bot handlers and CLI scripts.

#### `reconstructMessages(requestData: List[Dict[str, Any]]) -> List[ModelMessage]`

Reconstructs `ModelMessage` objects from serialized request data (dicts with `role`, `content`, optional `tool_calls` and `tool_call_id`). Used by:
- `scripts/run_llm_debug_query.py` -- CLI debug replay
- `DevCommandsHandler.llmReplayCommand` -- `/llm_replay` bot command

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

**File:** [`lib/rate_limiter/manager.py:37`](../../lib/rate_limiter/manager.py:37)  
**Import:** `from lib.rate_limiter import RateLimiterManager`

```python
manager = RateLimiterManager.getInstance()

# Apply rate limit for a named queue
await manager.applyLimit("yandex-search")  # Blocks if over limit

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

# Initialize (called once from main.py after setGlobalProxyConfig)
proxyService.initialize(configManager.getProxyConfig(), loop=loop)

# Resolve proxy for a service (replaces direct ProxyConfig.fromServiceConfig)
proxyConfig = proxyService.resolveProxy(serviceConfig, "my-service")
```

**Key methods:**

| Method | Returns | Purpose |
|---|---|---|
| `initialize(proxyConfig, loop)` | `None` | Idempotent init. Reads global proxy config, creates `ProxyLifecycle` for global proxy if lifecycle section present, registers CRON_JOB/DO_EXIT handlers. Global proxy start command runs immediately via the shared event loop (`loop.run_until_complete()`). |
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

## 7. Service Singleton Pattern

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

## See Also

- [`index.md`](index.md) — Project overview, singleton services quick reference
- [`architecture.md`](architecture.md) — ADR-001 (singleton services), service initialization order
- [`handlers.md`](handlers.md) — Using services from handler methods
- [`database.md`](database.md) — CacheService for DB hot-path access
- [`libraries.md`](libraries.md) — Low-level lib/ai, lib/cache, lib/rate_limiter APIs
- [`configuration.md`](configuration.md) — Service TOML config sections
- [`testing.md`](testing.md) — Mocking services in tests, singleton reset fixtures

---

*This guide is auto-maintained and should be updated whenever service integration patterns change*  
*Last updated: 2026-06-26*
