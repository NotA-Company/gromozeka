---
category: guide
---

# Gromozeka — Database Operations

> **Audience:** LLM agents
> **Purpose:** Complete reference for database operations, migrations, schema, and multi-source routing
> **Role:** Agent-facing operations guide (routing convention, migration recipe, method highlights). Schema facts are owned by the schema pair ([`database-schema.md`](../database-schema.md) / [`database-schema-llm.md`](../database-schema-llm.md)), portability rules by [`sql-portability-guide.md`](../sql-portability-guide.md), and multi-source operator configuration by [`database-multi-source.md`](../database-multi-source.md).

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

### Signature coverage: defer to the schema-LLM owner

Full method signatures are owned by [`database-schema-llm.md` §Database Operations](../database-schema-llm.md#database-operations) (human-readable repository index: [`database-schema.md` §Repository Pattern](../database-schema.md#repository-pattern)). Per-repository pointers and the agent-facing notes that section does not carry:

- `chatMessages` — [Message Operations](../database-schema-llm.md#message-operations). Notes: `getChatMessagesByMessageIds` backs the `get_messages_by_ids` LLM tool (ADR-019) and does NOT dedup its input IDs; the `userId` filter on `getChatMessagesSince` scopes results to one sender (used by the memory-refinement cron).
- `chatSearch` — [Search Operations](../database-schema-llm.md#search-operations). Notes: lives on the `chatSearch` repo (not `chatMessages`) since `ChatSearchRepository` was split out; `modelName` is resolved to a `model_id` partition key internally via the constructor-injected `modelIdResolver` (Decisions D6/D10); returns `[]` when `sqlite-vec` is unavailable.
- `chatUsers` — [User Operations](../database-schema-llm.md#user-operations).
- `mediaAttachments` — [Media Operations](../database-schema-llm.md#media-operations).
- `chatSettings` — [Settings Operations](../database-schema-llm.md#settings-operations); see §2 for the `(value, updated_by)` tuple gotcha.
- `userMemories` — all 12 methods: [`database-schema-llm.md` §user_memories](../database-schema-llm.md#user_memories). Retrieval-path mapping: `getPermanentMemories` is the injection block; `getLatestMemories` is the ephemeral-only fallback used when memory embeddings are off (not both `MEMORY_ENABLED && EMBEDDINGS_ENABLED`); semantic `searchMemories` is used when both are on.
- `cache` / `common` / `spam` / `chatSummarization` / `delayedTasks` — [Cache Operations](../database-schema-llm.md#cache-operations), [Settings Operations](../database-schema-llm.md#settings-operations), [Spam Detection Operations](../database-schema-llm.md#spam-detection-operations), [Summarization Operations](../database-schema-llm.md#summarization-operations), [Task Operations](../database-schema-llm.md#task-operations).

### Methods not covered by the schema-LLM operations section

#### chatEmbeddings

| Repository | Method | Returns | Purpose |
|---|---|---|---|
| `chatEmbeddings` | `saveMessageEmbedding(chatId, messageId, embedding, model)` | `None` | Single-write the float32 vector into the dimension-specific `vec_message_embeddings_{N}` vec0 table and `UPDATE chat_messages.model_id` with the resolved `model_id` (resolved via the constructor-injected `modelIdResolver`). `dimensions` is derived from `len(embedding)`. The previous dual-write to `message_embeddings` + vec0 is retired (`message_embeddings` was dropped in `migration_025`). |
| `chatEmbeddings` | `getMessagesWithoutEmbeddings(chatId, *, limit, modelName?, dimensions?, dataSource?)` | `List[ChatMessageDict]` | Used by `ChatSearchHandler._dtCronJob` to find messages missing a current embedding. Returns full `ChatMessageDict` rows (joined with `chat_users` for `username`/`full_name`); uses a stale predicate keyed on `chat_messages.model_id` (NULL, or `model_id` differing from the resolved active `(model, dimensions)` pair). The `dimensions` filter scopes the check by dimensionality so model-drift re-embedding only surfaces rows embedded under a different (model, dimensions) tuple |
| `chatEmbeddings` | `deleteObsoleteModelEmbeddings(chatId, currentModelId)` | `int` | Cleanup stale vec0 rows for a chat (used when switching to an incompatible model that produces different dimensions). Runs `DELETE FROM vec_message_embeddings_{N} WHERE chat_id = :chatId AND model_id != :currentModelId` across every `vec_message_embeddings_%` table enumerated via `provider.listTables()` |

#### divinations

| Repository | Method | Returns | Purpose |
|---|---|---|---|
| `divinations` | `insertReading(...)` | `None` | Persist a tarot/runes reading row in `divinations` |
| `divinations` | `getLayout(systemId, layoutName)` | `Optional[DivinationLayoutDict]` | Get cached layout with fuzzy search |
| `divinations` | `saveLayout(...)` | `bool` | Save/update layout definition in cache |
| `divinations` | `saveNegativeCache(systemId, layoutId)` | `bool` | Save negative cache entry for non-existent layout |
| `divinations` | `isNegativeCacheEntry(layoutDict)` | `bool` | Check if layout dict is a negative cache entry |

#### models lookup

`db.embeddingModels.getOrCreateModelId(model, dimensions) -> int` — cache-first allocation of the sequential `model_id` for a `(model, dimensions)` pair (`COALESCE(MAX(model_id), 0) + 1` + `provider.upsert(..., updateExpressions={})` + SELECT-back). Constructed FIRST in `Database.__init__` so its bound method can be injected as `modelIdResolver` into `chatEmbeddings` / `chatSearch` / `userMemories` (Decision D10). See §5.5 and [`database-schema-llm.md` §models](../database-schema-llm.md#models).

### Cleanup-path methods (cron and shutdown)

| Repository | Method | Returns | Purpose |
|---|---|---|---|
| `cache` | `getCacheStorage(*, dataSource?)` / `setCacheStorage(namespace, key, value, *, dataSource?)` / `unsetCacheStorage(namespace, key)` | `List[CacheStorageDict]` / `bool` / `bool` | The `cache_storage` trio — persistence backing for `CacheService` (startup load via `getCacheStorage`, save-on-write via `setCacheStorage`, flush drops via `unsetCacheStorage`). The `cache` table itself is NOT accessed via the `Database` wrapper anymore: its SQL is owned inline by [`GenericDatabaseCache`](../../lib/cache/sql_cache.py) (`lib/cache`, ADR-024). The weekly TTL sweep runs as `GenericDatabaseCache(self.db.manager, namespace=<CacheType member>).clearOld(ttl)` from `HandlersManager._cleanupOldData()` (see `docs/llm/teamlead-memory.md` § "DB Cache Cleanup"): single pass over all `CacheType` members with conditional TTL (7-day aggressive TTL for `WEATHER`/`YANDEX_SEARCH`/`URL_CONTENT`/`URL_CONTENT_CONDENSED`, 365-day default floor for the rest). Constants live at the top of `internal/bot/common/handlers/manager.py` (`CACHE_CLEANUP_DEFAULT_TTL_SECS`, `CACHE_CLEANUP_AGGRESSIVE_TTL_SECS`, `AGGRESSIVE_CLEANUP_CACHE_TYPES`). Triggers: weekly cron (Monday 00:00 UTC via `_dtCronJob`) and on-shutdown (`_dtOnExit`) |
| `delayedTasks` | `cleanupOldCompletedDelayedTasks(ttl)` | `bool` | Cleanup old completed delayed tasks. Called from `_cleanupOldData()` with `DELAYED_TASKS_CLEANUP_TTL_SECS` (30 days) |
| `DatabaseBayesStorage` | `cleanupOldTokens(rules)` | `bool` | Delete old/rare rows from `bayes_tokens`. `rules` is a sequence of `(ttlSeconds, maxCount)` tuples; for each rule, runs `DELETE FROM bayes_tokens WHERE updated_at < :cutoffTime AND total_count <= :maxCount` across ALL tokens regardless of `chat_id` (one DELETE per rule). Returns `True` if all rules applied, `False` on any exception. NOTE: `DatabaseBayesStorage` is NOT a standard `self.db.<name>` repository — it's a separate class at [`internal/database/bayes_storage.py`](../../internal/database/bayes_storage.py), instantiated as `DatabaseBayesStorage(self.db)`. Called from `HandlersManager._cleanupOldData()` with `BAYES_TOKEN_CLEANUP_RULES` (defined near the top of `internal/bot/common/handlers/manager.py`; defaults: tokens with `total_count <= 1` older than 90 days, OR `total_count <= 2` older than 180 days). Sibling method `cleanupRareTokens(minCount, chatId=None)` is unrelated (no production caller in the cleanup path) |

### Repository coverage notes

The full `UserMemoriesRepository` has 12 public methods — the complete list lives in [`database-schema-llm.md` §user_memories](../database-schema-llm.md#user_memories). There is no in-place content-PATCH method (`updateMemory` was removed — zero production callers; content changes go through `deleteMemory` + `addMemory`). All SQL goes through `BaseSQLProvider`. Embeddings (regen cron + the memory tools) are produced via `LLMService.generateEmbedding`.

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
- **Every PUBLIC WRITE method on a GLOBAL table SHOULD expose `dataSource`** and forward it to `manager.getProvider(dataSource=..., readonly=False)`. Precedent: `CacheRepository`, `CommonFunctionsRepository`, and `EmbeddingModelsRepository`.
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
   If the last is `migration_029_*.py`, the next is `030`. Never reuse a version number — `migration_016` is already taken by `migration_016_add_stat_tables.py`, so the example below uses `030`.

2. **Create the migration file** with the pattern `migration_{version:03d}_{description}.py`

3. **Implement the migration class:**

```python
"""Add user preferences table."""

from typing import Type

from lib.db.providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration030AddUserPreferences(BaseMigration):
    """Add user preferences table.

    Attributes:
        version: Migration version number (30).
        description: Human-readable description.
    """

    version: int = 30
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
    return Migration030AddUserPreferences
```

**Migration pattern requirements:**

1. **Use `async def up(self, sqlProvider: BaseSQLProvider)`** — not sync, not cursor-based
2. **No `AUTOINCREMENT`** — use composite natural keys or app-generated IDs (see AGENTS.md)
3. **No `DEFAULT CURRENT_TIMESTAMP`** — application sets timestamps explicitly
4. **Use `ParametrizedQuery`** for DDL and `batchExecute` for multiple statements
5. **Use `:named` placeholders** for any parametrised DDL/DML (never `?` or `%s`)
6. **For backfill upserts**, call `sqlProvider.upsert(table, values, conflictColumns, updateExpressions=...)` with the `ExcludedValue` marker from `lib.db.providers.base` rather than hand-writing `ON CONFLICT … DO UPDATE` — the marker translates to `excluded.col` on SQLite/PostgreSQL and `VALUES(col)` on MySQL
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
| `CacheStorageDict` | Row from the `cache_storage` table (multi-namespace key/value cache) |
| `MessageEmbeddingDict` | **DELETED** in `migration_025` — the `message_embeddings` BLOB side table was dropped; chat-history embeddings now live in vec0 only with `chat_messages.model_id` (FK to `models`) carrying the provenance |
| `ModelDict` | Row from the `models` embedding-provenance lookup table (created by `migration_025`); `model_id` / `model` / `dimensions` / `created_at` |
| `SpamMessageDict` | Row from `spam_messages` |
| `ChatSummarizationCacheDict` | Row from the chat-summarization cache table |
| `DivinationLayoutDict` | Cached layout definition (composite PK `(system_id, layout_id)`) |
| `UserMemoryDict` | Row from `user_memories` (per-(chat, user, thread) memory store; carries optional `score: NotRequired[float]` from semantic `searchMemories`) |
| `ThreadResultDict` | Row returned by `chatMessages.getMessageThread` — root + target + chronological thread |
| `VectorSearchResult` | Row from `BaseSQLProvider.vectorSearch` (`rowKey` dict + `distance: float`; lives in `lib/db/providers/base.py`) |

> **Note on `SearchResultDict`:** this TypedDict was **deleted**. `chatSearch.searchChatMessages` now returns `List[ChatMessageDict]` with `score: NotRequired[float]` set to `0.0` in filter-only mode and the cosine similarity (0.0–1.0) in semantic mode. The same `ChatMessageDict` (minus `score`) is returned by every other chat-message repository method.

### Key Enums

Authoritative enum member tables are owned by the schema pair: [`database-schema.md` §Enums](../database-schema.md#enums) (human) and [`database-schema-llm.md` §Enums](../database-schema-llm.md#enums) (raw values). The notes below keep only agent-facing behaviour that is not a member listing.

#### `MediaStatus` — STT semantics

**STT (media-transcription) semantics:** the existing `media_attachments` table is reused — **no migration**. The `status` column carries the transcription lifecycle (`NEW → PENDING → DONE|FAILED`) and the transcript text is persisted in the existing `description` column. `STTService` is **stateless** — it performs no DB I/O; the **handler round** owns the row lifecycle (read / cache-hit short-circuit / claim to `PENDING` / persist / terminalize via plain `updateMediaAttachment`). Single attachments have no concurrent writes, so last-write semantics suffice — there is no CAS, and the former `setStatusVerified` helper has been removed. A `DONE` row always early-returns (it is no longer re-transcribed if the gate later flips off→on). See [`database-schema.md`](../database-schema.md) `media_attachments`, [`services.md`](services.md) §7, and ADR-020.

#### `CacheType` — runtime binding

Namespace StrEnum for the `cache` table (members listed in the schema docs). StrEnum — members bind directly as the `namespace: str` of [`GenericDatabaseCache`](../../lib/cache/sql_cache.py) (`lib/cache/sql_cache.py`, ADR-024): passed by the `weather` / `yandex_search` handlers when constructing their caches, and enumerated by `HandlersManager._cleanupOldData` for the weekly TTL sweep (see §1). NOT used by `CacheService` — its hot path is in-memory LRUs keyed by its own `CacheNamespace` enum ([`internal/services/cache/models.py`](../../internal/services/cache/models.py)), with the `cache_storage` table (not `cache`) as its persistence backing.

#### `MemoryType`

Closed set of `user_memories.type` column values: `BIO`, `PREFERENCE`, `FACT`, `EVENT`, `RELATIONSHIP`. Lives in the database layer (not `internal.bot.models`) to avoid a circular import — `internal.database` initialises before `internal.bot`. Freeform categorisation beyond these is handled by the JSON `tags` column.

#### `UserMemorySource`

Provenance of a `user_memories` row: `REFINEMENT` (background refinement cron), `CHAT` (inline during a conversation), `MIGRATION` (backfilled from legacy `user_data` by `migration_020`), `USER` (explicitly authored/imported by the user). Stored as the TEXT `source` column.

---

## 5.5 `models` Lookup Table (Embedding Provenance)

Lookup table created by `migration_025`: one row per distinct `(model, dimensions)` pair seen by the system; the small app-generated sequential integer `model_id` is the FK-like key stored on every embedding-bearing row (`chat_messages.model_id`, `user_memories.model_id`, and the vec0 partition keys) so the pair itself is stored exactly once. **Owner of the column table, primary-key/constraint details, and migration history:** [`database-schema.md` §models](../database-schema.md#models) and [`database-schema-llm.md` §models](../database-schema-llm.md#models).

**Constructor-injection pattern (Decision D10)** — the agent-relevant part: `EmbeddingModelsRepository` is constructed FIRST in `Database.__init__` so its bound `getOrCreateModelId` method can be injected as the `modelIdResolver` kwarg into the three embedding-touching repos:

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

---

## 6. Adding Methods to `Database`

**Repository Pattern:** Database operations are organized into specialized repositories in `internal/database/repositories/`. Every repository inherits from `BaseRepository` (takes a `DatabaseManager`, NOT a `Database`) and goes through `BaseSQLProvider` for every query — never raw `sqlite3`, never `cursor.execute(..., ?)`, never `with self.db._getConnection()`. Those patterns predate the async refactor and the SQL-portability rules in AGENTS.md; they are NOT valid in new code.

### Available repositories: message, search, and settings stores

**Available Repositories** (15 total — all wired as attributes on the `Database` wrapper in [`internal/database/database.py`](../../internal/database/database.py)):

| Attribute | Class | File |
|---|---|---|
| `common` | `CommonFunctionsRepository` | `common.py` (settings key/value) |
| `chatMessages` | `ChatMessagesRepository` | `chat_messages.py` |
| `chatEmbeddings` | `ChatEmbeddingsRepository` | `chat_embeddings.py` |
| `chatSearch` | `ChatSearchRepository` | `chat_search.py` (owns `searchChatMessages`) |
| `chatUsers` | `ChatUsersRepository` | `chat_users.py` (`getUserChats` / `getAllGroupChats` accept `botStatus: Optional[ChatBotStatus] = ChatBotStatus.ACTIVE` — default excludes inaccessible chats; `None` returns all. Applied as the predicate `(:botStatus IS NULL OR ci.bot_status = :botStatus)` against the `chat_info` JOIN) |
| `chatSettings` | `ChatSettingsRepository` | `chat_settings.py` |
### Available repositories: chatInfo, memories, and media stores

| Attribute | Class | File |
|---|---|---|
| `chatInfo` | `ChatInfoRepository` | `chat_info.py` (chat metadata; owns the `bot_status` accessibility column added by `migration_026`, column only — no supporting index). Surface: `getChatInfo` (read) and `updateChatInfo(..., *, botStatus: Optional[ChatBotStatus] = ChatBotStatus.ACTIVE)` (upsert). `updateChatInfo`'s `botStatus` is keyword-only with default `ChatBotStatus.ACTIVE`; `bot_status` is ALWAYS written into both the INSERT `values` and the `CONFLICT`-UPDATE expressions (via `ExcludedValue`). `CacheService.setChatInfo` forwards `info["bot_status"]` (direct subscript, NOT `.get(...)`), so `CacheService.markChatInaccessible` / `markChatActive` reach the column via the same upsert path as every other `chat_info` write. **Self-heal consequence:** because `TheBot.getChatInfo` hardcodes `bot_status = ChatBotStatus.ACTIVE` in both platform return dicts and `updateChatInfo`'s default is `ACTIVE`, the every-message refresh path (`BaseBotHandler.updateChatInfo` → `TheBot.getChatInfo` → `CacheService.setChatInfo` → repo `updateChatInfo`) ALWAYS writes `ACTIVE` — a transient `INACCESSIBLE` set by `markChatInaccessible` self-heals to `ACTIVE` on the next inbound message, which is correct because receiving a message proves the chat is accessible. There is no dedicated status-mutation repository method (`setChatBotStatus` / `getInactiveChatIds` were removed during the accessibility simplification — see [`docs/design/chat-accessibility-tracking.md`](../design/chat-accessibility-tracking.md) "Implementation Divergence (2026-08-12)"). |
| `chatSummarization` | `ChatSummarizationRepository` | `chat_summarization.py` |
| `userMemories` | `UserMemoriesRepository` | `user_memories.py` |
| `mediaAttachments` | `MediaAttachmentsRepository` | `media_attachments.py` |
### Available repositories: tasks, divination, cache, and models

| Attribute | Class | File |
|---|---|---|
| `spam` | `SpamRepository` | `spam.py` |
| `delayedTasks` | `DelayedTasksRepository` | `delayed_tasks.py` |
| `divinations` | `DivinationsRepository` | `divinations.py` (reading rows + cached layout definitions) |
| `cache` | `CacheRepository` | `cache.py` (the `cache_storage` trio only — `CacheService` persistence backing; the `cache` table itself is owned by `GenericDatabaseCache` in `lib/cache/sql_cache.py`, see ADR-024) |
| `embeddingModels` | `EmbeddingModelsRepository` | `embedding_models.py` (embedding-provenance lookup table; constructed FIRST so its bound `getOrCreateModelId` method can be injected as `modelIdResolver` into `chatEmbeddings` / `chatSearch` / `userMemories` — Decision D10) |

> `DatabaseBayesStorage` (`internal/database/bayes_storage.py`) wraps a `Database` and is not exposed as `db.<name>`; `DatabaseStatsStorage` now lives at `lib/stats/sql_storage.py` and takes a `DatabaseManager` directly, constructed via the `StatsAggregationService` factory — see §1 for the Bayes cleanup-path usage. `WebhookUpdatesRepository` also left this tree with ADR-025 — it lives at [`lib/max_webhook_receiver/repository.py`](../../lib/max_webhook_receiver/repository.py) over the webhook receiver's OWN database and is no longer reachable from the `Database` wrapper.

### Adding a method to an existing repository

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

### dataSource routing and provider method cheatsheet

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

### Creating a new repository

**Creating a new repository:**

1. Create new file in `internal/database/repositories/my_repository.py`
2. Inherit from `BaseRepository` (constructor takes a `DatabaseManager`, NOT a `Database`):
```python
import logging
from typing import Optional

from .. import utils as dbUtils
from lib.db.manager import DatabaseManager
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

### Checklist after modifying Database

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

`BaseSQLProvider` exposes the dialect-portable helpers — `upsert()` with the `ExcludedValue` marker, `applyPagination()`, `getTextType()`, `getCaseInsensitiveComparison()`, `getLikeComparison()` — plus the native vector-search hooks (`isVectorSearchSupported()`, `vectorSearch()`, `listTables()`, `createVectorTable()`). **Owner of the hook contracts, per-provider SQL shapes, and the vector-search portability rules:** [`sql-portability-guide.md`](../sql-portability-guide.md) (Issues #1-#13 and "Native Vector Search Portability"). Always call the hooks instead of hand-writing dialect SQL — `COLLATE NOCASE`, positional `LIMIT offset, limit`, and hand-written `ON CONFLICT ... DO UPDATE` are all forbidden in new code.

### SQLite vector search — `sqlite-vec` + `vec0` virtual table

The `vec0` DDL, partition-key layout, and lifecycle are owned by the schema pair: [`database-schema.md` §vec_message_embeddings_N](../database-schema.md#vec_message_embeddings_n-virtual-table) and [`database-schema-llm.md`](../database-schema-llm.md#vec_message_embeddings_n-virtual-table). Agent-facing summary: tables are named `vec_message_embeddings_{N}` / `vec_user_memories_{N}` per embedding dimension, `chat_id` + `model_id` are PARTITION KEYs so equality predicates prune the search, tables are created lazily at runtime by `createVectorTable()` on first write (`readonly=True` would block DDL — never create in the search path), and the semantic search path returns `[]` when `sqlite-vec` is unavailable (no numpy fallback — retired alongside the `message_embeddings` BLOB store in `migration_025`).

---

## 8. Utility Functions

**File:** [`lib/db/utils.py`](../../lib/db/utils.py)

### `sqlToCustomType(data, expectedType)`

Convert SQL response data to the expected Python type with smart type coercion.

```python
from lib.db.utils import sqlToCustomType

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

#### Known migrations catalog

The migration-by-migration catalog (001 through the current version) is owned by [`database-schema.md` §Migration System](../database-schema.md#migration-system); the live file list is [`internal/database/migrations/versions/`](../../internal/database/migrations/versions/). Do not maintain a second catalog in this guide — when adding a migration, document it in the schema docs (step 5 above) and link from here instead.

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
