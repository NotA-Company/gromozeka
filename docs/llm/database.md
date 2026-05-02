# Gromozeka — Database Operations

> **Audience:** LLM agents, dood!
> **Purpose:** Complete reference for database operations, migrations, schema, and multi-source routing, dood!
> **Self-contained:** Everything needed for database work is here, dood!

---

## Table of Contents

1. [Key Database Methods](#1-key-database-methods)
2. [Chat Settings in Database](#2-chat-settings-in-database)
3. [Multi-Source Database Routing](#3-multi-source-database-routing)
4. [Adding a Database Migration](#4-adding-a-database-migration)
5. [Database Models Reference](#5-database-models-reference)
6. [Adding Methods to Database](#6-adding-methods-to-database)
7. [Migration Documentation Protocol](#7-migration-documentation-protocol)

---

## 1. Key Database Methods

**File:** [`internal/database/database.py`](../../internal/database/database.py)

**Repository Pattern:** Database operations are now accessed through specialized repositories, dood!

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

---

## 2. Chat Settings in Database

Chat settings are stored in the cache layer (not directly in DB for hot path):

```python
# Get settings (from cache, falls back to DB)
chatSettings: ChatSettingsDict = self.db.chatSettings.getChatSettings(chatId)

# Set a setting (updatedBy is REQUIRED keyword-only arg, dood!)
self.db.chatSettings.setChatSetting(
    chatId=chatId,
    key=ChatSettingsKey.CHAT_MODEL,
    value=ChatSettingsValue("gpt-4"),
    updatedBy=messageSender.id,
)

# Remove a setting (revert to default)
self.db.chatSettings.unsetChatSetting(chatId=chatId, key=ChatSettingsKey.CHAT_MODEL)
```

**IMPORTANT:** `getChatSettings(chatId)` returns `Dict[str, tuple[str, int]]` where each value is a `(value, updated_by)` tuple. The `updated_by` field is the user ID who last changed the setting (0 for system changes), dood!

**Via CacheService (preferred for hot path):**
```python
# Import
from internal.services.cache import CacheService

# Get settings with cache
cache = CacheService.getInstance()
chatSettings: ChatSettingsDict = cache.getCachedChatSettings(chatId)

# Set a setting (passes userId to setChatSetting automatically)
cache.setChatSetting(chatId, key, value, userId=user.id)

# Unset a setting
cache.unsetChatSetting(chatId=chatId, key=key)
```

---

## 3. Multi-Source Database Routing

**Config structure:**
```toml
[database]
default = "default"

[database.sources.default]
path = "bot_data.db"
readonly = false
pool-size = 5
timeout = 30

[database.sources.default.parameters]
keepConnection = false  # Connect on demand (default for file-based DBs)

[database.sources.readonly]
path = "bot_data.db"
readonly = true
pool-size = 10
timeout = 10

[database.sources.readonly.parameters]
keepConnection = true  # Connect immediately (good for readonly replicas)
```

**`keepConnection` parameter:**
- `true` — Connect immediately when provider is created (good for readonly replicas, in-memory DBs)
- `false` — Connect on first query (default for file-based DBs, saves resources)
- `None` — Auto-detect: `true` for in-memory SQLite3, `false` otherwise
- **Special case:** In-memory SQLite3 (`:memory:`) defaults to `true` to prevent data loss

**Key class:** [`SourceConfig`](../../internal/database/database.py:81) — config for one DB source.

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
- Migrations now rely on the provider's `keepConnection` parameter for connection management
- No explicit `await sqlProvider.connect()` call is made during migration
- Providers with `keepConnection=true` connect immediately before migrations run
- Providers with `keepConnection=false` connect on first query during migration
- This ensures consistent behavior across all database operations

---

## 4. Adding a Database Migration

### Step 1: Check existing migrations first (CRITICAL, dood!)

```bash
ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
# Identifies the highest numbered migration
```

**Version Calculation:** `New Version = Latest Version + 1`

### Step 2: Create migration file

**Path:** `internal/database/migrations/versions/NNN_description.py`

```python
"""Migration: add_my_table - vNNN, dood!"""

from internal.database.migrations.base import BaseMigration


class MigrationAddMyTable(BaseMigration):
    """Migration to add my_table, dood!

    Attributes:
        version: Migration version number
        description: Migration description
    """

    version: int = NNN  # Next sequential version number
    description: str = "Add my_table"

    def up(self, cursor) -> None:
        """Apply migration, dood!

        Args:
            cursor: SQLite cursor for executing SQL
        """
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS my_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                value TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_my_table_chat_id ON my_table(chat_id)
        """)

    def down(self, cursor) -> None:
        """Revert migration, dood!

        Args:
            cursor: SQLite cursor for executing SQL
        """
        cursor.execute("DROP TABLE IF EXISTS my_table")
```

### Step 3: Register migration

Check `internal/database/migrations/__init__.py` or the DB manager for registration pattern, dood!

### Step 4: Add methods to `Database`

In [`internal/database/database.py`](../../internal/database/database.py), add methods to use the new table (see [Section 6](#6-adding-methods-to-database)), dood!

### Step 5: Update models if needed

In [`internal/database/models.py`](../../internal/database/models.py), add new `TypedDict` or enum values, dood!

### Step 6: Update documentation

**CRITICAL: Always update docs in the same commit as migration, dood!**

1. Update `docs/database-schema.md` — add migration entry with description
2. Update `docs/database-schema-llm.md` — update affected table schemas
3. Document any API changes resulting from schema changes

### Step 7: Write tests

In `tests/test_db_wrapper.py` and `internal/database/migrations/test_migrations.py`, dood!

### Step 8: Run quality checks

```bash
make format lint
make test
```

### Migration checklist

- [ ] Checked highest existing version number first
- [ ] Created migration file with correct sequential version
- [ ] Implemented `up(cursor)` with `IF NOT EXISTS` guards
- [ ] Implemented `down(cursor)` for rollback
- [ ] Registered migration in registry
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

Various spam classification reasons — used by `SpamHandler`, dood!

---

## 6. Adding Methods to `Database`

**Repository Pattern:** Database operations are organized into specialized repositories in `internal/database/repositories/`, dood!

**Available Repositories:**
- `chatMessages` — Message operations
- `chatUsers` — User operations
- `chatSettings` — Settings operations
- `mediaAttachments` — Media operations
- `cache` — Cache operations
- `delayedTasks` — Task operations
- And 6 more specialized repositories

**Adding methods to existing repository:**

1. Open the appropriate repository file in `internal/database/repositories/`
2. Add your method following the repository pattern:
```python
def myNewDbMethod(self, chatId: int, value: str) -> Optional[SomeDict]:
    """Short description, dood!

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
    """Get data for chat, dood!

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
    """Repository for my_table operations, dood!"""
    
    def __init__(self, db: 'Database'):
        super().__init__(db)
    
    def myMethod(self, chatId: int) -> Optional[SomeDict]:
        """Method description, dood!"""
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

## 7. Migration Documentation Protocol

**Critical lesson from migration_009 documentation error, dood!**

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
- `migration_001` to `migration_013` — Baseline migrations through latest schema updates
- `migration_010`: Adds `updated_by INTEGER NOT NULL` to `chat_settings` table (audit trail)
- `migration_011` and `migration_012`: Additional schema improvements
- `migration_013`: Removes `DEFAULT CURRENT_TIMESTAMP` from all timestamp columns (explicit timestamp handling)

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

*This guide is auto-maintained and should be updated whenever significant database changes are made, dood!*
*Last updated: 2026-05-02, dood!*
