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
5. `UserDataHandler` — PARALLEL — user data
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
- **Repository Pattern**: 15 specialized repositories handle specific data domains (chat_info, chat_messages, chat_settings, chat_users, chat_summarization, cache, spam, user_data, media_attachments, delayed_tasks, common, chat_search, chat_embeddings, divinations, webhook_updates)
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
- `UserDataRepository` — User-specific data
- `WebhookUpdatesRepository` — Max webhook payload storage and consumption (backed by `migration_019`)
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
- `getChatSettings(chatId)` — returns `Dict[str, tuple[str, int]]` where tuple is `(value, updated_by)`
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

**Decision:** A rolling per-`(chat, user, thread)` memory summary is refined in the background by an LLM on a 60s `CRON_JOB` owned by `UserDataHandler`, and injected into normal chat context as a new `EnsuredMessage.userSummary` field.

**Why:** Lets future replies carry short-term context about each user without re-reading their whole history or putting durable facts into every message's `userData`. The work is asynchronous and bounded so it never blocks the hot reply path or floods the LLM provider.

**Components** (see [`docs/llm/memories/user-memory-refinement.md`](memories/user-memory-refinement.md) for the durable implementation summary):

- **Counter** — `UserDataHandler._accounting: Dict[(chatId, userId, threadId), int]`, in-memory only (lost on restart; refinement re-fires after the next threshold crossing). Incremented at the very top of `newMessageHandler`, gated by the per-chat `MEMORY_REFINEMENT_ENABLED` setting, before any other gate.
- **Cron** — `UserDataHandler._dtCronJob(task)` registered on `DelayedTaskFunction.CRON_JOB` (runs every 60s alongside other handlers' cron ticks — multiple handlers may subscribe to the same function).
- **Global lock** — a single `asyncio.Lock` (`_refineLock`) serializes the whole scan+dispatch. If a previous batch is still running (a single LLM call can exceed 60s), the tick early-returns (`if self._refineLock.locked(): return`) instead of spawning a concurrent run. This prevents provider flooding; there is no per-entry locking and no `createTask`.
- **Refinement run** — `_runRefinement` fetches recent messages via `chatMessages.getChatMessagesSince` (additive `userId` filter), renders them, and calls `LLMService.generateTextViaLLM` with `chatId=None` (skips rate-limiting for the background call) and a per-tool dict enabling `ADD_USER_DATA`/`DELETE_USER_DATA`/`SEARCH_MESSAGES`/`GET_CURRENT_DATETIME`. A synthetic minimal `EnsuredMessage` is built so the `add_user_data`/`delete_user_data` tools can resolve `chatId`/`userId` from `extraData["ensuredMessage"]`.
- **Persistence** — the resulting summary + cursors land in `chat_users.metadata.memoryRefinement[str(threadId)]` (`{summary, lastProcessedMessageId, lastProcessedMessageDate}`). Written via **direct read-modify-write through `chatUsers.updateUserMetadata()`** — NOT `setUserMetadata(isUpdate=True)`, which shallow-merges at the top level and would wipe sibling threads' summaries (see [`tasks.md`](tasks.md) §3 gotcha). The `lastRefinedTS` (drives the 6h time threshold) is tracked **in-memory** on `UserDataHandler._lastRefinedTS` (lost on restart; absent → 0 → due).
- **Context injection** — `BaseBotHandler.getUserMemorySummary(chatId, userId, threadId)` reads the summary; `HandlersManager._processMessageRec` and `BaseBotHandler._updateEMessageUserData` attach it as `EnsuredMessage.userSummary` (gated). `formatForLLM` omits it from JSON when `None` → byte-identical default output.

**Load-bearing invariants:**
- The global lock is the concurrency boundary for refinement. Never add per-entry locks or fire-and-forget tasks — a slow run must block the next tick, not pile up concurrent calls.
- Nested `memoryRefinement` writes must read-modify-write the whole metadata dict. Never pass a partial `{"memoryRefinement": {<threadId>: ...}}` through `setUserMetadata(isUpdate=True)`.
- The dispatch loop uses a **credit-consumed** counter reset in the per-entry `finally` block: `_accounting[key] = max(0, _accounting.get(key,0) - preCount)` where `preCount` is the count captured at scan time, NOT an unconditional zeroing. This preserves increments from messages that arrived during the (possibly multi-second) LLM call. When the result is `0` the key is **popped** from `_accounting` (not kept at `0`) so empty keys aren't re-iterated next tick. Never revert to `= 0`.
- Due-list selection is an **online top-K by smallest `lastRefinedTS`** maintained during the scan, NOT a collect-all → sort → truncate. A bounded `due` list of size ≤ `_memoryMaxRefinesPerTick` is kept, holding the entries with the SMALLEST `lastRefinedTS` (oldest-due / never-refined carry TS=0). When full, a new candidate with a smaller `lastRefinedTS` than the running max evicts that max and the running max is recomputed. The 3rd tuple element is `lastRefinedTS` (int), not `elapsed` (float). Dispatch order within the selected K is unspecified — acceptable since K is tiny and all selected entries get processed in the happy path. Never revert to the old `due.sort(key=lambda x: (-x[2], -x[1]))[:maxRefinesPerTick]` (largest-elapsed-first).
- **Never-refined users are deliberately NOT skipped.** An earlier `isNeverRefined and newMessagesCount < minMessages: continue` pre-filter was removed because it gated on the *new-message counter*, but refinement of a never-refined user actually pulls *lifetime* messages via `getChatMessagesSince(sinceDateTime=None)`. The skip was over-conservative — it blocked users with plenty of pre-existing chat history but few messages since feature-enable. Now never-refined users (TS=0 → due-by-time) enter the due list normally and get refined from their lifetime history; if genuinely too few lifetime messages, `_runRefinement` bails once on the `< min-messages-to-refine` path and advances the in-memory `_lastRefinedTS` so the candidate isn't retried until the count/time threshold fires again.
- `_runRefinement` sets `_lastRefinedTS[key] = int(time.time())` on the `< min-messages` bail path, so idle (e.g. post-restart, previously-refined) users aren't re-scanned and re-bailed on every 60s tick. The count threshold still fires independently once messages accumulate. Never remove this — without it the cron hot-loops over idle due-by-time users.
- **Lock ordering for nested metadata RMW:** `_persistMemoryEntry` (called inside `_runRefinement`, hence under `_refineLock`) acquires `CacheService.chatUserMetadataLock()` to serialize its read-modify-write of `chat_users.metadata` against `setUserMetadata(isUpdate=True)`. The ordering is `_refineLock` (outer) → `chatUserMetadataLock` (inner) — never invert it. `setUserMetadata(isUpdate=True)` is the only other `chatUserMetadataLock` holder and it never touches `_refineLock`, so the current two paths cannot deadlock; a new metadata-RMW site added inside the refinement flow must respect the same ordering. See ADR-015.

**Config:** `[user-memory]` in [`configs/00-defaults/user-memory.toml`](../../configs/00-defaults/user-memory.toml) (global kill switch + thresholds; read ONCE in `__init__` and cached as instance attributes); per-chat `MEMORY_REFINEMENT_ENABLED` / `MEMORY_REFINE_MODEL` / `MEMORY_REFINE_FALLBACK_MODEL` / `MEMORY_REFINE_SYSTEM_PROMPT` / `MEMORY_REFINE_USER_PROMPT_TEMPLATE` chat settings under `[bot.defaults]`. See [`configuration.md`](configuration.md) §`[user-memory]`.

---

### ADR-015: Write-Through `chat_users` Cache in `CacheService`

**Decision:** `CacheService` gained a write-through cache for the single-row `chat_users` lookup. The existing `CacheNamespace.CHAT_USERS` namespace (keyed `f"{chatId}:{userId}"`, `MEMORY_ONLY`) was reused; its value TypedDict `HCChatUserCacheDict` ([`internal/services/cache/types.py:130`](../../internal/services/cache/types.py:130)) was extended with a second lazily-loaded field `userInfo: NotRequired[ChatUserDict]` (non-Optional; presence-of-key is the "loaded" sentinel) alongside the existing `data` (the `user_data` blob). Every single-row `(chatId, userId)` read and username/fullName/metadata write in the handler layer now routes through `CacheService` instead of `self.db.chatUsers.*`. Aggregate/by-username queries (`getChatUserByUsername`, `getChatUsers`, `getUserChats`, `getAllGroupChats`, `getUserIdByUserName`) are untouched.

**Why:** On every inbound message the bot read the `chat_users` row for the sender 2–5 times (memory-summary reads during LLM history reconstruction, spam `checkSpam`, per-message `updateChatUser` upsert, internal metadata-read inside `setUserMetadata`). The cache eliminates the redundant reads on the warm path. It mirrors the established `user_data` cache pattern (`getChatUserData`/`setChatUserData`): `MEMORY_ONLY` namespace, durability from explicit write-through inside the setter methods.

**New `CacheService` methods** ([`internal/services/cache/service.py:1008`](../../internal/services/cache/service.py:1008)):

- `async getChatUser(chatId, userId, *, refresh=False) -> Optional[ChatUserDict]` — LRU read, DB fallback on miss/`refresh`. Returns a **defensive shallow copy** (`dict(cachedRow)`) so callers cannot mutate the cached row. On a cache hit (and `refresh=False`) the cached row is returned with no DB access. On a miss OR `refresh=True`, the row is read from DB: if found, it is cached and a copy returned; **if absent, `None` is returned WITHOUT caching the absence** (an absent row indicates something went wrong upstream and is not worth memoizing — the next call re-queries the DB).
- `async updateChatUser(chatId, userId, username, fullName) -> None` — write-through upsert with **skip-when-unchanged** (if the cached row's `username`/`full_name` already equal the supplied values, the DB upsert is skipped entirely). On a cache hit the cached row is mutated in place; **on a cache miss the cache is intentionally LEFT COLD** (no re-read warming) — the row may never be read again, and the next `getChatUser` lazy-loads it if needed, so a warming re-read would be a wasted query on the write path.
- `async getUserMetadata(chatId, userId) -> UserMetadataDict` — parses the cached row's `metadata` column via `json.loads` (empty/None → `{}`). Returns a freshly-parsed dict (no aliasing).
- `async updateUserMetadata(chatId, userId, metadata) -> None` — write-through **full-dict replace** (serializes via `utils.jsonDumps`, writes via `db.chatUsers.updateUserMetadata`, then updates the cached row's `metadata`/`updated_at` in place). Performs **NO merge**.
- `def invalidateChatUser(chatId, userId) -> None` — sync; pops **only** the `userInfo` key (preserves the `data` user_data blob). Escape hatch for out-of-band mutations; no callers today.
- `async chatUserMetadataLock() -> AsyncIterator[None]` — async context manager (`@contextlib.asynccontextmanager`) wrapping a single process-global `asyncio.Lock` (`_chatUsersMetadataLock`). Callers that do read-modify-write of `chat_users.metadata` (e.g. `setUserMetadata(isUpdate=True)` and `UserDataHandler._persistMemoryEntry`) MUST hold it across the full RMW to avoid lost-update races between concurrent writers. Plain reads (`getUserMetadata`) and full-replace writes (`updateUserMetadata` with no preceding read) do NOT need it. Intentionally process-global rather than per-`(chat, user)` — metadata writes are infrequent, so cross-user contention is negligible. Lock ordering when nested inside refinement: `_refineLock` (outer) → `chatUserMetadataLock` (inner) — see ADR-014.

**Refactored call sites:** `internal/bot/common/handlers/{base,spam,message_preprocessor,user_data}.py` route single-row reads/writes through `self.cache.*`.

**`messages_count` staleness trade-off (load-bearing):** the `messages_count` column is incremented by a raw SQL `UPDATE ... SET messages_count = messages_count + 1` inside `ChatMessagesRepository.saveChatMessage` ([`internal/database/repositories/chat_messages.py:154`](../../internal/database/repositories/chat_messages.py:154)), which bypasses `ChatUsersRepository` and therefore this cache. A cached row's `messages_count` drifts. The two correctness-critical readers that gate on `messages_count` vs `AUTO_SPAM_MAX_MESSAGES` — `SpamHandler.checkSpam` ([`spam.py`](../../internal/bot/common/handlers/spam.py)) and `markAsSpam` — use the **conditional-refresh micro-optimisation** `SpamHandler._getUserInfoFreshIfMessagesLessThan(chatId, userId, messagesCountThreshold)` instead of an unconditional `refresh=True`. Because `messages_count` is monotonically non-decreasing, a cached value at or above the threshold can only stay there or grow, so it remains valid for any `>=` / `>` gate; only a cached value strictly below the threshold might have drifted up past it, so only that case pays for a `refresh=True` re-fetch. The two call sites pass different thresholds matching their gate direction: `checkSpam` (a `>=` gate) passes `maxCheckMessages` unchanged; `markAsSpam` (a STRICT `>` gate) passes `maxSpamMessages + 1` so the boundary case (`cached == maxSpamMessages`) still triggers a refresh, closing the false-ban window. Read-heavy paths (memory summary, metadata) consume the warm cache and do not need an accurate count.

**Absent-row non-memoization (intentional):** `getChatUser` does NOT cache a missing row. An absent `(chatId, userId)` row indicates something went wrong upstream (e.g. a message arrived before the row was seeded) and is not worth memoizing — every read of an absent row re-queries the DB until the row appears. This also keeps `userInfo` non-Optional (presence-of-key is the "loaded" sentinel).

**Skip-when-unchanged optimization & `updated_at` semantics shift:** because `updateChatUser` is a no-op when `username`/`full_name` are unchanged, `updated_at` no longer refreshes on such calls. Accepted trade-off; callers must not assume `updated_at` moves on every `updateChatUser` invocation. (`saveChatMessage`'s raw increment still bumps `updated_at` independently on every message.)

**Nested-write safety invariant:** `updateUserMetadata` does NO merge. Callers writing a nested sub-dict (e.g. `memoryRefinement[str(threadId)]`) must read the FULL metadata via `getUserMetadata`, mutate the single nested key, and write the FULL metadata back via `updateUserMetadata`. A blind shallow top-level merge (`{**old, **new}`) would wipe sibling keys — the memory-refinement write path (`user_data.py` `_persistMemoryEntry`) keeps its explicit full-read + nested-mutate + full-write pattern, and that whole RMW is serialized via `chatUserMetadataLock()` (above) so concurrent metadata writers cannot lose updates. This invariant is documented in both `setUserMetadata` and `updateUserMetadata` docstrings; see also ADR-014 and [`tasks.md`](tasks.md) §3.

**Coupling note — every metadata writer must route through the cache:** `setUserMetadata(isUpdate=True)` and `_persistMemoryEntry` now read/merge against the cached row. A future contributor adding a raw `db.chatUsers.updateUserMetadata(...)` call that bypasses the cache (the way `chat_messages.py:154` bypasses it for `messages_count`) would silently desync the cache and corrupt subsequent `setUserMetadata(isUpdate=True)` merges. Do not add such bypasses for `metadata`.

**Lazy field independence:** a cached entry may carry `data` without `userInfo`, or vice versa. Both are `NotRequired`; presence-of-key is the "loaded" sentinel. `CHAT_USERS` is `MEMORY_ONLY`, so `persistAll`/`loadFromDatabase` ignore it — cold cache at startup, warmed lazily on first `getChatUser`. The new methods do not touch `self.dirtyKeys` (that set is never flushed for `MEMORY_ONLY` namespaces).

**Write-through ordering:** all setters write the DB first and update the cache only on success, so a DB failure leaves the cache untouched (no cache-DB divergence).

**Tests:** [`tests/services/cache/test_user_info.py`](../../tests/services/cache/test_user_info.py) (cache unit tests), [`tests/bot/common/handlers/test_user_info_cache_regression.py`](../../tests/bot/common/handlers/test_user_info_cache_regression.py) (regression: a warm-message produces 0 `chat_users` DB reads/writes), [`tests/bot/common/handlers/test_spam_microopt.py`](../../tests/bot/common/handlers/test_spam_microopt.py) (conditional-refresh helper: at-or-above-threshold no-refresh, below-threshold refresh, cold-cache no-refresh, strict-`<` boundary + `markAsSpam` `+1` form). Plan of record: [`docs/plans/user-info-cache-plan-v1.md`](../plans/user-info-cache-plan-v1.md) (§16 supersedes §3/§14/§15 for the post-review contract).

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
*Last updated: 2026-06-28*
