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
8. [Migration Documentation Protocol](#8-migration-documentation-protocol)

---

## 1. Key Database Methods

**File:** [`internal/database/database.py`](../../internal/database/database.py)

**Repository Pattern:** Database operations are now accessed through specialized repositories

| Repository | Method | Returns | Purpose |
|---|---|---|---|
| `chatMessages` | `saveChatMessage(...)` | `None` | Save incoming/outgoing message |
| `chatMessages` | `getChatMessageByMessageId(chatId, messageId)` | `Optional[ChatMessageDict]` | Get message by ID |
| `chatMessages` | `getChatMessagesByRootId(chatId, rootMessageId, threadId)` | `List[ChatMessageDict]` | Get thread messages |
| `chatMessages` | `updateChatMessageCategory(chatId, messageId, category)` | `None` | Update message category |
| `chatMessages` | `updateChatMessageMetadata(chatId, messageId, metadata)` | `None` | Update message metadata |
| `chatUsers` | `getChatUser(chatId, userId)` | `Optional[ChatUserDict]` | Get user in chat |
| `chatUsers` | `updateChatUser(chatId, userId, username, fullName)` | `None` | Upsert user in chat |
| `chatUsers` | `updateUserMetadata(chatId, userId, metadata)` | `None` | Update user metadata |
| `chatUsers` | `getUserChats(userId)` | `List[ChatInfoDict]` | Get all chats for user |
| `mediaAttachments` | `addMediaAttachment(...)` | `None` | Add media attachment record |
| `mediaAttachments` | `getMediaAttachment(mediaId)` | `Optional[MediaAttachmentDict]` | Get media by unique ID |
| `mediaAttachments` | `updateMediaAttachment(mediaId, ...)` | `None` | Update media record |
| `mediaAttachments` | `ensureMediaInGroup(mediaId, mediaGroupId)` | `None` | Ensure media in group |
| `mediaAttachments` | `getMediaGroupLastUpdatedAt(mediaGroupId)` | `Optional[datetime]` | Get MAX(created_at) from media_groups |
| `chatSettings` | `setChatSetting(chatId, key, value, *, updatedBy)` | `None` | Set a chat setting with audit trail |
| `chatSettings` | `getChatSetting(chatId, setting)` | `Optional[str]` | Get single setting value |
| `chatSettings` | `getChatSettings(chatId)` | `Dict[str, tuple[str, int]]` | Get all settings as (value, updated_by) |
| `cache` | `clearOldCacheEntries(ttl)` | `None` | Cleanup stale cache |
| `delayedTasks` | `cleanupOldCompletedDelayedTasks(ttl)` | `None` | Cleanup old tasks |
| `divinations` | `insertReading(...)` | `None` | Persist a tarot/runes reading row in `divinations` |
| `divinations` | `getLayout(systemId, layoutName)` | `Optional[DivinationLayoutDict]` | Get cached layout with fuzzy search |
| `divinations` | `saveLayout(...)` | `bool` | Save/update layout definition in cache |
| `divinations` | `saveNegativeCache(systemId, layoutId)` | `bool` | Save negative cache entry for non-existent layout |
| `divinations` | `isNegativeCacheEntry(layoutDict)` | `bool` | Check if layout dict is a negative cache entry |

---

## 2. Chat Settings in Database

Chat settings are stored in the cache layer (not directly in DB for hot path):

```python
# Get settings (from cache, falls back to DB)
chatSettings: ChatSettingsDict = self.db.chatSettings.getChatSettings(chatId)

# Set a setting (updatedBy is REQUIRED keyword-only arg)
self.db.chatSettings.setChatSetting(
    chatId=chatId,
    key=ChatSettingsKey.CHAT_MODEL,
    value=ChatSettingsValue("gpt-4"),
    updatedBy=messageSender.id,
)

# Remove a setting (revert to default)
self.db.chatSettings.unsetChatSetting(chatId=chatId, key=ChatSettingsKey.CHAT_MODEL)
```

**IMPORTANT:** `getChatSettings(chatId)` returns `Dict[str, tuple[str, int]]` where each value is a `(value, updated_by)` tuple. Always index `[0]` to get the value. The `updated_by` field is the user ID who last changed the setting (0 for system changes).

```python
# Get settings ( from cache, falls back to DB)
chatSettings: ChatSettingsDict = self.db.chatSettings.getChatSettings(chatId)

# Access individual setting value (index [0] for the value)
value = chatSettings.get('chat-model', ('gpt-4', 0))[0]

# Set a setting (updatedBy is REQUIRED keyword-only arg)
self.db.chatSettings.setChatSetting(
    chatId=chatId,
    key=ChatSettingsKey.CHAT_MODEL,
    value=ChatSettingsValue("gpt-4"),
    updatedBy=messageSender.id,
)

# Remove a setting (revert to default)
self.db.chatSettings.unsetChatSetting(chatId=chatId, key=ChatSettingsKey.CHAT_MODEL)
```

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
- [`SourceConfig`](../../internal/config/types.py) — config for one DB provider
- [`SQLProviderConfig`](../../internal/database/providers/__init__.py) — provider config dict with `provider` and `parameters`

**Routing priority:** `dataSource` param → `chatId` mapping → default source

**Read methods with `dataSource` parameter:**

Most read methods accept an optional `dataSource: Optional[str] = None` parameter:
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

## 5. Database Models Reference

**File:** [`internal/database/models.py`](../../internal/database/models.py)

### Key TypedDicts

| TypedDict | Purpose |
|---|---|
| `ChatMessageDict` | Stored message |
| `ChatInfoDict` | Chat metadata |
| `ChatUserDict` | User in chat |
| `MediaAttachmentDict` | Media file record |
| `DelayedTaskDict` | Delayed task record |
| `CacheDict` | Cached data entry |

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

#### `MediaStatus`

| Value | Meaning |
|---|---|
| `NEW` | Just added |
| `PENDING` | Processing |
| `DONE` | Successfully processed |
| `FAILED` | Processing failed |

#### `SpamReason`

Various spam classification reasons — used by `SpamHandler`

---

## 6. Adding Methods to `Database`

**Repository Pattern:** Database operations are organized into specialized repositories in `internal/database/repositories/`

**Available Repositories:**
- `chatMessages` — Message operations
- `chatUsers` — User operations
- `chatSettings` — Settings operations
- `mediaAttachments` — Media operations
- `cache` — Cache operations
- `delayedTasks` — Task operations
- `divinations` — Tarot/runes reading persistence (`insertReading(...)`)
- And 5 more specialized repositories

**Adding methods to existing repository:**

1. Open the appropriate repository file in `internal/database/repositories/`
2. Add your method following the repository pattern:
```python
def myNewDbMethod(self, chatId: int, value: str) -> Optional[SomeDict]:
    """Short description

    Args:
        chatId: Chat ID to query
        value: Value to insert/update

    Returns:
        SomeDict if found, None otherwise
    """
    with self.db._getConnection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM some_table WHERE chat_id = ?",
            (chatId,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)
```

**For read-only methods, pass `readonly=True`:**
```python
def getMyData(self, chatId: int, dataSource: Optional[str] = None) -> Optional[SomeDict]:
    """Get data for chat

    Args:
        chatId: Chat ID to query
        dataSource: Optional explicit data source name

    Returns:
        SomeDict if found, None otherwise
    """
    with self.db._getConnection(chatId=chatId, dataSource=dataSource, readonly=True) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM my_table WHERE chat_id = ?", (chatId,))
        row = cursor.fetchone()
        return dict(row) if row else None
```

**Creating a new repository:**

1. Create new file in `internal/database/repositories/my_repository.py`
2. Inherit from `BaseRepository`:
```python
from internal.database.repositories.base import BaseRepository

class MyRepository(BaseRepository):
    """Repository for my_table operations"""
    
    def __init__(self, db: 'Database'):
        super().__init__(db)
    
    def myMethod(self, chatId: int) -> Optional[SomeDict]:
        """Method description"""
        with self.db._getConnection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM my_table WHERE chat_id = ?", (chatId,))
            row = cursor.fetchone()
            return dict(row) if row else None
```

3. Register in `internal/database/database.py`:
```python
from internal.database.repositories.my_repository import MyRepository

class Database:
    def __init__(self, ...):
        # ... existing code ...
        self.myRepository = MyRepository(self)
```

**Checklist after modifying `Database`:**
- [ ] Method has docstring
- [ ] Method has type hints
- [ ] Uses context manager `with self.db._getConnection()`
- [ ] Migration created if schema changed
- [ ] Tests in `tests/test_db_wrapper.py`
- [ ] Ran `make format lint` and `make test`

---

## 7. Provider Helper Methods

**File:** [`internal/database/providers/base.py`](../../internal/database/providers/base.py)

The `BaseSQLProvider` abstract class provides cross-database compatibility methods for common SQL operations. Use these methods instead of writing RDBMS-specific SQL directly

### `getCaseInsensitiveComparison(column, param)`

Get RDBMS-specific case-insensitive comparison for exact matches.

```python
# Exact case-insensitive match
query = sqlProvider.getCaseInsensitiveComparison("name", "userName")
# Returns: 'LOWER(name) = LOWER(:userName)' for SQLite/MySQL
# Returns: 'LOWER(name) = LOWER(:userName)' for PostgreSQL (or could use ILIKE)
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
| `isReadOnly()` | Check if provider is in read-only mode |

---

## 8. Migration Documentation Protocol

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
- `migration_001` to `migration_015` — Baseline migrations through latest schema updates
- `migration_010`: Adds `updated_by INTEGER NOT NULL` to `chat_settings` table (audit trail)
- `migration_011` and `migration_012`: Additional schema improvements
- `migration_013`: Removes `DEFAULT CURRENT_TIMESTAMP` from all timestamp columns (explicit timestamp handling)
- `migration_014`: Adds the [`divinations`](#divinations) table (composite PK `(chat_id, message_id)`) plus `idx_divinations_user_created` index for tarot/runes readings
- `migration_015`: Adds the [`divination_layouts`](#divination_layouts) table (composite PK `(system_id, layout_id)`) plus `idx_divination_layouts_system` index for layout discovery cache

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
*Last updated: 2026-05-02*
