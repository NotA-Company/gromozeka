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
10. (Telegram only) `DeleteFromUserMessageHandler` — PARALLEL — must run before reaction (no point reacting to a message we're about to delete)
11. (Telegram only) `ReactOnUserMessageHandler` — PARALLEL
12. (Telegram only) `TopicManagerHandler` — PARALLEL
13. (if enabled) `WeatherHandler` — PARALLEL — weather forecasts
14. (if enabled) `YandexSearchHandler` — PARALLEL — Yandex search
15. (if enabled) `ResenderHandler` — PARALLEL — message forwarding
16. (if enabled) `DivinationHandler` — PARALLEL — tarot/runes divination
17. (if enabled) `SandboxHandler` — PARALLEL — sandboxed code execution
18. (if enabled) `ChatSearchHandler` — PARALLEL — chat search /search command
19. (if enabled) `StatsHandler` — PARALLEL — usage statistics display (gated by `[stats].enabled`, registered after ChatSearchHandler, before custom handlers; see manager.py:612-619)
20. (custom handlers via `CustomHandlerLoader`) — PARALLEL by default (configurable per-handler)
21. `LLMMessageHandler` — SEQUENTIAL — **MUST BE LAST**

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
- Provider abstraction layer (`lib/db/providers/`) handles database-specific SQL dialects
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
- `EmbeddingModelsRepository` — Embedding-model lookup table (`models` table, backed by `migration_025_embedding_model_lookup`); resolves model name + dimensions to a stable `model_id` integer that the embedding repos (chat-search + user-memories) FK into. Process-local cache; constructor-injected `modelIdResolver` (D10) in the three refactored repos.
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
from internal.database.repositories import DivinationsRepository

repo = DivinationsRepository(db.manager)
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
- `[stats] enabled = false` (default) — when enabled, `StatsAggregationService.getInstance().initialize(configManager, database)` is called (synchronous) and the factory `createStatsStorage(eventType, dataSource)` constructs and registers five storages (LLM, tool, STT, message, command). The factory reads `[stats] enabled` itself; when disabled, it returns unregistered `NullStatsStorage` and the registry stays empty.
- `aggregation-interval-seconds` (default `3600`) — periodic aggregation cycle cadence in seconds (minimum 60, gated on shared CRON_JOB tick)
- `events-retention-days` (default `30`) — retention window for processed `stat_events` rows (day-truncated UTC midnight cutoff); `0` = keep forever

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
- **Lock ordering for nested metadata RMW:** the cursor-persist block inside `_runSingleRefinement` (`user_memories.py`, runs under `_refineLock`) acquires `CacheService.chatUserMetadataLock()` to serialize its read-modify-write of `chat_users.metadata` against `setUserMetadata(isUpdate=True)`. (The Phase 4a refinement rewrite inlined this cursor persist — it was formerly a standalone `_persistMemoryEntry` method; see [`memories/chat-users-cache.md`](memories/chat-users-cache.md).) The ordering is `_refineLock` (outer) → `chatUserMetadataLock` (inner) — never invert it. `setUserMetadata` (both `isUpdate=True` and `isUpdate=False` branches — the lock wraps the entire method body) is the only other `chatUserMetadataLock` holder and it never touches `_refineLock`, so the no-deadlock argument holds; a new metadata-RMW site added inside the refinement flow must respect the same ordering. See ADR-015.

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
- `async chatUserMetadataLock() -> AsyncIterator[None]` — async context manager (`@contextlib.asynccontextmanager`) wrapping a single process-global `asyncio.Lock` (`_chatUsersMetadataLock`). Callers that do read-modify-write of `chat_users.metadata` (e.g. `setUserMetadata(isUpdate=True)` and `UserMemoriesHandler._runSingleRefinement`'s inlined cursor-persist block — formerly the standalone `_persistMemoryEntry`) MUST hold it across the full RMW to avoid lost-update races between concurrent writers. Plain reads (`getUserMetadata`) and full-replace writes (`updateUserMetadata` with no preceding read) do NOT need it. (Caveat: this guidance applies at the bare cache-method level — the higher-level `BaseBotHandler.setUserMetadata` wrapper acquires the lock for BOTH its `isUpdate=True` read-merge-write and `isUpdate=False` full-replace branches; see its docstring. The `isUpdate=False` branch holds the lock not because the bare full-replace needs it, but to prevent a concurrent RMW elsewhere from clobbering the full-replace write.) Intentionally process-global rather than per-`(chat, user)` — metadata writes are infrequent, so cross-user contention is negligible. Lock ordering when nested inside refinement: `_refineLock` (outer) → `chatUserMetadataLock` (inner) — see ADR-014.

**Refactored call sites:** `internal/bot/common/handlers/{base,spam,message_preprocessor,user_memories}.py` route single-row reads/writes through `self.cache.*`.

**`messages_count` staleness trade-off (load-bearing):** the `messages_count` column is incremented by a raw SQL `UPDATE ... SET messages_count = messages_count + 1` inside `ChatMessagesRepository.saveChatMessage` ([`internal/database/repositories/chat_messages.py:154`](../../internal/database/repositories/chat_messages.py:154)), which bypasses `ChatUsersRepository` and therefore this cache. A cached row's `messages_count` drifts. The two correctness-critical readers that gate on `messages_count` vs `AUTO_SPAM_MAX_MESSAGES` — `SpamHandler.checkSpam` ([`spam.py`](../../internal/bot/common/handlers/spam.py)) and `markAsSpam` — use the **conditional-refresh micro-optimisation** `SpamHandler._getUserInfoFreshIfMessagesLessThan(chatId, userId, messagesCountThreshold)` instead of an unconditional `refresh=True`. Because `messages_count` is monotonically non-decreasing, a cached value at or above the threshold can only stay there or grow, so it remains valid for any `>=` / `>` gate; only a cached value strictly below the threshold might have drifted up past it, so only that case pays for a `refresh=True` re-fetch. The two call sites pass different thresholds matching their gate direction: `checkSpam` (a `>=` gate) passes `maxCheckMessages` unchanged; `markAsSpam` (a STRICT `>` gate) passes `maxSpamMessages + 1` so the boundary case (`cached == maxSpamMessages`) still triggers a refresh, closing the false-ban window. Read-heavy paths (memory summary, metadata) consume the warm cache and do not need an accurate count.

**Absent-row non-memoization (intentional):** `getChatUser` does NOT cache a missing row. An absent `(chatId, userId)` row indicates something went wrong upstream (e.g. a message arrived before the row was seeded) and is not worth memoizing — every read of an absent row re-queries the DB until the row appears. This also keeps `userInfo` non-Optional (presence-of-key is the "loaded" sentinel).

**Skip-when-unchanged optimization & `updated_at` semantics shift:** because `updateChatUser` is a no-op when `username`/`full_name` are unchanged, `updated_at` no longer refreshes on such calls. Accepted trade-off; callers must not assume `updated_at` moves on every `updateChatUser` invocation. (`saveChatMessage`'s raw increment still bumps `updated_at` independently on every message.)

**Nested-write safety invariant:** `updateUserMetadata` does NO merge. Callers writing a nested sub-dict (e.g. `memoryRefinement[str(threadId)]`) must read the FULL metadata via `getUserMetadata`, mutate the single nested key, and write the FULL metadata back via `updateUserMetadata`. A blind shallow top-level merge (`{**old, **new}`) would wipe sibling keys — the memory-refinement write path (`user_memories.py`'s `_runSingleRefinement` inlined cursor-persist block, formerly `_persistMemoryEntry`) keeps its explicit full-read + nested-mutate + full-write pattern, and that whole RMW is serialized via `chatUserMetadataLock()` (above) so concurrent metadata writers cannot lose updates. This invariant is documented in both `setUserMetadata` and `updateUserMetadata` docstrings; see also ADR-014 and [`tasks.md`](tasks.md) §3.

**Coupling note — every metadata writer must route through the cache:** `setUserMetadata(isUpdate=True)` and `_runSingleRefinement`'s inlined cursor persist (formerly `_persistMemoryEntry`) now read/merge against the cached row. A future contributor adding a raw `db.chatUsers.updateUserMetadata(...)` call that bypasses the cache (the way `chat_messages.py:154` bypasses it for `messages_count`) would silently desync the cache and corrupt subsequent `setUserMetadata(isUpdate=True)` merges. Do not add such bypasses for `metadata`.

**Lazy field independence:** a cached entry may carry `permanentMemories` without `userInfo`, or vice versa. Both are `NotRequired`; presence-of-key is the "loaded" sentinel. `CHAT_USERS` is `MEMORY_ONLY`, so `persistAll`/`loadFromDatabase` ignore it — cold cache at startup, warmed lazily on first `getChatUser`. The new methods do not touch `self.dirtyKeys` (that set is never flushed for `MEMORY_ONLY` namespaces).

**Write-through ordering:** all setters write the DB first and update the cache only on success, so a DB failure leaves the cache untouched (no cache-DB divergence).

**Tests:** [`tests/services/cache/test_user_info.py`](../../tests/services/cache/test_user_info.py) (cache unit tests), [`tests/bot/common/handlers/test_user_info_cache_regression.py`](../../tests/bot/common/handlers/test_user_info_cache_regression.py) (regression: a warm-message produces 0 `chat_users` DB reads/writes), [`tests/bot/common/handlers/test_spam_microopt.py`](../../tests/bot/common/handlers/test_spam_microopt.py) (conditional-refresh helper: at-or-above-threshold no-refresh, below-threshold refresh, cold-cache no-refresh, strict-`<` boundary + `markAsSpam` `+1` form). Plan of record: [`docs/archive/plans/user-info-cache-plan-v1.md`](../archive/plans/user-info-cache-plan-v1.md) (§16 supersedes §3/§14/§15 for the post-review contract).

---

### ADR-016: Unified `user_memories` Store (Structured Memories + vec0 + Tool Self-Management)

**Decision:** Every durable fact, preference, event, relationship, or high-level bio note about a user lives as one row in a single `user_memories` table (`migration_020`), discriminated by a `MemoryType` tag and a freeform `tags` set, split into **permanent** (always injected) and **ephemeral** (retrieved per turn) classes. Memories are searchable via a vec0 virtual table (`vec_user_memories_{dim}`, cosine distance) and are managed by the LLM itself through three tools (`add_memory` / `delete_memory` / `search_memories`). A per-message `userMemories` snapshot (injected at arrival time into `chat_messages.metadata`) replaces the old opaque per-message `userSummary` JSON injection.

**Context:** The predecessor (ADR-014) refined a single rolling-bio **string** per `(chat, user, thread)` — an opaque summary blob stored in `chat_users.metadata.memoryRefinement[threadId].summary` and injected whole into every chat turn as `EnsuredMessage.userSummary`. That design could not represent discrete facts, could not be searched, could not be selectively retained vs. expired, and forced the model to emit one re-written paragraph per run. The legacy `user_data` key-value table held durable facts but was equally opaque (one JSON blob per user, no type/tags, no search, no dedup). Both were LLM-read-only at chat time: the model could not add, delete, or look up a specific memory on demand.

The unified store gives each memory a `type` (`bio`/`preference`/`fact`/`event`/`relationship`), a `tags` set, a `permanent` flag, a `source` provenance, and an embedding — so memories are individually addressable, filterable, de-duplicated (cosine similarity at insert time), and curatable by the model itself.

**Components** (see [`memories/user-memories.md`](memories/user-memories.md) for the canonical durable summary):

- **`user_memories` table** (`migration_020`) — composite natural key `(chat_id, user_id, memory_id)` (no `AUTOINCREMENT`); `memory_id` is an app-generated UUID hex. Three indexes back the read paths (`idx_user_memories_chat_user_thread`, `idx_user_memories_chat_user_permanent`, `idx_user_memories_type`).
- **vec0 virtual table `vec_user_memories_{dim}`** — lazy-created at runtime by `UserMemoriesRepository._upsertVecMemoryEmbedding` on first write of a given dimension (mirrors `chat_embeddings._upsertVecMessageEmbedding`). NOT created by the migration. Carries `memory_id` (the row identifier), three partition keys (`chat_id`/`user_id`/`model_id`), a `permanent` filterable metadata column, and the `embedding` vector column (cosine distance); the `model_id` partition key (INTEGER FK into the `models` lookup table added in `migration_025`; was TEXT `model` pre-migration_025) scopes vectors per embedding model so a model swap does not cross-contaminate vector spaces. `thread_id` and `type` are deliberately NOT carried in vec0 (they were write-only and never read back); semantic search re-applies them in a JOIN step on the authoritative `user_memories` columns (`model_id` and `permanent` are pushed into the vec0 filter clause directly).
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
- **vec0 is the sole embedding store** — since `migration_025_embedding_model_lookup`, this is true for BOTH `user_memories` and `chat_messages`: the `message_embeddings` BLOB side table was dropped (chat-history search no longer has a BLOB fallback either), and the per-row `embedding_model`/`embedding_dimensions` columns on `user_memories` were swapped for a single `model_id` INTEGER FK into the new `models` lookup table. The vec0 partition key on both vec0 families is now `model_id INTEGER` (was TEXT `model` pre-migration_025). When vec0 is unavailable, both `searchMemories` and the chat-history `_semanticSearch` return `[]` (no numpy fallback — the numpy paths in `chat_search.py` and `user_memories.py` were removed in the same refactor).
- **Refinement rewrite** — `_runSingleRefinement` no longer emits a summary string; it curates the store live via the three tools during the LLM call. The accounting/cron/locking machinery (ADR-014) and the `chat_users` cursor persist (ADR-015) are unchanged.
- The per-tool JSONL refinement log now records `addCount` / `deleteCount` / `searchCount` (the primary observability for the grey-zone dedup review) instead of a summary string.

**Config:** `[user-memory]` (global kill switch + thresholds including `memory-reindex-batch-size`); per-chat memory settings under `[bot.defaults]` — master gate `MEMORY_ENABLED` (renamed in the chatSettings consolidation from the old injection-only flag), plus `MEMORY_REFINEMENT_ENABLED` / `MEMORY_REFINE_MODEL` / `MEMORY_REFINE_FALLBACK_MODEL` / `MEMORY_REFINE_SYSTEM_PROMPT` / `MEMORY_REFINE_USER_PROMPT_TEMPLATE`. Memory embeddings are a derived condition (`MEMORY_ENABLED && EMBEDDINGS_ENABLED`), not a separate flag; semantic memory retrieval happens when both are on, otherwise latest (runtime semantic→latest fallback on embed failure). See [`configuration.md`](configuration.md) §`[user-memory]` and [`memories/user-memories.md`](memories/user-memories.md).

**Relationship to ADR-014 / ADR-015:** ADR-014 documented the rolling-bio refinement machinery (cron + global lock + context injection); the cron/lock/accounting invariants still govern `_runSingleRefinement`, but the *storage* and *injection* decisions there are superseded by this ADR (structured store + centralised arrival-time per-message injection, not string blob + `userSummary` field). ADR-015's `chat_users` cache and `chatUserMetadataLock()` still back the refinement message-cursor persist.

---

### ADR-017: Memory Compaction v1 — Compact Per-Message ID Storage + By-Id Cache + Soft-Delete

**Decision:** Each message's `metadata["memories"]` stores **compact memory IDs** (`{"permanentIds": [...], "shortTermIds": [...]}`) instead of a full per-message content snapshot. The read path resolves IDs → content at render time through a new `CacheNamespace.MEMORIES_BY_ID` cache + `CacheService.getMemoriesByIds` + `UserMemoriesRepository.getMemoriesByIds`. `user_memories.deleteMemory` becomes a **soft delete** (sets `deleted_at`, drops vec0 + provenance; the row survives) so a historical message referencing a now-deleted memory can still resolve its content. Spec/plan: [`docs/archive/plans/memory-compaction-v1.md`](../archive/plans/memory-compaction-v1.md) (status: IMPLEMENTED).

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
read/write paths (detail in [`memory-compaction-v1.md`](../archive/plans/memory-compaction-v1.md)
§10 "Follow-up refactor"; historical plan — see ADR-017 headnote for status):

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

**Decision:** Drop the `EnsuredMessage.userMemories` content field entirely; resolve compact memory IDs to content **lazily, on-demand, inside `formatForLLM`** (not at load time), and render each memory **exactly once per rendered context** via a newest→oldest exclusion computation. `metadata["memories"]` (`CompactMemoryIdsDict`: `{permanentIds, shortTermIds}`) is now the sole canonical source of which memories a message carries. Spec/plans: [`docs/archive/plans/memories-context-dedup-plan-v1.md`](../archive/plans/memories-context-dedup-plan-v1.md), [`memories-context-dedup-plan-v2.md`](../archive/plans/memories-context-dedup-plan-v2.md) (status: IMPLEMENTED).

**Context:** ADR-017 compacted *storage* to UUID lists but each message still rendered its full resolved content block into the LLM context — the permanent block (~1.5 KB) was duplicated ~N× across a thread (~75 KB for a 50-message thread). Three symbols encoded the eager, per-message, duplicated model: `EnsuredMessage.userMemories` (a per-message content snapshot field), `EnsuredMessage.resolveMemories` (eagerly resolved IDs→content at load time, before any render), and `EnsuredMessage.setUserMemories` (the write-path setter that split content from compact IDs). This ADR removes all three and moves resolution to render time with per-context deduplication, so each memory appears at most once in a given rendered context (at its newest occurrence).

**Components** (see [`memories/user-memories.md`](memories/user-memories.md) "Injection" / "Render-time resolution (lazy + dedup)" for the canonical summary):

- **`EnsuredMessage.userMemories` field REMOVED** (attribute + `__slots__` entry). The JSON output key `"userMemories"` still exists (built as a LOCAL dict inside `formatForLLM`), but there is no longer a per-message content attribute holding it.
- **`EnsuredMessage.resolveMemories` REMOVED** — resolution moved from load time into `formatForLLM`'s JSON branch. `fromDBChatMessage` lost its `injectMemories`/`cache` params (metadata IDs come straight from the DB row).
- **`EnsuredMessage.setUserMemories` REMOVED** — the write path (`MessagePreprocessorHandler.injectMemories`) now writes compact IDs directly into `metadata["memories"]` and pre-populates the by-id cache via `cache.warmMemoriesByIds(...)`.
- **`EnsuredMessage.getMemoryIds() -> Set[str]`** (new) — merged union of both cohorts from `metadata["memories"]`; the dedup algorithm's input.
- **`CacheService.warmMemoriesByIds(entries, *, chatId)`** (new) — pre-populates the `MEMORIES` namespace so the current message's render-time resolution is a cache HIT (avoids a redundant DB batch query on the inbound message).

  > **Amendment (post-ship correction):** `CacheService.warmMemoriesByIds` was specified here but **not shipped** — the method does not exist in the codebase. The `MEMORIES` namespace populates lazily (cache-aside) on the first `formatForLLM` read via `cache.getMemoriesByIds`. Additionally, `injectMemories()` runs **after** `saveChatMessage(...)` (not before the row is saved); because it mutates `metadata` after the initial insert, the compact IDs are re-persisted to `chat_messages.metadata` via a separate `db.chatMessages.updateChatMessageMetadata(...)` call. See [`docs/llm/handlers.md`](handlers.md) §1 (`MessagePreprocessorHandler`) and [`memories/user-memories.md`](memories/user-memories.md).
- **`formatForLLM` / `toModelMessage` / `toModelMessageList`** now take keyword-only `cache: Optional[CacheService]` (REQUIRED — no default; pyright errors on any caller that omits it) + `excludeMemoryIds: Optional[Set[str]] = None` (the `None` default is treated as the empty set inside `formatForLLM`). Only `cache` is required; `excludeMemoryIds` keeps its `None` default, so pyright does NOT force callers to pass it. (The plan proposed dropping both defaults, but the implementation kept `excludeMemoryIds=None` — call sites that omit it render all memories.) The JSON branch resolves IDs on-demand via `cache.getMemoriesByIds(...)` (only when `cache is not None`), filters each cohort by `excludeMemoryIds` before resolving, omits the `"userMemories"` key when `cache is None` / no IDs survive / nothing resolves, and **never mutates `self.metadata`** (the condense branch persists `eRootMessage.metadata` to DB, so mutating it during render would corrupt the persisted compact IDs).
- **Per-context deduplication is applied INLINE at each call site** (no shared helper). Each call site walks its message sequence newest→oldest, accumulating an exclude-set: for each message it applies `excludeMemoryIds = ownIds ∩ seen`, then adds its own IDs to `seen`. In `getThreadByMessageForLLM` the tail messages are walked newest→oldest into a `deque` (the `excludedMemoryIds` set accumulates each message's `getMemoryIds()`); `handleRandomMessage` does the same across its history+current sequence. Condense-summary plain-text messages carry no memory blocks and never participate in dedup.

**Consequences:**

- **Rendered-context duplication eliminated:** the newest message renders its full memory set; each older message renders only memories not already shown by any newer message; each memory appears exactly once, at its latest (newest) occurrence. ~75 KB → ~1.5 KB for the permanent block in a 50-message thread.
- **Condense-replay root exemption (accepted trade-off):** in the condense-replay path of `getThreadByMessageForLLM`, the single `keepFirstN` (root) message is EXEMPT from dedup — it renders its full memory set (`excludeMemoryIds=set()`) to keep the assembly code simple. Consequence: a memory present in BOTH the root and a newer tail message may appear twice (once at the root, once at its latest tail occurrence). The common (non-condensed) thread case is unaffected: there the root participates in the newest→oldest walk and deduplicates normally.
- **Lazy resolution is per-render, not per-load:** a message can be rendered many times (or never); resolution happens only when actually formatted for the LLM. On chat-context render paths, `cache` is gated on the `MEMORY_ENABLED` chat setting (`cache=self.cache if needMemories else None`), so memories render only when injection is enabled for the chat; non-chat / TEXT paths pass `cache=None, excludeMemoryIds=set()` explicitly and render no memories.
- **Non-mutation invariant preserved:** `formatForLLM` and `getMemoryIds` READ `metadata["memories"]` only — the condense-branch re-persistence hazard (ADR-017 deviation #1) is inherited and respected.
- **Signature enforcement (no AST value guard):** the render methods (`formatForLLM`/`toModelMessage`/`toModelMessageList`) declare `cache` as a **required** keyword-only param (no default), so pyright errors on any caller that omits it — this is the structural enforcement that `cache` is *present*. `excludeMemoryIds` is also keyword-only but defaults to `None` (treated as the empty set internally), so pyright does NOT force callers to pass it; the plan's "make both required" proposal was relaxed for `excludeMemoryIds`. There is intentionally **no** AST guard that checks the *value* passed to `cache=` (such a guard cannot robustly distinguish chat-context paths, which must pass `cache=self.cache`, from non-chat / TEXT paths, which must pass `cache=None`); value-correctness is upheld by the call-site audit and the test suite instead. `tests/test_memory_resolution_coverage.py` retains only Check-2 (the `setUserMemories`/metadata-bypass ban), now a vacuous regression guard against reintroduction of the removed setter.
- **Stale-ID behavioral delta:** when all referenced memory IDs fail to resolve, the `"userMemories"` key is OMITTED entirely (previously emitted an empty-cohort dict `{"permanent": [], "shortTerm": []}`).

**Relationship to ADR-017:** ADR-017 established compact ID storage + the by-id cache + soft-delete — all of which this ADR builds on unchanged. This ADR only changes the *resolution* timing (load→render), the *write* path (no per-message content field), and adds per-context *deduplication*. ADR-017's `resolveMemories`/`setUserMemories`/`fromDBChatMessage(injectMemories=, cache=)` machinery (and the follow-up refactor note above) is superseded by this ADR.

---

### ADR-019: Condensed-Context Retrieval — Coverage Tracking + Lazy JSON Render + `get_messages_by_ids` Tool

**Decision:** When the LLM's conversation context is condensed (older messages summarised to fit the context window), record *which* message IDs each summary covers plus structured metadata (participants, date range, message count) on the persisted `CondensingDict`; render every condensed summary as a JSON object (consistent with the real-user-message JSON shape) via a shared lazy renderer; and expose an `get_messages_by_ids` LLM tool so the model can fetch the originals underlying a summary on demand. Spec: [`docs/archive/plans/condensed-context-retrieval-plan-v1.md`](../archive/plans/condensed-context-retrieval-plan-v1.md) (status: IMPLEMENTED, then SIMPLIFIED 2026-07-13 — see note below).

> **Simplification (2026-07-13):** The original implementation computed coverage metadata on the *caller* side via a `returnCoverage` kwarg on `condenseContext`, `CondenseBatchCoverage` index ranges, and parallel `indexToEntry`/`indexToEntry2` lists that mapped indices back to source rows. That caller-side index-range machinery was **deleted** and replaced by `ModelMessage.source`-based provenance: coverage is now computed *inside* `condenseContext` by the `generateCondensingDict` helper, which walks each batch's `ModelMessage`s and reads `.source`. The callers (Path A / Path B) simply consume `condensingDictMap.values()` — no parallel-list bookkeeping. This ADR describes the simplified design.

**Context:** Two persistent write sites summarise older messages into a `role="user"` `ModelMessage` so the context fits the model window:

- **Path A — `condensedThread`** (`BaseBotHandler.getThreadByMessageForLLM`, [`base.py`](../../internal/bot/common/handlers/base.py)) stores `List[CondensingDict]` under `chat_messages.metadata.condensedThread` and re-summarises (cascade) when the rebuilt context still overruns.
- **Path B — `randomContext`** (`LLMMessageHandler.handleRandomMessage`, [`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py)) stores a single summary under `chat_messages.metadata.randomContext` when the random-answer history is too long.

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
  - `None` source (tool-history emissions) → `logger.warning` + skip *metadata extraction* only; `messageCount += 1` still runs unconditionally, so tool-history emissions ARE counted in `messageCount` (only `messageId`/`username`/timestamp are skipped).
  - Returns `CondensingDict` with `text` + conditionally-populated `messageIds` / `participants` (`list(set(...))` — set-unique but **unsorted**) / `dateRange` (`{from:min ts, to:max ts}`, omitted if none) / `messageCount`. Does NOT set `tillMessageId`/`tillTS`. Wrapped in try/except → fallback `CondensingDict(text=respText)` on failure (summary preserved, coverage dropped).
- **`condenseContext` always-tuple return** ([`internal/services/llm/service.py`](../../internal/services/llm/service.py)) — signature: `condenseContext(messages, model, *, keepFirstN=0, keepLastN=1, condensingModel=None, condensingPrompt=None, condensingSystemPrompt=None, maxTokens=None, force=False)`. **Always** returns `Tuple[Sequence[ModelMessage], Dict[int, CondensingDict]]`: first element = condensed message list (head + summaries + tail); second = `Dict[int, CondensingDict]` keyed by body-index → fully-populated `CondensingDict` (coverage computed inside via `generateCondensingDict` reading `ModelMessage.source`). When no condensing occurs the second element is `{}`. Path C (`generateTextViaLLM`) unpacks `_messages, _ = await self.condenseContext(...)` — byte-identical behaviour, ignores coverage.
- **`renderCondensedSummary(data: CondensingDict) -> str`** — shared JSON renderer (module-level in `message_metadata.py`). **Signature narrowed to `CondensingDict`-only** (no legacy `str` branch); the Path B read site pre-wraps legacy `str` rows into `CondensingDict(text=randomContext)` before calling. Output shape: `{type:"condensed", coveredMessageIds:[...], participants:[...], dateRange:{"from":<ISO>,"to":<ISO>}, messageCount:N, summary:"..."}`. Falsy-drop mirrors `formatForLLM` (empty/absent fields omitted, never `null`); `type`+`summary` always present. Both injection sites call this (Path A at `base.py`; Path B at `ensured_message.py`'s `toModelMessageList`), replacing the raw `condensedMessage["text"]` / raw-string injections.
- **`mergeCondensingDicts(dictList) -> CondensingDict`** (module-level in `message_metadata.py`) — unions multiple `CondensingDict`s: `text` = `"\n".join`; `messageIds` = plain `extend` (concat, **NO de-dup** — duplicates preserved across batches); `participants` = `list(set(...))` (set-unique but **unsorted**); `dateRange` = min/max; `messageCount` = sum. Used by Path B to merge all batches into a single `randomContext`.
- **Caller consumption (simplified)** —
  - **Path A** (`getThreadByMessageForLLM`): `condensedRet, condensingDictMap = await self.condenseContext(...)`; `condenseCache.extend(condensingDictMap.values())` (or `= list(...)` for re-condense). No parallel-list machinery.
  - **Path B** (`handleRandomMessage`): `condensedRet, condensingDictMap = await self.condenseContext(...)`; `if condensingDictMap: ensuredMessage.metadata["randomContext"] = mergeCondensingDicts(condensingDictMap.values())` (SKIP write when coverage empty — nothing meaningful to persist).
- **`get_messages_by_ids` LLM tool** ([`chat_search.py`](../../internal/bot/common/handlers/chat_search.py)) — registered in `ChatSearchHandler.__init__` as a normal `registerTool(...)` call alongside the other search tools (constant `ToolName.GET_MESSAGES_BY_IDS`, `internal/bot/constants.py`). Accepts a list of ID strings (batch). The JSON-Schema `items.type=string` override (`extra={"items": {"type": "string"}}`) was **commented out** at registration; the actual string-coercion safety net is in the tool body — each entry is run through `str(mid).strip()` and re-wrapped as `MessageId(midStr)` before lookup, so an LLM emitting ints still lands string-coerced IDs (`MessageId` is `int|str`). Returns `{messages:[...EnsuredMessage JSON...], notFound:[...], count:N}`, reusing `_formatMessageDict`. Never-raise (whole body wrapped in try/except). **Two-layer gating**: (1) `[search-history].enabled` via the handler's existing conditional registration (the tool rides the handler's gate — *no manager.py change*); (2) at chat time, gated solely by `USE_TOOLS` (the model is never sent the tool when `USE_TOOLS=false`). NOT gated by `ALLOW_TOOLS_COMMANDS` (which gates only slash commands of `CommandCategory.TOOLS`). Additionally **NOT** gated on `EMBEDDINGS_ENABLED` or any search-specific flag (pure DB lookup — available whenever chat-search is on, even with semantic search disabled).
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

### ADR-020: STTService — Synchronous, Stateless STT Service and Dependency Firewall

**Decision:** Media transcription (Speech-to-Text) is wired into the bot via a **stateless** singleton `STTService` ([`internal/services/stt/`](../../internal/services/stt/)) that owns the `lib/stt` provider lifecycle (construct / resolve proxy / `aclose`), bounds the **source bytes** of caller-supplied data before the provider call, and serves as the **final never-raise boundary** for the feature. The service exposes a single handler-time entry, `transcribeMedia(data, *, chatId) -> STTOutcome`, which awaits a thin pipeline inline and returns an immutable `STTOutcome`. **The service does NOT touch the database** — no row read/insert/cache/claim/persist/reclaim. The full `media_attachments` row lifecycle is owned by the `BaseBotHandler._processMediaV2` STT branch + its `_transcribeMedia` background task in [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py).

**Why now:** `lib/stt` was built first as a bot-free library (provider-neutral models, PyAV extraction, the Yandex SpeechKit v3 wire protocol — see [`docs/design/lib-stt-v1.md`](../design/lib-stt-v1.md)). This ADR records the integration-side decisions that turned the library into a wired (but default-off) service. It does not re-litigate library contracts; those live in the library spec.

**Scope (this round):** `STTService` is **implemented, tested, and wired into `BaseBotHandler._processMediaV2`** — the `_transcribeMedia` background task consumes `STTService.getInstance().transcribeMedia(data, chatId=...)` (the bytes are downloaded synchronously inside `_processMediaV2` and passed in) and terminalizes the row via plain `updateMediaAttachment`. The feature remains **DEFAULT-OFF** — `[stt] enabled = false` ships the service as a no-op, and the per-chat `PARSE_ATTACHMENTS` + `TRANSCRIBE_MEDIA` settings (both default `false`) must also be on before any media is transcribed. The handler round landed as a fold-into-`_processMediaV2` extension (no standalone `STTHandler`); the bounded `downloadAttachment(maxBytes)` platform extension was **dropped**. **STT v1.1 (Object-Storage routing + statistics) is also implemented.** The Yandex provider has a co-located `YandexObjectStorage` helper and retains the `lib/stt` firewall. It additionally accepts default-off `[stt].force-mono`: enabling it advertises mono-only formats and therefore downmixes/re-encodes otherwise pass-through multi-channel input. Independently, any final mono extracted audio requests speaker labeling for inline and `uri` submissions; canonical response labels become opaque, recording-local generic tags with the result-level `SPEAKER` role. This is a provider contract, documented authoritatively in [`lib-stt-v1.md`](../design/lib-stt-v1.md), not a new service or architecture seam.

**Key decisions:**

1. **Synchronous, stateless transcription** (chosen over an async in-flight registry). `transcribeMedia` awaits the full pipeline inline and returns an `STTOutcome`; it performs **no DB I/O**. Admission is **unbounded** — there is no `asyncio.timeout` around the semaphore; **the handler bounds the originating turn** (via its pipeline timeout). This fits the single-process assumption and avoids background-task / cross-turn coordination. A future async-registry design is not precluded but is not needed for v1.
2. **`provider.stt(bytes)` is the call site** — NOT `extractAudio()` + `transcribe()` separately. `AbstractSTTProvider.stt(data)` is the never-raise entry that wraps extract + transcribe inside `lib/stt` (see [`docs/design/lib-stt-v1.md`](../design/lib-stt-v1.md) §4). `STTService` calls the single entry; it never drives extraction/transcription as separate steps.
3. **Source-byte bounding survives (post-download); duration bounding moves to the handler.** `lib/stt` no longer bounds decoded PCM (a prior ratified simplification — see [`docs/design/lib-stt-v1.md`](../design/lib-stt-v1.md) §5). The service bounds only caller-supplied **source bytes** (`len(data) > maxSourceBytes` → `SOURCE_TOO_LARGE`); the default was raised to **1 GiB** (`1073741824`). The download itself is the handler's responsibility (the handler supplies the `data` bytes), so this check is post-download. **Duration bounding is the handler's job** — `DURATION_EXCEEDED` is reserved on the enum for the handler layer and is not currently produced (the wired `_transcribeMedia` task does not duration-gate in v1). If RSS gate-5 ([`stt-next-steps.md`](../archive/design/stt-next-steps.md) §4) fails at release, the ratified fallback is to restore a decoded-buffer cap inside `extractAudio` in `lib/stt`, **not** a service-side change.
4. **Dependency firewall — proxy is injected, never resolved inside `lib/stt`.** `STTService` resolves the proxy via `ProxyService.resolveProxy(sttConfig, "stt")` and **injects** the resulting `ProxyConfig` into the `YandexSpeechKitProvider` constructor. `STTService` never resolves a proxy itself inside `lib/stt`, and `lib/stt` never imports `internal.*`. This mirrors `lib/openweathermap` / `lib/geocode_maps` and is load-bearing contract #1 in the library spec.
5. **Never-raise layering.** `provider.stt()` never raises → `STTService.transcribeMedia` is the FINAL never-raise boundary for the feature. Every failure path returns an `STTOutcome(success=False, …)` + a structured log; `asyncio.CancelledError` propagates. **Persistence was REMOVED from the service** (the service is stateless) — the handler round owns the `media_attachments` row lifecycle (read / cache-hit / claim to `PENDING` / persist the outcome via plain `updateMediaAttachment` / terminalize). Single attachments have no concurrent writes, so last-write semantics suffice — there is no CAS.
6. **Service-only originally; handler round landed as a fold-into-`_processMediaV2` extension.** The service shipped first as a smaller, reviewable commit (exercised by its own unit tests, no user-visible effect). The handler round (the `_processMediaV2` STT branch + `_transcribeMedia` background task + `TRANSCRIBE_MEDIA` chat gate + `CHANGELOG.md` entry) is now implemented and tested (16 tests in `tests/bot/common/handlers/test_base.py::TestProcessMediaV2STT`); `ret.task = sttTask` mirrors the image-parsing pattern (`ret.task = parseTask`); the feature stays default-off until an operator flips all gates on.
7. **Thin formatter — structured delivery.** [`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py) emits one plain-text line per non-empty segment: `[Speaker#<tag>] [start..end] text` for a non-empty generic tag on a `SPEAKER` result, otherwise `[Ch#<tag>]` only for multiple distinct tags on a `CHANNEL` result, or an untagged timestamped line. Speaker labels are opaque and recording-local. The wired render path delivers the resulting description structurally as the JSON `mediaDescription` field.

**`STTErrorCode` ownership:** the shared [`STTErrorCode`](../../lib/stt/models.py) enum (9 members as of v1.1 — `OBJECT_STORAGE_ERROR` was added) is the stable failure vocabulary, but its members are produced at different layers:

- **Service-produced** (produced ONLY by `STTService`): `STT_DISABLED`. `SOURCE_TOO_LARGE` is produced by the service (source-byte cap, `len(data) > maxSourceBytes`) **and** as of v1.1 also surfaced by the Yandex provider when the *extracted* payload ≥ `max-inline-bytes` and Object Storage is disabled (see [`docs/design/stt-v1.1.md`](../design/stt-v1.1.md) §4.2/§4.5). (`PROVIDER_ERROR` is also produced by the service as the catch-all fallback for unexpected exceptions — structured logs distinguish a service-caught fallback from a provider-returned `PROVIDER_ERROR`.)
- **Provider-produced** (returned inside a `TranscriptionResult(ERROR, …)` from `provider.stt()`): `NO_AUDIO`, `PROVIDER_ERROR`, `PROTOCOL_ERROR`, and as of v1.1 `SOURCE_TOO_LARGE` (over inline threshold without Object Storage) + `OBJECT_STORAGE_ERROR` (Object-Storage upload failure before submit).
- **Reserved / partially-produced at the handler layer** (not produced by the service or provider): `SOURCE_SIZE_UNKNOWN`, `DOWNLOAD_ERROR`, `DURATION_EXCEEDED`. The bounded-download platform extension that would have produced `SOURCE_SIZE_UNKNOWN` was **dropped** (user decision 2026-08-03 — the wired `_transcribeMedia` task uses the existing unbounded `downloadAttachment`); `DOWNLOAD_ERROR` is emitted only as a structured log label by `_transcribeMedia` when `downloadAttachment` returns `None` (not persisted — there is no `errorCode` column); `DURATION_EXCEEDED` remains vocabulary-only (no duration gating in v1).

**Lifecycle (in `main.py`):** `STTService.getInstance().initialize(configManager)` (NO `database` arg) runs AFTER proxy + rate-limiter init, BEFORE the bot application. `await STTService.getInstance().aclose()` runs as shutdown Step 2.5 (after LLM close, before DB close), wrapped in best-effort `try/except`. When `[stt] enabled = false` (the shipped default), the provider is never constructed and `aclose()` is a no-op.

**Database:** NO migration, and the service itself does NO DB I/O. The existing `media_attachments` table is reused by the wired `_processMediaV2` STT branch + its `_transcribeMedia` background task: the `status` column (`MediaStatus`: `NEW → PENDING → DONE|FAILED`) carries the lifecycle and the transcript text is persisted in the existing `description` column. `_transcribeMedia` terminalizes rows via plain `MediaAttachmentsRepository.updateMediaAttachment(mediaId, status=..., description=...)` (`PENDING`→`DONE`+transcript on success | `PENDING`→`FAILED` on failure/exception). Single attachments have no concurrent writes, so last-write semantics suffice — there is **no CAS** and no `setStatusVerified` method (the former CAS helper was removed when the design was simplified). `asyncio.CancelledError` propagates (not swallowed by the broad `except Exception`) and leaves the row `PENDING` for orphan-reclaim. See [`database.md`](database.md) and [`docs/database-schema.md`](../../docs/database-schema.md).

**References:**

- [`docs/design/media-transcription-stt-v1.md`](../design/media-transcription-stt-v1.md) — parent product decisions D1–D8.
- [`docs/design/lib-stt-v1.md`](../design/lib-stt-v1.md) — `lib/stt` library spec (contracts, module layout, test matrix).
- [`docs/archive/design/stt-next-steps.md`](../archive/design/stt-next-steps.md) — integration roadmap (handler round landed; manual release gates pending).
- [`services.md`](services.md) §7 — `STTService` quick reference.
- [`configuration.md`](configuration.md) §`[stt]` — config reference.

---

### ADR-021: HTTP layer migrated to `httpx2` (PTB via `alias_httpx()`)

**Decision:** Gromozeka's HTTP client layer runs on **`httpx2`** (Pydantic-org fork of `httpx 0.28.1`, API-identical) instead of `httpx`. `requirements.direct.txt` carries a single direct dependency — `httpx2[http2,socks]==2.10.0` — and the previous `httpx[http2]==0.28.1` + `httpx-socks[asyncio]==0.11.0` direct pins were removed. The frozen `requirements.txt` **genuinely lost only `httpx-socks` / `python-socks`** and gained `httpx2` / `httpcore2` / `socksio` / `truststore`. **`httpx` and `httpcore` REMAIN pinned in `requirements.txt`** as shadowed transitive dependencies of `python-telegram-bot` and `openai` — they are still installed in the venv, but at runtime `import httpx` resolves to `httpx2` process-wide via the `alias_httpx()` startup hook below, so the real `httpx`/`httpcore` packages never execute. (Any doc claiming "httpx was removed from the dependency tree" is wrong; httpx2 is what actually runs.)

**Why:** upstream `encode/httpx` is on a ~20-month stable-release gap with a stalled 1.0 effort; `httpx2` ships monthly under the Pydantic organization with OIDC Trusted Publishing + Sigstore attestations and is gaining ecosystem momentum (Starlette, MCP Python SDK). httpx2 is the same code as httpx 0.28.1, so this is opportunistic maintenance/security-velocity modernization, not a rescue or a performance play. Full comparison, supply-chain assessment, and verdict live in [`docs/design/httpx2-migration-research.md`](../design/httpx2-migration-research.md); the D1–D7 design decisions and phased plan live in [`docs/design/httpx2-migration-v1.md`](../design/httpx2-migration-v1.md).

**Owned code (`import httpx2 as httpx`):** all Gromozeka-owned modules that previously did `import httpx` now do `import httpx2 as httpx` (13 production + 6 test files). The `httpx.` references (`httpx.AsyncClient`, `httpx.Timeout`, `httpx.HTTPError`, `httpx.MockTransport`, `httpx.AsyncHTTPTransport`, etc.) are unchanged — the alias preserves them literally. Naming the alias `httpx` keeps the diff minimal and reviewable (decision D5 in the design doc).

**PTB strategy b2 — `alias_httpx()` startup hook (load-bearing):** `python-telegram-bot` 22.8 owns its own `httpx` clients and constructs `httpx.AsyncClient` internally from `HTTPXRequest(httpx_kwargs=...)`; its source cannot be edited. To get PTB onto httpx2 without forking it, [`main.py`](../../main.py) calls `httpx2.alias_httpx()` at the very top — **before** any import that transitively pulls httpx (the first such import is `from internal.bot.telegram.application import TelegramBotApplication`, which pulls PTB). After the call, `import httpx` resolves to `httpx2` process-wide, so PTB's internal `httpx.AsyncClient` becomes an `httpx2.AsyncClient` and the object boundary disappears. The same alias call is mirrored at the top of [`tests/conftest.py`](../../tests/conftest.py) so tests see the same process-wide resolution. This is the single most order-sensitive line in the migration; moving it below any httpx-transitive import silently reverts PTB to the real (transitively-installed, still-pinned) `httpx 0.28.1` instead of `httpx2`.

**Proxy layer simplification (decision D2):** [`lib/proxy/__init__.py`](../../lib/proxy/__init__.py) dropped `httpx-socks` entirely. SOCKS5 now uses httpx2's native `proxy="socks5://..."` support (the `httpx2[socks]` extra pulls `socksio`). The `_HTTPX_SOCKS_AVAILABLE` flag and the `AsyncProxyTransport` conditional import are gone. `ProxyKwargs` collapsed to a single-key `{proxy: str}` used for **both** HTTP and SOCKS5; `toKwargs()` takes no `verify` argument (the caller applies `verify=<sslContext>` at the `httpx2.AsyncClient` level uniformly). The two `"transport" not in proxyKwargs` special-cases (`lib/max_bot/client.py` `_getHttpClient` and `internal/bot/common/handlers/yandex_search.py` `_downloadUrl`) are gone — there is never a `transport` key.

**HTTP/2-over-SOCKS guard (decision D3):** the web-fetch handler's old heuristic (`useHttp2 = "transport" not in proxyKwargs`) detected SOCKS *indirectly* via the transport object; after D2 it would always return `True` and silently re-enable the then-suspect HTTP/2-over-SOCKS combination. The new rule keyed off the resolved proxy type directly: `useHttp2 = self._proxyConfig.getCombined().type != ProxyType.SOCKS5`. **(2026-08-13 follow-up):** the guard was subsequently removed after source+web research established h2-over-SOCKS was never a protocol limitation — SOCKS5 is a raw TCP tunnel; HTTP/2 is negotiated via TLS ALPN entirely above the tunnel, and httpcore2's native SOCKS path supports it. The restriction was an artifact of the retired third-party `httpx-socks` transport, which did not propagate client-level `http2=True` into a user-supplied transport. ALPN degrades gracefully to HTTP/1.1 if the target server lacks h2 support.

**Logging:** the `httpx` / `httpcore` logger silencers in [`main.py`](../../main.py) and [`lib/logging_utils.py`](../../lib/logging_utils.py) were replaced by `httpx2` / `httpcore2` silencers.

**SSL note (truststore):** httpx2 (since 2.3.0) resolves SSL through `truststore` (OS trust store) instead of bundling `certifi` certs. Custom CA bundles (e.g. the Минцифры root CA for the Max platform-api2 endpoint) still thread through via the explicit `verify=<ssl.SSLContext>` built by `lib/max_bot/utils.buildMaxSslContext()`.

**Status — code complete, manual smokes pending:** all code phases landed; `make test` 3942 passed / 11 skipped / 0 failed; `make lint` 0 pyright errors. The HTTP/2-over-SOCKS probe was resolved (closed-by-analysis on 2026-08-13 — see D3 follow-up above). The remaining operator-only manual verification gates from design doc §8 — the Минцифры-SSL-through-SOCKS smoke (verify the custom `sslContext` reaches target TLS through `proxy="socks5://..."`) and the live Telegram getMe/sendMessage round-trip through PTB over the aliased httpx2 — remain **PENDING**. The migration is not yet operationally validated end-to-end against the real Telegram/Max/Минцифры endpoints.

**References:**

- [`docs/design/httpx2-migration-research.md`](../design/httpx2-migration-research.md) — research, comparison, supply-chain assessment, verdict (marked ADOPTED).
- [`docs/design/httpx2-migration-v1.md`](../design/httpx2-migration-v1.md) — design doc + D1–D7 decisions + phased plan (marked IMPLEMENTED; manual gates pending).
- [`libraries.md`](libraries.md) §5 / §7 / §8 / §13 — the migrated client libraries and the simplified `lib/proxy` layer.

---

### ADR-022: SQL providers and DatabaseManager extracted to `lib/db`

**Decision:** The generic SQL layer moved out of `internal/` into a bot-free `lib/db/` package: all seven provider modules (`base.py`, `sqlite3.py`, `sqlink.py`, `mysql.py`, `postgresql.py`, `utils.py`, and `__init__.py` with the `getSqlProvider` factory + `SQLProviderConfig`) now live at `lib/db/providers/` (mirroring the `lib/stt/providers/` layout), and `DatabaseManager` / `DatabaseManagerConfig` / `SQLProviderInitializationHook` live at `lib/db/manager.py`. A new `lib/db/__init__.py` re-exports the public API. `internal/database/` SURVIVES with everything bot-specific — migrations, repositories, the `Database` wrapper, `stats_storage.py`, `bayes_storage.py`, internal `utils.py` (`sqlToTypedDict`), `models.py` — and imports the SQL layer from `lib.db`. Cutover was big-bang: the old locations were deleted in the same commit the copies landed (git-mv, history preserved); there is no shim and no dual-home. Dependency direction is now `internal → lib.db → {lib.proxy, lib.utils, stdlib, 3rd-party}` — no cycles (the `make lint` `import main` gate guards this).

**Why:** the provider layer and `DatabaseManager` contain zero bot knowledge but sat under `internal/`, blocking `lib/` code from using them. The concrete case is `lib/stats`: its `StatsStorage` ABC is bot-free, but the only SQL implementation (`DatabaseStatsStorage`) lives in `internal/database/stats_storage.py` as an ABC-in-lib / impl-in-internal split that existed solely because the provider layer was internal. Extracting to `lib/db` makes a `lib/stats` SQL storage possible (that move itself is a separate follow-up arc). Design doc with the D1–D8 decisions and the full consumer census: [`docs/design/lib-db-extraction-v1.md`](../design/lib-db-extraction-v1.md).

**The MessageId cut:** `providers/utils.py`'s `convertToSQLite` had the layer's single `internal.*` import (`from internal.models import MessageId` + an `isinstance` branch). It was replaced with a module-local `@runtime_checkable` Protocol (`SQLStringifiable`, `def asStr(self) -> str`) and an `isinstance(data, SQLStringifiable)` branch. `MessageId.__str__` already returned `asStr()`, so stored values are identical before and after; the Protocol keeps the explicit intent and the warning suppression without the internal import. Locked by a fail-first regression test (`tests/lib/db/providers/test_utils.py`) using a double whose `asStr()` returns `"42"` while `__str__` returns `"WRONG"`.

**Known temporary deviation (mysql/postgresql):** `lib/db/providers/mysql.py` and `postgresql.py` moved AS-IS with hard module-level `import aiomysql` / `import asyncpg` (+ `# type: ignore[reportMissingImports]`), unregistered in the factory. This deviates from the repo's optional-dependency convention (module-level `try/except ImportError` + `_AVAILABLE` flag). Rationale: the drivers are not in requirements, both files are unimportable and untested today, and their class-level annotations (`Optional[aiomysql.Pool]`) evaluate at import time, making conversion non-trivial. Convert to the `_AVAILABLE` pattern only when the providers are actually wired.

**Status:** Implemented (Phase 1 code arc + Phase 2/3 doc sync). `make test` green; `make check-docs` green at every arc.

**References:**

- [`docs/design/lib-db-extraction-v1.md`](../design/lib-db-extraction-v1.md) — the ratified design (D1–D8), consumer census, phased plan.
- [`database.md`](database.md) — provider section (post-rewrite).
- [`libraries.md`](libraries.md) — the `lib/db` library entry.

---

## 2. Dependency Map

### 2.1 Component Dependency Graph

```
GromozekBot (main.py)
├── ConfigManager (internal/config/manager.py)
├── DatabaseManager (lib/db/manager.py)
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
6. `STTService.getInstance().initialize(configManager)` — sixth (only when `[stt]` is configured; default-off is a no-op; NO `database` arg — the service is stateless). Constructed after proxy + rate-limiter init so it can resolve the STT proxy, and before the bot application. Closed as shutdown Step 2.5 (`aclose()`, best-effort try/except, after LLM close, before DB close). See ADR-020.
7. `BotApplication` init — which triggers:
   - `HandlersManager.__init__()`:
     - `CacheService.getInstance()` + `cache.injectDatabase(db)`
     - `StorageService.getInstance()` + `storage.injectConfig(configManager)`
     - `QueueService.getInstance()`
     - All handler constructors (which get `CacheService`, `QueueService`, etc.)
8. `HandlersManager.injectBot(bot)` — injects `TheBot` into all handlers

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
*Last updated: 2026-08-02*
