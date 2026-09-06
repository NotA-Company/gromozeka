---
category: guide
---

# Database Layer

The database layer: multi-source routing, the repository pattern, the migration system, and SQL portability across backends.

## 5. Database Layer

The database layer provides SQL access via [`Database`](/internal/database/database.py) with multi-source routing, connection pooling, repository pattern, and an automatic migration system It supports SQLite, MySQL, and PostgreSQL through a provider abstraction

### Database Class

[`Database`](/internal/database/database.py) is the main interface to the database It supports multiple named database providers, with per-chat routing so different chats can use different databases The database uses a repository pattern with 15 specialized repositories for different data domains

```python
from internal.database import Database

db = Database(config={
    "default": "default",
    "providers": {
        "default": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "bot_data.db",
                "readOnly": False,
                "timeout": 30,
            },
        }
    },
    # Optional: route specific chats to other providers
    "chatMapping": {
        "-1001234567890": "secondary",
    }
})
```

### Repository Pattern

The database layer uses a repository pattern with 15 specialized repositories Each repository handles a specific data domain and provides type-safe methods for data access

| Repository | File | Purpose |
|---|---|---|
| [`CacheRepository`](/internal/database/repositories/cache.py) | `cache.py` | Cache storage operations |
| [`ChatInfoRepository`](/internal/database/repositories/chat_info.py) | `chat_info.py` | Chat metadata operations |
| [`ChatMessagesRepository`](/internal/database/repositories/chat_messages.py) | `chat_messages.py` | Message history operations |
| [`ChatSettingsRepository`](/internal/database/repositories/chat_settings.py) | `chat_settings.py` | Chat settings operations |
| [`ChatSummarizationRepository`](/internal/database/repositories/chat_summarization.py) | `chat_summarization.py` | Chat summarization operations |
| [`ChatUsersRepository`](/internal/database/repositories/chat_users.py) | `chat_users.py` | Per-chat user metadata operations |
| [`CommonFunctionsRepository`](/internal/database/repositories/common.py) | `common.py` | Common database operations |
| [`DelayedTasksRepository`](/internal/database/repositories/delayed_tasks.py) | `delayed_tasks.py` | Background task queue operations |
| [`ChatSearchRepository`](/internal/database/repositories/chat_search.py) | `chat_search.py` | Message search and user listing operations |
| [`ChatEmbeddingsRepository`](/internal/database/repositories/chat_embeddings.py) | `chat_embeddings.py` | Message embedding operations |
| [`DivinationsRepository`](/internal/database/repositories/divinations.py) | `divinations.py` | Tarot/runes readings and layout discovery operations |
| [`MediaAttachmentsRepository`](/internal/database/repositories/media_attachments.py) | `media_attachments.py` | Media metadata operations |
| [`SpamRepository`](/internal/database/repositories/spam.py) | `spam.py` | Spam detection operations |
| [`UserMemoriesRepository`](/internal/database/repositories/user_memories.py) | `user_memories.py` | Per-(chat, user, thread) structured memory operations (permanent + ephemeral, vec0-backed) |
| [`WebhookUpdatesRepository`](/lib/max_webhook_receiver/repository.py) | `repository.py` | Max webhook payload storage and consumption |

### Multi-Source Routing

When you call most database methods with a `chatId`, the database automatically selects the right source If a chat isn't in the `chatMapping`, it falls back to the `default` source

```python
# Routes to the source mapped for chatId (-1001234567890 -> "secondary")
settings = db.getChatSettings(chatId=-1001234567890)

# Explicitly pass dataSource to override routing
messages = db.getChatMessages(chatId=123, dataSource="archive")
```

### SQL Portability

The database layer supports multiple SQL backends through a provider abstraction SQL portability is fully implemented, supporting SQLite, MySQL, and PostgreSQL

| Provider | Type | Config Key |
|---|---|---|
| SQLite | `sqlite3` | Built-in, uses `sqlite3` stdlib |
| MySQL | `mysql` | Requires `mysql-connector-python` |
| PostgreSQL | `postgresql` | Requires `psycopg2-binary` |

**Important**: Migration 013 removed `DEFAULT CURRENT_TIMESTAMP` for cross-database compatibility All timestamp columns now use explicit values in application code

### Connection Management

Database providers support configurable connection management via the `keepConnection` parameter

**`keepConnection` parameter values:**
- `true` — Connect immediately when provider is created (good for readonly replicas, in-memory DBs)
- `false` — Connect on first query (default for file-based DBs, saves resources)
- `null` — Auto-detect: `true` for in-memory SQLite3, `false` otherwise

**Special case:** In-memory SQLite3 (`:memory:`) defaults to `true` to prevent data loss

**Configuration example:**
```toml
[database.providers.default.parameters]
keepConnection = false  # Connect on demand (default for file-based DBs)

[database.providers.readonly.parameters]
keepConnection = true  # Connect immediately (good for readonly replicas)
```

**Migration connection management:** Migrations rely on the provider's `keepConnection` parameter for connection management No explicit `await sqlProvider.connect()` call is made during migration

### Database Schema (15+ Tables)

The schema is defined and evolved through migrations. Key tables include:

| Table | Purpose |
|---|---|
| `chat_info` | Chat metadata (id, type, title, etc.) |
| `chat_settings` | Per-chat key-value bot settings |
| `chat_users` | Per-chat user metadata, join counts, message counts |
| `chat_messages` | Message history for LLM context |
| `spam_messages` | Detected spam messages |
| `cache` | General-purpose persistent cache |
| `cache_storage` | Extended cache storage |
| `media_attachments` | Uploaded media metadata |
| `delayed_tasks` | Background task queue persistence |
| `summarization_cache` | Chat summarization results |
| `bayes_filter` | Bayes filter training data |

### Migration System

Migrations live in [`internal/database/migrations/versions/`](/internal/database/migrations/versions/) and are auto-discovered by [`MigrationManager`](/internal/database/migrations/manager.py)

Each migration inherits from [`BaseMigration`](/internal/database/migrations/base.py:9):

```python
from internal.database.migrations.base import BaseMigration
from lib.db.providers import BaseSQLProvider

class Migration(BaseMigration):
    version = 13          # Must be unique sequential integer!
    description = "Add my_new_table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        await sqlProvider.execute("""
            CREATE TABLE IF NOT EXISTS my_new_table (
                chat_id INTEGER PRIMARY KEY NOT NULL,
                value TEXT,
                created_at TIMESTAMP NOT NULL
            )
        """)

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        await sqlProvider.execute("DROP TABLE IF EXISTS my_new_table")
```

Migrations are applied automatically on [`Database`](/internal/database/database.py) initialization The schema version is tracked in the `settings` table using the `db-migration-version` and `db-migration-last-run` keys.

### How to Add a Migration

1. **Check the latest migration version** first

```bash
ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
```

2. **Create the migration file** using the next sequential number:

```bash
# If latest is migration_012, create migration_013
cp internal/database/migrations/versions/migration_012_unify_cache_tables.py \
   internal/database/migrations/versions/migration_013_my_change.py
```

3. **Edit the file** to set `version`, `description`, and implement `up()` / `down()`

4. **Register the migration** in [`internal/database/migrations/versions/__init__.py`](/internal/database/migrations/versions/__init__.py) if needed.

5. **Run the bot** — migrations are applied automatically

> **NEVER reuse or skip version numbers!** The version number is immutable once deployed

---

### 14.4 Adding a Database Migration

> **Critical**: Always verify the current highest version before creating a migration

**Step 1**: Find the highest current migration version

```bash
ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
# Example output: migration_012_unify_cache_tables.py
# -> Next version is 013
```

**Step 2**: Create the migration file

```python
# internal/database/migrations/versions/migration_013_my_change.py
"""Migration 013 - Add my new column"""

import sqlite3

from internal.database.migrations.base import BaseMigration


class Migration(BaseMigration):
    """Adds my_column to the chat_info table

    This migration adds a new column to support the XYZ feature.
    """

    version: int = 13
    description: str = "Add my_column to chat_info table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply migration: add my_column

        Args:
            sqlProvider: SQL provider for executing SQL
        """
        await sqlProvider.execute("""
            ALTER TABLE chat_info
            ADD COLUMN my_column TEXT DEFAULT NULL
        """)

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback migration

        Note: SQLite before 3.35 does not support DROP COLUMN.
        Consider a table-rebuild approach for older SQLite versions.

        Args:
            sqlProvider: SQL provider for executing SQL
        """
        # SQLite 3.35+: await sqlProvider.execute("ALTER TABLE chat_info DROP COLUMN my_column")
        pass
```

**Step 3**: The migration manager auto-discovers files in the `versions/` directory No manual registration needed.

**Step 4**: Run the bot — migrations are applied automatically on startup

**Step 5**: Update any schema documentation in `docs/`
