# Database Schema Reference for LLMs

## Quick Reference

**Database**: SQLite with multi-source support
**Database Class**: [`Database`](../internal/database/database.py:1)
**Models**: [`internal/database/models.py`](../internal/database/models.py:1)
**Repositories**: [`internal/database/repositories/`](../internal/database/repositories/)
**Migrations**: 20 (up to `migration_020`)

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
    message_type TEXT NOT NULL DEFAULT 'text',
    message_category TEXT NOT NULL DEFAULT 'user',
    quote_text TEXT,
    media_id TEXT,
    media_group_id TEXT,
    markup TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, message_id),
    FOREIGN KEY (chat_id, user_id) REFERENCES chat_users(chat_id, user_id),
    FOREIGN KEY (media_id) REFERENCES media_attachments(file_unique_id)
)
```

**TypedDict**: [`ChatMessageDict`](../internal/database/models.py:108)
**Relationships**: References [`chat_users`](#chat_users), [`media_attachments`](#media_attachments), [`media_groups`](#media_groups)

**Note**: The `media_group_id` column links messages that are part of a media group (album of photos/videos sent together).

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
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
)
```

**TypedDict**: [`ChatInfoDict`](../internal/database/models.py:215)

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

**Available Keys**: See [`ChatSettingsKey`](../internal/bot/models/chat_settings.py:41) enum

---

### media_group
**Purpose**: Media group relationships for grouped media messages
**Primary Key**: `(media_group_id, media_id)`

```sql
CREATE TABLE media_group (
    media_group_id TEXT NOT NULL,
    media_id TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (media_group_id, media_id),
    FOREIGN KEY (media_id) REFERENCES media_attachments(file_unique_id)
)
```

**Relationships**: References [`media_attachments`](#media_attachments), referenced by [`chat_messages`](#chat_messages)

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
    metadata TEXT NOT NULL DEFAULT '',
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

---

### user_data
**Purpose**: Arbitrary user key-value data
**Primary Key**: `(user_id, chat_id, key)`

```sql
CREATE TABLE user_data (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (user_id, chat_id, key)
)
```

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

**TypedDict**: [`SpamMessageDict`](../internal/database/models.py:303)

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

**Indexes**: `bayes_tokens_chat_idx`, `bayes_tokens_total_idx`

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

**TypedDict**: [`ChatSummarizationCacheDict`](../internal/database/models.py:326)
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

**TypedDict**: [`CacheStorageDict`](../internal/database/models.py:364)

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
    question       TEXT    NOT NULL DEFAULT '',
    draws_json     TEXT    NOT NULL,                          -- JSON list of drawn symbols
    interpretation TEXT    NOT NULL DEFAULT '',
    image_prompt   TEXT,
    invoked_via    TEXT    NOT NULL,                          -- 'command' | 'llm_tool'
    created_at     TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, message_id)
)
```

**Indexes**: `idx_divinations_user_created` on `(chat_id, user_id, created_at)`

**Repository**: `db.divinations.insertReading(...)`

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

**Repository**: `DivinationLayoutsRepository`

**Usage**:
- Caches discovered layouts from LLM + web search
- Negative cache entries prevent repeated failed discoveries (`name_en=''`, `n_symbols=0`)
- Retrieved via `DivinationLayoutsRepository.getLayout()`
- Saved via `DivinationLayoutsRepository.saveLayout()`

**Note**: Only populated when `[divination] enabled = true`. Negative cache pattern stores failed discoveries with empty `name_en` and `n_symbols=0`.

---

### message_embeddings
**Purpose**: Float32 embedding vectors for chat messages — powers semantic ranking in `searchChatMessages`. Created by `migration_017`. Only populated when `[search-history] enabled = true`. See [`docs/llm/database.md`](../llm/database.md) §5.5 and [`docs/llm/configuration.md`](../llm/configuration.md) §`[search-history]`.
**Primary Key**: `(chat_id, message_id)` — same natural key as `chat_messages`

```sql
CREATE TABLE message_embeddings (
    chat_id    INTEGER   NOT NULL,
    message_id TEXT      NOT NULL,                             -- MessageId.asStr() (Telegram int) or verbatim (Max str)
    embedding  BLOB      NOT NULL,                             -- array.array('f', vec).tobytes() (float32 LE)
    dimensions INTEGER   NOT NULL,                             -- len(embedding), derived in saveMessageEmbedding
    model      TEXT      NOT NULL,                             -- e.g. 'text-embedding-3-small' (resolved model name)
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, message_id)
)
```

**Indexes**: `idx_message_embeddings_chat_model` on `(chat_id, model)` — speeds up `_loadEmbeddingsFromDb` (filters by both chat and model name). Created by `migration_018`. The PK leftmost prefix covers per-chat enumeration (`WHERE chat_id = ?`).

**Repository methods** (`ChatEmbeddingsRepository`):
- `saveMessageEmbedding(chatId, messageId, embedding, model)` — upsert vector; `dimensions` derived from `len(embedding)`.
- `getMessageEmbedding(chatId, messageId) -> Optional[MessageEmbeddingDict]` — single-row lookup that reads only the `message_embeddings` row. Returns `message_id` + the embedding fields (`embedding`, `dimensions`, `model`, `created_at`, `updated_at`). No JOIN against `chat_messages`; call `getChatMessageByMessageId` separately if the message text is also needed.
- `getMessagesWithoutEmbeddings(chatId, limit, modelName) -> list[ChatMessageDict]` — used by `ChatSearchHandler._dtCronJob` (backfill). Returns full `ChatMessageDict` rows (joined with `chat_users` for `username`/`full_name`); the `message_embeddings` table is only used as a `NOT EXISTS` filter, not selected from. When `modelName` is set, rows whose existing embedding was made by a different model are also surfaced.
- `deleteChatEmbeddings(chatId)` — drop all embeddings for a chat (e.g. on model switch).

**Public dispatcher** (`ChatMessagesRepository`):
- `searchChatMessages(chatId, queryEmbedding=..., ...) -> list[SearchResultDict]` — combined filter + (optional) semantic search; cosine similarity over the embedding blob when `queryEmbedding` is provided. Embeddings are re-loaded fresh from `message_embeddings` on every call. The semantic path delegates to `ChatEmbeddingsRepository._semanticSearch` via a private back-reference.

**In-memory cache**: `ChatMessagesRepository` does NOT keep a per-chat `TTLDict` of decoded float matrices — the previous `_embeddingCache` and the `[search-history.embeddings].cache-ttl-seconds` / `cache-max-chats` settings were removed. Caching decoded vectors belongs in the handler layer (via `CacheService`) and is intentionally not implemented at the repository level.

**Note**: No foreign-key to `chat_messages` — messages can be deleted from `chat_messages` without cascading (embeddings become orphans and are eventually overwritten by a future re-embed pass). The `model` column lets a chat switch `EMBEDDING_MODEL` cleanly: `getMessagesWithoutEmbeddings(chatId, ..., modelName=newModel)` skips rows already produced by `newModel`, so the `ChatSearchHandler._dtCronJob` backfill re-uses compatible rows.

---

### vec_message_embeddings_N (virtual table)
**Purpose**: Ephemeral `vec0` virtual tables (one per embedding dimension in use, e.g. `vec_message_embeddings_384`, `vec_message_embeddings_1024`) that mirror `message_embeddings` rows for native cosine-similarity KNN search via the `sqlite-vec` extension. **Authoritative data lives in [`message_embeddings`](#message_embeddings)** — these are rebuildable sidecar indexes.
**Primary Key**: vec0 internal rowid (not a natural key)
**Created by**: `SQLite3Provider.createVectorTable()` at runtime (lazily, on first write of a given dimension in `saveMessageEmbedding`). No migration creates them. Absent when `sqlite-vec` is not installed.

```sql
CREATE VIRTUAL TABLE vec_message_embeddings_384 USING vec0(
    message_id TEXT,
    chat_id INTEGER PARTITION KEY,
    model TEXT PARTITION KEY,
    date TEXT,                            -- ISO-8601 from chat_messages; enables maxMessages pre-filter
    embedding FLOAT[384] distance_metric=cosine
)
```

| Column | Type | Notes |
|--------|------|-------|
| `message_id` | TEXT | Matches `message_embeddings.message_id` |
| `chat_id` | INTEGER | `PARTITION KEY` — `WHERE chat_id = ?` prunes the search |
| `model` | TEXT | `PARTITION KEY` — `WHERE model = ?` prunes the search |
| `date` | TEXT | ISO-8601 from `chat_messages.date`; enables `maxMessages` pre-filter via `date >= :minDate` |
| `embedding` | FLOAT[N] | float32 vector, `N` = dimension (matches table-name suffix); `distance_metric=cosine` |

**Lifecycle**: dual-written by `ChatEmbeddingsRepository.saveMessageEmbedding()` alongside `message_embeddings`. Stale rows from a previous model are cleaned up statelessly by `ChatSearchHandler._dtCronJob` — it lists `vec_message_embeddings_%` via `provider.listTables()` and runs `DELETE FROM {table} WHERE chat_id = :chatId AND model != :currentModel` on each. Vec0 DDL is extension-specific; standard SQL portability rules (`AUTOINCREMENT`, `DEFAULT CURRENT_TIMESTAMP`, etc.) do not apply.

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
**Purpose**: Unified per-(chat, user, thread) memory store — durable facts, preferences, events, relationships, and high-level bio notes about a user. Retires the legacy `user_data` key-value table and the rolling-bio JSON blob (`chat_users.metadata.memoryRefinement`); both are backfilled into this table by `migration_020`. Created by `migration_020`. Semantic search runs over a vec0 virtual table (`vec_user_memories_{dim}`, cosine distance) that is **not** created by the migration — it is created lazily at runtime on first write (mirrors `message_embeddings`). Unlike chat-history search there is no BLOB side table: `embedding_model` / `embedding_dimensions` are tracked on `user_memories` itself and vec0 is the sole embedding store. When vec0 is unavailable, `searchMemories` returns `[]` (no numpy fallback).
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
    embedding_model      TEXT,     -- NULL = not yet embedded
    embedding_dimensions INTEGER,  -- NULL = not yet embedded
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

**TypedDict**: [`UserMemoryDict`](../internal/database/models.py:551) (snake_case keys matching columns; `score` is `NotRequired[float]` populated by semantic search).

**Enum**: [`MemoryType`](../internal/database/models.py:473) (`BIO`/`PREFERENCE`/`FACT`/`EVENT`/`RELATIONSHIP`); [`UserMemorySource`](../internal/database/models.py:515) (`REFINEMENT`/`CHAT`/`MIGRATION`/`USER`).

**Repository** (`UserMemoriesRepository`, accessed as `db.userMemories`) — 10 public methods; all SQL goes through `BaseSQLProvider`:
- `addMemory(chatId, userId, memoryId, *, type, content, tags, permanent, source, embedding=None, embeddingModel=None, threadId=None) -> None` — INSERT (caller generates the UUID). `source` is a `UserMemorySource`; `threadId` is keyword-only; when both `embedding` (`List[float]`) and `embeddingModel` are provided the row is embedded during add.
- `deleteMemory(chatId, userId, memoryId) -> bool` — SOFT DELETE: sets `deleted_at` + bumps `updated_at`, drops the vec0 row, nulls `embedding_model`/`embedding_dimensions`. Unrestricted (may target permanent). Row survives for historical reads; never raises.
- `getPermanentMemories(chatId, userId, threadId, *, limit=10) -> List[UserMemoryDict]` — merges cross-thread permanent (`thread_id IS NULL`) AND this-thread permanent. Filters `deleted_at IS NULL`.
- `getLatestMemories(chatId, userId, threadId, *, limit=5) -> List[UserMemoryDict]` — thread-scoped newest-first, **ephemeral-only** (`permanent = 0`); permanent memories are served by `getPermanentMemories`. Filters `deleted_at IS NULL`.
- `getMemoriesByIds(memoryIds: List[str], *, chatId: Optional[int] = None, dataSource: Optional[str] = None) -> List[UserMemoryDict]` — the single read that does NOT filter `deleted_at`: resolves UUIDs to content for historical message reconstruction (compact-ID storage). No `chatId`/`userId` scoping in the WHERE clause (UUIDs globally unique); `chatId`/`dataSource` are routing-only (forwarded to `getProvider(..., readonly=True)`); default `None` → default DB.
- `searchMemories(chatId, userId, queryEmbedding=None, *, threadId=None, type=None, tags=None, permanent=None, limit=20, embeddingModel, offset=0) -> List[UserMemoryDict]` — filter-only (`queryEmbedding is None`) or semantic (vec0 KNN, `score = 1.0 - distance`). `queryEmbedding` is `Optional[List[float]]`; `embeddingModel` (required, pass `None` for filter-only) replaces the old `dimensions` arg and is part of the vec0 `model` partition filter. `tags` applied as a portable SQL `LIKE '%"tagN"%'` filter (ANY-match) against the JSON-TEXT `tags` column. Both modes filter `deleted_at IS NULL`.
- `saveMemoryEmbedding(chatId, userId, memoryId, embedding, embeddingModel) -> bool` — lazy-create `vec_user_memories_{dim}` + upsert the vector (`embedding` is `List[float]`, `embeddingModel` the model name) + set provenance. Its internal row SELECT also filters `deleted_at IS NULL` (defense-in-depth).
- `deleteMemoryEmbedding(chatId, userId, memoryId) -> None` — best-effort vec0 DELETE; never raises.
- `getMemoriesWithoutEmbeddings(chatId, modelName, *, limit) -> List[UserMemoryDict]` — stale detection (NULL or mismatched `embedding_model`); backs the regen cron + initial backfill. Filters `deleted_at IS NULL` (so a soft-deleted memory is never re-embedded).
- `deleteObsoleteMemoryEmbeddings(chatId, currentModel, currentDimensions) -> int` — model-drift cleanup.

**Backfills** (`migration_020.up()`):
- `user_data` rows → permanent cross-thread `type='fact'`, `content="{key}: {data}"`, `tags=[]`, `source='migration'`, original timestamps preserved.
- `chat_users.metadata.memoryRefinement[str(threadId)]` entries (non-empty summary) → permanent thread-scoped `type='bio'`, `tags=["migrated_bio"]`, `source='migration'`, summary preserved in `content`.

**Note**: No `AUTOINCREMENT`/`SERIAL`, no `DEFAULT CURRENT_TIMESTAMP` — `memory_id` is an app-generated UUID and timestamps are application-set. Created by `migration_020`; `deleted_at` added by `migration_021` (soft-delete — `down()` is a no-op that logs: portable `DROP COLUMN` unavailable, nullable additive column safe on rollback). `down()` for migration 020 drops only `user_memories`; `user_data` is kept for rollback safety. The vec0 runtime table (`vec_user_memories_{dim}`) is NOT created by a migration — it is created lazily on first write at runtime.

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
**Location**: [`internal/database/models.py:377`](../internal/database/models.py:377)

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
    threadId: Optional[int] = None,
    messageText: str = "",
    messageType: MessageType = MessageType.TEXT,
    messageCategory: MessageCategory = MessageCategory.UNSPECIFIED,
    rootMessageId: Optional[MessageId] = None,
    quoteText: Optional[str] = None,
    mediaId: Optional[str] = None,
    markup: str = "",
    metadata: str = ""
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
    dataSource: Optional[str] = None
) -> List[ChatMessageDict]
```

**Get Message by ID**
```python
db.chatMessages.getChatMessageByMessageId(
    chatId: int,
    messageId: MessageId,
    dataSource: Optional[str] = None
) -> Optional[ChatMessageDict]
```

**Get Messages by Root ID**
```python
db.chatMessages.getChatMessagesByRootId(
    chatId: int,
    rootMessageId: MessageId,
    threadId: Optional[int] = None,
    dataSource: Optional[str] = None
) -> List[ChatMessageDict]
```

**Get Messages by User**
```python
db.chatMessages.getChatMessagesByUser(
    chatId: int,
    userId: int,
    limit: int = 100,
    dataSource: Optional[str] = None
) -> List[ChatMessageDict]
```

**Update Message Category**
```python
db.chatMessages.updateChatMessageCategory(
    chatId: int,
    messageId: MessageId,
    messageCategory: MessageCategory
) -> bool
```

---

### User Operations

**Save/Update User**
```python
db.chatUsers.saveChatUser(
    chatId: int,
    userId: int,
    username: str,
    fullName: str,
    timezone: Optional[str] = None
) -> bool
```

**Get User**
```python
db.chatUsers.getChatUser(
    chatId: int,
    userId: int,
    dataSource: Optional[str] = None
) -> Optional[ChatUserDict]
```

**Get All Users**
```python
db.chatUsers.getChatUsers(
    chatId: int,
    limit: Optional[int] = None,
    minMessages: Optional[int] = None,
    lastActiveDays: Optional[int] = None,
    seenSince: Optional[datetime.datetime] = None,
    dataSource: Optional[str] = None,
) -> List[ChatUserDict]
```

Default mode (no `minMessages` / `lastActiveDays`): orders by `updated_at DESC`.
Activity-filtered mode (any of `minMessages` / `lastActiveDays` set): orders by
`messages_count DESC` and applies both filters.

**Update User Metadata**
```python
db.chatUsers.updateChatUserMetadata(
    chatId: int,
    userId: int,
    metadata: str
) -> bool
```

---

### Chat Operations

**Save/Update Chat Info**
```python
db.chatInfo.saveChatInfo(
    chatId: int,
    title: Optional[str] = None,
    username: Optional[str] = None,
    chatType: str = "private",
    isForum: bool = False
) -> bool
```

**Get Chat Info**
```python
db.chatInfo.getChatInfo(
    chatId: int,
    dataSource: Optional[str] = None
) -> Optional[ChatInfoDict]
```

**Save Topic**
```python
db.chatInfo.saveChatTopic(
    chatId: int,
    topicId: int,
    name: Optional[str] = None,
    iconColor: Optional[int] = None,
    iconCustomEmojiId: Optional[str] = None
) -> bool
```

**Get Topics**
```python
db.chatInfo.getChatTopics(
    chatId: int,
    dataSource: Optional[str] = None
) -> List[ChatTopicInfoDict]
```

---

### Settings Operations

**Get Chat Setting**
```python
db.chatSettings.getChatSetting(
    chatId: int,
    key: str,
    default: Optional[str] = None,
    dataSource: Optional[str] = None
) -> Optional[str]
```

**Get All Chat Settings**
```python
db.chatSettings.getChatSettings(
    chatId: int,
    dataSource: Optional[str] = None
) -> Dict[str, tuple[str, int]]  # Returns tuple: (value, updated_by)
```

**Set Chat Setting**
```python
db.chatSettings.setChatSetting(
    chatId: int,
    key: str,
    value: str,
    updatedBy: int  # REQUIRED keyword-only argument - user ID who changed the setting
) -> bool
```

**Get Global Setting**
```python
db.common.getSetting(
    key: str,
    default: Optional[str] = None,
    dataSource: Optional[str] = None
) -> Optional[str]
```

**Set Global Setting**
```python
db.common.setSetting(
    key: str,
    value: str,
    dataSource: Optional[str] = None
) -> bool
```

---

### Media Operations

**Save Media Attachment**
```python
db.mediaAttachments.saveMediaAttachment(
    fileUniqueId: str,
    fileId: Optional[str] = None,
    fileSize: Optional[int] = None,
    mediaType: str = "photo",
    metadata: str = "",
    status: MediaStatus = MediaStatus.PENDING,
    mimeType: Optional[str] = None,
    localUrl: Optional[str] = None,
    prompt: Optional[str] = None,
    description: Optional[str] = None
) -> bool
```

**Get Media Attachment**
```python
db.mediaAttachments.getMediaAttachment(
    fileUniqueId: str,
    dataSource: Optional[str] = None
) -> Optional[MediaAttachmentDict]
```

**Update Media Status**
```python
db.mediaAttachments.updateMediaStatus(
    fileUniqueId: str,
    status: MediaStatus
) -> bool
```

**Update Media Description**
```python
db.mediaAttachments.updateMediaDescription(
    fileUniqueId: str,
    description: str
) -> bool
```

---

### User Data Operations

**Add User Data**
```python
db.userData.addUserData(
    userId: int,
    chatId: int,
    key: str,
    data: str
) -> bool
```

**Get User Data**
```python
db.userData.getUserData(
    userId: int,
    chatId: int,
    dataSource: Optional[str] = None
) -> Dict[str, str]
```

**Delete User Data**
```python
db.userData.deleteUserData(
    userId: int,
    chatId: int,
    key: str
) -> bool
```

---

### Spam Detection Operations

**Save Spam Message**
```python
db.spam.saveSpamMessage(
    chatId: int,
    userId: int,
    messageId: MessageId,
    text: str,
    reason: SpamReason,
    score: float
) -> bool
```

**Save Ham Message**
```python
db.spam.saveHamMessage(
    chatId: int,
    userId: int,
    messageId: MessageId,
    text: str,
    reason: str,
    score: float
) -> bool
```

**Get Spam Messages**
```python
db.spam.getSpamMessages(
    chatId: int,
    limit: int = 100,
    dataSource: Optional[str] = None
) -> List[SpamMessageDict]
```

**Update Bayes Token**
```python
db.spam.updateBayesToken(
    token: str,
    chatId: Optional[int],
    spamCount: int,
    hamCount: int
) -> bool
```

**Get Bayes Token**
```python
db.spam.getBayesToken(
    token: str,
    chatId: Optional[int] = None,
    dataSource: Optional[str] = None
) -> Optional[Dict[str, Any]]
```

**Update Bayes Class**
```python
db.spam.updateBayesClass(
    chatId: Optional[int],
    isSpam: bool,
    messageCount: int,
    tokenCount: int
) -> bool
```

---

### Cache Operations

**Get Cache**
```python
db.cache.getCache(
    cacheType: CacheType,
    key: str,
    dataSource: Optional[str] = None
) -> Optional[CacheDict]
```

**Set Cache**
```python
db.cache.setCache(
    cacheType: CacheType,
    key: str,
    data: str
) -> bool
```

**Get Cache Storage**
```python
db.cache.getCacheStorage(
    namespace: str,
    key: str,
    dataSource: Optional[str] = None
) -> Optional[CacheStorageDict]
```

**Set Cache Storage**
```python
db.cache.setCacheStorage(
    namespace: str,
    key: str,
    value: str
) -> bool
```

**Get Summarization Cache**
```python
db.chatSummarization.getChatSummarizationCache(
    chatId: int,
    topicId: Optional[int],
    firstMessageId: MessageId,
    lastMessageId: MessageId,
    prompt: str,
    dataSource: Optional[str] = None
) -> Optional[ChatSummarizationCacheDict]
```

**Set Summarization Cache**
```python
db.chatSummarization.setChatSummarizationCache(
    chatId: int,
    topicId: Optional[int],
    firstMessageId: MessageId,
    lastMessageId: MessageId,
    prompt: str,
    summary: str
) -> bool
```

---

### Task Operations

**Save Delayed Task**
```python
db.delayedTasks.saveDelayedTask(
    taskId: str,
    delayedTs: int,
    function: str,
    kwargs: str
) -> bool
```

**Get Pending Tasks**
```python
db.delayedTasks.getPendingDelayedTasks(
    currentTs: int,
    dataSource: Optional[str] = None
) -> List[DelayedTaskDict]
```

**Mark Task Done**
```python
db.delayedTasks.markDelayedTaskDone(
    taskId: str
) -> bool
```

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
db.chatMessages.getChatMessages(chatId=123, dataSource="archive")

# Chat mapping routing (Tier 2)
db.chatMessages.getChatMessages(chatId=-1001234567890)  # Routes to "archive"

# Default routing (Tier 3)
db.chatMessages.getChatMessages(chatId=456)  # Routes to "default"
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
# Set cache
db.cache.setCache(
    cacheType=CacheType.WEATHER,
    key=f"{lat},{lon}",
    data=json.dumps(weather_data)
)

# Get cache
cached = db.cache.getCache(
    cacheType=CacheType.WEATHER,
    key=f"{lat},{lon}"
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

---

## Key Relationships

```
chat_info (1) ──< (N) chat_topics
chat_info (1) ──< (N) chat_users
chat_users (1) ──< (N) chat_messages
chat_users (1) ──< (N) user_data
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