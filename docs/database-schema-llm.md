# Database Schema Reference for LLMs

## Quick Reference

**Database**: SQLite with multi-source support
**Database Class**: [`Database`](../internal/database/database.py:1)
**Models**: [`internal/database/models.py`](../internal/database/models.py:1)
**Repositories**: [`internal/database/repositories/`](../internal/database/repositories/)
**Migrations**: 26 (up to `migration_026`)

---

## Table Definitions

### chat_messages
**Purpose**: Stores all chat messages with metadata
**Primary Key**: `(chat_id, message_id)`

```sql
CREATE TABLE chat_messages (
    chat_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    date TIMESTAMP NOT NULL,
    user_id INTEGER NOT NULL,
    reply_id TEXT,
    thread_id INTEGER NOT NULL DEFAULT 0,
    root_message_id TEXT,
    message_text TEXT NOT NULL,
    message_type TEXT DEFAULT 'text' NOT NULL,
    message_category TEXT DEFAULT 'user' NOT NULL,
    quote_text TEXT,
    media_id TEXT,
    media_group_id TEXT,
    markup TEXT DEFAULT '' NOT NULL,
    metadata TEXT DEFAULT '' NOT NULL,
    created_at TIMESTAMP NOT NULL,
    model_id INTEGER,                  -- migration_025; FK to models.model_id (NULL = not yet embedded)
    PRIMARY KEY (chat_id, message_id)
)
```

Schema above is the post-`migration_025` shape (canonical form with no `DEFAULT CURRENT_TIMESTAMP`). Columns `markup`/`metadata` were added by `migration_007`; `media_group_id` by `migration_008`; `model_id` by `migration_025` (Phase 2 of the embedding-model-lookup refactor — replaces the legacy `message_embeddings` BLOB side table; chat-history embeddings now live in vec0 only with `model_id` carrying the provenance). **No `updated_at` column** — only `created_at`. **No SQL `FOREIGN KEY` declarations** — the relationships below are logical (enforced by the application, not by DDL).

**TypedDict**: [`ChatMessageDict`](../internal/database/models.py:108)
**Relationships**: References [`chat_users`](#chat_users) (logical, via `(chat_id, user_id)`), [`media_attachments`](#media_attachments) (logical, via `media_id`), [`media_groups`](#media_groups) (logical, via `media_group_id`).

**Note**: The `media_group_id` column links messages that are part of a media group (album of photos/videos sent together).

**`metadata` JSON convention**: the column holds a JSON object (`internal/bot/models/message_metadata.py` → `MetadataDict`, `total=False`). Keys relevant to the condensed-context-retrieval feature (ADR-019):

- `condensedThread` — `List[CondensingDict]` (Path A, `getThreadByMessageForLLM`). Each `CondensingDict` has only **`text: str`** as a required field; ALL others (`tillMessageId`, `tillTS`, `messageIds`, `participants`, `dateRange`, `messageCount`) are **`NotRequired`** (absent on legacy rows / when no coverage data is available, read defensively via `in`/`.get()`). `tillMessageId`/`tillTS` are legacy boundary markers NOT set by `generateCondensingDict` (the coverage producer). New writes populate `messageIds` (authoritative covered-ID list), `participants` (sorted unique sender logins), `dateRange` (`CondensedDateRangeDict`), `messageCount` (covered count).
- `randomContext` — `Union[str, CondensingDict]` (Path B, `handleRandomAnswer`). Reshaped in ADR-019 from flat `str` → single `CondensingDict` on new writes (produced by `generateCondensingDict`, merged across batches via `mergeCondensingDicts`); legacy `str` rows are pre-wrapped into `CondensingDict(text=...)` by the read site before calling the renderer.

`CondensedDateRangeDict = TypedDict("CondensedDateRangeDict", {"from": float, "to": float})` uses **functional TypedDict syntax** because the JSON key `from` is a Python reserved keyword (class-body syntax would be a `SyntaxError`). It is the *storage* shape — two unix-timestamp floats; the render helper converts to ISO strings at call-time (ISO strings are NOT pre-baked into storage).

Both keys render to the LLM as a JSON object via the shared `renderCondensedSummary(data: CondensingDict) -> str` helper (`{type:"condensed", coveredMessageIds:[...], participants:[...], dateRange:{"from":<ISO>,"to":<ISO>}, messageCount:N, summary:"..."}`; falsy fields omitted; `type`+`summary` always present), so the model sees a uniform format consistent with real user messages and can call the `get_messages_by_ids` tool (`ChatSearchHandler`, three-layer gated, pure DB lookup) to fetch the originals. Condensed summaries + originals always coexist — condensing adds metadata, it never deletes source rows. No migration: legacy rows render correctly (degraded, no `coveredMessageIds`); new rows are richer.

Other `MetadataDict` keys (unrelated to this feature): `forwardedFrom`, `messagePrefix`, `usedTools`, `memories` (`CompactMemoryIdsDict` — see ADR-017/ADR-018).

---

### chat_users
**Purpose**: Per-chat user information and statistics
**Primary Key**: `(chat_id, user_id)`

```sql
CREATE TABLE chat_users (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    full_name TEXT NOT NULL,
    timezone TEXT,
    messages_count INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, user_id)
)
```

**TypedDict**: [`ChatUserDict`](../internal/database/models.py:163)

**`metadata` JSON convention**: the column holds a JSON object (`internal/bot/models/user_metadata.py` → `UserMetadataDict`, `total=False`) with boolean flags (`isSpammer`, `notSpammer`, `dropMessages`, `leftChat`) plus an optional `memoryRefinement: Dict[str(threadId), UserMemoryThreadDict]` sub-dict. Each per-thread entry carries `summary`, `lastProcessedMessageId`, `lastProcessedMessageDate` (cursor for `getChatMessagesSince`). The `lastRefinedTS` is NO LONGER persisted — it is tracked in-memory on `UserMemoriesHandler._lastRefinedTS` (lost on restart; absent → 0). The nested sub-dict must be written via read-modify-write through `CacheService.updateUserMetadata()` (full-dict replace, NO merge) — `setUserMetadata(isUpdate=True)` does a shallow top-level merge and would wipe sibling threads (see [`docs/llm/tasks.md`](llm/tasks.md) §3). Single-row `(chatId, userId)` reads/writes are cached via `CacheService` (ADR-015); the cached `messages_count` is best-effort stale (incremented by raw SQL in `saveChatMessage`, bypassing the cache).

---

### chat_info
**Purpose**: Chat metadata and configuration
**Primary Key**: `chat_id`

```sql
CREATE TABLE chat_info (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    username TEXT,
    type TEXT NOT NULL,
    is_forum BOOLEAN NOT NULL DEFAULT FALSE,
    bot_status TEXT NOT NULL DEFAULT 'active',   -- migration_026; accessibility state (ChatBotStatus)
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

Schema above is the post-`migration_026` shape. The `bot_status` column (added by `migration_026`; column only — no supporting index) backs the chat-accessibility-tracking subsystem — values of the [`ChatBotStatus`](#chatbotstatus) StrEnum (`'active'` / `'inaccessible'`). The string-literal `DEFAULT 'active'` is portable across SQLite/PostgreSQL/MySQL and backfills every existing row to `'active'` as part of the `ALTER TABLE` (no separate backfill; satisfies the optimistic-default binding decision). **Non-clobber rule:** `ChatInfoRepository.updateChatInfo` takes an optional keyword-only `botStatus: Optional[ChatBotStatus] = None`. When `None` (the default — used by the routine every-message refresh), `bot_status` is omitted from both `values` and `updateExpressions` of the upsert: on `INSERT` the column takes `DEFAULT 'active'` (a freshly-seen chat is assumed accessible), and on `CONFLICT` the existing value is preserved — so a routine refresh can never clobber an `INACCESSIBLE` row back to `ACTIVE`. When `botStatus` is provided, the column is written into both the INSERT `values` and the `CONFLICT`-UPDATE expressions; `CacheService.setChatInfo` forwards `info.get("bot_status")` so `markChatInaccessible` / `markChatActive` reach the column via the same upsert path.

**TypedDict**: [`ChatInfoDict`](../internal/database/models.py:215) — `bot_status` is `NotRequired[ChatBotStatus]` (DB-row-backed reads include it via `SELECT ci.*`; platform-sourced write dicts from `TheBot.getChatInfo` omit it because the accessibility subsystem owns the column).

---

### chat_topics
**Purpose**: Forum topic information
**Primary Key**: `(chat_id, topic_id)`

```sql
CREATE TABLE chat_topics (
    chat_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    icon_color INTEGER,
    icon_custom_emoji_id TEXT,
    name TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, topic_id),
    FOREIGN KEY (chat_id) REFERENCES chat_info(chat_id)
)
```

**TypedDict**: [`ChatTopicInfoDict`](../internal/database/models.py:234)

---

### chat_settings
**Purpose**: Per-chat configuration settings
**Primary Key**: `(chat_id, key)`

```sql
CREATE TABLE chat_settings (
    chat_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_by INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, key)
)
```

**Available Keys**: See [`ChatSettingsKey`](../internal/bot/models/chat_settings.py:281) enum

---

### media_groups
**Purpose**: Media group relationships for grouped media messages
**Primary Key**: `(media_group_id, media_id)`

```sql
CREATE TABLE media_groups (
    media_group_id TEXT NOT NULL,
    media_id TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (media_group_id, media_id)
)
```

Schema above is the post-`migration_013` shape. Created by `migration_008`. **No `updated_at`** and **no SQL `FOREIGN KEY`** — the relationship to [`media_attachments`](#media_attachments) is logical (enforced by the application).

**Relationships**: Logically references [`media_attachments`](#media_attachments) via `media_id`; logically referenced by [`chat_messages`](#chat_messages) via `media_group_id`.

**Note**: This table tracks which media items belong to the same media group (album). Multiple messages can share the same `media_group_id` when media is sent as an album.

---

### media_attachments
**Purpose**: Media file information
**Primary Key**: `file_unique_id`

```sql
CREATE TABLE media_attachments (
    file_unique_id TEXT PRIMARY KEY,
    file_id TEXT,
    file_size INTEGER,
    media_type TEXT NOT NULL,
    metadata TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    mime_type TEXT,
    local_url TEXT,
    prompt TEXT,
    description TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

**TypedDict**: [`MediaAttachmentDict`](../internal/database/models.py:255)

**STT (media-transcription) semantics:** For STT semantics (lifecycle, gating, CAS-removal), see [ADR-020](llm/architecture.md#adr-020-sttservice--synchronous-stateless-stt-service-and-dependency-firewall).

**Note on `metadata`:** `migration_013` declares `metadata TEXT NOT NULL` (no `DEFAULT ''`) for cross-RDBMS portability — application code always supplies the value.

---

### user_data (DROPPED)

Dropped in `migration_022` (superseded by [`user_memories`](#user_memories)). Historical rows were backfilled into `user_memories` by `migration_020`.

---

### spam_messages
**Purpose**: Spam message tracking
**Primary Key**: `(chat_id, user_id, message_id)`

```sql
CREATE TABLE spam_messages (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    text TEXT NOT NULL,
    reason TEXT NOT NULL,
    score FLOAT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, user_id, message_id)
)
```

**TypedDict**: [`SpamMessageDict`](../internal/database/models.py:325)

---

### ham_messages
**Purpose**: Legitimate message tracking for spam filter training
**Primary Key**: `(chat_id, user_id, message_id)`

```sql
CREATE TABLE ham_messages (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    text TEXT NOT NULL,
    reason TEXT NOT NULL,
    score FLOAT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, user_id, message_id)
)
```

---

### bayes_tokens
**Purpose**: Bayesian spam filter token statistics
**Primary Key**: `(token, chat_id)`

```sql
CREATE TABLE bayes_tokens (
    token TEXT NOT NULL,
    chat_id INTEGER,
    spam_count INTEGER NOT NULL DEFAULT 0,
    ham_count INTEGER NOT NULL DEFAULT 0,
    total_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (token, chat_id)
)
```

**Indexes**: `bayes_tokens_chat_idx` (`chat_id`), `bayes_tokens_total_idx` (`total_count`), `idx_bayes_tokens_updated_at` (`updated_at`; added in `migration_024`, optimizes the age-based `cleanupOldTokens` DELETE)

---

### bayes_classes
**Purpose**: Bayesian spam filter class statistics
**Primary Key**: `(chat_id, is_spam)`

```sql
CREATE TABLE bayes_classes (
    chat_id INTEGER,
    is_spam BOOLEAN NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    token_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, is_spam)
)
```

**Indexes**: `bayes_classes_chat_idx`

---

### chat_stats
**Purpose**: Daily chat statistics
**Primary Key**: `(chat_id, date)`

```sql
CREATE TABLE chat_stats (
    chat_id INTEGER NOT NULL,
    date TIMESTAMP NOT NULL,
    messages_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, date)
)
```

---

### chat_user_stats
**Purpose**: Daily per-user chat statistics
**Primary Key**: `(chat_id, user_id, date)`

```sql
CREATE TABLE chat_user_stats (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    date TIMESTAMP NOT NULL,
    messages_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, user_id, date)
)
```

---

### chat_summarization_cache
**Purpose**: Cached chat summaries
**Primary Key**: `csid`

```sql
CREATE TABLE chat_summarization_cache (
    csid TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    topic_id INTEGER,
    first_message_id TEXT NOT NULL,
    last_message_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

**TypedDict**: [`ChatSummarizationCacheDict`](../internal/database/models.py:348)
**Indexes**: `chat_summarization_cache_ctfl_index`

---

### cache_storage
**Purpose**: Generic key-value cache with namespaces
**Primary Key**: `(namespace, key)`

```sql
CREATE TABLE cache_storage (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (namespace, key)
)
```

**TypedDict**: [`CacheStorageDict`](../internal/database/models.py:386)

---

### divinations
**Purpose**: Persisted tarot/runes readings (see `DivinationHandler`)
**Primary Key**: `(chat_id, message_id)`

```sql
CREATE TABLE divinations (
    chat_id        INTEGER NOT NULL,
    message_id     TEXT    NOT NULL,
    user_id        INTEGER NOT NULL,
    system_id      TEXT    NOT NULL,                          -- 'tarot' | 'runes'
    deck_id        TEXT    NOT NULL,                          -- e.g. 'rws', 'elder_futhark'
    layout_id      TEXT    NOT NULL,                          -- e.g. 'three_card', 'three_runes'
    question       TEXT    NOT NULL,                          -- may be empty string at app layer
    draws_json     TEXT    NOT NULL,                          -- JSON list of drawn symbols
    interpretation TEXT    NOT NULL,                          -- may be empty string at app layer
    image_prompt   TEXT,
    invoked_via    TEXT    NOT NULL,                          -- 'command' | 'llm_tool'
    created_at     TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, message_id)
)
```

**Indexes**: `idx_divinations_user_created` on `(chat_id, user_id, created_at)`

**Repository**: `db.divinations.insertReading(...)` (class `DivinationsRepository`)

**Notes**: Only populated when `[divination] enabled = true`. No foreign-key relationship to other tables; image media is resolved via the normal message-history pipeline.

---

### divination_layouts
**Purpose**: Cache layout definitions discovered via LLM for reuse
**Primary Key**: `(system_id, layout_id)`

```sql
CREATE TABLE divination_layouts (
    system_id      TEXT    NOT NULL,                          -- 'tarot' | 'runes'
    layout_id      TEXT    NOT NULL,                          -- Machine-readable identifier
    name_en        TEXT    NOT NULL,                          -- English name (source of truth)
    name_ru        TEXT    NOT NULL,                          -- Russian display name
    n_symbols      INTEGER NOT NULL,                          -- Number of positions
    positions      TEXT    NOT NULL,                          -- JSON array of position definitions
    description    TEXT,                                       -- Layout description
    created_at     TIMESTAMP NOT NULL,
    updated_at     TIMESTAMP NOT NULL,
    PRIMARY KEY (system_id, layout_id)
)
```

**Indexes**: `idx_divination_layouts_system` on `system_id`

**Repository**: `DivinationsRepository` (accessed as `db.divinations`) — there is no separate `DivinationLayoutsRepository` class; layout CRUD was merged into `DivinationsRepository` (the same class that owns `insertReading`). Layout-specific methods: `getLayout`, `saveLayout`, `saveNegativeCache`, `isNegativeCacheEntry`.

**Usage**:
- Caches discovered layouts from LLM + web search
- Negative cache entries prevent repeated failed discoveries (`name_en=''`, `n_symbols=0`, `positions='[]'`)
- Retrieved via `DivinationsRepository.getLayout()`
- Saved via `DivinationsRepository.saveLayout()`

**Note**: Only populated when `[divination] enabled = true`. Negative cache pattern stores failed discoveries with empty `name_en` and `n_symbols=0`.

---

### models
**Purpose**: Embedding-provenance lookup table — one row per distinct `(model, dimensions)` pair seen by the system. The small app-generated sequential integer `model_id` is the FK-like key stored on every embedding-bearing row (`chat_messages.model_id`, `user_memories.model_id`, and the vec0 partition keys) so the `(model, dimensions)` pair itself is stored exactly once. Created by `migration_025` (Phase 2 of the embedding-model-lookup refactor).
**Primary Key**: `model_id` (app-generated sequential integer — Decision D7 of the refactor: small ints are cheaper as vec0 partition keys than UUID strings; the DB does not generate IDs, no `AUTOINCREMENT`/`SERIAL`).

```sql
CREATE TABLE models (
    model_id   INTEGER PRIMARY KEY NOT NULL,
    model      TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL,
    UNIQUE (model, dimensions)
)
```

**TypedDict**: [`ModelDict`](../internal/database/models.py:579)

**Repository** (`EmbeddingModelsRepository`, accessed as `db.embeddingModels`): process-local cache `{(model, dimensions): model_id}` so the common path (a hot model that's already been allocated) is a single dict hit. Constructed FIRST in `Database.__init__` so its bound `getOrCreateModelId` method can be injected as the `modelIdResolver` kwarg into the three embedding-touching repos (`chatEmbeddings`, `chatSearch`, `userMemories` — Decision D10). Methods:
- `getOrCreateModelId(model, dimensions) -> int` — cache-first allocation via `COALESCE(MAX(model_id), 0) + 1` + `provider.upsert(..., updateExpressions={})` (portable `ON CONFLICT DO NOTHING`) + SELECT-back. Runtime probe-then-insert against the `UNIQUE(model, dimensions)` constraint.
- `getModelById(modelId) -> Optional[ModelDict]` — single-row diagnostic lookup.
- `listModels() -> List[ModelDict]` — list all known models ordered by `model_id` (diagnostic/admin).

**Unique constraint**: `UNIQUE(model, dimensions)` — defensive second guard alongside the runtime probe-then-insert.

---

### message_embeddings (DROPPED)

**Dropped in `migration_025`** (along with its `idx_message_embeddings_chat_model` index). Chat-history embeddings now live in vec0 only, with `chat_messages.model_id` (FK to [`models`](#models)) carrying the provenance; the in-process numpy cosine fallback was retired in the same refactor and `searchChatMessages` returns `[]` when vec0 is unavailable. The legacy `(chat_id, message_id) → float32-BLOB` store is gone; vectors cannot be regenerated from `model_id` alone, so `down()` re-creates the table EMPTY (vectors are irrecoverable). Created originally by `migration_017`; its index was added by `migration_018`.

---

### vec_message_embeddings_N (virtual table)
**Purpose**: Ephemeral `vec0` virtual tables (one per embedding dimension in use, e.g. `vec_message_embeddings_384`, `vec_message_embeddings_1024`) that hold chat-message embedding vectors for native cosine-similarity KNN search via the `sqlite-vec` extension. Created lazily at runtime by `SQLite3Provider.createVectorTable()` on the first write of a given dimension (in `ChatEmbeddingsRepository.saveMessageEmbedding`); no migration creates them — `migration_025` deliberately DROPPED every `vec_message_embeddings_{N}` table (vec0 DDL is not `ALTER`-able; the partition-key change from `model TEXT` to `model_id INTEGER` required a full drop + lazy recreate). Recreated on the next embed call after `migration_025` runs. **Authoritative storage is now `chat_messages.model_id` + vec0 only** — there is no BLOB side table any more; vec0 carries the float vectors themselves and `chat_messages.model_id` carries the provenance.
**Primary Key**: vec0 internal rowid (not a natural key)
**Created by**: `SQLite3Provider.createVectorTable()` at runtime (lazily, on first write of a given dimension in `saveMessageEmbedding`). No migration creates them. Absent when `sqlite-vec` is not installed (in which case `searchChatMessages` returns `[]` — the numpy fallback was retired in the same refactor).

```sql
CREATE VIRTUAL TABLE vec_message_embeddings_384 USING vec0(
    message_id TEXT,
    chat_id INTEGER PARTITION KEY,
    model_id INTEGER PARTITION KEY,
    date TEXT,                            -- ISO-8601 from chat_messages; enables maxMessages pre-filter
    embedding FLOAT[384] distance_metric=cosine
)
```

| Column | Type | Notes |
|--------|------|-------|
| `message_id` | TEXT | Matches `chat_messages.message_id` |
| `chat_id` | INTEGER | `PARTITION KEY` — `WHERE chat_id = ?` prunes the search |
| `model_id` | INTEGER | `PARTITION KEY` — matches `chat_messages.model_id` / `models.model_id`; `WHERE model_id = ?` prunes the search. Replaces the legacy `model TEXT PARTITION KEY` (post-`migration_025`) |
| `date` | TEXT | ISO-8601 from `chat_messages.date`; enables `maxMessages` pre-filter via `date >= :minDate` |
| `embedding` | FLOAT[N] | float32 vector, `N` = dimension (matches table-name suffix); `distance_metric=cosine` |

**Lifecycle**: single-written by `ChatEmbeddingsRepository.saveMessageEmbedding()` — vec0 INSERT plus `UPDATE chat_messages.model_id`. The previous dual-write to `message_embeddings` + vec0 is retired (`message_embeddings` was dropped in `migration_025`). Stale rows from a previous model are cleaned up statelessly by `ChatSearchHandler._dtCronJob` — it lists `vec_message_embeddings_%` via `provider.listTables()` and runs `DELETE FROM {table} WHERE chat_id = :chatId AND model_id != :currentModelId` on each. Vec0 DDL is extension-specific; standard SQL portability rules (`AUTOINCREMENT`, `DEFAULT CURRENT_TIMESTAMP`, etc.) do not apply.

---

### stat_events
**Purpose**: Append-only event log for raw statistics events
**Primary Key**: `event_id` (app-generated UUID)

```sql
CREATE TABLE stat_events (
    event_id     TEXT      NOT NULL,
    event_type   TEXT      NOT NULL,
    event_time   TIMESTAMP NOT NULL,
    data         TEXT      NOT NULL,
    labels       TEXT      NOT NULL,
    processed    INTEGER   NOT NULL DEFAULT 0,
    processed_id TEXT      DEFAULT NULL,
    claimed_at   TIMESTAMP DEFAULT NULL,
    created_at   TIMESTAMP NOT NULL,
    PRIMARY KEY (event_id)
)
```

**Indexes**: `idx_stat_events_unprocessed`, `idx_stat_events_lookup`

**Repository**: `DatabaseStatsStorage.record()` in `internal/database/stats_storage.py`

**Note**: Created by `migration_016`. Part of the v3 statistics library (`lib/stats/`). Used to record LLM events (tokens, errors, fallbacks) and other metrics before aggregation into `stat_aggregates`.

---

### stat_aggregates
**Purpose**: Pre-computed period buckets for aggregated statistics metrics
**Primary Key**: `(event_type, period_start, period_type, labels_hash, metric_key)`

```sql
CREATE TABLE stat_aggregates (
    event_type   TEXT      NOT NULL,
    period_start TEXT      NOT NULL,
    period_type  TEXT      NOT NULL,
    labels_hash  TEXT      NOT NULL,
    labels       TEXT      NOT NULL,
    metric_key   TEXT      NOT NULL,
    metric_value REAL      NOT NULL,
    updated_at   TIMESTAMP NOT NULL,
    PRIMARY KEY (event_type, period_start, period_type, labels_hash, metric_key)
)
```

**Repository**: `DatabaseStatsStorage.aggregate()` in `internal/database/stats_storage.py`

**Period types**: `hour`, `day`, `month`, `total`

**Labels**: consumer, modelName, modelId, provider, generationType (for LLM events)

**Note**: Created by `migration_016`. Automatically updated when `DatabaseStatsStorage.aggregate()` is called. Provides efficient querying of pre-aggregated metrics for dashboards and analytics.

---

### delayed_tasks
**Purpose**: Scheduled task execution
**Primary Key**: `id`

```sql
CREATE TABLE delayed_tasks (
    id TEXT PRIMARY KEY,
    delayed_ts INTEGER NOT NULL,
    function TEXT NOT NULL,
    kwargs TEXT NOT NULL,
    is_done BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

**TypedDict**: [`DelayedTaskDict`](../internal/database/models.py:284)

---

### webhook_updates
**Purpose**: Raw incoming Max Messenger webhook payloads awaiting consumption by the bot. Written by the standalone webhook receiver process (`internal/max_webhook_receiver/`) on every webhook POST; the bot's long-poll loop reads and marks rows processed.
**Primary Key**: `id` (application-generated UUID)

```sql
CREATE TABLE webhook_updates (
    id           TEXT      PRIMARY KEY NOT NULL,
    received_at  TIMESTAMP NOT NULL,
    update_type  TEXT      NOT NULL,
    raw_json     TEXT      NOT NULL,
    processed    INTEGER   NOT NULL DEFAULT 0,
    processed_at TIMESTAMP
)
```

**Indexes**: `idx_webhook_updates_unprocessed` on `(processed, received_at)` — backs `WHERE processed = 0 ORDER BY received_at ASC`

**TypedDict**: [`WebhookUpdatesRow`](../internal/database/models.py:303)

**Repository** (`WebhookUpdatesRepository`, accessed as `db.webhookUpdates`):
- `addUpdate(updateId, updateType, rawJson) -> bool` — store a raw payload (caller generates the UUID; `received_at` set by the repo).
- `getUnprocessedUpdates(limit=100) -> List[WebhookUpdatesRow]` — pending rows oldest-first; pagination via `provider.applyPagination`.
- `markProcessed(updateIds) -> None` — atomic batch update (single `batchExecute`) so the whole batch commits together; prevents duplicate delivery.
- `deleteProcessedOlderThan(ttlSeconds=3600) -> bool` — reap processed rows past the TTL; cutoff computed in Python for cross-RDBMS portability.

**Note**: Created by `migration_019`. No `AUTOINCREMENT`/`SERIAL`, no `DEFAULT CURRENT_TIMESTAMP` — `id` is caller-generated and timestamps are application-set. Processed rows are reaped by the receiver's background cleanup task (default TTL 1h).

---

### user_memories
**Purpose**: Unified per-(chat, user, thread) memory store — durable facts, preferences, events, relationships, and high-level bio notes about a user. Retires the legacy `user_data` key-value table (dropped in `migration_022`) and the rolling-bio JSON blob (`chat_users.metadata.memoryRefinement`); both were backfilled into this table by `migration_020`. Created by `migration_020`. Semantic search runs over a vec0 virtual table (`vec_user_memories_{dim}`, cosine distance) that is **not** created by the migration — it is created lazily at runtime on first write (mirrors `vec_message_embeddings_{dim}`). There is no BLOB side table: embedding provenance is normalised into the [`models`](#models) lookup table (Phase 2 of the embedding-model-lookup refactor, `migration_025`) and tracked on `user_memories` via a single `model_id` FK; vec0 is the sole embedding store. When vec0 is unavailable, `searchMemories` returns `[]` (no numpy fallback).
**Primary Key**: `(chat_id, user_id, memory_id)` — composite natural key (no `AUTOINCREMENT`).

```sql
CREATE TABLE user_memories (
    chat_id    INTEGER   NOT NULL,
    user_id    INTEGER   NOT NULL,
    thread_id  INTEGER,            -- NULL = cross-thread permanent within chat
    memory_id  TEXT      NOT NULL, -- app-generated UUID hex
    type       TEXT      NOT NULL, -- MemoryType: bio|preference|fact|event|relationship
    content    TEXT      NOT NULL,
    tags       TEXT      NOT NULL DEFAULT '[]',  -- JSON array of strings
    permanent  INTEGER   NOT NULL DEFAULT 0,    -- boolean 0/1
    source     TEXT      NOT NULL DEFAULT 'refinement', -- refinement|chat|migration|user
    model_id   INTEGER,            -- migration_025; FK to models.model_id (NULL = not yet embedded)
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    deleted_at TIMESTAMP NULL,     -- migration_021; NULL = live, set by deleteMemory (soft-delete)
    PRIMARY KEY (chat_id, user_id, memory_id)
)
```

**Indexes**:
- `idx_user_memories_chat_user_thread` on `(chat_id, user_id, thread_id, updated_at DESC)` — backs `getLatestMemories` and same-thread retrieval.
- `idx_user_memories_chat_user_permanent` on `(chat_id, user_id, permanent, updated_at DESC)` — backs `getPermanentMemories`.
- `idx_user_memories_type` on `(chat_id, user_id, type)` — backs type-filtered scans.

**TypedDict**: [`UserMemoryDict`](../internal/database/models.py:528) (snake_case keys matching columns; `score` is `NotRequired[float]` populated by semantic search). Post-`migration_025`, `model_id: Optional[int]` replaces the legacy `embedding_model` / `embedding_dimensions` pair.

**Enum**: [`MemoryType`](../internal/database/models.py:450) (`BIO`/`PREFERENCE`/`FACT`/`EVENT`/`RELATIONSHIP`); [`UserMemorySource`](../internal/database/models.py:492) (`REFINEMENT`/`CHAT`/`MIGRATION`/`USER`).

**Repository** (`UserMemoriesRepository`, accessed as `db.userMemories`) — 12 public methods; all SQL goes through `BaseSQLProvider`. Constructed with a constructor-injected `modelIdResolver: Callable[[str, int], Awaitable[int]]` (Decision D10 — bound `EmbeddingModelsRepository.getOrCreateModelId`) so the `(model, dimensions)` pair is resolved to a `model_id` internally without leaking that detail into handler-facing signatures (Decision D6 — signatures stay stable):
- `addMemory(chatId, userId, memoryId, *, type, content, tags, permanent, source, embedding=None, embeddingModel=None, threadId=None) -> None` — INSERT (caller generates the UUID). `source` is a `UserMemorySource`; `threadId` is keyword-only; when both `embedding` (`List[float]`) and `embeddingModel` are provided the row is embedded during add.
- `deleteMemory(chatId, userId, memoryId) -> bool` — SOFT DELETE: sets `deleted_at` + bumps `updated_at`, drops the vec0 row, nulls `model_id`. Unrestricted (may target permanent). Row survives for historical reads; never raises.
- `getPermanentMemories(chatId, userId, threadId, *, limit=10) -> List[UserMemoryDict]` — merges cross-thread permanent (`thread_id IS NULL`) AND this-thread permanent. Filters `deleted_at IS NULL`.
- `getLatestMemories(chatId, userId, threadId, *, limit=5) -> List[UserMemoryDict]` — thread-scoped newest-first, **ephemeral-only** (`permanent = 0`); permanent memories are served by `getPermanentMemories`. Filters `deleted_at IS NULL`.
- `getMemory(chatId, userId, memoryId, *, dataSource=None) -> Optional[UserMemoryDict]` — single-row read by the full PK `(chatId, userId, memoryId)`; backs the `/memory_config` wizard's per-memory detail view. Unrestricted by `permanent`/`thread_id`. Filters `deleted_at IS NULL`.
- `getMemoriesByIds(memoryIds: List[str], *, chatId: Optional[int] = None, dataSource: Optional[str] = None) -> List[UserMemoryDict]` — the single read that does NOT filter `deleted_at`: resolves UUIDs to content for historical message reconstruction (compact-ID storage). No `chatId`/`userId` scoping in the WHERE clause (UUIDs globally unique); `chatId`/`dataSource` are routing-only (forwarded to `getProvider(..., readonly=True)`); default `None` → default DB. Auto-chunked in batches of `MAX_SQL_VARIABLES`.
- `getDistinctTags(chatId, userId, memoryType=None, *, dataSource=None) -> List[str]` — sorted distinct tag strings across the user's (live) memories; backs the wizard's tag-filter picker. Optional `memoryType` filter.
- `searchMemories(chatId, userId, queryEmbedding=None, *, threadId=None, type=None, tags=None, permanent=None, limit=20, embeddingModel, offset=0) -> List[UserMemoryDict]` — filter-only (`queryEmbedding is None`) or semantic (vec0 KNN, `score = 1.0 - distance`). `queryEmbedding` is `Optional[List[float]]`; `embeddingModel` (required, pass `None` for filter-only) is resolved to `model_id` internally via the injected `modelIdResolver` (Decision D6 — handler-facing signatures unchanged). `tags` applied as a portable SQL `LIKE '%"tagN"%'` filter (ANY-match) against the JSON-TEXT `tags` column. Both modes filter `deleted_at IS NULL`.
- `saveMemoryEmbedding(chatId, userId, memoryId, embedding, embeddingModel) -> bool` — lazy-create `vec_user_memories_{dim}` + upsert the vector (`embedding` is `List[float]`, `embeddingModel` the model name, resolved to `model_id` via `modelIdResolver`) + set `model_id` on the relational row. Its internal row SELECT also filters `deleted_at IS NULL` (defense-in-depth).
- `deleteMemoryEmbedding(chatId, userId, memoryId, vecOnly=False) -> bool` — best-effort vec0 DELETE; never raises. When `vecOnly=False` (default), also nulls `model_id` on the relational row and bumps `updated_at`. Returns `True` when a vec0 row was deleted OR no vec0 table existed; `False` when tables existed but the `memory_id` was absent.
- `getMemoriesWithoutEmbeddings(chatId, *, limit=50, modelName=None, dimensions=None, dataSource=None) -> List[UserMemoryDict]` — stale detection (NULL `model_id`, or `model_id` differing from the resolved active `(model, dimensions)` pair via a stale predicate keyed on `model_id`); backs the regen cron + initial backfill. Filters `deleted_at IS NULL` (so a soft-deleted memory is never re-embedded).
- `deleteObsoleteMemoryEmbeddings(chatId, currentModel, currentDimensions) -> int` — model-drift cleanup: resets stale rows' `model_id` to NULL and drops their vec0 rows.

**Backfills** (`migration_020.up()`):
- `user_data` rows (table dropped in `migration_022`) → permanent cross-thread `type='fact'`, `content="{key}: {data}"`, `tags=[]`, `source='migration'`, original timestamps preserved.
- `chat_users.metadata.memoryRefinement[str(threadId)]` entries (non-empty summary) → permanent thread-scoped `type='bio'`, `tags=["migrated_bio"]`, `source='migration'`, summary preserved in `content`.

**Note**: No `AUTOINCREMENT`/`SERIAL`, no `DEFAULT CURRENT_TIMESTAMP` — `memory_id` is an app-generated UUID and timestamps are application-set. Created by `migration_020`; `deleted_at` added by `migration_021` (soft-delete — `down()` is a no-op that logs: portable `DROP COLUMN` unavailable, nullable additive column safe on rollback). `down()` for migration 020 drops only `user_memories`; the legacy `user_data` table was subsequently dropped by `migration_022` (superseded by `user_memories`). The vec0 runtime table (`vec_user_memories_{dim}`) is NOT created by a migration — it is created lazily on first write at runtime.

---

### settings
**Purpose**: Global system settings
**Primary Key**: `key`

```sql
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

**Special Keys**: `db-migration-version`, `db-migration-last-run`

---

## Enums

### MessageCategory
**Location**: [`internal/database/models.py:28`](../internal/database/models.py:28)

```python
UNSPECIFIED = "unspecified"
USER = "user"
USER_COMMAND = "user-command"
CHANNEL = "channel"
BOT = "bot"
BOT_COMMAND_REPLY = "bot-command-reply"
BOT_ERROR = "bot-error"
BOT_SUMMARY = "bot-summary"
BOT_RESENDED = "bot-resended"
BOT_SPAM_NOTIFICATION = "bot-spam-notification"
USER_SPAM = "user-spam"
DELETED = "deleted"
USER_CONFIG_ANSWER = "user-config-answer"
```

---

### MediaStatus
**Location**: [`internal/database/models.py:15`](../internal/database/models.py:15)

```python
NEW = "new"
PENDING = "pending"
DONE = "done"
FAILED = "failed"
```

---

### SpamReason
**Location**: [`internal/database/models.py:95`](../internal/database/models.py:95)

```python
AUTO = "auto"
USER = "user"
ADMIN = "admin"
UNBAN = "unban"
```

---

### CacheType
**Location**: [`internal/database/models.py:399`](../internal/database/models.py:399)

```python
WEATHER = "weather"
GEOCODING = "geocoding"
YANDEX_SEARCH = "yandex_search"
GM_SEARCH = "geocode_maps_search"
GM_REVERSE = "geocode_maps_reverse"
GM_LOOKUP = "geocode_maps_lookup"
URL_CONTENT = "url_content"
URL_CONTENT_CONDENSED = "url_content_condensed"
```

---

### ChatBotStatus
**Location**: [`internal/database/models.py:108`](../internal/database/models.py:108) (StrEnum; lives in the database layer so `internal.database` initialises without importing `internal.bot`)

```python
ACTIVE = "active"              # Bot is present / assumed present (optimistic default; set by DEFAULT 'active' on INSERT)
INACCESSIBLE = "inaccessible"  # Bot was kicked / restricted / lost admin rights (lazy mark-on-failure at getChatAdmins catch sites)
```

Backs the `chat_info.bot_status` column (added by `migration_026`; column only — no supporting index). Owned by the accessibility subsystem — written through `ChatInfoRepository.updateChatInfo(..., botStatus=...)` (via `CacheService.setChatInfo`, which forwards `info.get("bot_status")`); read with the optional `botStatus` filter on `ChatUsersRepository.getUserChats` / `getAllGroupChats`. See [`docs/design/chat-accessibility-tracking.md`](design/chat-accessibility-tracking.md) (and its "Implementation Divergence (2026-08-12)" section for the shipped design).

---

## Database Operations

### Message Operations

**Save Message**
```python
db.chatMessages.saveChatMessage(
    date: datetime,
    chatId: int,
    userId: int,
    messageId: MessageId,
    replyId: Optional[MessageId] = None,
    threadId: Optional[int] = None,           # None → DEFAULT_THREAD_ID (0)
    messageText: str = "",
    messageType: MessageType = MessageType.TEXT,
    messageCategory: MessageCategory = MessageCategory.UNSPECIFIED,
    rootMessageId: Optional[MessageId] = None,
    quoteText: Optional[str] = None,
    mediaId: Optional[str] = None,
    markup: Optional[Sequence[Mapping[str, Any]]] = None,   # None → []
    metadata: Optional[Mapping[str, Any]] = None,           # None → {}
    mediaGroupId: Optional[str] = None
) -> bool
```

**Get Messages Since Date**
```python
db.chatMessages.getChatMessagesSince(
    chatId: int,
    sinceDateTime: Optional[datetime] = None,
    tillDateTime: Optional[datetime] = None,
    threadId: Optional[int] = None,
    limit: Optional[int] = None,
    messageCategory: Optional[Sequence[MessageCategory]] = None,
    userId: Optional[int] = None,
    *,
    dataSource: Optional[str] = None
) -> List[ChatMessageDict]
```

**Get Message by ID**
```python
db.chatMessages.getChatMessageByMessageId(
    chatId: int,
    messageId: MessageId,
    *,
    dataSource: Optional[str] = None
) -> Optional[ChatMessageDict]
```

**Get Messages by IDs (batch)**
```python
db.chatMessages.getChatMessagesByMessageIds(
    chatId: int,
    messageIds: Sequence[MessageId],
    *,
    dataSource: Optional[str] = None
) -> List[ChatMessageDict]
```
Auto-chunked into batches of `MAX_SQL_VARIABLES` to stay under the engine's bound-parameter limit; ordered ascending by `date`.

**Get Messages by Root ID**
```python
db.chatMessages.getChatMessagesByRootId(
    chatId: int,
    rootMessageId: MessageId,
    threadId: Optional[int] = None,
    *,
    dataSource: Optional[str] = None
) -> List[ChatMessageDict]
```

**Get Messages by User**
```python
db.chatMessages.getChatMessagesByUser(
    chatId: int,
    userId: int,
    limit: int = 100,
    *,
    dataSource: Optional[str] = None
) -> List[ChatMessageDict]
```

**Get First Message by Media Group ID**
```python
db.chatMessages.getFirstChatMessageByMediaGroupId(
    chatId: int,
    mediaGroupId: str,
    threadId: Optional[int] = None,
    *,
    dataSource: Optional[str] = None
) -> Optional[ChatMessageDict]
```

**Update Message Category**
```python
db.chatMessages.updateChatMessageCategory(
    chatId: int,
    messageId: MessageId,
    messageCategory: MessageCategory
) -> bool
```

**Update Message Metadata**
```python
db.chatMessages.updateChatMessageMetadata(
    chatId: int,
    messageId: MessageId,
    metadata: str | Any
) -> bool
```

**Get Thread Context**
```python
db.chatMessages.getMessageThread(
    chatId: int,
    messageId: MessageId,
    *,
    dataSource: Optional[str] = None
) -> Optional[ThreadResultDict]
```
Returns `None` if the target message does not exist. Otherwise returns a `ThreadResultDict` with `root_message` (None when the target is itself a root), `target_message`, and `thread_messages` (chronological, includes the target).

---

### Search Operations

**Unified chat-message search** (`db.chatSearch`, class `ChatSearchRepository`):
```python
db.chatSearch.searchChatMessages(
    chatId: int,
    queryEmbedding: Optional[List[float]] = None,
    *,
    limit: Optional[int] = 10,
    topK: int = 100,
    userFilter: Optional[int] = None,
    categoryFilter: Optional[Sequence[MessageCategory]] = None,
    maxAgeDays: Optional[int] = None,
    rootMessageId: Optional[MessageId] = None,
    modelName: Optional[str] = None,
    maxMessages: Optional[int] = None,
    dataSource: Optional[str] = None,
    threadId: Optional[int] = None,
    substring: Optional[str] = None
) -> List[ChatMessageDict]
```
Two modes: filter-only (`queryEmbedding is None`, sorted by `date DESC`, `score=0.0`) or semantic (cosine similarity over the `vec_message_embeddings_{N}` vec0 tables, `score = similarity`). See [`vec_message_embeddings_N`](#vec_message_embeddings_n-virtual-table) for the storage side. When `sqlite-vec` is unavailable, the semantic path returns `[]` (the in-process numpy cosine fallback was retired alongside the `message_embeddings` BLOB store in `migration_025`).

---

### User Operations

**Save/Update User**
```python
db.chatUsers.updateChatUser(
    chatId: int,
    userId: int,
    username: str,
    fullName: str
) -> bool
```
Upsert — inserts a new `chat_users` row or refreshes `username` / `fullName` / `updated_at` on conflict. `timezone` is **not** settable via this method (the column exists in the schema but is populated through other paths).

**Get User**
```python
db.chatUsers.getChatUser(
    chatId: int,
    userId: int,
    *,
    dataSource: Optional[str] = None
) -> Optional[ChatUserDict]
```

**Get User by Username**
```python
db.chatUsers.getChatUserByUsername(
    chatId: int,
    username: str,
    *,
    dataSource: Optional[str] = None
) -> Optional[ChatUserDict]
```
Case-insensitive exact match on `username` (portable `LOWER(...) = LOWER(...)` via the provider hook).

**Get All Users**
```python
db.chatUsers.getChatUsers(
    chatId: int,
    limit: Optional[int] = None,
    minMessages: Optional[int] = None,
    lastActiveDays: Optional[int] = None,
    seenSince: Optional[datetime.datetime] = None,
    *,
    dataSource: Optional[str] = None,
) -> List[ChatUserDict]
```
`seenSince` and `lastActiveDays` both apply to `updated_at`; when both are passed `lastActiveDays` wins (the relative window is more specific). Ordered by `updated_at DESC`. `limit=None` returns every matching row.

**Update User Metadata**
```python
db.chatUsers.updateUserMetadata(
    chatId: int,
    userId: int,
    metadata: str
) -> bool
```
Shallow top-level write — see the [`chat_users` metadata convention](#chat_users) for the read-modify-write rule (`CacheService.updateUserMetadata()` is the safe path; this repo method does NOT merge).

---

### Chat Operations

**Save/Update Chat Info**
```python
db.chatInfo.updateChatInfo(
    chatId: int,
    type: str,
    title: Optional[str] = None,
    username: Optional[str] = None,
    isForum: Optional[bool] = False
) -> bool
```
Note the parameter order: `type` is **required** and positional (no default); `title` / `username` / `isForum` are optional. Upsert keyed on `chat_id`.

**Get Chat Info**
```python
db.chatInfo.getChatInfo(
    chatId: int,
    *,
    dataSource: Optional[str] = None
) -> Optional[ChatInfoDict]
```

**Save/Update Topic**
```python
db.chatInfo.updateChatTopicInfo(
    chatId: int,
    topicId: int,
    iconColor: Optional[int] = None,
    customEmojiId: Optional[str] = None,
    topicName: Optional[str] = None        # None → "Default"
) -> bool
```

**Get Topics**
```python
db.chatInfo.getChatTopics(
    chatId: int,
    *,
    dataSource: Optional[str] = None
) -> List[ChatTopicInfoDict]
```

---

### Settings Operations

**Get Chat Setting**
```python
db.chatSettings.getChatSetting(
    chatId: int,
    setting: str,
    *,
    dataSource: Optional[str] = None
) -> Optional[str]
```
Returns `None` if the key is unset (there is **no `default` parameter** at this layer — callers that need a default can use `Optional[str]` and fall back themselves, or use the handler-layer `getChatSettings()` which returns `ChatSettingsValue` objects with `.toStr()` / `.toBool()` / etc.).

**Get All Chat Settings**
```python
db.chatSettings.getChatSettings(
    chatId: int,
    *,
    dataSource: Optional[str] = None
) -> Dict[str, tuple[str, int]]  # value → (value, updated_by)
```

**Set Chat Setting**
```python
db.chatSettings.setChatSetting(
    chatId: int,
    key: str,
    value: Any,
    *,
    updatedBy: int  # REQUIRED keyword-only — user ID who changed the setting
) -> bool
```

**Unset / Clear**
```python
db.chatSettings.unsetChatSetting(chatId: int, key: str) -> bool
db.chatSettings.clearChatSettings(chatId: int) -> bool
```

**Get Global Setting**
```python
db.common.getSetting(
    key: str,
    default: Optional[str] = None,
    *,
    dataSource: Optional[str] = None
) -> Optional[str]
```

**Set Global Setting**
```python
db.common.setSetting(
    key: str,
    value: str,
    *,
    dataSource: Optional[str] = None
) -> bool
```

**Get All Global Settings**
```python
db.common.getSettings(
    *,
    dataSource: Optional[str] = None
) -> Dict[str, str]
```

---

### Media Operations

**Add Media Attachment**
```python
db.mediaAttachments.addMediaAttachment(
    *,
    fileUniqueId: str,
    fileId: str,
    fileSize: Optional[int] = None,
    mediaType: MessageType = MessageType.IMAGE,
    mimeType: Optional[str] = None,
    metadata: str | Dict[str, Any] = "{}",
    status: MediaStatus = MediaStatus.NEW,
    localUrl: Optional[str] = None,
    prompt: Optional[str] = None,
    description: Optional[str] = None
) -> bool
```
Note: **all parameters are keyword-only**, the default `status` is `MediaStatus.NEW` (not `PENDING`), and `fileId` is **required** (no default).

**Update Media Attachment (unified partial update)**
```python
db.mediaAttachments.updateMediaAttachment(
    mediaId: str,                            # file_unique_id
    *,
    fileSize: Optional[int] = None,
    status: Optional[MediaStatus] = None,
    metadata: Optional[str | Dict[str, Any]] = None,
    mimeType: Optional[str] = None,
    localUrl: Optional[str] = None,
    description: Optional[str] = None,
    prompt: Optional[str] = None
) -> bool
```
Single method that updates any subset of fields (only non-`None` fields are written). Replaces the older separate `updateMediaStatus` / `updateMediaDescription` methods that no longer exist.

**Get Media Attachment**
```python
db.mediaAttachments.getMediaAttachment(
    mediaId: str,
    *,
    dataSource: Optional[str] = None
) -> Optional[MediaAttachmentDict]
```

**Get Media Attachments by Group ID**
```python
db.mediaAttachments.getMediaAttachmentsByGroupId(
    mediaGroupId: str,
    *,
    dataSource: Optional[str] = None
) -> List[MediaAttachmentDict]
```
JOINs `media_groups` to `media_attachments`.

**Get Media Group Last Updated At**
```python
db.mediaAttachments.getMediaGroupLastUpdatedAt(
    mediaGroupId: str,
    *,
    dataSource: Optional[str] = None
) -> Optional[datetime.datetime]
```

**Ensure Media in Group**
```python
db.mediaAttachments.ensureMediaInGroup(
    *,
    mediaId: str,
    mediaGroupId: str
) -> bool
```
Idempotent upsert into `media_groups` (`ON CONFLICT DO NOTHING`).

---

### Spam Detection Operations

`db.spam` (`SpamRepository`) only owns the **message-log** side of spam/ham training (rows in `spam_messages` / `ham_messages`). The Bayes-model statistics live in `bayes_tokens` / `bayes_classes` and are exposed through a **separate** class, `DatabaseBayesStorage` (`internal/database/bayes_storage.py`) — see [Bayes Statistics Operations](#bayes-statistics-operations) below.

**Add Spam Message**
```python
db.spam.addSpamMessage(
    chatId: int,
    userId: int,
    messageId: MessageId,
    messageText: str,
    spamReason: SpamReason,
    score: float,
    confidence: float
) -> bool
```

**Add Ham Message**
```python
db.spam.addHamMessage(
    chatId: int,
    userId: int,
    messageId: MessageId,
    messageText: str,
    spamReason: SpamReason,
    score: float,
    confidence: float
) -> bool
```

**Get Spam Messages (paginated list)**
```python
db.spam.getSpamMessages(
    limit: int = 1000,
    *,
    dataSource: Optional[str] = None
) -> List[SpamMessageDict]
```
Returns ALL spam messages across ALL chats (there is **no `chatId` filter** here — pass one of the chat-scoped variants below for that), ordered by insertion order, capped by `limit`. `dataSource` is keyword-only.

**Get Spam Messages by Text (case-insensitive)**
```python
db.spam.getSpamMessagesByText(
    text: str,
    *,
    dataSource: Optional[str] = None
) -> List[SpamMessageDict]
```
Portable `LOWER(...) = LOWER(...)` match via `provider.getCaseInsensitiveComparison(...)`.

**Get Spam Messages by User**
```python
db.spam.getSpamMessagesByUserId(
    chatId: int,
    userId: int,
    *,
    dataSource: Optional[str] = None
) -> List[SpamMessageDict]
```

**Delete Spam Messages by User**
```python
db.spam.deleteSpamMessagesByUserId(
    chatId: int,
    userId: int
) -> bool
```

---

### Bayes Statistics Operations

Bayes-filter statistics are NOT on `db.spam`. They live on a separate `DatabaseBayesStorage` instance (`internal/database/bayes_storage.py`, implements `lib.bayes_filter.storage_interface.BayesStorageInterface`) which is constructed with a `Database` handle and an optional `dataSource`:

```python
from internal.database.bayes_storage import DatabaseBayesStorage

storage = DatabaseBayesStorage(db, dataSource=None)
```

All methods take an optional `chatId: Optional[int] = None`. `chatId=None` targets the **global** model (`chat_id IS NULL`); an int targets a chat-local model.

**Token statistics**
```python
storage.getTokenStats(tokens: Iterable[str], chatId: Optional[int] = None) -> Dict[str, TokenStats]
storage.updateTokenStats(token: str, is_spam: bool, increment: int = 1, chat_id: Optional[int] = None) -> bool
storage.batchUpdateTokens(tokenUpdates: List[Dict[str, Any]], chatId: Optional[int] = None) -> bool
storage.getAllTokens(chatId: Optional[int] = None) -> List[str]
storage.getVocabularySize(chatId: Optional[int] = None) -> int
storage.getTopSpamTokens(limit: int = 10, chatId: Optional[int] = None) -> List[TokenStats]
storage.getTopHamTokens(limit: int = 10, chatId: Optional[int] = None) -> List[TokenStats]
```

**Class statistics**
```python
storage.getClassStats(is_spam: bool, chat_id: Optional[int] = None) -> ClassStats
storage.updateClassStats(isSpam: bool, messageIncrement: int = 1, tokenIncrement: int = 0, chatId: Optional[int] = None) -> bool
```

**Aggregate / maintenance**
```python
storage.getModelStats(chatId: Optional[int] = None) -> BayesModelStats
storage.clearStats(chatId: Optional[int] = None) -> bool
storage.cleanupRareTokens(minCount: int = 2, chatId: Optional[int] = None) -> None
storage.cleanupOldTokens(rules: Sequence[Tuple[int, int]]) -> bool   # each rule = (ttlSeconds, maxCount)
```

Note the asymmetric parameter names: `getTokenStats` / `getClassStats` use `chatId`, but `updateTokenStats` uses `chat_id` (and `is_spam` snake_case) — these come straight from the `BayesStorageInterface`. `updateClassStats` is camelCased. The underlying tables (`bayes_tokens`, `bayes_classes`) were added by `migration_006`.

---

### Cache Operations

The `db.cache` repository (`CacheRepository`) owns **two** distinct tables — `cache` (typed entries with TTL) and `cache_storage` (simple namespace/key/value). All methods take a keyword-only `dataSource: Optional[str] = None`.

**Get Cache Entry (TTL-aware)**
```python
db.cache.getCacheEntry(
    key: str,
    cacheType: CacheType,
    ttl: Optional[int] = None,
    *,
    dataSource: Optional[str] = None
) -> Optional[CacheDict]
```
Returns `None` immediately (without querying) when `ttl is not None and ttl <= 0`. When `ttl > 0`, only rows whose `updated_at >= now - ttl seconds` match. Note parameter order: `key` first, `cacheType` second.

**Set Cache Entry**
```python
db.cache.setCacheEntry(
    key: str,
    data: str,
    cacheType: CacheType,
    *,
    dataSource: Optional[str] = None
) -> bool
```
Upsert keyed on `(namespace=cacheType, key)`; on conflict `data` and `updated_at` are refreshed (`created_at` stays).

**Clear Entire Cache Type**
```python
db.cache.clearCache(
    cacheType: CacheType,
    *,
    dataSource: Optional[str] = None
) -> None
```

**Clear Old Cache Entries**
```python
db.cache.clearOldCacheEntries(
    ttl: Optional[int],
    cacheType: Optional[CacheType] = None,
    *,
    dataSource: Optional[str] = None
) -> bool
```
`ttl=None` or `0` removes **all** entries of the matching type(s). `cacheType=None` applies the cleanup across every namespace.

**Get Cache Storage Entries (list all)**
```python
db.cache.getCacheStorage(
    *,
    dataSource: Optional[str] = None
) -> List[CacheStorageDict]
```
There is **no namespace/key filter** — this returns every `cache_storage` row, ordered by `updated_at DESC`.

**Set Cache Storage Entry**
```python
db.cache.setCacheStorage(
    namespace: str,
    key: str,
    value: str,
    *,
    dataSource: Optional[str] = None
) -> bool
```

**Unset Cache Storage Entry**
```python
db.cache.unsetCacheStorage(namespace: str, key: str) -> bool
```

---

### Summarization Operations

`db.chatSummarization` (`ChatSummarizationRepository`) is the cache for chat-history summaries, keyed by a SHA-512 `csid` over `(chatId, topicId, firstMessageId, lastMessageId, prompt)`. Upsert semantics — re-summarising the same range with the same prompt refreshes the row in place.

**Add / Refresh Summarization**
```python
db.chatSummarization.addChatSummarization(
    chatId: int,
    topicId: Optional[int],
    firstMessageId: MessageId,
    lastMessageId: MessageId,
    prompt: str,
    summary: str
) -> bool
```

**Get Summarization (cache lookup)**
```python
db.chatSummarization.getChatSummarization(
    chatId: int,
    topicId: Optional[int],
    firstMessageId: MessageId,
    lastMessageId: MessageId,
    prompt: str,
    *,
    dataSource: Optional[str] = None
) -> Optional[ChatSummarizationCacheDict]
```
`dataSource` is keyword-only. The write path (`addChatSummarization`) routes via `chatId` and has no `dataSource` override.

---

### Task Operations

`db.delayedTasks` (`DelayedTasksRepository`). Tasks are application-generated UUID strings (no DB-side `AUTOINCREMENT`); `kwargs` is a JSON-serialised string the caller builds.

**Add Delayed Task**
```python
db.delayedTasks.addDelayedTask(
    taskId: str,
    function: str,
    kwargs: str,
    delayedTS: int
) -> bool
```
Parameter order: `taskId, function, kwargs, delayedTS` (not `delayedTS, function, kwargs`). Writes to the default source only; no `chatId`/`dataSource` override.

**Update Delayed Task (mark done / reset)**
```python
db.delayedTasks.updateDelayedTask(
    id: str,
    isDone: bool
) -> bool
```
Generic completion-flag mutator — pass `isDone=True` to mark done, `isDone=False` to re-arm. Bumps `updated_at`. There is no dedicated `markDelayedTaskDone` method.

**Get Pending Tasks**
```python
db.delayedTasks.getPendingDelayedTasks(
    *,
    dataSource: Optional[str] = None
) -> List[DelayedTaskDict]
```
Returns every row with `is_done = FALSE` (there is **no `currentTs` parameter** — callers filter `delayed_ts` against the current time themselves). `dataSource` is keyword-only.

**Cleanup Old Completed Tasks**
```python
db.delayedTasks.cleanupOldCompletedDelayedTasks(
    ttl: Optional[int],
    *,
    dataSource: Optional[str] = None
) -> bool
```
Deletes rows with `is_done = TRUE AND updated_at < now - ttl`. `ttl=None` or `0` removes every completed task regardless of age.

---

## Multi-Source Routing

### Routing Priority (3-tier)

1. **Tier 1 (Highest)**: Explicit `dataSource` parameter
2. **Tier 2 (Medium)**: Chat ID mapping lookup
3. **Tier 3 (Lowest)**: Default source fallback

### Configuration Example

```toml
[database]
default = "default"

[database.providers.default]
provider = "sqlite3"

[database.providers.default.parameters]
dbPath = "data/bot.db"
readOnly = false
timeout = 30
useWal = true

[database.providers.archive]
provider = "sqlite3"

[database.providers.archive.parameters]
dbPath = "data/archive.db"
readOnly = true
timeout = 10
```

### Usage Examples

```python
# Explicit routing (Tier 1)
db.chatMessages.getChatMessagesSince(chatId=123, dataSource="archive")

# Chat mapping routing (Tier 2)
db.chatMessages.getChatMessagesSince(chatId=-1001234567890)  # Routes to "archive"

# Default routing (Tier 3)
db.chatMessages.getChatMessagesSince(chatId=456)  # Routes to "default"
```

---

## Common Query Patterns

### Get Recent Chat Context
```python
messages = db.chatMessages.getChatMessagesSince(
    chatId=chat_id,
    sinceDateTime=datetime.now() - timedelta(hours=1),
    limit=50,
    messageCategory=[MessageCategory.USER, MessageCategory.BOT]
)
```

### Get Conversation Thread
```python
thread_messages = db.chatMessages.getChatMessagesByRootId(
    chatId=chat_id,
    rootMessageId=root_msg_id,
    threadId=topic_id
)
```

### Get Chat Configuration
```python
settings = db.chatSettings.getChatSettings(chatId=chat_id)
# Returns Dict[str, tuple[str, int]] where tuple is (value, updated_by)
model = settings.get('chat-model', ('gpt-4', 0))[0]  # Index [0] for value
updatedBy = settings.get('chat-model', ('gpt-4', 0))[1]  # Index [1] for updated_by
use_tools = settings.get('use-tools', ('false', 0))[0] == 'true'
```

### Cache API Response
```python
# Set cache (note: positional order is key, data, cacheType)
db.cache.setCacheEntry(
    key=f"{lat},{lon}",
    data=json.dumps(weather_data),
    cacheType=CacheType.WEATHER
)

# Get cache (TTL in seconds; pass ttl=None for "no expiry")
cached = db.cache.getCacheEntry(
    key=f"{lat},{lon}",
    cacheType=CacheType.WEATHER,
    ttl=3600
)
if cached:
    weather_data = json.loads(cached['data'])
```

---

## TypedDict to Table Mapping

| TypedDict | Table(s) | Joins |
|-----------|----------|-------|
| `ChatMessageDict` | `chat_messages` | `chat_users`, `media_attachments` |
| `ChatUserDict` | `chat_users` | None |
| `ChatInfoDict` | `chat_info` | None |
| `ChatTopicInfoDict` | `chat_topics` | None |
| `MediaAttachmentDict` | `media_attachments` | None |
| `DelayedTaskDict` | `delayed_tasks` | None |
| `WebhookUpdatesRow` | `webhook_updates` | None |
| `SpamMessageDict` | `spam_messages` | None |
| `ChatSummarizationCacheDict` | `chat_summarization_cache` | None |
| `CacheDict` | `cache` | None |
| `CacheStorageDict` | `cache_storage` | None |
| `UserMemoryDict` | `user_memories` | None |
| `ModelDict` | `models` | None |

---

## Key Relationships

```
chat_info (1) ──< (N) chat_topics
chat_info (1) ──< (N) chat_users
chat_users (1) ──< (N) chat_messages
chat_users (1) ──< (N) user_memories
media_attachments (1) ──< (N) chat_messages
chat_messages (1) ──< (N) chat_messages (self-reference via reply_id, root_message_id)
```

---

## Notes for LLM Usage

1. **Always specify chatId** for operations that support multi-source routing
2. **Use TypedDict types** for type-safe returns
3. **Check return values** - most operations return `bool` for success/failure
4. **Use dataSource parameter** only when explicit routing is needed
5. **Message IDs are strings** - stored as TEXT in database
6. **Timestamps are datetime objects** - automatically converted by SQLite adapters
7. **JSON fields** (metadata, markup) are stored as TEXT strings
8. **Read-only sources** reject write operations with ValueError
9. **Thread-safe** - uses thread-local connections per source
10. **Auto-updates** - `chat_stats` and `chat_user_stats` updated automatically on message save