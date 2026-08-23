# Gromozeka — Database Operations

> **Audience:** LLM agents
> **Purpose:** Complete reference for database operations, migrations, schema, and multi-source routing
> **Self-contained:** Everything needed for database work is here

---

## Table of Contents

1. [Key Database Methods](#1-key-database-methods)
2. [Chat Settings in Database](#2-chat-settings-in-database)
3. [Multi-Source Database Routing](#3-multi-source-database-routing)
4. [Adding a Database Migration](#4-adding-a-database-migration)
5. [Database Models Reference](#5-database-models-reference)
6. [Adding Methods to Database](#6-adding-methods-to-database)
7. [Provider Helper Methods](#7-provider-helper-methods)
8. [Utility Functions](#8-utility-functions)
9. [Migration Documentation Protocol](#9-migration-documentation-protocol)

---

## 1. Key Database Methods

**File:** [`internal/database/database.py`](../../internal/database/database.py)

**Repository Pattern:** Database operations are now accessed through specialized repositories

| Repository | Method | Returns | Purpose |
|---|---|---|---|
| `chatMessages` | `saveChatMessage(...)` | `None` | Save incoming/outgoing message |
| `chatMessages` | `getChatMessageByMessageId(chatId, messageId)` | `Optional[ChatMessageDict]` | Get message by ID |
| `chatMessages` | `getChatMessagesByMessageIds(chatId, messageIds, *, dataSource?)` | `List[ChatMessageDict]` | Batch-fetch multiple messages by ID in one query. Portable `IN (:id0, :id1, ...)` named-placeholder expansion; same user JOIN as `getChatMessageByMessageId`; `ORDER BY c.date ASC`; early-returns `[]` on empty input. Does NOT dedup input IDs (caller's responsibility — duplicate IDs produce one row). Backs the `get_messages_by_ids` LLM tool (ADR-019). |
| `chatMessages` | `getChatMessagesByRootId(chatId, rootMessageId, threadId)` | `List[ChatMessageDict]` | Get thread messages |
| `chatMessages` | `getMessageThread(chatId, messageId, *, dataSource?)` | `Optional[ThreadResultDict]` | Get target + thread root + chronological thread messages |
| `chatMessages` | `getChatMessagesSince(chatId, sinceDateTime?, tillDateTime?, threadId?, limit?, messageCategory?, userId?, *, dataSource?)` | `List[ChatMessageDict]` | Messages newer than `sinceDateTime` (ordered date DESC). The additive `userId` filter (`AND (:userId IS NULL OR c.user_id = :userId)`) scopes results to one sender — used by the memory-refinement cron to fetch a user's recent messages |
| `chatMessages` | `updateChatMessageCategory(chatId, messageId, category)` | `None` | Update message category |
| `chatMessages` | `updateChatMessageMetadata(chatId, messageId, metadata)` | `None` | Update message metadata |
| `chatSearch` | `searchChatMessages(chatId, queryEmbedding=None, *, limit?, topK?, userFilter?, categoryFilter?, maxAgeDays?, rootMessageId?, modelName?, maxMessages?, threadId?, substring?, dataSource?)` | `List[ChatMessageDict]` | Combined filter + (optional) semantic search via cosine similarity over the `vec_message_embeddings_{N}` vec0 tables. When `queryEmbedding` is `None` results are returned in date order with `score=0.0`. Lives on the `chatSearch` repo (not `chatMessages`) — moved when `ChatSearchRepository` was split out to remove the old `_embeddingsRepo` back-reference. `SearchResultDict` was deleted; `ChatMessageDict` now carries an optional `score: NotRequired[float]` field populated by the search path. The repository takes a constructor-injected `modelIdResolver: Callable[[str, int], Awaitable[int]]` (Decision D10 — bound `EmbeddingModelsRepository.getOrCreateModelId`); the `modelName` arg is resolved to a `model_id` partition key internally without leaking that detail into the handler-facing signature (Decision D6 — handler-facing signatures stay stable). When `sqlite-vec` is unavailable, the semantic path returns `[]` (no numpy fallback — the numpy cosine path was retired alongside the `message_embeddings` BLOB store in `migration_025`). |
| `chatEmbeddings` | `saveMessageEmbedding(chatId, messageId, embedding, model)` | `None` | Single-write the float32 vector into the dimension-specific `vec_message_embeddings_{N}` vec0 table and `UPDATE chat_messages.model_id` with the resolved `model_id` (resolved via the constructor-injected `modelIdResolver`). `dimensions` is derived from `len(embedding)`. The previous dual-write to `message_embeddings` + vec0 is retired (`message_embeddings` was dropped in `migration_025`). |
| `chatEmbeddings` | `getMessagesWithoutEmbeddings(chatId, *, limit, modelName?, dimensions?, dataSource?)` | `List[ChatMessageDict]` | Used by `ChatSearchHandler._dtCronJob` to find messages missing a current embedding. Returns full `ChatMessageDict` rows (joined with `chat_users` for `username`/`full_name`); uses a stale predicate keyed on `chat_messages.model_id` (NULL, or `model_id` differing from the resolved active `(model, dimensions)` pair). The `dimensions` filter scopes the check by dimensionality so model-drift re-embedding only surfaces rows embedded under a different (model, dimensions) tuple |
| `chatEmbeddings` | `deleteObsoleteModelEmbeddings(chatId, currentModelId)` | `int` | Cleanup stale vec0 rows for a chat (used when switching to an incompatible model that produces different dimensions). Runs `DELETE FROM vec_message_embeddings_{N} WHERE chat_id = :chatId AND model_id != :currentModelId` across every `vec_message_embeddings_%` table enumerated via `provider.listTables()` |
| `chatUsers` | `getChatUser(chatId, userId)` | `Optional[ChatUserDict]` | Get user in chat |
| `chatUsers` | `updateChatUser(chatId, userId, username, fullName)` | `None` | Upsert user in chat |
| `chatUsers` | `updateUserMetadata(chatId, userId, metadata)` | `None` | Update user metadata (JSON string). The `metadata` column carries an optional `memoryRefinement` sub-dict — write nested sub-dicts via read-modify-write through this method directly, NOT `setUserMetadata(isUpdate=True)` (see [`tasks.md`](tasks.md) §3 shallow-merge gotcha) |
| `chatUsers` | `getChatUsers(chatId, limit?, minMessages?, lastActiveDays?, seenSince?, dataSource?)` | `List[ChatUserDict]` | List users in a chat. Default mode: order by `updated_at DESC` (most recently active first) with optional `seenSince` filter. Activity-filtered mode (any of `minMessages` / `lastActiveDays` set): order by `messages_count DESC` with both filters applied |
| `chatUsers` | `getUserChats(userId, *, botStatus=ChatBotStatus.ACTIVE, dataSource?)` | `List[ChatInfoDict]` | Get all chats for user. `botStatus` filter (added by `migration_026`): default `ChatBotStatus.ACTIVE` excludes inaccessible chats; `None` returns all. Applied as `(:botStatus IS NULL OR ci.bot_status = :botStatus)` against the `chat_info` JOIN. `getAllGroupChats(...)` shares the same `botStatus` parameter and predicate |
| `mediaAttachments` | `addMediaAttachment(...)` | `None` | Add media attachment record |
| `mediaAttachments` | `getMediaAttachment(mediaId)` | `Optional[MediaAttachmentDict]` | Get media by unique ID |
| `mediaAttachments` | `updateMediaAttachment(mediaId, ...)` | `bool` | Update media record fields (only non-`None` kwargs are written; `updated_at` is refreshed). Used by `_transcribeMedia` to terminalize STT rows (`PENDING`→`DONE`+`description` on success | `PENDING`→`FAILED` on failure/exception). Single attachments have no concurrent writes, so plain last-write semantics suffice — there is no CAS (the former `setStatusVerified` CAS helper was removed when the design was simplified). |
| `mediaAttachments` | `ensureMediaInGroup(mediaId, mediaGroupId)` | `None` | Ensure media in group |
| `mediaAttachments` | `getMediaGroupLastUpdatedAt(mediaGroupId)` | `Optional[datetime]` | Get MAX(created_at) from media_groups |
| `chatSettings` | `setChatSetting(chatId, key, value, *, updatedBy)` | `None` | Set a chat setting with audit trail |
| `chatSettings` | `getChatSetting(chatId, setting)` | `Optional[str]` | Get single setting value |
| `chatSettings` | `getChatSettings(chatId)` | `Dict[str, tuple[str, int]]` | Get all settings as (value, updated_by) |
| `cache` | `clearOldCacheEntries(ttl, cacheType=None)` | `bool` | Delete `cache` rows whose `updated_at < now − ttl`. `cacheType=None` purges ALL namespaces; pass a `CacheType` member to scope to one namespace. Driven by `HandlersManager._cleanupOldData()` on a per-namespace schedule (see `docs/llm/teamlead-memory.md` § "DB Cache Cleanup"): 365-day default floor for all namespaces, then a 7-day aggressive pass for `WEATHER`/`YANDEX_SEARCH`/`URL_CONTENT`/`URL_CONTENT_CONDENSED`. Constants live at the top of `internal/bot/common/handlers/manager.py` (`CACHE_CLEANUP_DEFAULT_TTL_SECS`, `CACHE_CLEANUP_AGGRESSIVE_TTL_SECS`, `AGGRESSIVE_CLEANUP_CACHE_TYPES`). Triggers: weekly cron (Monday 00:00 UTC via `_dtCronJob`) and on-shutdown (`_dtOnExit`) |
| `delayedTasks` | `cleanupOldCompletedDelayedTasks(ttl)` | `bool` | Cleanup old completed delayed tasks. Called from `_cleanupOldData()` with `DELAYED_TASKS_CLEANUP_TTL_SECS` (30 days) |
| `DatabaseBayesStorage` | `cleanupOldTokens(rules)` | `bool` | Delete old/rare rows from `bayes_tokens`. `rules` is a sequence of `(ttlSeconds, maxCount)` tuples; for each rule, runs `DELETE FROM bayes_tokens WHERE updated_at < :cutoffTime AND total_count <= :maxCount` across ALL tokens regardless of `chat_id` (one DELETE per rule). Returns `True` if all rules applied, `False` on any exception. NOTE: `DatabaseBayesStorage` is NOT a standard `self.db.<name>` repository — it's a separate class at [`internal/database/bayes_storage.py`](../../internal/database/bayes_storage.py), instantiated as `DatabaseBayesStorage(self.db)`. Called from `HandlersManager._cleanupOldData()` with `BAYES_TOKEN_CLEANUP_RULES` (defined near the top of `internal/bot/common/handlers/manager.py`; defaults: tokens with `total_count <= 1` older than 90 days, OR `total_count <= 2` older than 180 days). Sibling method `cleanupRareTokens(minCount, chatId=None)` is unrelated (no production caller in the cleanup path) |
| `divinations` | `insertReading(...)` | `None` | Persist a tarot/runes reading row in `divinations` |
| `divinations` | `getLayout(systemId, layoutName)` | `Optional[DivinationLayoutDict]` | Get cached layout with fuzzy search |
| `divinations` | `saveLayout(...)` | `bool` | Save/update layout definition in cache |
| `divinations` | `saveNegativeCache(systemId, layoutId)` | `bool` | Save negative cache entry for non-existent layout |
| `divinations` | `isNegativeCacheEntry(layoutDict)` | `bool` | Check if layout dict is a negative cache entry |
| `webhookUpdates` | `addUpdate(updateId, updateType, rawJson)` | `bool` | Store a raw Max webhook payload (caller-generated UUID) in `webhook_updates` |
| `webhookUpdates` | `getUnprocessedUpdates(limit=100)` | `List[WebhookUpdatesRow]` | Pending webhook payloads oldest-first; backs the receiver's GET /updates long-poll |
| `webhookUpdates` | `markProcessed(updateIds)` | `None` | Atomically mark a batch of updates processed (single batch commit prevents duplicate delivery) |
| `webhookUpdates` | `deleteProcessedOlderThan(ttlSeconds=3600)` | `bool` | Reap processed rows past the TTL; cutoff computed in Python for cross-RDBMS portability |
| `userMemories` | `addMemory(chatId, userId, memoryId, *, type, content, tags, permanent, source, embedding=None, embeddingModel=None, threadId=None)` | `None` | INSERT a memory row (caller generates the UUID hex; `memoryId` is not delegated to the DB). `source` is a `UserMemorySource`; when `embedding` (`List[float]`) + `embeddingModel` are provided the row is embedded during add |
| `userMemories` | `getPermanentMemories(chatId, userId, threadId, *, limit=10)` | `List[UserMemoryDict]` | Permanent block for injection — merges cross-thread (`thread_id IS NULL`) AND this-thread permanent (`permanent = 1`), newest-updated-first |
| `userMemories` | `getLatestMemories(chatId, userId, threadId, *, limit=5)` | `List[UserMemoryDict]` | Ephemeral-only (`permanent = 0`) newest-first, thread-scoped — backs the `latest` retrieval path (the fallback used when memory embeddings are off, i.e. not both `MEMORY_ENABLED && EMBEDDINGS_ENABLED`; semantic `searchMemories` is used when both are on) |
| `userMemories` | `searchMemories(chatId, userId, queryEmbedding=None, *, threadId=None, type=None, tags=None, permanent=None, limit=20, embeddingModel, offset=0)` | `List[UserMemoryDict]` | Filter-only (`queryEmbedding is None`, plain SQL scan, `score = 0.0`) or semantic (`queryEmbedding` is a `List[float]`, vec0 KNN, `score = 1.0 - distance`). `embeddingModel` (required; pass `None` for filter-only) is resolved to `model_id` internally via the constructor-injected `modelIdResolver` (Decision D6 — handler-facing signature stable; D10 — `model_id` resolution happens inside the repo, never in handler code). Always scoped to one `(chat_id, user_id)`; `tags` applied as a portable SQL `LIKE '%"tagN"%'` filter against the JSON-TEXT column |
| `userMemories` | `getMemoriesWithoutEmbeddings(chatId, *, limit=50, modelName=None, dimensions=None, dataSource=None)` | `List[UserMemoryDict]` | Backfill/regen-cron input — rows whose `model_id` is NULL or differs from the resolved active `(model, dimensions)` pair (single-table stale detection via a stale predicate keyed on `model_id`; also serves the initial backfill) |
| `userMemories` | `saveMemoryEmbedding(chatId, userId, memoryId, embedding, embeddingModel)` | `bool` | Lazy-create `vec_user_memories_{dim}` (if missing) + upsert the vector (`embedding` is `List[float]`, `embeddingModel` resolved to `model_id` via `modelIdResolver`) + set `model_id` on the row (vec0 write must succeed before provenance is set) |
| `models` | `getOrCreateModelId(model, dimensions)` | `int` | Cache-first allocation of the small sequential integer identifying a `(model, dimensions)` pair in the `models` lookup table (created by `migration_025`). Allocation: `COALESCE(MAX(model_id), 0) + 1` + `provider.upsert(..., updateExpressions={})` (portable `ON CONFLICT DO NOTHING`) + SELECT-back. Constructed FIRST in `Database.__init__` so its bound `getOrCreateModelId` can be injected as the `modelIdResolver` kwarg into `chatEmbeddings` / `chatSearch` / `userMemories` (Decision D10) |

The full `UserMemoriesRepository` has 12 public methods (the remainder are `deleteMemory` (soft-delete), `deleteMemoryEmbedding`, `deleteObsoleteMemoryEmbeddings`, `getMemory`/`getDistinctTags` wizard helpers, and `getMemoriesByIds` — the single read that skips the `deleted_at` filter to resolve soft-deleted memories for historical reconstruction); see [`docs/llm/memories/user-memories.md`](memories/user-memories.md) "Repository" and the schema docs for the complete list. There is no in-place content-PATCH method (`updateMemory` was removed — zero production callers; content changes go through `deleteMemory` + `addMemory`). All SQL goes through `BaseSQLProvider`. Embeddings (regen cron + the memory tools) are produced via `LLMService.generateEmbedding`.

---

## 2. Chat Settings in Database

Chat settings are stored in the cache layer (not directly in DB for hot path):

```python
# Get settings (from cache, falls back to DB)
chatSettings: ChatSettingsDict = self.db.chatSettings.getChatSettings(chatId)

# Set a setting (updatedBy is REQUIRED keyword-only arg).
# At the DB-repo layer, value is a plain str — the ChatSettingsValue wrapper
# lives at the handler layer (BaseBotHandler.setChatSetting).
self.db.chatSettings.setChatSetting(
    chatId=chatId,
    key=ChatSettingsKey.CHAT_MODEL,
    value="gpt-4",
    updatedBy=messageSender.id,
)

# Remove a setting (revert to default)
self.db.chatSettings.unsetChatSetting(chatId=chatId, key=ChatSettingsKey.CHAT_MODEL)
```

**IMPORTANT:** `getChatSettings(chatId)` returns `Dict[str, tuple[str, int]]` where each value is a `(value, updated_by)` tuple. Always index `[0]` to get the value. The `updated_by` field is the user ID who last changed the setting (0 for system changes). Note the keyword-only argument shape differs by layer: the **repository's** `setChatSetting(..., *, updatedBy: int)` takes an int user ID, while the **handler's** `BaseBotHandler.setChatSetting(..., *, user: MessageSender)` takes a `MessageSender` object.

---

## 3. Multi-Source Database Routing

**Config structure:**
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
keepConnection = true  # Connect on creation and keep connection open

[database.providers.readonly]
provider = "sqlite3"

[database.providers.readonly.parameters]
dbPath = "archive.db"
readOnly = true
timeout = 10
keepConnection = true  # Connect immediately (good for readonly replicas)

[database.chatMapping]
-1001234567890 = "readonly"
```

**`keepConnection` parameter:**
- `true` — Connect immediately when provider is created (good for readonly replicas, in-memory DBs)
- `false` — Connect on first query (default for file-based DBs, saves resources)
- **Special case:** In-memory SQLite3 (`:memory:`) defaults to `true` to prevent data loss

**Key classes:**
- `SourceConfig` — config for one DB provider
- [`SQLProviderConfig`](../../lib/db/providers/__init__.py) — provider config dict with `provider` and `parameters`

**Routing priority:** `dataSource` param → `chatId` mapping → default source

**The `dataSource` parameter convention (MUST-level rule):**

- **Every PUBLIC READ method MUST expose `dataSource: Optional[str] = None`** as a keyword-only argument and forward it to `manager.getProvider(dataSource=..., readonly=True)`. This is what lets a caller pin a read to a specific source on a multi-DB deployment.
- **Every PUBLIC WRITE method on a GLOBAL table SHOULD expose `dataSource`** and forward it to `manager.getProvider(dataSource=..., readonly=False)`. Precedent: `CacheRepository`, `CommonFunctionsRepository`, `WebhookUpdatesRepository`, and `EmbeddingModelsRepository`.
- **Per-chat-table writes route by `chatId` and MAY omit `dataSource`** — the chat→source mapping is the routing mechanism there, so `chatId` alone is sufficient. (Example: `saveChatMessage`, `saveMessageEmbedding`.)
- **Routing priority chain** at `DatabaseManager.getProvider` (quoted verbatim): `dataSource` > `chatId` mapping > default source. An unknown `dataSource` logs a warning and silently falls back to the default source (it does NOT raise).

```python
# Read from specific source
messages = db.chatMessages.getChatMessagesByRootId(
    chatId=chatId,
    rootMessageId=messageId,
    threadId=threadId,
    dataSource="readonly"  # Optional — explicit source selection
)

# Default routing (uses chatId mapping or default)
messages = db.chatMessages.getChatMessagesByRootId(
    chatId=chatId,
    rootMessageId=messageId,
    threadId=threadId,
)
```

**Readonly protection:** Sources with `readonly=True` reject write operations:
```python
# This will raise an error if "readonly" source has readonly=True
db.chatMessages.saveChatMessage(..., dataSource="readonly")  # ERROR!
```

**Cross-source deduplication keys:**
- `getUserChats()`: `(userId, chat_id)` — user-chat relationship uniqueness
- `getAllGroupChats()`: `chat_id` — chat uniqueness
- `getSpamMessages()`: `(chat_id, message_id)` — message uniqueness within chat
- `getCacheStorage()`: `(namespace, key)` — cache entry uniqueness
- `getCacheEntry()`: First match (no deduplication) — performance optimization

**Migration Connection Management:**
- Migrations rely on the provider's `keepConnection` parameter for connection management
- No explicit `await sqlProvider.connect()` call is made during migration
- Providers with `keepConnection=true` connect immediately before migrations run
- Providers with `keepConnection=false` connect on first query during migration
- This ensures consistent behavior across all database operations

### Migration checklist

- [ ] Checked highest existing version number first
- [ ] Created migration file with correct sequential version
- [ ] Implemented `up(sqlProvider: BaseSQLProvider)` using `ParametrizedQuery` and `batchExecute`
- [ ] Implemented `down(sqlProvider: BaseSQLProvider)` for rollback
- [ ] Migration uses portable SQL (no AUTOINCREMENT, no DEFAULT CURRENT_TIMESTAMP)
- [ ] Migration registered in versions directory (auto-discovered)
- [ ] Added `Database` repository methods to use new table
- [ ] Updated `internal/database/models.py` if new types needed
- [ ] Updated documentation files
- [ ] Tests pass: `make format lint && make test`

---

## 4. Adding a Database Migration

**File location:** [`internal/database/migrations/versions/`](../../internal/database/migrations/versions/)

**Quick start:** Use the migration generator script:

```bash
# Create a new migration (auto-detects next version number)
./venv/bin/python3 internal/database/migrations/create_migration.py "add user preferences table"
```

**Manual creation steps:**

1. **Find the next version number:**
   ```bash
   ls -1 internal/database/migrations/versions/ | grep migration_ | sort -V | tail -1
   ```
   If the last is `migration_025_*.py`, the next is `026`. Never reuse a version number — `migration_016` is already taken by `migration_016_add_stat_tables.py`, so the example below uses `025`.

2. **Create the migration file** with the pattern `migration_{version:03d}_{description}.py`

3. **Implement the migration class:**

```python
"""Add user preferences table."""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration025AddUserPreferences(BaseMigration):
    """Add user preferences table.

    Attributes:
        version: Migration version number (25).
        description: Human-readable description.
    """

    version: int = 25
    description: str = "Add user preferences table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create user_preferences table.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS user_preferences (
                        user_id INTEGER NOT NULL,
                        preference_key TEXT NOT NULL,
                        preference_value TEXT,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL,
                        PRIMARY KEY (user_id, preference_key)
                    )
                """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop user_preferences table.

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        await sqlProvider.execute("DROP TABLE IF EXISTS user_preferences")


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for auto-discovery.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration025AddUserPreferences
```

**Migration pattern requirements:**

1. **Use `async def up(self, sqlProvider: BaseSQLProvider)`** — not sync, not cursor-based
2. **No `AUTOINCREMENT`** — use composite natural keys or app-generated IDs (see AGENTS.md)
3. **No `DEFAULT CURRENT_TIMESTAMP`** — application sets timestamps explicitly
4. **Use `ParametrizedQuery`** for DDL and `batchExecute` for multiple statements
5. **Use `:named` placeholders** for any parametrised DDL/DML (never `?` or `%s`)
6. **For backfill upserts**, call `sqlProvider.upsert(table, values, conflictColumns, updateExpressions=...)` with the `ExcludedValue` marker from `internal.database.providers.base` rather than hand-writing `ON CONFLICT … DO UPDATE` — the marker translates to `excluded.col` on SQLite/PostgreSQL and `VALUES(col)` on MySQL
7. **Provide `getMigration()` function** for auto-discovery
8. **Always implement both `up()` and `down()`** for rollback support (a no-op `down()` that logs is acceptable when a portable `DROP COLUMN` is unavailable — see `migration_021`)

**Primary key strategies (ordered by preference):**

1. **Composite natural key** — `PRIMARY KEY (user_id, preference_key)`
2. **Single natural key** — `file_unique_id TEXT PRIMARY KEY`
3. **App-generated IDs** — `id TEXT PRIMARY KEY NOT NULL` (generate UUID/ULID in Python)

**See also:**
- [`internal/database/migrations/README.md`](../../internal/database/migrations/README.md) — Full migration guide with patterns
- [`docs/sql-portability-guide.md`](/docs/sql-portability-guide.md) — SQL portability rules

---

## 5. Database Models Reference

**File:** [`internal/database/models.py`](../../internal/database/models.py)

### Key TypedDicts

All defined in `internal/database/models.py`. Dict keys are snake_case to mirror DB columns (repository *method parameters* stay camelCase per AGENTS.md); the universal converter `dbUtils.sqlToTypedDict` maps columns to keys directly.

| TypedDict | Purpose |
|---|---|
| `ChatMessageDict` | Stored message (with optional `score: NotRequired[float]` populated by `chatSearch.searchChatMessages`) |
| `ChatInfoDict` | Chat metadata (`bot_status: ChatBotStatus` — REQUIRED field, never omitted; both DB-row-backed reads and platform-sourced write dicts from `TheBot.getChatInfo` populate it, the latter hardcoding `ChatBotStatus.ACTIVE`; added by `migration_026`) |
| `ChatTopicInfoDict` | Chat topic / forum thread metadata |
| `ChatUserDict` | User in chat |
| `MediaAttachmentDict` | Media file record |
| `DelayedTaskDict` | Delayed task record |
| `CacheDict` | Row from the `cache` table (single-namespace weather-style cache) |
| `CacheStorageDict` | Row from the `cache_storage` table (multi-namespace key/value cache) |
| `MessageEmbeddingDict` | **DELETED** in `migration_025` — the `message_embeddings` BLOB side table was dropped; chat-history embeddings now live in vec0 only with `chat_messages.model_id` (FK to `models`) carrying the provenance |
| `ModelDict` | Row from the `models` embedding-provenance lookup table (created by `migration_025`); `model_id` / `model` / `dimensions` / `created_at` |
| `WebhookUpdatesRow` | Row from `webhook_updates` (Max webhook payload store; `processed` is int 0/1) |
| `SpamMessageDict` | Row from `spam_messages` |
| `ChatSummarizationCacheDict` | Row from the chat-summarization cache table |
| `DivinationLayoutDict` | Cached layout definition (composite PK `(system_id, layout_id)`) |
| `UserMemoryDict` | Row from `user_memories` (per-(chat, user, thread) memory store; carries optional `score: NotRequired[float]` from semantic `searchMemories`) |
| `ThreadResultDict` | Row returned by `chatMessages.getMessageThread` — root + target + chronological thread |
| `VectorSearchResult` | Row from `BaseSQLProvider.vectorSearch` (`rowKey` dict + `distance: float`; lives in `lib/db/providers/base.py`) |

> **Note on `SearchResultDict`:** this TypedDict was **deleted**. `chatSearch.searchChatMessages` now returns `List[ChatMessageDict]` with `score: NotRequired[float]` set to `0.0` in filter-only mode and the cosine similarity (0.0–1.0) in semantic mode. The same `ChatMessageDict` (minus `score`) is returned by every other chat-message repository method.

### Key Enums

#### `MessageCategory`

| Value | Meaning |
|---|---|
| `USER` | Regular user message |
| `BOT` | Bot message (non-command) |
| `BOT_COMMAND_REPLY` | Bot reply to a command |
| `USER_COMMAND` | User command message |
| `BOT_ERROR` | Bot error message |
| `DELETED` | Deleted message |
| `USER_CONFIG_ANSWER` | User reply to a config prompt |
| `USER_SPAM` | Message classified as spam |
| `BOT_SPAM_NOTIFICATION` | Bot notification about a spam action |
| `BOT_RESENDED` | Message resended by the bot |
| `BOT_SUMMARY` | LLM-generated summary output |
| `CHANNEL` | Channel post |
| `UNSPECIFIED` | Catch-all / unset |

#### `MediaStatus`

| Value | Meaning |
|---|---|
| `NEW` | Just added |
| `PENDING` | Processing |
| `DONE` | Successfully processed |
| `FAILED` | Processing failed |

**STT (media-transcription) semantics:** the existing `media_attachments` table is reused — **no migration**. The `status` column carries the transcription lifecycle (`NEW → PENDING → DONE|FAILED`) and the transcript text is persisted in the existing `description` column. `STTService` is **stateless** — it performs no DB I/O; the **handler round** owns the row lifecycle (read / cache-hit short-circuit / claim to `PENDING` / persist / terminalize via plain `updateMediaAttachment`). Single attachments have no concurrent writes, so last-write semantics suffice — there is no CAS, and the former `setStatusVerified` helper has been removed. A `DONE` row always early-returns (it is no longer re-transcribed if the gate later flips off→on). See [`database-schema.md`](../database-schema.md) `media_attachments`, [`services.md`](services.md) §7, and ADR-020.

#### `SpamReason`

| Value | Meaning |
|---|---|
| `AUTO` | Automatically detected spam |
| `USER` | User reported spam |
| `ADMIN` | Admin marked as spam |
| `UNBAN` | User was unbanned |

#### `CacheType`

Namespaces for the `cache` table. Members: `WEATHER`, `GEOCODING`, `YANDEX_SEARCH`, `URL_CONTENT`, `URL_CONTENT_CONDENSED`, `GM_SEARCH`, `GM_REVERSE`, `GM_LOOKUP`. Used by `cache.clearOldCacheEntries(ttl, cacheType=...)` to scope cleanup (see §1) and by `CacheService` for hot-path access.

#### `MemoryType`

Closed set of `user_memories.type` column values: `BIO`, `PREFERENCE`, `FACT`, `EVENT`, `RELATIONSHIP`. Lives in the database layer (not `internal.bot.models`) to avoid a circular import — `internal.database` initialises before `internal.bot`. Freeform categorisation beyond these is handled by the JSON `tags` column.

#### `UserMemorySource`

Provenance of a `user_memories` row: `REFINEMENT` (background refinement cron), `CHAT` (inline during a conversation), `MIGRATION` (backfilled from legacy `user_data` by `migration_020`), `USER` (explicitly authored/imported by the user). Stored as the TEXT `source` column.

---

## 5.5 `models` Lookup Table (Embedding Provenance)

Lookup table created by `migration_025` (Phase 2 of the embedding-model-lookup refactor). One row per distinct `(model, dimensions)` pair seen by the system. The small app-generated sequential integer `model_id` is the FK-like key stored on every embedding-bearing row (`chat_messages.model_id`, `user_memories.model_id`, and the vec0 partition keys) so the `(model, dimensions)` pair itself is stored exactly once.

**Primary Key:** `model_id` — app-generated sequential integer (Decision D7 of the refactor: small ints are cheaper as vec0 partition keys than UUID strings; the DB does not generate IDs, no `AUTOINCREMENT`/`SERIAL`). Allocation happens app-side via `EmbeddingModelsRepository.getOrCreateModelId` (`COALESCE(MAX(model_id), 0) + 1` + `provider.upsert(..., updateExpressions={})` + SELECT-back).

| Column | Type | Nullable | Description |
|---|---|---|---|
| `model_id` | INTEGER | No | App-generated sequential integer primary key |
| `model` | TEXT | No | Embedding model name string (e.g. the resolved `EMBEDDING_MODEL` chat setting value) |
| `dimensions` | INTEGER | No | Vector dimensionality (e.g. 384, 1024) |
| `created_at` | TIMESTAMP | No | Set application-side (no DB default — matches `migration_013` rules) |

**Unique constraint:** `UNIQUE(model, dimensions)` — defensive second guard alongside the runtime probe-then-insert.

**Repository methods** (`EmbeddingModelsRepository`, accessed as `db.embeddingModels`):

```python
# Resolve (or allocate) the model_id for an active (model, dimensions)
# pair. Cache-first: a hot model is a single dict hit. On miss, allocate
# the next sequential id via COALESCE(MAX(model_id), 0) + 1, upsert with
# ON CONFLICT DO NOTHING (updateExpressions={}), then SELECT-back the
# canonical id (handles the race where another writer sneaked in between
# the MAX and the INSERT). Runtime probe-then-insert against the
# UNIQUE(model, dimensions) constraint.
modelId: int = await db.embeddingModels.getOrCreateModelId(
    model=modelName,
    dimensions=dimensions,
)

# Diagnostic / admin lookups (no production caller in the embed path).
row: Optional[ModelDict] = await db.embeddingModels.getModelById(modelId=modelId)
allModels: List[ModelDict] = await db.embeddingModels.listModels()
```

**Constructor-injection pattern (Decision D10):** `EmbeddingModelsRepository` is constructed FIRST in `Database.__init__` so its bound `getOrCreateModelId` method can be injected as the `modelIdResolver` kwarg into the three embedding-touching repos:

```python
self.embeddingModels = EmbeddingModelsRepository(self.manager)
self.chatEmbeddings = ChatEmbeddingsRepository(
    self.manager, modelIdResolver=self.embeddingModels.getOrCreateModelId
)
self.chatSearch = ChatSearchRepository(
    self.manager, modelIdResolver=self.embeddingModels.getOrCreateModelId
)
self.userMemories = UserMemoriesRepository(
    self.manager, modelIdResolver=self.embeddingModels.getOrCreateModelId
)
```

This keeps handler-facing signatures stable (Decision D6 — `embeddingModel: str` stays in `searchMemories`/`saveMemoryEmbedding`/etc.) while letting the repos resolve `model_id` internally. Handler code NEVER calls `getOrCreateModelId` directly.

**What it replaces:** the legacy `message_embeddings` BLOB side table (composite PK `(chat_id, message_id)`, dropped by `migration_025`) and the per-row `(model, dimensions)` / `(embedding_model, embedding_dimensions)` provenance pairs on `chat_messages` and `user_memories` respectively. Chat-history embeddings now live in the `vec_message_embeddings_{N}` vec0 tables only, with `chat_messages.model_id` carrying the provenance; the in-process numpy cosine fallback that operated on `message_embeddings` BLOBs was retired in the same refactor — `searchChatMessages` returns `[]` when vec0 is unavailable. The `_loadEmbeddingsFromDb` repository helper was deleted (no more BLOB source to load from); `_semanticSearch` collapsed to vec0-or-`[]`. `down()` for `migration_025` is schema-correct but data-lossy for vectors (the dropped BLOBs cannot be regenerated from `model_id` alone; vec0 tables are not re-created by `down()` — they re-populate via the normal backfill cron).

---

## 6. Adding Methods to `Database`

**Repository Pattern:** Database operations are organized into specialized repositories in `internal/database/repositories/`. Every repository inherits from `BaseRepository` (takes a `DatabaseManager`, NOT a `Database`) and goes through `BaseSQLProvider` for every query — never raw `sqlite3`, never `cursor.execute(..., ?)`, never `with self.db._getConnection()`. Those patterns predate the async refactor and the SQL-portability rules in AGENTS.md; they are NOT valid in new code.

**Available Repositories** (16 total — all wired as attributes on the `Database` wrapper in [`internal/database/database.py`](../../internal/database/database.py)):

| Attribute | Class | File |
|---|---|---|
| `common` | `CommonFunctionsRepository` | `common.py` (settings key/value) |
| `chatMessages` | `ChatMessagesRepository` | `chat_messages.py` |
| `chatEmbeddings` | `ChatEmbeddingsRepository` | `chat_embeddings.py` |
| `chatSearch` | `ChatSearchRepository` | `chat_search.py` (owns `searchChatMessages`) |
| `chatUsers` | `ChatUsersRepository` | `chat_users.py` (`getUserChats` / `getAllGroupChats` accept `botStatus: Optional[ChatBotStatus] = ChatBotStatus.ACTIVE` — default excludes inaccessible chats; `None` returns all. Applied as the predicate `(:botStatus IS NULL OR ci.bot_status = :botStatus)` against the `chat_info` JOIN) |
| `chatSettings` | `ChatSettingsRepository` | `chat_settings.py` |
| `chatInfo` | `ChatInfoRepository` | `chat_info.py` (chat metadata; owns the `bot_status` accessibility column added by `migration_026`, column only — no supporting index). Surface: `getChatInfo` (read) and `updateChatInfo(..., *, botStatus: Optional[ChatBotStatus] = ChatBotStatus.ACTIVE)` (upsert). `updateChatInfo`'s `botStatus` is keyword-only with default `ChatBotStatus.ACTIVE`; `bot_status` is ALWAYS written into both the INSERT `values` and the `CONFLICT`-UPDATE expressions (via `ExcludedValue`). `CacheService.setChatInfo` forwards `info["bot_status"]` (direct subscript, NOT `.get(...)`), so `CacheService.markChatInaccessible` / `markChatActive` reach the column via the same upsert path as every other `chat_info` write. **Self-heal consequence:** because `TheBot.getChatInfo` hardcodes `bot_status = ChatBotStatus.ACTIVE` in both platform return dicts and `updateChatInfo`'s default is `ACTIVE`, the every-message refresh path (`BaseBotHandler.updateChatInfo` → `TheBot.getChatInfo` → `CacheService.setChatInfo` → repo `updateChatInfo`) ALWAYS writes `ACTIVE` — a transient `INACCESSIBLE` set by `markChatInaccessible` self-heals to `ACTIVE` on the next inbound message, which is correct because receiving a message proves the chat is accessible. There is no dedicated status-mutation repository method (`setChatBotStatus` / `getInactiveChatIds` were removed during the accessibility simplification — see [`docs/design/chat-accessibility-tracking.md`](../design/chat-accessibility-tracking.md) "Implementation Divergence (2026-08-12)"). |
| `chatSummarization` | `ChatSummarizationRepository` | `chat_summarization.py` |
| `userMemories` | `UserMemoriesRepository` | `user_memories.py` |
| `mediaAttachments` | `MediaAttachmentsRepository` | `media_attachments.py` |
| `spam` | `SpamRepository` | `spam.py` |
| `delayedTasks` | `DelayedTasksRepository` | `delayed_tasks.py` |
| `divinations` | `DivinationsRepository` | `divinations.py` (reading rows + cached layout definitions) |
| `cache` | `CacheRepository` | `cache.py` |
| `embeddingModels` | `EmbeddingModelsRepository` | `embedding_models.py` (embedding-provenance lookup table; constructed FIRST so its bound `getOrCreateModelId` method can be injected as `modelIdResolver` into `chatEmbeddings` / `chatSearch` / `userMemories` — Decision D10) |
| `webhookUpdates` | `WebhookUpdatesRepository` | `webhook_updates.py` |

> `DatabaseBayesStorage` (`internal/database/bayes_storage.py`) and `DatabaseStatsStorage` (`internal/database/stats_storage.py`) are sibling classes that wrap a `Database` (not `DatabaseManager`) and are NOT exposed as `db.<name>` attributes — see §1 for the cleanup-path usage of the Bayes one.

**Adding a method to an existing repository:**

1. Open the appropriate repository file in `internal/database/repositories/`
2. Add an `async` method that resolves a provider via `self.manager.getProvider(...)` and goes through `BaseSQLProvider`:

```python
from typing import List, Optional

from .. import utils as dbUtils
from ..models import SomeDict


async def myNewDbMethod(self, chatId: int, value: str) -> Optional[SomeDict]:
    """Short description.

    Args:
        chatId: Chat ID to query (also used for source routing).
        value: Value to match.

    Returns:
        SomeDict if found, None otherwise.
    """
    try:
        sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=True)
        row = await sqlProvider.executeFetchOne(
            """
            SELECT * FROM some_table
            WHERE chat_id = :chatId AND value = :value
            """,
            {"chatId": chatId, "value": value},
        )
        return dbUtils.sqlToTypedDict(row, SomeDict) if row else None
    except Exception as e:
        logger.error(f"Failed myNewDbMethod for chat {chatId}: {e}")
        return None
```

**For read-only methods AND writes to global tables, take an optional `dataSource: Optional[str] = None`** so callers can pin a source explicitly. Per-chat-table writes instead route by `chatId` (the chat→source mapping is the routing mechanism) and MAY omit `dataSource`. See §3 "Multi-Source Database Routing" for the full convention.

```python
async def getMyData(
    self,
    chatId: int,
    *,
    dataSource: Optional[str] = None,
) -> Optional[SomeDict]:
    """Get data for chat.

    Args:
        chatId: Chat ID to query.
        dataSource: Optional explicit data source name.

    Returns:
        SomeDict if found, None otherwise.
    """
    try:
        sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
        row = await sqlProvider.executeFetchOne(
            """
            SELECT * FROM my_table WHERE chat_id = :chatId
            """,
            {"chatId": chatId},
        )
        return dbUtils.sqlToTypedDict(row, SomeDict) if row else None
    except Exception as e:
        logger.error(f"Failed getMyData for chat {chatId}: {e}")
        return None
```

**Useful `BaseSQLProvider` methods** (see §7 for the full list):
- `execute(query, params=None, fetchType=FetchType.NO_FETCH)` — write or no-return DDL/DML
- `executeFetchOne(query, params=None) -> dict | None` — single-row read
- `executeFetchAll(query, params=None) -> list[dict]` — multi-row read
- `batchExecute([ParametrizedQuery(...), ...])` — multiple statements in one transaction
- `upsert(table, values, conflictColumns, updateExpressions=...)` — portable upsert with `ExcludedValue` markers
- `applyPagination(query, limit, offset)` / `getTextType(maxLength)` / `getCaseInsensitiveComparison(column, param)` / `getLikeComparison(column, param)` — dialect-portable helpers

**Creating a new repository:**

1. Create new file in `internal/database/repositories/my_repository.py`
2. Inherit from `BaseRepository` (constructor takes a `DatabaseManager`, NOT a `Database`):
```python
import logging
from typing import Optional

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import SomeDict
from .base import BaseRepository

logger = logging.getLogger(__name__)


class MyRepository(BaseRepository):
    """Repository for my_table operations."""

    __slots__ = ()

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the repository.

        Args:
            manager: DatabaseManager instance for provider access.

        Returns:
            None
        """
        super().__init__(manager)

    async def myMethod(self, chatId: int) -> Optional[SomeDict]:
        """Method description.

        Args:
            chatId: Chat ID to query.

        Returns:
            SomeDict if found, None otherwise.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=True)
            row = await sqlProvider.executeFetchOne(
                """SELECT * FROM my_table WHERE chat_id = :chatId""",
                {"chatId": chatId},
            )
            return dbUtils.sqlToTypedDict(row, SomeDict) if row else None
        except Exception as e:
            logger.error(f"Failed myMethod for chat {chatId}: {e}")
            return None
```

3. Register in `internal/database/database.py`:
```python
from internal.database.repositories.my_repository import MyRepository

class Database:
    def __init__(self, config: DatabaseManagerConfig) -> None:
        # ... existing code ...
        self.myRepository = MyRepository(self.manager)  # pass the MANAGER, not self
```

Also export the new class from `internal/database/repositories/__init__.py` and add the attribute to `Database.__slots__` plus a class-level type annotation (every existing repo follows this pattern).

**Checklist after modifying `Database`:**
- [ ] Method is `async`
- [ ] Method has docstring with `Args:` / `Returns:`
- [ ] Method has type hints on every parameter and the return
- [ ] Goes through `BaseSQLProvider` (no raw `sqlite3`, no `_getConnection()`, no `cursor.execute`)
- [ ] Uses `:named` placeholders (not `?` or `%s`)
- [ ] Migration created if schema changed
- [ ] Tests in `tests/database/` (mirror layout: `tests/database/repositories/test_my_repository.py`)
- [ ] Ran `make format lint` and `make test`

---

## 7. Provider Helper Methods

**File:** [`lib/db/providers/base.py`](../../lib/db/providers/base.py)

The `BaseSQLProvider` abstract class provides cross-database compatibility methods for common SQL operations. Use these methods instead of writing RDBMS-specific SQL directly

### `getCaseInsensitiveComparison(column, param)`

Get RDBMS-specific case-insensitive comparison for exact matches.

```python
# Exact case-insensitive match
query = sqlProvider.getCaseInsensitiveComparison("name", "userName")
# Returns: 'LOWER(name) = LOWER(:userName)' on every concrete provider today
# (PostgreSQL could use ILIKE, but the LOWER() shape is what all three providers
# emit — never write `COLLATE NOCASE` by hand; that's SQLite-only.)
```

**Use cases:**
- Username/email lookups where case doesn't matter
- Finding chat settings by key
- Exact string matching across all RDBMS

### `getLikeComparison(column, param)`

Get RDBMS-specific case-insensitive LIKE comparison for pattern matching.

```python
# Partial/fuzzy case-insensitive match
query = sqlProvider.getLikeComparison("name", "searchTerm")
# Returns: 'LOWER(name) LIKE LOWER(:searchTerm)' for SQLite/MySQL/PostgreSQL
```

**Use cases:**
- Fuzzy search for layout names in divinations
- Partial text search where user input may be incomplete
- Type-ahead/search-as-you-type functionality

**Example - Divination layout search:**
```python
from internal.database.providers.base import BaseSQLProvider

async def getLayout(self, systemId: str, layoutName: str) -> Optional[DivinationLayoutDict]:
    """Search for layout with multiple strategies."""
    sqlProvider = await self.manager.getProvider(readonly=True)

    # Try exact match first
    row = await sqlProvider.executeFetchOne(
        "SELECT * FROM divination_layouts "
        f"WHERE system_id = :systemId AND {sqlProvider.getCaseInsensitiveComparison('layout_id', 'layoutName')}",
        {"systemId": systemId, "layoutName": layoutName}
    )

    # If not found, try fuzzy match with LIKE
    if not row:
        row = await sqlProvider.executeFetchOne(
            "SELECT * FROM divination_layouts "
            f"WHERE system_id = :systemId AND {sqlProvider.getLikeComparison('name_en', 'layoutName')}",
            {"systemId": systemId, "layoutName": f"%{layoutName}%"}
        )

    return row
```

### Other Provider Methods

| Method | Purpose |
|---|---|
| `applyPagination(query, limit, offset)` | Add RDBMS-specific LIMIT/OFFSET clause |
| `getTextType(maxLength)` | Get appropriate TEXT type for schema migrations |
| `upsert(table, values, conflictColumns, updateExpressions)` | Portable upsert operation |
| `await isReadOnly()` | Check if provider is in read-only mode (async — declared `async def isReadOnly(self) -> bool` on `BaseSQLProvider`) |
| `isVectorSearchSupported() -> bool` | Concrete (default `False`); providers with a loaded vector extension override to return `True` after confirming the extension is operational. Checked synchronously — the provider sets a private `_vectorSearchAvailable` flag during `connect()` (initialized to `False` in `__init__`). `SQLite3Provider` returns `True` when `sqlite-vec` loaded successfully. |
| `vectorSearch(*, table, vectorColumn, returnColumns, queryVector: bytes, k, filterClause, filterParams, distanceMetric) -> list[VectorSearchResult]` | Native KNN vector similarity search. `queryVector` is raw bytes (caller pre-serialises, e.g. `array.array("f", vec).tobytes()`). `filterClause` is a raw SQL WHERE fragment with `:named` params (built by trusted repository code). Returns rows ordered by distance ascending. Default implementation raises `NotImplementedError`. |
| `listTables(likePattern: str = "%") -> list[str]` | List table names matching a SQL LIKE pattern via native introspection. SQLite: `SELECT name FROM sqlite_master WHERE type='table' AND name LIKE :pattern`. Default raises `NotImplementedError`. Used to discover `vec_message_embeddings_%` tables for model-change cleanup. |
| `createVectorTable(tableName, columns: list[VectorColumnDef]) -> None` | Create a provider-native vector table/index. SQLite maps `VectorColumnDef` to vec0 DDL (`FLOAT[N] distance_metric=cosine`, `PARTITION KEY` suffix). `CREATE VIRTUAL TABLE IF NOT EXISTS` (idempotent). Default raises `NotImplementedError`. |

### Vector search types (`lib/db/providers/base.py`)

| Type | Kind | Purpose |
|---|---|---|
| `VectorSearchResult` | TypedDict | `rowKey: dict[str, str]` (column-name → stringified value, supports composite keys) + `distance: float` (raw metric value; cosine distance = `1.0 - similarity`). |
| `VectorDistanceMetric` | StrEnum | `COSINE`, `L2`. Providers validate support at call time and raise `ValueError` for unsupported metrics. |
| `VectorColumnType` | StrEnum | `TEXT`, `INTEGER`, `FLOAT`, `BLOB`, `VECTOR`. `VECTOR` requires `vectorDimension` and optionally `distanceMetric` in the column definition. |
| `VectorColumnDef` | TypedDict | `name: str`, `columnType: VectorColumnType`, `isPartitionKey: NotRequired[bool]`, `vectorDimension: NotRequired[int]`, `distanceMetric: NotRequired[VectorDistanceMetric]`. Uses `NotRequired[]` (NOT `total=False` — pyright rejects bracket access on `total=False`). |

### SQLite vector search — `sqlite-vec` + `vec0` virtual table

`SQLite3Provider` loads the `sqlite-vec` extension during `connect()` via aiosqlite's async wrappers: `enable_load_extension(True)` → `load_extension(sqlite_vec.loadable_path())` → `enable_load_extension(False)`, wrapped in `try/finally` so extension loading is always disabled afterward. The optional dependency is guarded by a module-level `try/except ImportError` with an `_SQLITE_VEC_AVAILABLE` flag (see AGENTS.md "optional dependencies"). Success sets `_vectorSearchAvailable = True`; `isVectorSearchSupported()` returns it. Loading failures are logged at `debug` and swallowed — the semantic search path then returns `[]` (no numpy fallback; the in-process numpy cosine path was retired alongside the `message_embeddings` BLOB store in `migration_025`).

The `vec0` virtual table uses **dimension-aware naming**: `vec_message_embeddings_{N}` where `N` is the embedding dimension (e.g. `vec_message_embeddings_384`, `vec_message_embeddings_1024`). This lets multiple dimension sizes coexist without conflict; the repository selects the correct table at runtime from `len(queryEmbedding)`. Tables are created lazily in the write path (`saveMessageEmbedding()` → `_upsertVecMessageEmbedding()` with `readonly=False`), never in the search path (`readonly=True` would block DDL). If a vec0 table is missing during search, the semantic path returns `[]`.

Schema (one table per dimension in use):

```sql
CREATE VIRTUAL TABLE vec_message_embeddings_384 USING vec0(
    message_id TEXT,
    chat_id INTEGER PARTITION KEY,
    model_id INTEGER PARTITION KEY,
    date TEXT,                            -- ISO-8601 from chat_messages; enables maxMessages pre-filter
    embedding FLOAT[384] distance_metric=cosine
);
```

`chat_id` and `model_id` are `PARTITION KEY`s so `WHERE chat_id = X AND model_id = Y` prunes the search to exactly that partition. The `model_id` partition key replaces the legacy `model TEXT` partition key (post-`migration_025`); it matches `chat_messages.model_id` / `models.model_id`. These vec0 tables are **lazily recreated** — `migration_025` deliberately DROPPED every `vec_message_embeddings_{N}` and `vec_user_memories_{N}` table because vec0 DDL is not `ALTER`-able (the partition-key change required a full drop + lazy recreate on the next embed call). Authoritative storage is now `chat_messages.model_id` + vec0 only — there is no BLOB side table any more; vec0 carries the float vectors themselves and `chat_messages.model_id` carries the provenance. No migration creates vec0 tables; `createVectorTable()` is called at runtime when a new dimension is first written.

---

## 8. Utility Functions

**File:** [`internal/database/utils.py`](../../internal/database/utils.py)

### `sqlToCustomType(data, expectedType)`

Convert SQL response data to the expected Python type with smart type coercion.

```python
from internal.database.utils import sqlToCustomType

# Handle Optional types gracefully
success, value = sqlToCustomType(rawValue, Optional[datetime.datetime])
# Returns (True, None) for Optional[...] when data is None
# Returns (True, datetime(...)) for valid datetime
# Returns (False, None) for conversion failures

# Handle Union types - tries each member
success, value = sqlToCustomType("123", Union[int, str])
# Tries int conversion first, then str fallback
```

**Supported conversions:**
- `None` → `Optional[T]`: Returns `(True, None)` for any Optional type
- `bytes` / `str` → `int`, `float`, `bool`: Decodes and converts
- `int`, `float`, `bool` → other numeric or string types
- JSON strings → `dict`, `list`, generic types like `dict[str, int]`
- ISO timestamps → `datetime.datetime`
- Unix timestamps → `datetime.datetime`

**Optional/Union handling:**
- When `data is None` and `expectedType` is `Optional[T]`, returns `(True, None)`
- When `data is not None`, unwraps `Optional[T]` and tries converting to `T`
- Handles both `typing.Union` and `types.UnionType` (Python 3.10+ syntax)

**Use cases:**
- Converting SQL query results to typed Python values
- Handling nullable database columns via `Optional` types
- Safe type conversion with `(success, value)` tuple pattern

---

## 9. Migration Documentation Protocol

**Critical lesson from migration_009 documentation error**

### Mandatory Steps for Migration Documentation Updates

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

5. **Cross-Check Schema Files**
   - Update both human and LLM documentation consistently
   - Ensure schema descriptions match migration history
   - Validate that all historical migrations are accounted for

**Known implemented migrations:**
- `migration_001` to `migration_028` — Baseline migrations through latest schema updates
- `migration_010`: Adds `updated_by INTEGER NOT NULL` to `chat_settings` table (audit trail)
- `migration_011` and `migration_012`: Additional schema improvements
- `migration_013`: Removes `DEFAULT CURRENT_TIMESTAMP` from all timestamp columns (explicit timestamp handling)
- `migration_014`: Adds the [`divinations`](#divinations) table (composite PK `(chat_id, message_id)`) plus `idx_divinations_user_created` index for tarot/runes readings
- `migration_015`: Adds the [`divination_layouts`](#divination_layouts) table (composite PK `(system_id, layout_id)`) plus `idx_divination_layouts_system` index for layout discovery cache
- `migration_016`: Adds [`stat_events`](../../lib/stats/stats_storage.py) (append-only event log) and [`stat_aggregates`](../../lib/stats/stats_storage.py) (period buckets) tables for statistics collection
- `migration_017`: Originally added the `message_embeddings` BLOB side table (composite PK `(chat_id, message_id)`) for semantic chat-history search. **Table + index subsequently DROPPED by `migration_025`** — chat-history embeddings now live in vec0 only with `chat_messages.model_id` (FK to `models`) carrying the provenance
- `migration_018`: Originally added `idx_message_embeddings_chat_model` index on `message_embeddings (chat_id, model)`. **Index + table subsequently DROPPED by `migration_025`**
- `migration_019`: Adds the [`webhook_updates`](../../docs/database-schema-llm.md#webhook_updates) table (`id TEXT PRIMARY KEY`) for Max webhook ingestion — raw webhook payloads are written here by the standalone webhook receiver and consumed via the `webhookUpdates` repository. Plus `idx_webhook_updates_unprocessed` on `(processed, received_at)` to back the unprocessed-rows query
- `migration_020`: Adds the [`user_memories`](../../docs/database-schema-llm.md#user_memories) table (composite PK `(chat_id, user_id, memory_id)`) — the unified per-(chat, user, thread) memory store that retires `user_data` (table subsequently dropped in `migration_022`) and the rolling-bio JSON blob. Three indexes (`idx_user_memories_chat_user_thread`, `idx_user_memories_chat_user_permanent`, `idx_user_memories_type`). Backfills `user_data` rows into permanent cross-thread `type='fact'` memories and `chat_users.metadata.memoryRefinement` rolling-bio entries into permanent thread-scoped `type='bio'` memories. The vec0 virtual table (`vec_user_memories_{dim}`) is **not** created by the migration — it is created lazily at runtime on first write (mirrors `message_embeddings`). Schema/ADR: [`docs/llm/memories/user-memories.md`](memories/user-memories.md) and ADR-016.
- `migration_021`: Adds the nullable `deleted_at` column to [`user_memories`](../../docs/database-schema-llm.md#user_memories) (soft-delete — `deleteMemory` sets `deleted_at` + drops vec0 + nulls provenance instead of hard-`DELETE`-ing the row, so historical messages referencing a deleted memory can still resolve its content via `getMemoriesByIds`). Every live read gains `AND deleted_at IS NULL`. Additive nullable column; `down()` is a no-op that logs (portable `DROP COLUMN` unavailable). Part of memory-compaction-v1 (see ADR-017 and [`docs/archive/plans/memory-compaction-v1.md`](/docs/archive/plans/memory-compaction-v1.md)).
- `migration_022`: DROP TABLE `user_data` (superseded by `user_memories`; data was backfilled into `user_memories` in `migration_020`). The no-op `down()` is intentional — re-creating the table would orphan the rows already moved to `user_memories`.
- `migration_023`: Idempotent data migration renaming the `chat_settings` key `memory-injection-enabled` → `memory-enabled` via `UPDATE chat_settings SET key='memory-enabled' WHERE key='memory-injection-enabled'`. Companion to the in-code `MEMORY_INJECTION_ENABLED` → `MEMORY_ENABLED` `ChatSettingsKey` enum rename.
- `migration_024`: Adds `idx_bayes_tokens_updated_at` index on `bayes_tokens (updated_at)` — optimizes the age-based `DatabaseBayesStorage.cleanupOldTokens` DELETE (`WHERE updated_at < :cutoffTime AND total_count <= :maxCount`), which runs across ALL chats from `HandlersManager._cleanupOldData()` on a weekly cron and at shutdown. The existing `bayes_tokens_total_idx(total_count)` and `bayes_tokens_chat_idx(chat_id)` do not help that DELETE (no chat_id filter; `updated_at` is the selective range predicate).
- `migration_025`: Normalises embedding provenance into a new [`models`](#55-models-lookup-table-embedding-provenance) lookup table (`model_id` integer PK with `UNIQUE(model, dimensions)`); swaps `chat_messages` and `user_memories` to carry `model_id` instead of the legacy `(model, dimensions)` / `(embedding_model, embedding_dimensions)` pairs. **DROPS the `message_embeddings` BLOB side table** (created by `migration_017`) and its `idx_message_embeddings_chat_model` index (`migration_018`). **DROPS both vec0 virtual-table families** (`vec_message_embeddings_{N}`, `vec_user_memories_{N}`) — they are lazily recreated at runtime with `model_id INTEGER PARTITION KEY` (was `model TEXT`). Temp-table swap pattern from `migration_013`. `down()` is schema-correct but data-lossy for vectors (the dropped BLOBs cannot be regenerated from `model_id` alone; vec0 tables are not re-created by `down()` — they re-populate via the normal backfill cron). DB backup strongly recommended before running the migration. See [`docs/plans/embedding-model-lookup-refactor-v1.md`](../plans/embedding-model-lookup-refactor-v1.md).
- `migration_026`: Adds `bot_status TEXT NOT NULL DEFAULT 'active'` to [`chat_info`](../../docs/database-schema-llm.md#chat_info) (column only — no supporting index). Backs the chat-accessibility-tracking subsystem (lazy mark-on-failure at `TheBot.getChatAdmins` catch sites, activity-based recovery in `MessagePreprocessorHandler`, and an optional `botStatus` filter on every chat-listing repository method). Portable DDL: string-literal `DEFAULT 'active'` backfills every existing row to `ACTIVE` as part of the `ALTER TABLE` (no separate backfill; no `AUTOINCREMENT`/`SERIAL`/`DEFAULT CURRENT_TIMESTAMP`). `down()` runs `DROP COLUMN bot_status` (SQLite ≥3.35). See [`docs/design/chat-accessibility-tracking.md`](../design/chat-accessibility-tracking.md) (and its "Implementation Divergence (2026-08-12)" section for the shipped design, which routes `bot_status` writes through `updateChatInfo(..., botStatus=...)` via `CacheService.setChatInfo` rather than a dedicated `setChatBotStatus` repository method).
- `migration_027`: Backfills `chat_messages` message history into [`stat_aggregates`](../../docs/database-schema-llm.md#stat_aggregates) as pre-aggregated `message` events (three periods — daily/monthly/total; hourly deliberately not backfilled; metrics `message_count` + `text_length`; same `jsonDumps`/`_hashLabels` canonicalization as the live aggregator), then **DROPS the legacy `chat_stats` and `chat_user_stats` tables** (write-only since `migration_001`). Applies the same exclusions as live recording (NULL/`DELETED`/`UNSPECIFIED` `message_category`); every backfilled row carries `sent = "False"` (uniform non-bot direction for history, bot-authored rows included — user decision 2026-08-22, migration edited in place before production deployment), so backfill and live user rows share the same `labels_hash` buckets and MERGE into one `stat_aggregates` bucket (direction stays binary at query time — bot = `sent` "True", users = "False" or absent, so label-less rows from legacy dev DBs that ran the older migration fold into users; the users/bot split is rendered only by the `/stats` HTML page generator, not the chat reply); `chat_type` is resolved per chat from `chat_info` with a chat-id-sign fallback. Python-side pre-aggregation with bounded memory — per-consumer buckets are flushed after each chat, while `__global__` running-total buckets accumulate across chats and flush once. Replace-semantics upserts make re-runs idempotent; `down()` recreates both legacy tables EMPTY (the original data is destroyed by the DROP, not restorable). See [`docs/design/stats-aggregation-v1.md`](../design/stats-aggregation-v1.md).
- `migration_028`: Adds `idx_stat_events_retention` on [`stat_events`](../../docs/database-schema-llm.md#stat_events) `(processed, created_at)` — covers the retention-purge DELETE (`WHERE processed = 1 AND created_at < :cutoff`) that the periodic stats-aggregation task runs for `[stats] events-retention-days`, so processed-event cleanup stops table-scanning (same TTL-index precedent as `idx_cache_updated_at` from `migration_012` and `idx_bayes_tokens_updated_at` from `migration_024`). Idempotent (`CREATE INDEX IF NOT EXISTS`) and reversible (`down()` runs `DROP INDEX IF EXISTS`). See [`docs/design/stats-aggregation-v1.md`](../design/stats-aggregation-v1.md).

---

## See Also

- [`index.md`](index.md) — Project overview, mandatory rules
- [`architecture.md`](architecture.md) — Multi-source DB ADR (ADR-004, ADR-008, ADR-009, ADR-010)
- [`handlers.md`](handlers.md) — Using `self.db` in handlers
- [`services.md`](services.md) — `CacheService` for hot-path DB access
- [`configuration.md`](configuration.md) — `[database]` TOML config section
- [`testing.md`](testing.md) — Writing DB tests with `testDatabase` fixture
- [`tasks.md`](tasks.md) — Step-by-step: "modify database schema" decision tree

---

*This guide is auto-maintained and should be updated whenever significant database changes are made*
*Last updated: 2026-08-02*
