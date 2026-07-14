# Gromozeka — Architecture & Design Decisions

> **Audience:** LLM agents  
> **Purpose:** Architecture Decision Records, component dependencies, design patterns  
> **Self-contained:** Everything needed for architecture understanding is here

---

## Table of Contents

1. [Architecture Decision Records](#1-architecture-decision-records)
2. [Dependency Map](#2-dependency-map)
3. [Design Patterns](#3-design-patterns)

---

## 1. Architecture Decision Records

### ADR-001: Singleton Services

**Decision:** `CacheService`, `QueueService`, `LLMService`, `StorageService`, `RateLimiterManager` are all singletons

**Why:** Single instance ensures consistent state across all handlers and avoids duplicate resource usage

**Constraint:** Always use `getInstance()` — never `SomeService()` directly:
```python
# CORRECT
cache = CacheService.getInstance()

# WRONG — creates duplicate state
cache = CacheService()
```

**Thread safety:** All singletons use `RLock` for thread-safe instantiation

**Singleton pattern (MUST preserve when modifying services):**
```python
class MyService:
    """Singleton service"""

    _instance: Optional["MyService"] = None
    _lock: RLock = RLock()

    def __new__(cls) -> "MyService":
        """Create or return singleton instance"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize service once"""
        if hasattr(self, "initialized"):
            return
        self.initialized = True
        # ... actual init ...

    @classmethod
    def getInstance(cls) -> "MyService":
        """Get the singleton instance

        Returns:
            The singleton MyService instance
        """
        return cls()
```

---

### ADR-002: Handler Chain Pattern

**Decision:** Messages flow through an ordered list of `BaseBotHandler` subclasses via [`HandlersManager`](../../internal/bot/common/handlers/manager.py:332)

**Why:** Separation of concerns — each handler does one thing. Easy to add new features without modifying existing handlers

**Chain order (CRITICAL):**
1. `MessagePreprocessorHandler` — SEQUENTIAL — saves message + media
2. `SpamHandler` — SEQUENTIAL — spam check before all others
3. `ConfigureCommandHandler` — PARALLEL — settings config
4. `SummarizationHandler` — PARALLEL — summarization
5. `UserMemoriesHandler` — PARALLEL — user memories
6. `DevCommandsHandler` — PARALLEL — debug commands
7. `MediaHandler` — PARALLEL — media processing
8. `CommonHandler` — PARALLEL — standard commands
9. `HelpHandler` — PARALLEL — help command
10. (Telegram only) `ReactOnUserMessageHandler` — PARALLEL
11. (Telegram only) `TopicManagerHandler` — PARALLEL
12. (if enabled) `WeatherHandler` — PARALLEL — weather forecasts
13. (if enabled) `YandexSearchHandler` — PARALLEL — Yandex search
14. (if enabled) `ResenderHandler` — PARALLEL — message forwarding
15. (if enabled) `DivinationHandler` — PARALLEL — tarot/runes divination
16. (if enabled) `SandboxHandler` — PARALLEL — sandboxed code execution
17. (if enabled) `ChatSearchHandler` — PARALLEL — chat search /search command
18. (custom handlers via `CustomHandlerLoader`) — PARALLEL by default (configurable per-handler)
19. `LLMMessageHandler` — SEQUENTIAL — **MUST BE LAST**

**Return values:** Handlers return [`HandlerResultStatus`](../../internal/bot/common/handlers/base.py:81):
- `FINAL` — stop chain, success
- `SKIPPED` — continue (most common)
- `NEXT` — continue (processed but need more)
- `ERROR` — continue (recoverable error)
- `FATAL` — stop chain, error

---

### ADR-003: Multi-Platform Abstraction (`TheBot`)

**Decision:** [`TheBot`](../../internal/bot/common/bot.py:33) wraps both Telegram and Max Messenger APIs behind a unified interface

**Why:** Handlers don't need to know which platform they're on

**Constraint:** Never call Telegram/Max APIs directly from handlers. Always use `self.sendMessage()`, `self.deleteMessage()`, etc. from `BaseBotHandler`

---

### ADR-004: Multi-Source Database Routing

**Decision:** [`Database`](../../internal/database/database.py) supports multiple database sources with internal routing using repository pattern

**Why:** Allows read replicas, separate databases for different data types, cross-bot data reading

**Architecture Principles:**
- **Repository Pattern**: 15 specialized repositories handle specific data domains (chat_info, chat_messages, chat_settings, chat_users, chat_summarization, cache, spam, media_attachments, delayed_tasks, common, chat_search, chat_embeddings, divinations, webhook_updates, user_memories)
- **Simple Priority Routing**: `dataSource` param → `chatId` mapping → default source
- **Readonly Protection**: Sources marked `readonly=True` reject write operations
- **Cross-Bot Communication**: Can read from external bot databases via `dataSource` param
- **SQL Portability**: All SQL is provider-agnostic, supporting SQLite3, PostgreSQL, MySQL, and SQLink

**Config:** `[database.providers.*]` in TOML, routing via `chatMapping` for specific chats:
```toml
[database]
default = "default"

[database.providers.default]
provider = "sqlite3"

[database.providers.default.parameters]
dbPath = "bot_data.db"
readOnly = false
timeout = 30
useWal = true

[database.providers.readonly]
provider = "sqlink"

[database.providers.readonly.parameters]
dbPath = "archive.db"
readOnly = true
timeout = 10
```

**SQL Portability Notes:**
- Migration 013 removed `DEFAULT CURRENT_TIMESTAMP` from all timestamp columns for cross-database compatibility
- All timestamp values are now explicitly set in application code
- Provider abstraction layer (`internal/database/providers/`) handles database-specific SQL dialects
- Supports SQLite3, PostgreSQL, MySQL, and SQLink (SQLite3 over REST) providers

**Repository Structure:**
- `ChatInfoRepository` — Chat metadata and information
- `ChatMessagesRepository` — Message storage and retrieval
- `ChatSearchRepository` — Chat search and history retrieval
- `ChatEmbeddingsRepository` — Chat message embeddings for search
- `ChatSettingsRepository` — Chat configuration settings
- `ChatUsersRepository` — User-chat relationships
- `ChatSummarizationRepository` — Chat summarization data
- `CacheRepository` — Cache storage operations
- `CommonFunctionsRepository` — Shared/common operations
- `DelayedTasksRepository` — Scheduled task management
- `DivinationsRepository` — Tarot/runes divination data
- `MediaAttachmentsRepository` — Media file attachments
- `SpamRepository` — Spam detection and messages
- `WebhookUpdatesRepository` — Max webhook payload storage and consumption (backed by `migration_019`)
- `UserMemoriesRepository` — Unified per-`(chat, user, thread)` structured memory store (backed by `migration_020`; supersedes the legacy `user_data` key-value table, dropped in `migration_022`, + rolling-bio blob — see ADR-016)
- `BaseRepository` — Abstract base with common functionality

**Implementation Details:**
- `ConnectionManager`: Manages connection pools per data source with thread-safe access
- Backward compatible: Works with legacy single database mode
- Optional `dataSource` parameter: Zero breaking changes
- Repository pattern provides clear separation of concerns and easier testing

---

### ADR-005: LLM Provider Fallback

**Decision:** [`LLMManager`](../../lib/ai/manager.py:49) supports multiple providers with automatic fallback

**Why:** If primary LLM provider fails, automatically falls back to secondary

**Providers:** `yc-openai`, `openrouter`, `yc-sdk`, `custom-openai`.

---

### ADR-006: Command Discovery via Decorators

**Decision:** Commands are discovered via `@commandHandlerV2(...)` decorator on methods

**Why:** Zero-registration — add decorator, command is auto-discovered by `HandlersManager`

**Decorator location:** Imported from `internal.bot.models` as `commandHandlerV2`

---

### ADR-007: Configuration Layering

**Decision:** Config loads from multiple TOML files and merges them in order

**Why:** Separates defaults from environment-specific overrides

**Load order:** `--config` file first, then `--config-dir` files sorted alphabetically

**Merge behavior:** Later files override earlier ones. Nested dicts are merged recursively

---

### ADR-008: Cross-Source Aggregation with Intelligent Deduplication

**Decision:** Cross-source database queries use semantic deduplication keys per method type

**Why:** Prevents duplicates when aggregating data across multiple SQLite sources

**Deduplication Keys Strategy:**
- `getUserChats()`: `(userId, chat_id)` — user-chat relationship uniqueness
- `getAllGroupChats()`: `chat_id` — chat uniqueness
- `getSpamMessages()`: `(chat_id, message_id)` — message uniqueness within chat
- `getCacheStorage()`: `(namespace, key)` — cache entry uniqueness
- `getCacheEntry()`: First match (no deduplication) — performance optimization

**Error Handling:** Continue aggregation on individual source failures with warning logs

---

### ADR-009: Time-Based Media Group Completion Detection

**Decision:** Telegram media groups (albums) use time-based completion detection with configurable delay

**Why:** Telegram sends media groups as separate messages with same `media_group_id` but doesn't indicate when all items have arrived

**Solution:** Wait a configurable delay after the last media item is received before considering a media group complete.

**Architecture Choice:**
- **Per-Job Configuration**: Each `ResendJob` has its own `mediaGroupDelaySecs` parameter (default: 10.0 seconds)
- **Database Method**: `getMediaGroupLastUpdatedAt()` returns `MAX(created_at)` from `media_groups` table
- **Processing Logic**: `_dtCronJob` checks media group age before processing using `utils.getAgeInSecs()`

**Processing Flow:**
1. For each message with `media_group_id`, check if already processed
2. Get last updated timestamp using `getMediaGroupLastUpdatedAt()`
3. If age < `job.mediaGroupDelaySecs`, mark as pending and skip
4. If age >= `job.mediaGroupDelaySecs`, mark as processed and resend all media together

**Configuration:**
```toml
[[resender.jobs]]
id = "telegram-to-max"
sourceChatId = -1001234567890
targetChatId = 9876543210
mediaGroupDelaySecs = 10.0  # Optional, defaults to 10.0
```

**Edge Cases Handled:**
- **Slow uploads**: Each new media item updates timestamp, extending wait time
- **Fast uploads**: All media arrive quickly, processed together after delay
- **Single media**: Processed immediately if no `media_group_id`

---

### ADR-010: Chat Settings Audit Trail

**Decision:** `chat_settings` table includes `updated_by` column (INTEGER NOT NULL) to track which user last modified each setting

**Why:** Required for audit capability — knowing who changed what setting

**Implementation:**
- Migration `migration_010` adds `updated_by` column via table recreation pattern
- Existing data: `updated_by=0` set for all existing rows during migration
- `setChatSetting(chatId, key, value, *, updatedBy: int)` — `updatedBy` is required keyword-only argument

**API Design:**
- `getChatSetting(chatId, setting)` — returns `Optional[str]` (just the value for backward compatibility)
- `getChatSettings(chatId)` — (repository layer) returns `Dict[str, tuple[str, int]]` where tuple is `(value, updated_by)`; the handler/cache `getChatSettings()` returns `Dict[ChatSettingsKey, ChatSettingsValue]` instead (access via `.toBool()`/`.toStr()`/etc.)
- This minimizes breaking changes while providing audit capability

---

### ADR-011: Divination Layout Discovery Pattern

**Decision:** Unknown tarot/runes layouts trigger automatic LLM + web search discovery, cached in `divination_layouts` table with negative cache for failures

**Why:** Allows users to request any layout (not just predefined ones), avoids repeated failed discoveries, and scales to thousands of possible layouts

**Discovery Flow (Multi-Tier Resolution):**

**Tier 1**: Predefined layouts in `lib/divination/layouts.py`
- Fast lookup in `TAROT_LAYOUTS` and `RUNES_LAYOUTS` dicts
- Zero database queries for known layouts

**Tier 2**: Database cache (`divination_layouts` table)
- Composite PK: `(system_id, layout_id)`
- Successful discoveries: Full layout definition cached
- Failed discoveries (negative cache): `name_en=''`, `n_symbols=0` entries prevent retries
- Case-insensitive fuzzy search via `getLikeComparison()` for partial matches

**Tier 3**: LLM + Web Search discovery (if `divination discovery-enabled = true`)
- Call 1: `LLMService.generateText(tools=True)` with web search
  - Prompt: `divination-discovery-info-prompt`
  - System: `divination-discovery-system-prompt`
  - Tool: `web_search` automatically used by LLM
- Call 2: `LLMService.generateStructured(schema)` to parse description
  - Prompt: `divination-discovery-structure-prompt`
  - Schema: Strict JSON Schema with required fields
  - Returns validated dictionary
- Save: Persist to `divination_layouts` cache on success
- Negative cache: On failure, store empty entry with 24-hour implied TTL

**Performance Optimizations:**
- Negative cache prevents spamming LLM for non-existent layouts
- Fuzzy search: `divinationLayouts.getLayout()` tries exact match first, then LIKE pattern
- Case-insensitive search: Uses `getCaseInsensitiveComparison()` for exact, `getLikeComparison()` for fuzzy
- No blocking: Discovery only triggered for unknown layouts, not every request

**Configuration:**
```toml
[divination]
discovery-enabled = true  # Master switch
```

**Chat Settings for Discovery:**
- `divination-discovery-system-prompt` — System instruction (both calls)
- `divination-discovery-info-prompt` — Web search prompt (first call)
- `divination-discovery-structure-prompt` — Structured parsing prompt (second call)

**Repository Pattern:**
```python
from internal.database.repositories import DivinationLayoutsRepository

repo = DivinationLayoutsRepository(db.manager)
layout = await repo.getLayout(systemId='tarot', layoutName='three_card')

# Negative cache check
if repo.isNegativeCacheEntry(layout):
    # Layout doesn't exist, don't retry
    return None

# Save successful discovery
await repo.saveLayout(
    systemId='tarot',
    layoutId='custom_layout',
    nameEn='Custom Layout',
    nameRu='Кастомный расклад',
    nSymbols=3,
    positions=json.dumps([...]),
    description='Custom description'
)

# Save negative cache
await repo.saveNegativeCache(systemId='tarot', layoutId='invalid')
```

---

### ADR-012: Statistics Collection with Best-Effort Recording

**Decision:** Statistics collection uses a two-table schema (`stat_events` append-only log, `stat_aggregates` period buckets) with best-effort recording that never blocks LLM requests.

**Why:** Track LLM usage (tokens, errors, fallbacks), enable analytics, and support future metrics without impacting bot responsiveness.

**Architecture:**

```
                        ┌───────────────────────┐
                        │      main.py          │
                        │  GromozekBot.__init__ │
                        └──────┬───────┬────────┘
                               │       │
                     creates    │       │  creates
                               ▼       ▼
               ┌────────────────┐   ┌──────────────────────┐
               │  LLMManager    │   │ DatabaseStatsStorage │
               │  (lib/ai)      │◄──│ (internal/database/  │
               │                │   │  stats_storage.py)   │
               │ .statsStorage ─┼──►│                      │
               └───────┬────────┘   │ - record()           │
                       │            │ - aggregate()        │
                       │ propagate  │ - db: Database       │
                       ▼            │ - dataSource: "stats"│
               ┌─────────────────┐  └──────────┬───────────┘
               │ AbstractModel   │             │
               │ (lib/ai)        │             │ single provider
               │                 │             ▼
               │ .statsStorage   │  ┌──────────────────────┐
               │ _runWithFallback│  │   DatabaseManager    │
               └─────────────────┘  │                      │
                                    │ "stats" provider     │
                                    └──────────┬───────────┘
                                               │
                           ┌───────────────────┼───────────────────┐
                           ▼                   ▼
                    ┌─────────────┐    ┌───────────────┐
                    │ stat_events │    │stat_aggregates│
                    │ (append-only│    │ (materialized │
                    │  log)       │    │  views)       │
                    └─────────────┘    └───────────────┘
                           │                   ▲
                           │    aggregate()    │
                           └───────────────────┘
```

**Data flow:**

1. **Recording:** `AbstractModel._recordAttemptStats()` calls `statsStorage.record()` after each LLM attempt
2. **Best-effort:** `record()` catches all exceptions, logs, and returns — never propagates to LLM caller
3. **Labels:** Events are tagged with `consumer`, `modelName`, `modelId`, `provider`, `generationType`
4. **Global rollup:** Aggregation produces both per-consumer and `__global__` (all-chat) stats
5. **Periods:** Aggregates computed for `hour`, `day`, `month`, and `total` periods
6. **Claim-aggregate-commit:** `aggregate()` claims unprocessed events, computes sums, upserts to `stat_aggregates`, marks events processed

**Configuration:**
- `[stats] enabled = false` (default) — disabled until aggregation trigger and query API are implemented
- When enabled: `DatabaseStatsStorage` created in `main.py`, passed to `LLMManager`, propagated to all models

**Stats recorded for LLM events:**
- `generation_text`, `generation_structured`, `generation_image` — 0/1 flags per generation type
- `request_count` — always 1 per attempt
- `input_tokens`, `output_tokens`, `total_tokens` — token counts (0 if unavailable)
- `is_error` — 1 if status in ERROR_STATUSES
- `status_{name}` — 1 for the actual status (e.g., `status_FINAL`, `status_ERROR`, etc.)

**Integration points:**
- `LLMManager.__init__(statsStorage=...)` — receives storage, propagates to models
- `AbstractModel.statsStorage` — holds reference, used in `_recordAttemptStats()`
- `LLMService` — passes `consumerId=str(chatId)` to generation methods

**Schema:** Created by `migration_016` — `stat_events` (append-only log) and `stat_aggregates` (period buckets) in the default data source.

---

### ADR-013: Max Webhook Receiver (Two-Process Local API Proxy)

**Decision:** Max Messenger webhook ingestion runs as a separate standalone aiohttp process ([`internal/max_webhook_receiver/`](../../internal/max_webhook_receiver/)) that accepts webhook POSTs from the Max API, stores raw payloads in the local `webhook_updates` table, and serves them back to the bot via a GET /updates endpoint that speaks the Max API protocol.

**Why:** Max's webhook model pushes updates to an HTTPS URL the operator controls. Rather than threading a second ingestion path into the bot process, a thin local receiver decouples the public HTTPS endpoint from the bot: it persists payloads durably, then the bot's existing long-poll loop consumes them unchanged.

**Two-process data flow:**

```
   Max API ──POST /webhook──▶  webhook receiver process
   (platform-api2.max.ru)      (internal/max_webhook_receiver/, aiohttp.web)
                                       │
                                       │ addUpdate() / db.webhookUpdates
                                       ▼
                               ┌──────────────────┐
                               │ webhook_updates  │  (shared SQLite)
                               └──────────────────┘
                                       ▲
                                       │ getUnprocessedUpdates() / markProcessed()
                                       │
   bot process (MaxBotApplication) ────┘
       MaxBotClient._pollingLoop()
       basePollingUrl = http://127.0.0.1:8443
       polls GET /updates  (Max API protocol: {"updates": [...], "marker": ...})
```

**Components:**
- **Receiver process** — `internal/max_webhook_receiver/__main__.py` (`python -m internal.max_webhook_receiver`). aiohttp.web app (`app.py`) with two routes: `POST <webhook-path>` (verifies `X-Max-Bot-Api-Secret`, stores raw body) and `GET /updates` (long-polls `webhook_updates`, marks rows processed, returns Max-shaped `{"updates": [...], "marker": ...}`). The webhook handler returns **500 on a DB write failure so the Max API retries the delivery** rather than silently acknowledging a transient loss (full status map: 403 bad secret, 400 malformed JSON, 500 DB write failure, 200 success). A background cleanup task reaps processed rows past a 1h TTL.
- **`webhook_updates` table** (`migration_019`) — durable buffer between the two processes. The receiver only writes; the bot (via the receiver's GET /updates handler) reads and marks processed. See [`database.md`](database.md) and [`docs/database-schema.md`](../../docs/database-schema.md).
- **`MaxBotClient.basePollingUrl`** ([`lib/max_bot/client.py`](../../lib/max_bot/client.py)) — when set, the client's existing `_pollingLoop()` routes getUpdates to the local receiver's `GET /updates` instead of `platform-api2.max.ru`. Trailing slash is stripped at construction. Authenticated via `Authorization` header when the receiver's `get-updates-secret` is set.
- **Webhook subscription** — managed by the bot process. When `webhook-receiver.register-webhook = true` (the default), the bot calls Max's `POST /subscriptions` on startup; when `webhook-receiver.unregister-webhook = true`, it calls `DELETE /subscriptions` on shutdown. The two keys default independently — `register-webhook` defaults to `true`, `unregister-webhook` defaults to `false` — so a bot restart does not tear down the Max subscription unless unregistering is explicitly opted in.

**Key invariants:**
- The bot never writes to `webhook_updates` directly in webhook mode — the receiver is the sole writer. The bot's poll loop hits the receiver's `GET /updates`, which internally calls `db.webhookUpdates.getUnprocessedUpdates()` / `markProcessed()` on the shared database.
- **Delivery semantics** are controlled by `webhook-receiver.mark-on-subsequent-poll` (default `true` = deferred/at-least-once): `GET /updates` does NOT mark rows on read; instead it returns a compound marker `"{received_at}|{id}"` for the last served row, and rows are acknowledged via `markProcessedBeforeMarker()` only when the bot passes that marker back on its next poll. A bot crash between polls leaves the rows unprocessed → re-delivered. When `false` (immediate/at-most-once), rows are marked processed on read via `markProcessed()` and the response carries `marker: null` (there is nothing to acknowledge on the next poll); a crash after serving loses them. A malformed marker passed back by a client is caught narrowly (`ValueError`/`OverflowError`/`TypeError` raised inside `_parseMarker`) and treated as a no-marker poll rather than 500-ing — this prevents the bot from wedging in an infinite retry loop against the same bad marker.
- `webhook-receiver.enabled = false` keeps the bot on normal long-polling to the real Max API; the receiver process still runs and still writes any webhook POSTs it receives, but the bot ignores them. This is the safe default.
- The receiver refuses to start when `webhook-receiver.secret` is empty or an unresolved `${VAR}` placeholder (it would otherwise be a publicly-known secret). The bot mirrors this guard in webhook mode: whenever `webhook-receiver.enabled = true` it rejects unresolved `${VAR}` placeholders in both `secret` and `get-updates-secret` at startup (an unresolved placeholder would otherwise be sent verbatim as a credential — to the Max API for `secret`, or as the `Authorization` header to the local receiver for `get-updates-secret`), and additionally requires `secret` to be non-empty when `register-webhook = true`.

**Local API proxy pattern:** the receiver's `GET /updates` re-shapes stored rows into the Max API `UpdateList` response, so the bot's polling code path is identical whether it points at the receiver or the real platform API. Only the base URL differs. This keeps the webhook feature a config flip rather than a parallel code path.

**Config:** `[webhook-receiver]` in [`configs/00-defaults/webhook-receiver.toml`](../../configs/00-defaults/webhook-receiver.toml). See [`configuration.md`](configuration.md) §`[webhook-receiver]`.

---

### ADR-014: Background User-Memory Refinement (Cron + Global Lock + Context Injection)

> **SUPERSEDED (partial):** The *storage* (rolling-bio blob in `chat_users.metadata`)
> and *injection* (`EnsuredMessage.userSummary` / `applyUserMetadata`) decisions in
> this ADR were superseded by ADR-016 (structured `user_memories` store + centralised
> arrival-time per-message injection, Phases 1–4b). The cron / lock / accounting invariants below are still
> authoritative. See ADR-016 and `docs/llm/memories/user-memories.md`.

**Decision:** A rolling per-`(chat, user, thread)` memory summary is refined in the background by an LLM on a 60s `CRON_JOB` owned by `UserMemoriesHandler`, and injected into normal chat context as a new `EnsuredMessage.userSummary` field.

**Why:** Lets future replies carry short-term context about each user without re-reading their whole history or putting durable facts into every message's `userData`. The work is asynchronous and bounded so it never blocks the hot reply path or floods the LLM provider.

> **Note (post-ADR-016):** the JSON field is now `userMemories` (per-message compact-ID memory injection per ADR-016/ADR-018); the historical `userData` name in the prose above is retained as a frozen record.

**Components** (see [`docs/llm/memories/user-memory-refinement.md`](memories/user-memory-refinement.md) for the durable implementation summary):

- **Counter** — `UserMemoriesHandler._accounting: Dict[(chatId, userId, threadId), int]`, in-memory only (lost on restart; refinement re-fires after the next threshold crossing). Incremented at the very top of `newMessageHandler`, gated by the per-chat `MEMORY_REFINEMENT_ENABLED` setting, before any other gate. **Refinement dispatch also requires `MEMORY_ENABLED=true && EMBEDDINGS_ENABLED=true`** (the scan gate re-checks all three per candidate): memory embeddings are on only when `MEMORY_ENABLED && EMBEDDINGS_ENABLED`, and refinement's `search_memories` tool is semantic and returns nothing without them, so a chat with `MEMORY_REFINEMENT_ENABLED=true` but either gate false will not refine. Candidates that fail the gate are dropped from `_accounting` / `_lastRefinedTS`. (Intentional asymmetry: `_runSingleRefinement`'s runtime re-check stays `MEMORY_REFINEMENT_ENABLED`-only — it trusts the scan-gate admission.)
- **Cron** — `UserMemoriesHandler._dtCronJob(task)` registered on `DelayedTaskFunction.CRON_JOB` (runs every 60s alongside other handlers' cron ticks — multiple handlers may subscribe to the same function).
- **Global lock** — a single `asyncio.Lock` (`_refineLock`) serializes the whole scan+dispatch. If a previous batch is still running (a single LLM call can exceed 60s), the tick early-returns (`if self._refineLock.locked(): return`) instead of spawning a concurrent run. This prevents provider flooding; there is no per-entry locking and no `createTask`.
- **Refinement run** — `_runSingleRefinement` fetches recent messages via `chatMessages.getChatMessagesSince` (additive `userId` filter), renders them, and calls `LLMService.generateTextViaLLM` with `chatId=None` (skips rate-limiting for the background call) and a per-tool dict enabling `ADD_MEMORY`/`DELETE_MEMORY`/`SEARCH_MESSAGES`/`GET_CURRENT_DATETIME`. A synthetic minimal `EnsuredMessage` is built so the `add_memory`/`delete_memory` tools can resolve `chatId`/`userId` from `extraData["ensuredMessage"]`.
- **Persistence** — the resulting summary + cursors land in `chat_users.metadata.memoryRefinement[str(threadId)]` (`{summary, lastProcessedMessageId, lastProcessedMessageDate}`). Written via **direct read-modify-write through `chatUsers.updateUserMetadata()`** — NOT `setUserMetadata(isUpdate=True)`, which shallow-merges at the top level and would wipe sibling threads' summaries (see [`tasks.md`](tasks.md) §3 gotcha). The `lastRefinedTS` (drives the 6h time threshold) is tracked **in-memory** on `UserMemoriesHandler._lastRefinedTS` (lost on restart; absent → 0 → due).
- **Context injection** — `BaseBotHandler._updateEMessageUserData` and `HandlersManager._processMessageRec` fetch the full `UserMetadataDict` via `cache.getUserMetadata` and pass it to `EnsuredMessage.applyUserMetadata(metadata)`, which extracts `memoryRefinement[str(threadId or DEFAULT_THREAD_ID)].summary` into `userSummary`. Intentionally not gated on `MEMORY_REFINEMENT_ENABLED` at injection — the write side gates, so absence-of-summary is the gate. `formatForLLM` omits `userSummary` from JSON when `None` → byte-identical default output.

**Load-bearing invariants:**
- The global lock is the concurrency boundary for refinement. Never add per-entry locks or fire-and-forget tasks — a slow run must block the next tick, not pile up concurrent calls.
- Nested `memoryRefinement` writes must read-modify-write the whole metadata dict. Never pass a partial `{"memoryRefinement": {<threadId>: ...}}` through `setUserMetadata(isUpdate=True)`.
- The dispatch loop uses a **credit-consumed** counter reset in the per-entry `finally` block: `_accounting[key] = max(0, _accounting.get(key,0) - preCount)` where `preCount` is the count captured at scan time, NOT an unconditional zeroing. This preserves increments from messages that arrived during the (possibly multi-second) LLM call. When the result is `0` the key is **popped** from `_accounting` (not kept at `0`) so empty keys aren't re-iterated next tick. Never revert to `= 0`.
- Due-list selection is an **online top-K by smallest `lastRefinedTS`** maintained during the scan, NOT a collect-all → sort → truncate. A bounded `due` list of size ≤ `_memoryMaxRefinesPerTick` is kept, holding the entries with the SMALLEST `lastRefinedTS` (oldest-due / never-refined carry TS=0). When full, a new candidate with a smaller `lastRefinedTS` than the running max evicts that max and the running max is recomputed. The 3rd tuple element is `lastRefinedTS` (int), not `elapsed` (float). Dispatch order within the selected K is unspecified — acceptable since K is tiny and all selected entries get processed in the happy path. Never revert to the old `due.sort(key=lambda x: (-x[2], -x[1]))[:maxRefinesPerTick]` (largest-elapsed-first).
- **Never-refined users are deliberately NOT skipped.** An earlier `isNeverRefined and newMessagesCount < minMessages: continue` pre-filter was removed because it gated on the *new-message counter*, but refinement of a never-refined user actually pulls *lifetime* messages via `getChatMessagesSince(sinceDateTime=None)`. The skip was over-conservative — it blocked users with plenty of pre-existing chat history but few messages since feature-enable. Now never-refined users (TS=0 → due-by-time) enter the due list normally and get refined from their lifetime history; if genuinely too few lifetime messages, `_runSingleRefinement` bails once on the `< min-messages-to-refine` path and advances the in-memory `_lastRefinedTS` so the candidate isn't retried until the count/time threshold fires again.
- `_runSingleRefinement` sets `_lastRefinedTS[key] = int(time.time())` on the `< min-messages` bail path, so idle (e.g. post-restart, previously-refined) users aren't re-scanned and re-bailed on every 60s tick. The count threshold still fires independently once messages accumulate. Never remove this — without it the cron hot-loops over idle due-by-time users.
- **Lock ordering for nested metadata RMW:** `_persistMemoryEntry` (called inside `_runSingleRefinement`, hence under `_refineLock`) acquires `CacheService.chatUserMetadataLock()` to serialize its read-modify-write of `chat_users.metadata` against `setUserMetadata(isUpdate=True)`. The ordering is `_refineLock` (outer) → `chatUserMetadataLock` (inner) — never invert it. `setUserMetadata` (both `isUpdate=True` and `isUpdate=False` branches — the lock wraps the entire method body) is the only other `chatUserMetadataLock` holder and it never touches `_refineLock`, so the no-deadlock argument holds; a new metadata-RMW site added inside the refinement flow must respect the same ordering. See ADR-015.

**Config:** `[user-memory]` in [`configs/00-defaults/user-memory.toml`](../../configs/00-defaults/user-memory.toml) (global kill switch + thresholds; read ONCE in `__init__` and cached as instance attributes); per-chat `MEMORY_REFINEMENT_ENABLED` / `MEMORY_REFINE_MODEL` / `MEMORY_REFINE_FALLBACK_MODEL` / `MEMORY_REFINE_SYSTEM_PROMPT` / `MEMORY_REFINE_USER_PROMPT_TEMPLATE` chat settings under `[bot.defaults]`. See [`configuration.md`](configuration.md) §`[user-memory]`. An optional `[user-memory.json-logging]` sub-table writes one JSONL line per successful refinement run for debugging/analysis (success-path-only — see [`configuration.md`](configuration.md) §`[user-memory.json-logging]` and [`memories/user-memory-refinement.md`](memories/user-memory-refinement.md) "JSONL refinement log").

---

### ADR-015: Write-Through `chat_users` Cache in `CacheService`

**Decision:** `CacheService` gained a write-through cache for the single-row `chat_users` lookup. The existing `CacheNamespace.CHAT_USERS` namespace (keyed `f"{chatId}:{userId}"`, `MEMORY_ONLY`) was reused; its value TypedDict `HCChatUserCacheDict` ([`internal/services/cache/types.py:130`](../../internal/services/cache/types.py:130)) was extended with a second lazily-loaded field `userInfo: NotRequired[ChatUserDict]` (non-Optional; presence-of-key is the "loaded" sentinel) alongside `permanentMemories` (the per-thread permanent-memory cache). Every single-row `(chatId, userId)` read and username/fullName/metadata write in the handler layer now routes through `CacheService` instead of `self.db.chatUsers.*`. Aggregate/by-username queries (`getChatUserByUsername`, `getChatUsers`, `getUserChats`, `getAllGroupChats`, `getUserIdByUserName`) are untouched.

**Why:** On every inbound message the bot read the `chat_users` row for the sender 2–5 times (memory-summary reads during LLM history reconstruction, spam `checkSpam`, per-message `updateChatUser` upsert, internal metadata-read inside `setUserMetadata`). The cache eliminates the redundant reads on the warm path. It mirrors the established permanent-memory cache pattern (`getChatUserPermanentMemories`/`invalidateChatUserPermanentMemories`): `MEMORY_ONLY` namespace, durability from explicit write-through inside the setter methods.

**New `CacheService` methods** ([`internal/services/cache/service.py:1008`](../../internal/services/cache/service.py:1008)):

- `async getChatUser(chatId, userId, *, refresh=False) -> Optional[ChatUserDict]` — LRU read, DB fallback on miss/`refresh`. Returns a **defensive shallow copy** (`dict(cachedRow)`) so callers cannot mutate the cached row. On a cache hit (and `refresh=False`) the cached row is returned with no DB access. On a miss OR `refresh=True`, the row is read from DB: if found, it is cached and a copy returned; **if absent, `None` is returned WITHOUT caching the absence** (an absent row indicates something went wrong upstream and is not worth memoizing — the next call re-queries the DB).
- `async updateChatUser(chatId, userId, username, fullName) -> None` — write-through upsert with **skip-when-unchanged** (if the cached row's `username`/`full_name` already equal the supplied values, the DB upsert is skipped entirely). On a cache hit the cached row is mutated in place; **on a cache miss the cache is intentionally LEFT COLD** (no re-read warming) — the row may never be read again, and the next `getChatUser` lazy-loads it if needed, so a warming re-read would be a wasted query on the write path.
- `async getUserMetadata(chatId, userId) -> UserMetadataDict` — parses the cached row's `metadata` column via `json.loads` (empty/None → `{}`). Returns a freshly-parsed dict (no aliasing).
- `async updateUserMetadata(chatId, userId, metadata) -> None` — write-through **full-dict replace** (serializes via `utils.jsonDumps`, writes via `db.chatUsers.updateUserMetadata`, then updates the cached row's `metadata`/`updated_at` in place). Performs **NO merge**.
- `def invalidateChatUser(chatId, userId) -> None` — sync; pops **only** the `userInfo` key (preserves `permanentMemories`). Escape hatch for out-of-band mutations; no callers today.
- `async chatUserMetadataLock() -> AsyncIterator[None]` — async context manager (`@contextlib.asynccontextmanager`) wrapping a single process-global `asyncio.Lock` (`_chatUsersMetadataLock`). Callers that do read-modify-write of `chat_users.metadata` (e.g. `setUserMetadata(isUpdate=True)` and `UserMemoriesHandler._persistMemoryEntry`) MUST hold it across the full RMW to avoid lost-update races between concurrent writers. Plain reads (`getUserMetadata`) and full-replace writes (`updateUserMetadata` with no preceding read) do NOT need it. (Caveat: this guidance applies at the bare cache-method level — the higher-level `BaseBotHandler.setUserMetadata` wrapper acquires the lock for BOTH its `isUpdate=True` read-merge-write and `isUpdate=False` full-replace branches; see its docstring. The `isUpdate=False` branch holds the lock not because the bare full-replace needs it, but to prevent a concurrent RMW elsewhere from clobbering the full-replace write.) Intentionally process-global rather than per-`(chat, user)` — metadata writes are infrequent, so cross-user contention is negligible. Lock ordering when nested inside refinement: `_refineLock` (outer) → `chatUserMetadataLock` (inner) — see ADR-014.

**Refactored call sites:** `internal/bot/common/handlers/{base,spam,message_preprocessor,user_memories}.py` route single-row reads/writes through `self.cache.*`.

**`messages_count` staleness trade-off (load-bearing):** the `messages_count` column is incremented by a raw SQL `UPDATE ... SET messages_count = messages_count + 1` inside `ChatMessagesRepository.saveChatMessage` ([`internal/database/repositories/chat_messages.py:154`](../../internal/database/repositories/chat_messages.py:154)), which bypasses `ChatUsersRepository` and therefore this cache. A cached row's `messages_count` drifts. The two correctness-critical readers that gate on `messages_count` vs `AUTO_SPAM_MAX_MESSAGES` — `SpamHandler.checkSpam` ([`spam.py`](../../internal/bot/common/handlers/spam.py)) and `markAsSpam` — use the **conditional-refresh micro-optimisation** `SpamHandler._getUserInfoFreshIfMessagesLessThan(chatId, userId, messagesCountThreshold)` instead of an unconditional `refresh=True`. Because `messages_count` is monotonically non-decreasing, a cached value at or above the threshold can only stay there or grow, so it remains valid for any `>=` / `>` gate; only a cached value strictly below the threshold might have drifted up past it, so only that case pays for a `refresh=True` re-fetch. The two call sites pass different thresholds matching their gate direction: `checkSpam` (a `>=` gate) passes `maxCheckMessages` unchanged; `markAsSpam` (a STRICT `>` gate) passes `maxSpamMessages + 1` so the boundary case (`cached == maxSpamMessages`) still triggers a refresh, closing the false-ban window. Read-heavy paths (memory summary, metadata) consume the warm cache and do not need an accurate count.

**Absent-row non-memoization (intentional):** `getChatUser` does NOT cache a missing row. An absent `(chatId, userId)` row indicates something went wrong upstream (e.g. a message arrived before the row was seeded) and is not worth memoizing — every read of an absent row re-queries the DB until the row appears. This also keeps `userInfo` non-Optional (presence-of-key is the "loaded" sentinel).

**Skip-when-unchanged optimization & `updated_at` semantics shift:** because `updateChatUser` is a no-op when `username`/`full_name` are unchanged, `updated_at` no longer refreshes on such calls. Accepted trade-off; callers must not assume `updated_at` moves on every `updateChatUser` invocation. (`saveChatMessage`'s raw increment still bumps `updated_at` independently on every message.)

**Nested-write safety invariant:** `updateUserMetadata` does NO merge. Callers writing a nested sub-dict (e.g. `memoryRefinement[str(threadId)]`) must read the FULL metadata via `getUserMetadata`, mutate the single nested key, and write the FULL metadata back via `updateUserMetadata`. A blind shallow top-level merge (`{**old, **new}`) would wipe sibling keys — the memory-refinement write path (`user_memories.py` `_persistMemoryEntry`) keeps its explicit full-read + nested-mutate + full-write pattern, and that whole RMW is serialized via `chatUserMetadataLock()` (above) so concurrent metadata writers cannot lose updates. This invariant is documented in both `setUserMetadata` and `updateUserMetadata` docstrings; see also ADR-014 and [`tasks.md`](tasks.md) §3.

**Coupling note — every metadata writer must route through the cache:** `setUserMetadata(isUpdate=True)` and `_persistMemoryEntry` now read/merge against the cached row. A future contributor adding a raw `db.chatUsers.updateUserMetadata(...)` call that bypasses the cache (the way `chat_messages.py:154` bypasses it for `messages_count`) would silently desync the cache and corrupt subsequent `setUserMetadata(isUpdate=True)` merges. Do not add such bypasses for `metadata`.

**Lazy field independence:** a cached entry may carry `permanentMemories` without `userInfo`, or vice versa. Both are `NotRequired`; presence-of-key is the "loaded" sentinel. `CHAT_USERS` is `MEMORY_ONLY`, so `persistAll`/`loadFromDatabase` ignore it — cold cache at startup, warmed lazily on first `getChatUser`. The new methods do not touch `self.dirtyKeys` (that set is never flushed for `MEMORY_ONLY` namespaces).

**Write-through ordering:** all setters write the DB first and update the cache only on success, so a DB failure leaves the cache untouched (no cache-DB divergence).

**Tests:** [`tests/services/cache/test_user_info.py`](../../tests/services/cache/test_user_info.py) (cache unit tests), [`tests/bot/common/handlers/test_user_info_cache_regression.py`](../../tests/bot/common/handlers/test_user_info_cache_regression.py) (regression: a warm-message produces 0 `chat_users` DB reads/writes), [`tests/bot/common/handlers/test_spam_microopt.py`](../../tests/bot/common/handlers/test_spam_microopt.py) (conditional-refresh helper: at-or-above-threshold no-refresh, below-threshold refresh, cold-cache no-refresh, strict-`<` boundary + `markAsSpam` `+1` form). Plan of record: [`docs/plans/user-info-cache-plan-v1.md`](../plans/user-info-cache-plan-v1.md) (§16 supersedes §3/§14/§15 for the post-review contract).

---

### ADR-016: Unified `user_memories` Store (Structured Memories + vec0 + Tool Self-Management)

**Decision:** Every durable fact, preference, event, relationship, or high-level bio note about a user lives as one row in a single `user_memories` table (`migration_020`), discriminated by a `MemoryType` tag and a freeform `tags` set, split into **permanent** (always injected) and **ephemeral** (retrieved per turn) classes. Memories are searchable via a vec0 virtual table (`vec_user_memories_{dim}`, cosine distance) and are managed by the LLM itself through three tools (`add_memory` / `delete_memory` / `search_memories`). A per-message `userMemories` snapshot (injected at arrival time into `chat_messages.metadata`) replaces the old opaque per-message `userSummary` JSON injection.

**Context:** The predecessor (ADR-014) refined a single rolling-bio **string** per `(chat, user, thread)` — an opaque summary blob stored in `chat_users.metadata.memoryRefinement[threadId].summary` and injected whole into every chat turn as `EnsuredMessage.userSummary`. That design could not represent discrete facts, could not be searched, could not be selectively retained vs. expired, and forced the model to emit one re-written paragraph per run. The legacy `user_data` key-value table held durable facts but was equally opaque (one JSON blob per user, no type/tags, no search, no dedup). Both were LLM-read-only at chat time: the model could not add, delete, or look up a specific memory on demand.

The unified store gives each memory a `type` (`bio`/`preference`/`fact`/`event`/`relationship`), a `tags` set, a `permanent` flag, a `source` provenance, and an embedding — so memories are individually addressable, filterable, de-duplicated (cosine similarity at insert time), and curatable by the model itself.

**Components** (see [`memories/user-memories.md`](memories/user-memories.md) for the canonical durable summary):

- **`user_memories` table** (`migration_020`) — composite natural key `(chat_id, user_id, memory_id)` (no `AUTOINCREMENT`); `memory_id` is an app-generated UUID hex. Three indexes back the read paths (`idx_user_memories_chat_user_thread`, `idx_user_memories_chat_user_permanent`, `idx_user_memories_type`).
- **vec0 virtual table `vec_user_memories_{dim}`** — lazy-created at runtime by `UserMemoriesRepository._upsertVecMemoryEmbedding` on first write of a given dimension (mirrors `chat_embeddings._upsertVecMessageEmbedding`). NOT created by the migration. Carries `memory_id` (the row identifier), three partition keys (`chat_id`/`user_id`/`model`), a `permanent` filterable metadata column, and the `embedding` vector column (cosine distance); the `model` partition key scopes vectors per embedding model so a model swap does not cross-contaminate vector spaces. `thread_id` and `type` are deliberately NOT carried in vec0 (they were write-only and never read back); semantic search re-applies them in a JOIN step on the authoritative `user_memories` columns (`model` and `permanent` are pushed into the vec0 filter clause directly).
- **`UserMemoriesRepository`** (`internal/database/repositories/user_memories.py`, wired as `db.userMemories`) — 10 public methods (writes, reads, search, embedding persistence, model-drift regen helpers); all SQL goes through `BaseSQLProvider`.
- **3 LLM tools** (registered in `UserMemoriesHandler.__init__`, gated on the global `[user-memory].enabled` kill switch): `add_memory` (dedup state machine at insert), `delete_memory` (refinement-only at chat time — D3 gating forces `useTools[DELETE_MEMORY] = False` on every chat-time turn), `search_memories` (semantic or filter-only). Embeddings (tools + regen cron) are produced via `LLMService.generateEmbedding(text, chatId, chatSettings) -> Optional[Tuple[modelName, List[float]]]`; the old `internal/bot/common/memory_embedding_utils.py` helper module was removed.
- **Injection** — **centralised** in `MessagePreprocessorHandler.injectMemories()`, which runs at message-arrival time (inside `newMessageHandler`, before the message is saved): it loads permanent memories (from the `getChatUserPermanentMemories` cache) and ephemeral memories (semantic vec0 `searchMemories` driven by `LLMService.generateEmbedding` when memory embeddings are on — i.e. `MEMORY_ENABLED && EMBEDDINGS_ENABLED` — otherwise `getLatestMemories`, with a runtime semantic→latest fallback if the query embed fails), then writes the **compact memory IDs** into `chat_messages.metadata.memories` and warms the by-id cache (`cache.warmMemoriesByIds`). There is no per-message content field — `formatForLLM` resolves the IDs lazily at render time (ADR-018) and emits the resolved block under the JSON key `userMemories`. The previous `BaseBotHandler._buildMemoriesBlock` helpers and the four handler-level injection sites were deleted (there is no `<user-memories>` system-message block any more).

  > **Amendment (post-ship correction):** `injectMemories()` actually runs **after** `saveChatMessage(...)` inside `newMessageHandler`, not before — the saved row is then re-persisted with the compact IDs via a separate `db.chatMessages.updateChatMessageMetadata(...)` call. The `cache.warmMemoriesByIds(...)` method was planned but **not shipped**; the by-id cache populates lazily (cache-aside) on the first `formatForLLM` read via `cache.getMemoriesByIds`. See ADR-018's amendment below and [`docs/llm/handlers.md`](handlers.md) §1 (`MessagePreprocessorHandler`).
- **Regeneration cron** — `UserMemoriesHandler._runMemoryEmbeddingRegen` runs every 60s tick (outside `_refineLock`) and mirrors `ChatSearchHandler._dtCronJob` one-to-one, adapted for the single-store model: chat discovery round-robins over the in-memory `self._trackedChats: MutableSet[int]` (populated by `newMessageHandler` when memory embeddings are on — i.e. `MEMORY_ENABLED && EMBEDDINGS_ENABLED`), model-drift cleanup, stale detection (`getMemoriesWithoutEmbeddings`), re-embed loop. **Cold-start tradeoff (intentional):** `_trackedChats` is empty on restart and only grows from live inbound messages, so a chat with a backlog that stays quiet after a restart is not backfilled until the next qualifying message arrives; eviction is one-way — a chat dropped by a per-chat gate failure is not re-added until the next message. Never raises. (The previous DB-scan discovery — the deleted `ChatSettingsRepository` method that queried `chat_settings` for memory-embedding settings — and that repository method itself were both removed.)

**Consequences:**

- **Old `user_data` table is backfilled in** (permanent cross-thread `type='fact'`, `thread_id=NULL`); the table itself was **kept** for rollback safety at the time of this ADR — only the `add_user_data` / `delete_user_data` LLM tools that wrote it were retired.

  > **Follow-up correction:** `migration_022` subsequently DROPPED the `user_data` table entirely. It is no longer present in the schema; do not assume it still exists. (See the Note on `docs/database-schema.md` `user_memories`.)
- **Old rolling-bio blob is backfilled in** (permanent thread-scoped `type='bio'`, `tags=["migrated_bio"]`); the stale `chat_users.metadata.memoryRefinement` blob is left unread (the refinement rewrite stops writing it; only the message cursor is still persisted there).
- **Old `userSummary` injection path is removed entirely** — `EnsuredMessage.applyUserMetadata`, the `userSummary` field, the `formatForLLM` key, and the `chat-prompt-suffix` documentation line are all gone (Phase 4b). The per-message compact memory-ID snapshot (injected at arrival time, persisted in `metadata.memories`) fully replaces per-message summary JSON.
- **vec0 is the sole embedding store** — unlike chat-history search (`message_embeddings` BLOB table + vec0), `user_memories` has no BLOB side table. `embedding_model` / `embedding_dimensions` are tracked on `user_memories` itself; the vectors live only in vec0. When vec0 is unavailable, `searchMemories` returns `[]` (no numpy fallback).
- **Refinement rewrite** — `_runSingleRefinement` no longer emits a summary string; it curates the store live via the three tools during the LLM call. The accounting/cron/locking machinery (ADR-014) and the `chat_users` cursor persist (ADR-015) are unchanged.
- The per-tool JSONL refinement log now records `addCount` / `deleteCount` / `searchCount` (the primary observability for the grey-zone dedup review) instead of a summary string.

**Config:** `[user-memory]` (global kill switch + thresholds including `memory-reindex-batch-size`); per-chat memory settings under `[bot.defaults]` — master gate `MEMORY_ENABLED` (renamed in the chatSettings consolidation from the old injection-only flag), plus `MEMORY_REFINEMENT_ENABLED` / `MEMORY_REFINE_MODEL` / `MEMORY_REFINE_FALLBACK_MODEL` / `MEMORY_REFINE_SYSTEM_PROMPT` / `MEMORY_REFINE_USER_PROMPT_TEMPLATE`. Memory embeddings are a derived condition (`MEMORY_ENABLED && EMBEDDINGS_ENABLED`), not a separate flag; semantic memory retrieval happens when both are on, otherwise latest (runtime semantic→latest fallback on embed failure). See [`configuration.md`](configuration.md) §`[user-memory]` and [`memories/user-memories.md`](memories/user-memories.md).

**Relationship to ADR-014 / ADR-015:** ADR-014 documented the rolling-bio refinement machinery (cron + global lock + context injection); the cron/lock/accounting invariants still govern `_runSingleRefinement`, but the *storage* and *injection* decisions there are superseded by this ADR (structured store + centralised arrival-time per-message injection, not string blob + `userSummary` field). ADR-015's `chat_users` cache and `chatUserMetadataLock()` still back the refinement message-cursor persist.

---

### ADR-017: Memory Compaction v1 — Compact Per-Message ID Storage + By-Id Cache + Soft-Delete

**Decision:** Each message's `metadata["memories"]` stores **compact memory IDs** (`{"permanentIds": [...], "shortTermIds": [...]}`) instead of a full per-message content snapshot. The read path resolves IDs → content at render time through a new `CacheNamespace.MEMORIES_BY_ID` cache + `CacheService.getMemoriesByIds` + `UserMemoriesRepository.getMemoriesByIds`. `user_memories.deleteMemory` becomes a **soft delete** (sets `deleted_at`, drops vec0 + provenance; the row survives) so a historical message referencing a now-deleted memory can still resolve its content. Spec/plan: [`docs/plans/memory-compaction-v1.md`](../plans/memory-compaction-v1.md) (status: IMPLEMENTED).

**Context:** ADR-016's injection design persists the resolved memory content into `chat_messages.metadata.memories` per message so `formatForLLM` can render it later without a re-fetch. For a user with 10 permanent + 5 ephemeral memories, that is ~2–3 KB per message; the permanent block (~1.5 KB) is byte-identical across every message in the same `(chat, user, thread)`, so a 50-message thread carries ~75 KB of duplicated permanent-memory JSON. Compacting the storage to UUID lists and resolving at read time eliminates the **storage** duplication (IDs are ~tiny relative to content). Note: ADR-017 eliminated only the *storage* duplication — each message still *rendered* its full resolved content block into the LLM context, so the ~75 KB of rendered duplication persisted until ADR-018 (context dedup) moved resolution lazily into `formatForLLM` and deduplicated per-context. Soft-delete is required because a historical message that references a deleted memory must still resolve its content for the LLM — a hard `DELETE` would make it resolve to `None` and silently drop from the rendered block.

**Components** (see [`memories/user-memories.md`](memories/user-memories.md) "Injection" / "Read-path resolution" / "By-id resolution cache" for the canonical summary):

- **Migration 021** (`migration_021_user_memories_soft_delete`) — adds nullable `deleted_at TIMESTAMP` to `user_memories`. `down()` is a no-op that logs (portable `DROP COLUMN` unavailable; nullable additive column safe on rollback).
- **`deleteMemory` soft-delete** (`UserMemoriesRepository`) — `UPDATE ... SET deleted_at = :deletedAt, updated_at = :updatedAt WHERE ... AND deleted_at IS NULL` + `deleteMemoryEmbedding(..., vecOnly=False)` (drops vec0 + nulls provenance). Row survives; never raises; re-delete of an already-soft-deleted id returns `False`. `updateMemory` was **removed** (zero production callers; content changes go through `deleteMemory` + `addMemory`).
- **`AND deleted_at IS NULL`** added to all 8 live read methods (the live injection/search path skips soft-deleted rows). `getMemoriesByIds` is the single deliberate exception.
- **`getMemoriesByIds(memoryIds: List[str]) -> List[UserMemoryDict]`** — fetches by UUID list with NO `deleted_at` filter, no `chatId`/`userId` (UUIDs globally unique), routing to the default DB. The historical-resolution read path.
- **`CacheNamespace.MEMORIES_BY_ID` + `CacheService.getMemoriesByIds`** — MEMORY_ONLY cache-aside resolver (`:named`→keyed by mid; misses batch-queried; not-found IDs negative-cached as `None`). No invalidation method (soft-delete preserves content; `addMemory` doesn't invalidate a not-yet-cached entry; restart clears it).
- **Write path** (`MessagePreprocessorHandler.injectMemories`) — splits `userMemories` (resolved content for the current turn, with `id` stripped from permanent entries) from `metadata["memories"]` (the compact ID lists persisted into `chat_messages.metadata`). The permanent-memories cache loader switches to `keepId=True` so the write path can extract `permanentIds`.
- **Read path** (`EnsuredMessage.loadMemoriesMetadata` + `resolveMemories`) — `fromDBChatMessage` stashes compact IDs without resolving (avoids a `CacheService`→`ensured_message` circular import); each render site calls `await msg.resolveMemories(self.cache)` before `formatForLLM`/`toModelMessage`. An AST-based coverage guard (`tests/test_memory_resolution_coverage.py`) enforces every `fromDBChatMessage(injectMemories=<not literal False>)` render site is followed by `resolveMemories`, and bans the `setUserMemories(metadata-derived)` bypass.

**Consequences:**

- **Backward compat without backfill:** old messages keep their inline content snapshots (`{"permanent": [...], "shortTerm": [...]}`) and render unchanged via `setUserMemories`; new messages carry the compact ID shape. `loadMemoriesMetadata` detects the format. A zero-memory compact-format message now renders WITHOUT a `userMemories` block (was an empty block) — empty blocks are LLM noise.
- **Soft-deleted rows accumulate** — the `user_memories` table grows over time. GC is deferred (the safe shape requires a join against `chat_messages.metadata` JSON TEXT to check ID references; tracked as a follow-up).
- **Prompt hoisting deferred** — memories still attach per-message (resolved from cache); hoisting the permanent block to a single system message is a separate future feature for which this compact storage is a prerequisite.

**Implementation deviations from the plan** (recorded in the plan's status note and [`memories/user-memories.md`](memories/user-memories.md) "Read-path resolution"):

1. **`resolveMemories` does NOT re-point `metadata["memories"]`** (plan §5.2.2 said to call `setUserMemories`, which re-points metadata). The condense branch of `getThreadByMessageForLLM` writes `eRootMessage.metadata` (whole dict) back to DB — re-pointing to resolved content would persist content over compact IDs for condensed-thread root messages, defeating compaction. Fix: `resolveMemories` populates `self.userMemories` only (deepcopy), leaving `metadata["memories"]` as compact IDs. (This contradicts the plan's claim that "no read-path consumer re-persists the message" — that claim is false for the condense path.)
2. **By-id cache uses `keepId=False`** (plan §4.3 said `keepId=True`). The cache is the read-path resolver: entries are looked up by dict key (the key IS the id), and `formatForLLM` renders content verbatim, so storing `id` would leak a uuid into the LLM prompt (violating `SingleMemoryDict.id`'s "absent on injected snapshots" invariant). The separate permanent-memories cache uses `keepId=True` (write path needs the ids).
3. **`resolveMemoriesBatch` deferred.** `getThreadByMessageForLLM`'s build-render-interleaved structure has no clean "collect all then resolve" call site, so per-message `resolveMemories` is used everywhere (correct per plan §5.2.3, just one DB query per message on a cold cache; warm cache makes subsequent messages cheap).
4. **AST coverage guard** implemented with a dynamic scan over `internal/` (not a fixed file list) + target-tracking for the `eRootMessage` exemption (built but never rendered) + `setUserMemories(metadata-derived)` bypass ban. 8 sanity tests prove detection.

> **Count reconciliation:** the plan records 6 deviations while ADR-017 lists 4 numbered implementation deviations because #5 (the `_llmToolGenerateImage`→`draw_command` symbol drift) is a plan-internal self-correction — ADR-017 names `draw_command` correctly throughout — and #6 (a zero-memory compact-format message omits the `userMemories` block) is recorded under ADR-017's **Consequences** above, not as a deviation.

**Follow-up refactor (2026-07-10, 3101 tests):** The sections above are the
original ADR-017 snapshot. A post-implementation refactor tightened the
read/write paths (detail in [`memory-compaction-v1.md`](../plans/memory-compaction-v1.md)
§10 "Follow-up refactor"):

- **Cache namespace renamed:** `MEMORIES_BY_ID`/`"memoriesById"`/property
  `memoriesById` → `MEMORIES`/`"memories"`/property `memories`. Same
  MEMORY_ONLY cache-aside resolver for `memory_id → SingleMemoryDict`, same
  negative-caching-of-`None` semantics.
- **`getMemoriesByIds` routing (repo + cache):** both
  `UserMemoriesRepository.getMemoriesByIds(memoryIds, *, chatId=None,
  dataSource=None)` and `CacheService.getMemoriesByIds(...)` now accept
  optional `chatId`/`dataSource`, forwarded to
  `getProvider(chatId=..., dataSource=..., readonly=True)`. Default `None` →
  default DB. The cache key stays the memory UUID (routing only selects which
  DB is queried on miss).
- **`fromDBChatMessage` `cache=` param:** `fromDBChatMessage(cls, data, db,
  *, forceGetAllMedia=False, injectMemories: bool, cache: Optional[CacheService]=None)`.
  When `injectMemories and cache is not None`, it calls `resolveMemories(cache)`
  internally. The six render sites pass `cache=self.cache`; `eRootMessage`
  (never rendered) passes `cache=None`.
- **`setUserMemories` is now the write-path setter:** takes content whose
  entries carry `id` (`keepId=True`), strips `id` into `userMemories` AND
  extracts `permanentIds`/`shortTermIds` into `metadata["memories"]`. The write
  path `injectMemories` routes through it. The read path (`resolveMemories`)
  still assigns `userMemories` directly without touching metadata (deviation
  #1 — unchanged).
- **`loadMemoriesMetadata` REMOVED / decision #7 superseded:** only the
  compact format is supported. The old content-format read-path branch is
  gone; old-format messages render with no memories (and log a conversion
  warning until cleared by the cleanup script). Mitigated by
  `scripts/clear_old_format_memories.py`.
- **`CompactMemoryIdsDict` added** (`internal/bot/models/message_metadata.py`):
  `{permanentIds: list[str], shortTermIds: list[str]}`.
  `MetadataDict.memories` is now `CompactMemoryIdsDict | UserMemoriesDict`
  (compact first — `sqlToCustomType` tries the common shape first, avoiding a
  spurious ERROR log; eliminated the `# type: ignore[assignment]` writes).
- **AST guard updated:** Check 1 now verifies each
  `fromDBChatMessage(injectMemories=<truthy>)` render site passes a non-None
  `cache=` keyword (was: looks for an external `resolveMemories`). Check 2
  (ban `setUserMemories(metadata-derived)`) unchanged; 9 sanity tests.

---

### ADR-018: Memories Context Deduplication — Lazy Render-Time Resolution + Newest→Oldest Per-Context Dedup

**Decision:** Drop the `EnsuredMessage.userMemories` content field entirely; resolve compact memory IDs to content **lazily, on-demand, inside `formatForLLM`** (not at load time), and render each memory **exactly once per rendered context** via a newest→oldest exclusion computation. `metadata["memories"]` (`CompactMemoryIdsDict`: `{permanentIds, shortTermIds}`) is now the sole canonical source of which memories a message carries. Spec/plans: [`docs/plans/memories-context-dedup-plan-v1.md`](../plans/memories-context-dedup-plan-v1.md), [`memories-context-dedup-plan-v2.md`](../plans/memories-context-dedup-plan-v2.md) (status: IMPLEMENTED).

**Context:** ADR-017 compacted *storage* to UUID lists but each message still rendered its full resolved content block into the LLM context — the permanent block (~1.5 KB) was duplicated ~N× across a thread (~75 KB for a 50-message thread). Three symbols encoded the eager, per-message, duplicated model: `EnsuredMessage.userMemories` (a per-message content snapshot field), `EnsuredMessage.resolveMemories` (eagerly resolved IDs→content at load time, before any render), and `EnsuredMessage.setUserMemories` (the write-path setter that split content from compact IDs). This ADR removes all three and moves resolution to render time with per-context deduplication, so each memory appears at most once in a given rendered context (at its newest occurrence).

**Components** (see [`memories/user-memories.md`](memories/user-memories.md) "Injection" / "Render-time resolution (lazy + dedup)" for the canonical summary):

- **`EnsuredMessage.userMemories` field REMOVED** (attribute + `__slots__` entry). The JSON output key `"userMemories"` still exists (built as a LOCAL dict inside `formatForLLM`), but there is no longer a per-message content attribute holding it.
- **`EnsuredMessage.resolveMemories` REMOVED** — resolution moved from load time into `formatForLLM`'s JSON branch. `fromDBChatMessage` lost its `injectMemories`/`cache` params (metadata IDs come straight from the DB row).
- **`EnsuredMessage.setUserMemories` REMOVED** — the write path (`MessagePreprocessorHandler.injectMemories`) now writes compact IDs directly into `metadata["memories"]` and pre-populates the by-id cache via `cache.warmMemoriesByIds(...)`.
- **`EnsuredMessage.getMemoryIds() -> Set[str]`** (new) — merged union of both cohorts from `metadata["memories"]`; the dedup algorithm's input.
- **`CacheService.warmMemoriesByIds(entries, *, chatId)`** (new) — pre-populates the `MEMORIES` namespace so the current message's render-time resolution is a cache HIT (avoids a redundant DB batch query on the inbound message).

  > **Amendment (post-ship correction):** `CacheService.warmMemoriesByIds` was specified here but **not shipped** — the method does not exist in the codebase. The `MEMORIES` namespace populates lazily (cache-aside) on the first `formatForLLM` read via `cache.getMemoriesByIds`. Additionally, `injectMemories()` runs **after** `saveChatMessage(...)` (not before the row is saved); because it mutates `metadata` after the initial insert, the compact IDs are re-persisted to `chat_messages.metadata` via a separate `db.chatMessages.updateChatMessageMetadata(...)` call. See [`docs/llm/handlers.md`](handlers.md) §1 (`MessagePreprocessorHandler`) and [`memories/user-memories.md`](memories/user-memories.md).
- **`formatForLLM` / `toModelMessage` / `toModelMessageList`** now take **required** keyword-only `cache: Optional[CacheService]` + `excludeMemoryIds: Set[str]` (no defaults — pyright enforces every caller; the original `Optional[...] = None` defaults were dropped to make the silent-memory-drop class of bug impossible by construction). The JSON branch resolves IDs on-demand via `cache.getMemoriesByIds(...)` (only when `cache is not None`), filters each cohort by `excludeMemoryIds` before resolving, omits the `"userMemories"` key when `cache is None` / no IDs survive / nothing resolves, and **never mutates `self.metadata`** (the condense branch persists `eRootMessage.metadata` to DB, so mutating it during render would corrupt the persisted compact IDs).
- **Per-context deduplication is applied INLINE at each call site** (no shared helper). Each call site walks its message sequence newest→oldest, accumulating an exclude-set: for each message it applies `excludeMemoryIds = ownIds ∩ seen`, then adds its own IDs to `seen`. In `getThreadByMessageForLLM` the tail messages are walked newest→oldest into a `deque` (the `excludedMemoryIds` set accumulates each message's `getMemoryIds()`); `handleRandomMessage` does the same across its history+current sequence. Condense-summary plain-text messages carry no memory blocks and never participate in dedup.

**Consequences:**

- **Rendered-context duplication eliminated:** the newest message renders its full memory set; each older message renders only memories not already shown by any newer message; each memory appears exactly once, at its latest (newest) occurrence. ~75 KB → ~1.5 KB for the permanent block in a 50-message thread.
- **Condense-replay root exemption (accepted trade-off):** in the condense-replay path of `getThreadByMessageForLLM`, the single `keepFirstN` (root) message is EXEMPT from dedup — it renders its full memory set (`excludeMemoryIds=set()`) to keep the assembly code simple. Consequence: a memory present in BOTH the root and a newer tail message may appear twice (once at the root, once at its latest tail occurrence). The common (non-condensed) thread case is unaffected: there the root participates in the newest→oldest walk and deduplicates normally.
- **Lazy resolution is per-render, not per-load:** a message can be rendered many times (or never); resolution happens only when actually formatted for the LLM. On chat-context render paths, `cache` is gated on the `MEMORY_ENABLED` chat setting (`cache=self.cache if needMemories else None`), so memories render only when injection is enabled for the chat; non-chat / TEXT paths pass `cache=None, excludeMemoryIds=set()` explicitly and render no memories.
- **Non-mutation invariant preserved:** `formatForLLM` and `getMemoryIds` READ `metadata["memories"]` only — the condense-branch re-persistence hazard (ADR-017 deviation #1) is inherited and respected.
- **Signature enforcement (no AST value guard):** the render methods (`formatForLLM`/`toModelMessage`/`toModelMessageList`) declare `cache`/`excludeMemoryIds` as **required** keyword-only params (no defaults), so pyright errors on any caller that omits either kwarg — this is the structural enforcement that the kwargs are *present*. There is intentionally **no** AST guard that checks the *value* passed to `cache=` (such a guard cannot robustly distinguish chat-context paths, which must pass `cache=self.cache`, from non-chat / TEXT paths, which must pass `cache=None`); value-correctness is upheld by the call-site audit and the test suite instead. `tests/test_memory_resolution_coverage.py` retains only Check-2 (the `setUserMemories`/metadata-bypass ban), now a vacuous regression guard against reintroduction of the removed setter.
- **Stale-ID behavioral delta:** when all referenced memory IDs fail to resolve, the `"userMemories"` key is OMITTED entirely (previously emitted an empty-cohort dict `{"permanent": [], "shortTerm": []}`).

**Relationship to ADR-017:** ADR-017 established compact ID storage + the by-id cache + soft-delete — all of which this ADR builds on unchanged. This ADR only changes the *resolution* timing (load→render), the *write* path (no per-message content field), and adds per-context *deduplication*. ADR-017's `resolveMemories`/`setUserMemories`/`fromDBChatMessage(injectMemories=, cache=)` machinery (and the follow-up refactor note above) is superseded by this ADR.

---

### ADR-019: Condensed-Context Retrieval — Coverage Tracking + Lazy JSON Render + `get_messages_by_ids` Tool

**Decision:** When the LLM's conversation context is condensed (older messages summarised to fit the context window), record *which* message IDs each summary covers plus structured metadata (participants, date range, message count) on the persisted `CondensingDict`; render every condensed summary as a JSON object (consistent with the real-user-message JSON shape) via a shared lazy renderer; and expose an `get_messages_by_ids` LLM tool so the model can fetch the originals underlying a summary on demand. Spec: [`docs/plans/condensed-context-retrieval-plan-v1.md`](../plans/condensed-context-retrieval-plan-v1.md) (status: IMPLEMENTED, then SIMPLIFIED 2026-07-13 — see note below).

> **Simplification (2026-07-13):** The original implementation computed coverage metadata on the *caller* side via a `returnCoverage` kwarg on `condenseContext`, `CondenseBatchCoverage` index ranges, and parallel `indexToEntry`/`indexToEntry2` lists that mapped indices back to source rows. That caller-side index-range machinery was **deleted** and replaced by `ModelMessage.source`-based provenance: coverage is now computed *inside* `condenseContext` by the `generateCondensingDict` helper, which walks each batch's `ModelMessage`s and reads `.source`. The callers (Path A / Path B) simply consume `condensingDictMap.values()` — no parallel-list bookkeeping. This ADR describes the simplified design.

**Context:** Two persistent write sites summarise older messages into a `role="user"` `ModelMessage` so the context fits the model window:

- **Path A — `condensedThread`** (`BaseBotHandler.getThreadByMessageForLLM`, [`base.py`](../../internal/bot/common/handlers/base.py)) stores `List[CondensingDict]` under `chat_messages.metadata.condensedThread` and re-summarises (cascade) when the rebuilt context still overruns.
- **Path B — `randomContext`** (`LLMMessageHandler.handleRandomAnswer`, [`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py)) stores a single summary under `chat_messages.metadata.randomContext` when the random-answer history is too long.

The originals are **always retained** in `chat_messages` (condensing adds summary metadata; it never deletes source rows). Three problems existed:

1. **Lost detail, no recovery path.** Once condensed the LLM saw only the summary text — there was no tool to fetch the originals, so the summary was the ceiling of detail for those messages for the rest of the conversation.
2. **Unidentifiable coverage.** The legacy `CondensingDict` recorded only a *boundary* marker (`tillMessageId`/`tillTS`) — not *which* messages a summary actually covered. Re-condense cascades and multi-batch summaries lost precision.
3. **Latent render asymmetry.** Real user messages are rendered as **JSON** (`EnsuredMessage.formatForLLM` JSON branch), but condensed summaries were injected as **raw text** `role="user"` at both sites. This was an undocumented asymmetry the LLM had to silently accommodate.

**Components** (see [`internal/bot/models/message_metadata.py`](../../internal/bot/models/message_metadata.py) and [`internal/services/llm/service.py`](../../internal/services/llm/service.py)):

- **`CondensingDict` evolution** — only `text` is required; all other fields (`tillMessageId`, `tillTS`, `messageIds`, `participants`, `dateRange`, `messageCount`) are `NotRequired`. Legacy rows carry `text` + the boundary markers; new writes populate `messageIds` as the authoritative coverage list. `tillMessageId`/`tillTS` are **legacy boundary markers NOT set by `generateCondensingDict`** — readers use `in`/`.get()` checks and fall back to `dateRange`/`messageIds` when absent.
- **`CondensedDateRangeDict`** — functional-syntax TypedDict `{"from": float, "to": float}` (the JSON key `from` is a Python reserved keyword, so class-body syntax would be a `SyntaxError`; functional syntax is the only way to express it). This is the *storage* shape — two unix-timestamp floats. The renderer converts to ISO strings at call-time; ISO strings are **not** pre-baked into storage (mirrors how real messages render `date`).
- **`MetadataDict.randomContext` reshape** — widened from `str` to `Union[str, CondensingDict]`. Path B new writes store a single `CondensingDict` (one summarisation possible per random context); legacy `str` rows are pre-wrapped into `CondensingDict(text=...)` by the read site before calling the renderer.
- **`CondensedSummaryKind(StrEnum)`** — single-member render-side discriminator (`CONDENSED = "condensed"`) for the JSON `"type"` key. **Deliberately separate from `MessageType`** (which classifies real message *media*: text/image/sticker). `condensed` is a render-only construct; the JSON shape is structurally disjoint from real user messages (carries `coveredMessageIds`/`participants`/`dateRange`/`messageCount`/`summary` instead of `login`/`name`/`messageId`/`text`/...), so the shared `"type"` key never collides.
- **`generateCondensingDict(text, messages) -> CondensingDict`** (module-level in `service.py`) — the coverage producer. Walks the batch's `ModelMessage`s and reads each `.source`:
  - `EnsuredMessage` source → extract `messageId` / `sender.username` / `date.timestamp()` (a raw source message).
  - `dict`/`CondensingDict` source → union existing fields (re-condense cascade).
  - `None` source (tool-history emissions) → `logger.warning` + skip, NOT counted in `messageCount`.
  - Returns `CondensingDict` with `text` + conditionally-populated `messageIds` / `participants` (sorted unique) / `dateRange` (`{from:min ts, to:max ts}`, omitted if none) / `messageCount`. Does NOT set `tillMessageId`/`tillTS`. Wrapped in try/except → fallback `CondensingDict(text=respText)` on failure (summary preserved, coverage dropped).
- **`condenseContext` always-tuple return** ([`internal/services/llm/service.py`](../../internal/services/llm/service.py)) — signature: `condenseContext(messages, model, *, keepFirstN=0, keepLastN=1, condensingModel=None, condensingPrompt=None, condensingSystemPrompt=None, maxTokens=None, force=False)`. **Always** returns `Tuple[Sequence[ModelMessage], Dict[int, CondensingDict]]`: first element = condensed message list (head + summaries + tail); second = `Dict[int, CondensingDict]` keyed by body-index → fully-populated `CondensingDict` (coverage computed inside via `generateCondensingDict` reading `ModelMessage.source`). When no condensing occurs the second element is `{}`. Path C (`generateTextViaLLM`) unpacks `_messages, _ = await self.condenseContext(...)` — byte-identical behaviour, ignores coverage.
- **`renderCondensedSummary(data: CondensingDict) -> str`** — shared JSON renderer (module-level in `message_metadata.py`). **Signature narrowed to `CondensingDict`-only** (no legacy `str` branch); the Path B read site pre-wraps legacy `str` rows into `CondensingDict(text=randomContext)` before calling. Output shape: `{type:"condensed", coveredMessageIds:[...], participants:[...], dateRange:{"from":<ISO>,"to":<ISO>}, messageCount:N, summary:"..."}`. Falsy-drop mirrors `formatForLLM` (empty/absent fields omitted, never `null`); `type`+`summary` always present. Both injection sites call this (Path A at `base.py`; Path B at `ensured_message.py`'s `toModelMessageList`), replacing the raw `condensedMessage["text"]` / raw-string injections.
- **`mergeCondensingDicts(dictList) -> CondensingDict`** (module-level in `message_metadata.py`) — unions multiple `CondensingDict`s: `text` = `"\n".join`; `messageIds` = concat de-duped via `asStr()` first-seen order; `participants` = sorted-unique set union; `dateRange` = min/max; `messageCount` = sum. Used by Path B to merge all batches into a single `randomContext`.
- **Caller consumption (simplified)** —
  - **Path A** (`getThreadByMessageForLLM`): `condensedRet, condensingDictMap = await self.condenseContext(...)`; `condenseCache.extend(condensingDictMap.values())` (or `= list(...)` for re-condense). No parallel-list machinery.
  - **Path B** (`handleRandomAnswer`): `condensedRet, condensingDictMap = await self.condenseContext(...)`; `if condensingDictMap: ensuredMessage.metadata["randomContext"] = mergeCondensingDicts(condensingDictMap.values())` (SKIP write when coverage empty — nothing meaningful to persist).
- **`get_messages_by_ids` LLM tool** ([`chat_search.py`](../../internal/bot/common/handlers/chat_search.py)) — registered in `ChatSearchHandler.__init__` as a normal `registerTool(...)` call alongside the other search tools (constant `ToolName.GET_MESSAGES_BY_IDS`, `internal/bot/constants.py`). Accepts a list of ID strings (batch; `extra={"items": {"type": "string"}}` so the emitted JSON-Schema forces strings — `MessageId` is `int|str`). Returns `{messages:[...EnsuredMessage JSON...], notFound:[...], count:N}`, reusing `_formatMessageDict`. Never-raise (whole body wrapped in try/except). **Three-layer gating**: (1) `[search-history].enabled` via the handler's existing conditional registration (the tool rides the handler's gate — *no manager.py change*); (2) `ALLOW_TOOLS_COMMANDS` per-chat master toggle at tool-resolution time; (3) **NOT** gated on `EMBEDDINGS_ENABLED` or any search-specific flag (pure DB lookup — available whenever chat-search is on, even with semantic search disabled).
- **`getChatMessagesByMessageIds` batch repo method** ([`chat_messages.py`](../../internal/database/repositories/chat_messages.py)) — portable `IN (:id0, :id1, ...)` named-placeholder expansion; early-returns `[]` on empty input; same JOIN shape as `getChatMessageByMessageId`; `ORDER BY c.date ASC`. Backs the tool.

**`chat-prompt-suffix`** (`configs/00-defaults/bot-defaults.toml`, `BOT_OWNER_SYSTEM`-gated page) gained a Russian block documenting the condensed-summary JSON shape (`type:"condensed"` + the 5 field bullets) and the `get_messages_by_ids` tool reference, so the model is explicitly told originals are retrievable.

**Key decisions:**

- **Coverage computed inside `condenseContext` via `ModelMessage.source`.** `condenseContext` operates on `ModelMessage` objects. In the simplified design each batch's `ModelMessage`s carry a `.source` attribute (set by the caller when building the message list): an `EnsuredMessage` for raw messages, or a `dict`/`CondensingDict` for re-condensed summaries. `generateCondensingDict` reads `.source` to extract `messageId`/`username`/`timestamp` — no index-range machinery, no parallel lists, no caller-side metadata mapping. Path C (`generateTextViaLLM`) unpacks `_messages, _` and ignores the coverage map, so its behaviour is unchanged.
- **Store-IDs-render-lazily mirrors ADR-018.** `messageIds`/`participants`/`dateRange` are stored as structured data on the `CondensingDict`; the JSON render with ISO-converted `dateRange` happens at call-time via `renderCondensedSummary`, never pre-baked into storage. Format-agnostic storage; a future render format change needs no data migration.
- **`CondensedSummaryKind` separate from `MessageType`.** Adding `condensed` to `MessageType` (the media-classification enum) would pollute it with a render-only construct. The JSON shapes are structurally disjoint, so a separate single-member `StrEnum` is unambiguous and self-documenting via the prompt suffix.
- **Path B `randomContext` reshape `str → CondensingDict` with defensive legacy read.** Only one summarisation is possible for random context, so it is a single `CondensingDict` (not a list). The union type + renderer handle legacy `str` rows gracefully (read site pre-wraps into `CondensingDict(text=...)`; no migration needed).
- **`tillMessageId`/`tillTS` relaxed to `NotRequired`** (simplification decision). `generateCondensingDict` does NOT set them; readers use `in`/`.get()` checks and fall back to `dateRange`/`messageIds`. They remain on legacy rows and are read defensively.
- **Backwards-compat without migration.** Old rows (legacy `CondensingDict` with boundary markers; legacy `randomContext` as flat `str`) render correctly via `renderCondensedSummary` — degraded (no `coveredMessageIds`, so the model cannot call `get_messages_by_ids` for them) but consistent output shape. New rows are richer.

**Relationship to ADR-018:** This ADR mirrors ADR-018's store-IDs-render-lazily discipline (structured data on the row; lazy JSON render at the injection site). It is independent of the memories subsystem (ADR-016/017/018) — it concerns the *condensing* path (`condensedThread`/`randomContext`), not the per-message memory-injection path.

> **Known pre-existing bug (out of scope, tracked separately):** a confirmed infinite-loop hazard in the `condenseContext` adaptive batch-shrink branch was NOT fixed by this feature and is tracked separately. Do not document a fix here.

---

## 2. Dependency Map

### 2.1 Component Dependency Graph

```
GromozekBot (main.py)
├── ConfigManager (internal/config/manager.py)
├── DatabaseManager (internal/database/manager.py)
│   └── Database (internal/database/database.py)
│       └── MigrationManager (internal/database/migrations/manager.py)
├── LLMManager (lib/ai/manager.py)
│   └── AbstractLLMProvider (lib/ai/abstract.py)
│       └── AbstractModel (lib/ai/abstract.py)
├── RateLimiterManager (lib/rate_limiter/manager.py)
└── BotApplication (Telegram or Max)
    └── HandlersManager (internal/bot/common/handlers/manager.py)
        ├── CacheService.getInstance() (internal/services/cache/service.py)
        ├── StorageService.getInstance() (internal/services/storage/service.py)
        ├── QueueService.getInstance() (internal/services/queue_service/service.py)
        └── [All Handler instances]
            └── BaseBotHandler (internal/bot/common/handlers/base.py)
                ├── CacheService.getInstance()
                ├── QueueService.getInstance()
                ├── StorageService.getInstance()
                ├── LLMService.getInstance() (internal/services/llm/service.py)
                ├── Database (via self.db)
                ├── LLMManager (via self.llmService.getLLMManager())
                ├── ConfigManager (via self.configManager)
            └── TheBot (internal/bot/common/bot.py) [injected]
                ├── CacheService.getInstance()
                └── Platform API (Telegram ExtBot or MaxBotClient)
                        (Max webhook mode: MaxBotClient polls the local
                         webhook receiver's GET /updates via basePollingUrl
                         instead of platform-api2.max.ru — see ADR-013)
```

**Separate process — Max webhook receiver** (only when webhook mode is deployed; see ADR-013):

```
python -m internal.max_webhook_receiver  (aiohttp.web)
├── ConfigManager (internal/config/manager.py)
├── Database (internal/database/database.py)  [shared SQLite with the bot]
│   └── webhookUpdates repository  →  webhook_updates table (migration_019)
├── POST <webhook-path>  ← Max API webhook POSTs
└── GET /updates          → MaxBotClient._pollingLoop() via basePollingUrl
```

### 2.2 Service Initialization Order (Critical)

Services MUST be initialized in this order:

1. `ConfigManager` — first, everything needs config
2. `DatabaseManager` / `Database` — second, services need DB
3. `LLMManager` — third, LLMService needs it
4. `RateLimiterManager.getInstance().loadConfig(...)` — fourth
5. `ProxyHelper.setGlobalProxyConfig()` + `ProxyService.getInstance().initialize(configManager.getProxyConfig(), loop=loop)` — fifth. Starts global proxy lifecycle immediately via the shared event loop (`loop.run_until_complete()`). Registers CRON_JOB/DO_EXIT handlers for health checks and graceful shutdown.
6. `BotApplication` init — which triggers:
   - `HandlersManager.__init__()`:
     - `CacheService.getInstance()` + `cache.injectDatabase(db)`
     - `StorageService.getInstance()` + `storage.injectConfig(configManager)`
     - `QueueService.getInstance()`
     - All handler constructors (which get `CacheService`, `QueueService`, etc.)
7. `HandlersManager.injectBot(bot)` — injects `TheBot` into all handlers

### 2.3 What Breaks if You Modify These Files

| File Modified | What Could Break | Verification |
|---|---|---|
| [`internal/database/database.py`](../../internal/database/database.py) | All DB operations, all handlers that use `self.db` | `make test` — `tests/database/integration/` |
| [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py) | ALL handlers (they all inherit from `BaseBotHandler`) | Full `make test` |
| [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py) | Handler chain order, command routing, parallelism | Full `make test` |
| [`internal/config/manager.py`](../../internal/config/manager.py) | Config loading for the entire app | Full `make test` |
| [`internal/services/cache/service.py`](../../internal/services/cache/service.py) | Chat settings, user data, admin caching | Full `make test` |
| [`lib/ai/abstract.py`](../../lib/ai/abstract.py) | ALL LLM provider implementations | `make test` — `tests/lib/ai/` |
| [`lib/ai/manager.py`](../../lib/ai/manager.py) | Model selection, provider init | `make test` — `tests/lib/ai/` |
| [`lib/ai/models.py`](../../lib/ai/models.py) | Message format, tool definitions | ALL handler tests that use LLM |
| [`lib/cache/interface.py`](../../lib/cache/interface.py) | All cache implementations | `make test` — cache tests |
| [`internal/bot/common/bot.py`](../../internal/bot/common/bot.py) | All message sending/receiving operations | Full `make test` |
| [`lib/markdown/parser.py`](../../lib/markdown/parser.py) | All message formatting in both platforms | Markdown tests in `tests/lib/markdown/` |

### 2.4 Safe vs. Risky Modifications

#### Safe (isolated)
- Adding a new repository to `Database` without changing existing repositories
- Adding a new handler file without modifying `manager.py`
- Adding a new config getter to `ConfigManager`
- Adding a new LLM provider to `lib/ai/providers/`
- Adding tests

#### Moderate Risk ()
- Modifying `CacheService` internal data structures
- Changing handler execution order in `HandlersManager`
- Modifying `BaseBotHandler.sendMessage()` signature

#### High Risk (ALWAYS run full `make test`)
- Modifying `BaseBotHandler.__init__()` signature
- Changing `Database` core connection methods or repository interfaces
- Modifying `ConfigManager._loadConfig()` or `_mergeConfigs()`
- Changing `TheBot.sendMessage()` signature
- Modifying `HandlersManager._processMessageRec()`
- Changing any TypedDict structure in `internal/database/models.py`
- Changing `HandlerResultStatus` enum values

---

## 3. Design Patterns

### 3.1 Service-Oriented Architecture

Three-layer structure:
- **Bot Layer**: [`internal/bot/`](../../internal/bot/) — Multi-platform handlers and managers
- **Service Layer**: [`internal/services/`](../../internal/services/) — Cache, queue, LLM, storage
- **Library Layer**: [`lib/`](../../lib/) — Reusable components (AI, markdown, APIs, filters)

### 3.2 Database Patterns

- **Migration System**: Auto-discovery with version tracking from `versions/` directory
- **TypedDict Models**: Runtime validation for all database operations
- **Transaction Safety**: Automatic rollback on failures

### 3.3 Memory Optimization

- Use `__slots__` for all data classes and models
- Singleton services: Cache and queue services use singleton pattern
- Namespace organization: Logical separation with persistence options

### 3.4 API Integration Standards

- **Rate Limiting**: Sliding window algorithm with per-service limits
- **Caching Strategy**: TTL-based with namespace organization
- **Error Handling**: Proper timeout and retry mechanisms
- **Golden Testing**: Deterministic testing without API quotas

### 3.5 Migration Documentation Protocol

**Critical lesson from migration_009 and migration_012 errors**

When creating or modifying database migrations, ALWAYS:

1. **Read ALL Existing Migrations First**
   - Never assume what migrations do from their names
   - Read the actual migration code for all relevant migrations
   ```bash
   ls internal/database/migrations/versions/
   # Then read each migration file to understand its purpose
   ```

2. **Verify Migration Functionality**
   - Check what columns/tables each migration actually adds/removes
   - Cross-reference with existing documentation
   - Identify any gaps or inconsistencies in current docs

3. **Document Only Actual Changes**
   - Each migration should only document what IT does
   - Never mix functionality from different migrations
   - Preserve complete migration history timeline

4. **Validate Documentation Changes**
   - Review all migrations mentioned in docs still exist
   - Ensure no migrations are accidentally omitted
   - Verify column attributions match actual migration code

5. **Update Both Human and LLM Documentation**
   - Update `docs/database-schema.md` AND `docs/database-schema-llm.md`
   - Add migration entry to the migrations list with description
   - Update affected table schemas with new columns
   - Update example queries if column affects common operations

### 3.6 Migration Versioning Protocol

**Critical lesson from migration version conflict**

**Mandatory Migration Creation Protocol:**

1. **ALWAYS Check Existing Migrations First**
   ```bash
   ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
   # This shows the highest numbered migration file
   ```

2. **Version Calculation Rule:**
    ```
    New Migration Version = Latest Migration Version + 1
    ```
    Example: If highest is `migration_012`, create `migration_013`

3. **Never assume the next version** — always list the directory first

---

## See Also

- [`index.md`](index.md) — Project overview, mandatory rules, project map
- [`handlers.md`](handlers.md) — Handler system details and creation guide
- [`database.md`](database.md) — Database operations, migrations, multi-source routing
- [`services.md`](services.md) — Service integration patterns (Cache, Queue, LLM, Storage)
- [`configuration.md`](configuration.md) — TOML configuration reference
- [`tasks.md`](tasks.md) — Step-by-step common task workflows

---

*This guide is auto-maintained and should be updated whenever significant architectural changes are made*
*Last updated: 2026-07-12*
