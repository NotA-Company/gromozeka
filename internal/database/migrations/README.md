# Database Migrations Module

**Status:** ✅ Implemented and Tested  
**Version:** 2.0.0  
**Date:** 2025-11-16

---

## Overview

This module provides a robust database migration system for the Gromozeka bot, dood! It allows for:

- **Version Tracking**: Tracks migration versions using the [`settings`](../manager.py:14) table
- **Sequential Execution**: Runs migrations in order automatically
- **Rollback Support**: Can rollback migrations when needed
- **Auto-Discovery**: Automatically discovers and loads migrations from the versions directory
- **Provider-Aware**: Skips read-only database sources during migration
- **Async Operations**: Fully async migration execution for better performance
- **Multi-Source Support**: Works with multiple database sources simultaneously

---

## Architecture

### Module Structure

```
internal/database/migrations/
├── __init__.py                        # Module exports
├── base.py                            # BaseMigration abstract class
├── manager.py                         # MigrationManager implementation
├── create_migration.py                # Migration generator script
├── test_migrations.py                 # Test suite
├── README.md                          # This file
└── versions/                          # Migration files
    ├── __init__.py                    # Auto-discovery system
    ├── migration_001_initial_schema.py
    ├── migration_002_add_is_spammer_to_chat_users.py
    ├── migration_003_add_metadata_to_chat_users.py
    ├── migration_004_add_cache_storage_table.py
    ├── migration_005_add_yandex_cache.py
    ├── migration_006_new_cache_tables.py
    ├── migration_007_messages_metadata.py
    ├── migration_008_add_media_group_support.py
    ├── migration_009_remove_is_spammer_from_chat_users.py
    ├── migration_010_add_updated_by_to_chat_settings.py
    ├── migration_011_add_confidence_to_spam_messages.py
    ├── migration_012_unify_cache_tables.py
    └── migration_013_remove_timestamp_defaults.py
```

### Key Components

#### [`BaseMigration`](base.py:17)
Abstract base class that all migrations must inherit from, dood!

```python
class BaseMigration(ABC):
    version: int          # Migration version number
    description: str      # Human-readable description
    
    @abstractmethod
    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration"""
        pass
    
    @abstractmethod
    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration"""
        pass
```

#### [`MigrationManager`](manager.py:31)
Manages migration execution, version tracking, and rollbacks, dood!

**Key Methods:**
- [`loadMigrationsFromVersions()`](manager.py:68) - Auto-discover migrations from versions directory
- [`getCurrentVersion()`](manager.py:136) - Get current migration version
- [`migrate(targetVersion=None)`](manager.py:187) - Run pending migrations
- [`rollback(steps=1)`](manager.py:247) - Rollback N migrations
- [`getStatus()`](manager.py:294) - Get migration status information

#### Auto-Discovery System

The migration system uses automatic discovery via [`DISCOVERED_MIGRATIONS`](versions/__init__.py:92):

```python
# Automatically discovers all migrations in versions/ directory
from .versions import DISCOVERED_MIGRATIONS

manager = MigrationManager()
manager.loadMigrationsFromVersions()  # No manual registration needed!
```

Each migration file must provide a `getMigration()` function:

```python
def getMigration() -> Type[BaseMigration]:
    """Return the migration class for auto-discovery."""
    return Migration014AddUserPreferences
```

---

## Migration History

This section documents all migrations in the system, dood!

| Version | File | Description | Tables Affected |
|---------|------|-------------|-----------------|
| 001 | [`migration_001_initial_schema.py`](versions/migration_001_initial_schema.py:1) | Initial database schema | All core tables |
| 002 | [`migration_002_add_is_spammer_to_chat_users.py`](versions/migration_002_add_is_spammer_to_chat_users.py:1) | Add is_spammer column to chat_users | chat_users |
| 003 | [`migration_003_add_metadata_to_chat_users.py`](versions/migration_003_add_metadata_to_chat_users.py:1) | Add metadata column to chat_users | chat_users |
| 004 | [`migration_004_add_cache_storage_table.py`](versions/migration_004_add_cache_storage_table.py:1) | Add cache_storage table | cache_storage |
| 005 | [`migration_005_add_yandex_cache.py`](versions/migration_005_add_yandex_cache.py:1) | Add Yandex search cache tables | yandex_cache |
| 006 | [`migration_006_new_cache_tables.py`](versions/migration_006_new_cache_tables.py:1) | Add new cache tables | cache, cache_storage |
| 007 | [`migration_007_messages_metadata.py`](versions/migration_007_messages_metadata.py:1) | Add markup and metadata to chat_messages | chat_messages |
| 008 | [`migration_008_add_media_group_support.py`](versions/migration_008_add_media_group_support.py:1) | Add media_group_id and media_groups table | chat_messages, media_groups |
| 009 | [`migration_009_remove_is_spammer_from_chat_users.py`](versions/migration_009_remove_is_spammer_from_chat_users.py:1) | Remove is_spammer column from chat_users | chat_users |
| 010 | [`migration_010_add_updated_by_to_chat_settings.py`](versions/migration_010_add_updated_by_to_chat_settings.py:1) | Add updated_by column to chat_settings | chat_settings |
| 011 | [`migration_011_add_confidence_to_spam_messages.py`](versions/migration_011_add_confidence_to_spam_messages.py:1) | Add confidence column to spam/ham messages | spam_messages, ham_messages |
| 012 | [`migration_012_unify_cache_tables.py`](versions/migration_012_unify_cache_tables.py:1) | Unify cache tables structure | cache, cache_storage |
| 013 | [`migration_013_remove_timestamp_defaults.py`](versions/migration_013_remove_timestamp_defaults.py:1) | Remove DEFAULT CURRENT_TIMESTAMP from timestamp columns | 19 tables (settings, chat_messages, chat_settings, chat_users, chat_info, chat_stats, chat_user_stats, media_attachments, delayed_tasks, user_data, spam_messages, ham_messages, chat_topics, chat_summarization_cache, bayes_tokens, bayes_classes, cache_storage, cache, media_groups) |

**Total Migrations:** 13

**Important Notes:**
- Migration 013 is critical for SQL portability - it recreates 19 tables to remove `DEFAULT CURRENT_TIMESTAMP` from all timestamp columns
- This migration includes ALL columns from migrations 2-12 to ensure no data loss
- The migration is reversible via the `down()` method
- This change enables the database to work with different SQL backends beyond SQLite

---

## Usage

### Automatic Migration on Startup

Migrations run automatically when [`Database`](../database.py:28) is initialized, dood!

```python
from internal.database import Database
from internal.database.manager import DatabaseManagerConfig

# Migrations run automatically during initialization
config = DatabaseManagerConfig(...)
db = Database(config)
# Migrations are applied to all non-readonly sources automatically
```

The migration process:
1. [`Database.__init__()`](../database.py:92) creates a [`MigrationManager`](manager.py:31)
2. Calls [`loadMigrationsFromVersions()`](manager.py:68) to auto-discover migrations
3. Registers [`migrateDatabase()`](../database.py:133) as a provider initialization hook
4. For each database provider:
   - Skips if the provider is read-only
   - Creates the settings table if needed
   - Runs all pending migrations

### Manual Migration Control

```python
from internal.database.migrations import MigrationManager

# Create manager and auto-load migrations
manager = MigrationManager()
manager.loadMigrationsFromVersions()

# Get a provider instance (from Database.manager)
sqlProvider = db.manager.getProvider("default")

# Run all pending migrations
await manager.migrate(sqlProvider=sqlProvider)

# Run migrations up to specific version
await manager.migrate(targetVersion=5, sqlProvider=sqlProvider)

# Rollback last migration
await manager.rollback(steps=1, sqlProvider=sqlProvider)

# Get migration status
status = await manager.getStatus(sqlProvider=sqlProvider)
print(f"Current version: {status['current_version']}")
print(f"Pending migrations: {status['pending_count']}")
print(f"Latest version: {status['latest_version']}")
```

### Provider-Aware Migration

The system automatically skips read-only database sources:

```python
async def migrateDatabase(self, sqlProvider: BaseSQLProvider, providerName: str, readOnly: bool) -> None:
    """Migrate database schema and run migrations for non-readonly sources."""
    
    if readOnly:
        logger.debug(f"Skipping DB migration for readonly source {providerName}, dood")
        return
    
    # Continue with migration for writable sources
    # ...
```

This ensures that:
- Read-only replicas are never modified
- Migration only runs on writable sources
- Multi-source configurations work safely

---

## Creating New Migrations

### Quick Start: Use the Migration Generator Script ⚡

The easiest way to create a new migration is using the provided script, dood!

```bash
# Create a new migration
./venv/bin/python3 internal/database/migrations/create_migration.py "add user preferences table"
```

**Output:**
```
✅ Created migration file: migration_014_add_user_preferences.py
   Class name: Migration014AddUserPreferences
   Version: 14

📝 Next steps, dood:
   1. Edit the migration file
   2. Implement up() and down() methods
   3. Add getMigration() function for auto-discovery
   4. Test your migration
```

The script will:
- ✅ Automatically determine the next version number
- ✅ Generate a properly named migration file
- ✅ Create a template with TODO comments and examples
- ✅ Show you the exact next steps to complete

### Manual Creation (Alternative)

If you prefer to create migrations manually, dood:

#### Step 1: Determine Version Number

```bash
# List existing migrations
ls internal/database/migrations/versions/

# Next version = highest + 1
# If you see migration_013_*.py, next is 014
```

#### Step 2: Create Migration File

**Naming Convention:** `migration_{version:03d}_{description}.py`

```bash
# Example: Create migration 014
touch internal/database/migrations/versions/migration_014_add_user_preferences.py
```

#### Step 3: Implement Migration Class

```python
"""
Add user preferences table, dood!
"""

from typing import TYPE_CHECKING
from ..base import BaseMigration

if TYPE_CHECKING:
    from ..providers import BaseSQLProvider


class Migration014AddUserPreferences(BaseMigration):
    """Add user preferences table, dood!"""

    version = 14
    description = "Add user preferences table"

    async def up(self, sqlProvider: "BaseSQLProvider") -> None:
        """Create user_preferences table, dood!"""
        await sqlProvider.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER NOT NULL,
                preference_key TEXT NOT NULL,
                preference_value TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                PRIMARY KEY (user_id, preference_key)
            )
            """
        )
        
        # Add index for better performance
        await sqlProvider.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id
            ON user_preferences(user_id)
            """
        )

    async def down(self, sqlProvider: "BaseSQLProvider") -> None:
        """Drop user_preferences table, dood!"""
        await sqlProvider.execute("DROP TABLE IF EXISTS user_preferences")


def getMigration() -> type[BaseMigration]:
    """Return the migration class for auto-discovery."""
    return Migration014AddUserPreferences
```

**Important:** The `getMigration()` function is required for auto-discovery!

#### Step 4: Test Your Migration

```bash
# Run the migration test suite
./venv/bin/python3 internal/database/migrations/test_migrations.py
```

---

## Best Practices

### DO ✅

- **Use `IF NOT EXISTS`** for CREATE statements
- **Use `IF EXISTS`** for DROP statements
- **Test both `up()` and `down()` methods** before deployment
- **Keep migrations small and focused** on one change
- **Add comments** explaining complex changes
- **Use async/await** for all database operations
- **Provide `getMigration()` function** for auto-discovery
- **Version sequentially** (no gaps in version numbers)
- **Avoid DEFAULT CURRENT_TIMESTAMP** for SQL portability

### DON'T ❌

- **Never modify existing migration files** after deployment
- **Don't skip version numbers** (must be sequential)
- **Don't make migrations dependent on application code**
- **Don't mix data migrations with schema changes** (separate them)
- **Don't use database-specific features** (stick to SQL standard)
- **Don't forget the `getMigration()` function** (breaks auto-discovery)
- **Don't use synchronous database operations** (must be async)

---

## Migration Patterns

### Adding a Table

```python
async def up(self, sqlProvider: "BaseSQLProvider") -> None:
    await sqlProvider.execute("""
        CREATE TABLE IF NOT EXISTS new_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TIMESTAMP
        )
    """)

async def down(self, sqlProvider: "BaseSQLProvider") -> None:
    await sqlProvider.execute("DROP TABLE IF EXISTS new_table")
```

### Adding a Column

```python
async def up(self, sqlProvider: "BaseSQLProvider") -> None:
    # Check if column exists first
    result = await sqlProvider.execute("PRAGMA table_info(existing_table)")
    columns = [row["name"] for row in result]
    
    if "new_column" not in columns:
        await sqlProvider.execute("""
            ALTER TABLE existing_table 
            ADD COLUMN new_column TEXT
        """)

async def down(self, sqlProvider: "BaseSQLProvider") -> None:
    # SQLite doesn't support DROP COLUMN easily
    # Document that this migration is not reversible
    pass
```

### Adding an Index

```python
async def up(self, sqlProvider: "BaseSQLProvider") -> None:
    await sqlProvider.execute("""
        CREATE INDEX IF NOT EXISTS idx_table_column
        ON table_name(column_name)
    """)

async def down(self, sqlProvider: "BaseSQLProvider") -> None:
    await sqlProvider.execute("DROP INDEX IF EXISTS idx_table_column")
```

### Recreating a Table (for complex changes)

```python
async def up(self, sqlProvider: "BaseSQLProvider") -> None:
    # Create new table with desired schema
    await sqlProvider.execute("""
        CREATE TABLE IF NOT EXISTS table_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            new_column TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    
    # Copy data from old table
    await sqlProvider.execute("""
        INSERT INTO table_new (id, name, created_at, updated_at)
        SELECT id, name, created_at, updated_at
        FROM table_old
    """)
    
    # Drop old table
    await sqlProvider.execute("DROP TABLE IF EXISTS table_old")
    
    # Rename new table
    await sqlProvider.execute("ALTER TABLE table_new RENAME TO table")

async def down(self, sqlProvider: "BaseSQLProvider") -> None:
    # Reverse the process
    await sqlProvider.execute("""
        CREATE TABLE IF NOT EXISTS table_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    
    await sqlProvider.execute("""
        INSERT INTO table_old (id, name, created_at, updated_at)
        SELECT id, name, created_at, updated_at
        FROM table
    """)
    
    await sqlProvider.execute("DROP TABLE IF EXISTS table")
    await sqlProvider.execute("ALTER TABLE table_old RENAME TO table")
```

---

## Testing

### Run Test Suite

```bash
./venv/bin/python3 internal/database/migrations/test_migrations.py
```

### Test Coverage

The test suite includes:

1. **Fresh Database Initialization** - Tests creating a new database
2. **Migration Status** - Tests status reporting
3. **Rollback** - Tests rolling back migrations
4. **Existing Database Upgrade** - Tests upgrading an old database
5. **Auto-Discovery** - Tests automatic migration loading

All tests create temporary databases and clean up automatically, dood!

---

## Version Tracking

### Storage

Migration versions are stored in the [`settings`](../manager.py:14) table:

- **Key:** `db-migration-version` - Current version (integer)
- **Key:** `db-migration-last-run` - ISO timestamp of last migration

### Checking Current Version

```python
# Using the migration manager
version = await manager.getCurrentVersion(sqlProvider=sqlProvider)
print(f"Current migration version: {version}")

# Using the database directly
from internal.database.migrations.manager import MIGRATION_VERSION_KEY
version = await sqlProvider.execute(
    f"SELECT value FROM settings WHERE key = '{MIGRATION_VERSION_KEY}'",
    fetchType=FetchType.FETCH_ONE
)
```

---

## Error Handling

### Automatic Rollback

If a migration fails, the transaction is automatically rolled back, dood!

```python
try:
    await migration.up(sqlProvider)
    await self._setVersion(migration.version, sqlProvider=sqlProvider)
except Exception as e:
    # Transaction automatically rolled back by provider
    logger.error(f"Migration {migration.version} failed: {e}")
    raise MigrationError(f"Failed to apply migration {migration.version}") from e
```

### Recovery

If a migration fails:

1. **Fix the migration code**
2. **Restart the application** - it will retry the failed migration
3. **Check logs** for detailed error information
4. **Verify database state** - the failed migration should not have been applied

---

## Troubleshooting

### Migration Not Running

**Problem:** New migration not executing

**Solution:**
1. Check migration file has `getMigration()` function
2. Verify version number is sequential
3. Check current version: `await manager.getCurrentVersion(sqlProvider=sqlProvider)`
4. Ensure migration file is in `versions/` directory
5. Check logs for auto-discovery errors

### Duplicate Version Error

**Problem:** `MigrationError: Duplicate migration versions detected`

**Solution:**
1. Check all migration files have unique version numbers
2. Ensure no gaps in version sequence
3. Verify `getMigration()` returns the correct class

### Import Error

**Problem:** `ImportError: cannot import name 'migration_XXX'`

**Solution:**
1. Verify file name matches pattern: `migration_XXX_description.py`
2. Check file is in `versions/` directory
3. Ensure `getMigration()` function exists and returns a valid migration class
4. Check for syntax errors in the migration file

### Auto-Discovery Not Working

**Problem:** Migrations not being discovered automatically

**Solution:**
1. Check `versions/__init__.py` exists and is importable
2. Verify `DISCOVERED_MIGRATIONS` is being populated
3. Check logs for discovery errors
4. Ensure migration files follow naming convention
5. Verify `getMigration()` function in each migration file

---

## Multi-Source Migration

The migration system supports multiple database sources with automatic read-only detection:

```python
# Configuration with multiple sources
config = DatabaseManagerConfig(
    sources={
        "primary": {
            "type": "sqlite",
            "path": "/data/primary.db",
            "readOnly": False  # Migrations will run here
        },
        "replica": {
            "type": "sqlite",
            "path": "/data/replica.db",
            "readOnly": True  # Migrations will be skipped
        }
    }
)

db = Database(config)
# Migrations run only on "primary" source
```

**Key Points:**
- Each source is migrated independently
- Read-only sources are automatically skipped
- Version tracking is per-source
- Migration order is maintained across sources

---

## SQL Portability

Migration 013 introduced critical changes for SQL portability:

### What Changed

- **Removed:** `DEFAULT CURRENT_TIMESTAMP` from all timestamp columns
- **Added:** Explicit timestamp handling in application code
- **Result:** Database can now work with PostgreSQL, MySQL, and other SQL backends

### Why This Matters

```python
# Before (SQLite-specific)
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  # SQLite only!
)

# After (SQL-standard compatible)
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    content TEXT,
    created_at TIMESTAMP  # Application sets the value
)
```

### Application Impact

When inserting records, always set timestamps explicitly:

```python
from internal.database.utils import getCurrentTimestamp

currentTimestamp = getCurrentTimestamp()

await sqlProvider.execute(
    "INSERT INTO messages (content, created_at) VALUES (:content, :created_at)",
    {"content": "Hello", "created_at": currentTimestamp}
)
```

---

## Future Enhancements

Potential features for future versions, dood!

1. **Migration Status Command** - CLI tool to check status
2. **Data Migrations** - Separate support for data transformations
3. **Dry-run Mode** - Preview migrations without applying
4. **Migration Locking** - Prevent concurrent migrations
5. **Migration Dependencies** - Support for complex migration graphs
6. **Rollback Safety Checks** - Warn before destructive rollbacks

---

## References

### Internal Documentation

- [`internal/database/database.py`](../database.py:28) - Database wrapper and migration orchestration
- [`internal/database/manager.py`](../manager.py:14) - Database manager
- [`internal/database/providers/base.py`](../providers/base.py:1) - SQL provider interface
- [`internal/database/utils.py`](../utils.py:1) - Database utilities

### Implementation Plan

- [`docs/reports/sql-portability-implementation-summary.md`](../../../docs/reports/sql-portability-implementation-summary.md:1) - SQL portability implementation
- [`docs/reports/sql-portability-implementation-status.md`](../../../docs/reports/sql-portability-implementation-status.md:1) - Implementation status

### External Resources

- [SQLite Documentation](https://www.sqlite.org/docs.html)
- [Alembic Migrations](https://alembic.sqlalchemy.org/) - Reference implementation
- [Django Migrations](https://docs.djangoproject.com/en/stable/topics/migrations/) - Design patterns

---

**End of Documentation, dood!**
