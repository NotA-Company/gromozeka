# Database Migrations Module

**Status:** ✅ Implemented and Tested  
**Version:** 1.0.0  
**Date:** 2025-10-23

---

## Overview

This module provides a robust database migration system for the Gromozeka bot, dood! It allows for:

- **Version Tracking**: Tracks migration versions using the existing [`settings`](../wrapper.py:127) table
- **Sequential Execution**: Runs migrations in order automatically
- **Rollback Support**: Can rollback migrations when needed
- **Backward Compatibility**: Works with existing databases
- **Error Handling**: Automatic transaction rollback on failures

---

## Architecture

### Module Structure

```
internal/database/migrations/
├── __init__.py                        # Migration registry and exports
├── base.py                            # BaseMigration abstract class
├── manager.py                         # MigrationManager implementation
├── create_migration.py                # Migration generator script
├── test_migrations.py                 # Test suite
├── README.md                          # This file
└── versions/                          # Migration files
    ├── __init__.py
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

#### [`BaseMigration`](base.py:11)
Abstract base class that all migrations must inherit from, dood!

```python
class BaseMigration(ABC):
    version: int          # Migration version number
    description: str      # Human-readable description
    
    def up(self, db: DatabaseWrapper) -> None:
        """Apply the migration"""
        pass
    
    def down(self, db: DatabaseWrapper) -> None:
        """Rollback the migration"""
        pass
```

#### [`MigrationManager`](manager.py:22)
Manages migration execution, version tracking, and rollbacks, dood!

**Key Methods:**
- [`getCurrentVersion()`](manager.py:54) - Get current migration version
- [`migrate(targetVersion=None)`](manager.py:91) - Run pending migrations
- [`rollback(steps=1)`](manager.py:143) - Rollback N migrations
- [`getStatus()`](manager.py:193) - Get migration status information

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
- Migration 013 recreates 19 tables to remove `DEFAULT CURRENT_TIMESTAMP` from all timestamp columns for SQL portability
- This migration includes ALL columns from migrations 2-12 to ensure no data loss
- The migration is reversible via the `down()` method

---

## Usage

### Automatic Migration on Startup

Migrations run automatically when [`DatabaseWrapper`](../wrapper.py:77) is initialized, dood!

```python
from internal.database import Database

# Migrations run automatically during initialization
db = DatabaseWrapper("path/to/database.db")
```

### Manual Migration Control

```python
from internal.database.migrations import MigrationManager, MIGRATIONS

# Create manager
manager = MigrationManager(db)
manager.registerMigrations(MIGRATIONS)

# Run all pending migrations
manager.migrate()

# Run migrations up to specific version
manager.migrate(targetVersion=5)

# Rollback last migration
manager.rollback(steps=1)

# Get migration status
status = manager.getStatus()
print(f"Current version: {status['current_version']}")
print(f"Pending migrations: {status['pending_count']}")
```

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
✅ Created migration file: migration_003_add_user_preferences.py
   Class name: Migration003AddUserPreferences
   Version: 3

📝 Next steps, dood:
   1. Edit the migration file
   2. Implement up() and down() methods
   3. Register in __init__.py files
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
    from ...wrapper import DatabaseWrapper


class Migration014AddUserPreferences(BaseMigration):
    """Add user preferences table, dood!"""

    version = 14
    description = "Add user preferences table"

    def up(self, db: "DatabaseWrapper") -> None:
        """Create user_preferences table, dood!"""
        with db.getCursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id INTEGER NOT NULL,
                    preference_key TEXT NOT NULL,
                    preference_value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, preference_key)
                )
                """
            )
            
            # Add index for better performance
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id
                ON user_preferences(user_id)
                """
            )

    def down(self, db: "DatabaseWrapper") -> None:
        """Drop user_preferences table, dood!"""
        with db.getCursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS user_preferences")
```

### Step 4: Register Migration

Add to [`internal/database/migrations/__init__.py`](__init__.py:1):

```python
from .versions import migration_014_add_user_preferences

MIGRATIONS: List[Type[BaseMigration]] = [
    migration_001_initial_schema.Migration001InitialSchema,
    migration_002_add_is_spammer_to_chat_users.Migration002AddIsSpammerToChatUsers,
    migration_003_add_metadata_to_chat_users.Migration003AddMetadataToChatUsers,
    migration_004_add_cache_storage_table.Migration004AddCacheStorageTable,
    migration_005_add_yandex_cache.Migration005AddYandexCache,
    migration_006_new_cache_tables.Migration006NewCacheTables,
    migration_007_messages_metadata.Migration007MessagesMetadata,
    migration_008_add_media_group_support.Migration008AddMediaGroupSupport,
    migration_009_remove_is_spammer_from_chat_users.Migration009RemoveIsSpammerFromChatUsers,
    migration_010_add_updated_by_to_chat_settings.Migration010AddUpdatedByToChatSettings,
    migration_011_add_confidence_to_spam_messages.Migration011AddConfidenceToSpamMessages,
    migration_012_unify_cache_tables.Migration012UnifyCacheTables,
    migration_013_remove_timestamp_defaults.Migration013RemoveTimestampDefaults,
    migration_014_add_user_preferences.Migration014AddUserPreferences,  # Add here
]
```

Also update [`internal/database/migrations/versions/__init__.py`](versions/__init__.py:1):

```python
from . import migration_014_add_user_preferences

__all__ = [
    "migration_001_initial_schema",
    "migration_002_add_is_spammer_to_chat_users",
    "migration_003_add_metadata_to_chat_users",
    "migration_004_add_cache_storage_table",
    "migration_005_add_yandex_cache",
    "migration_006_new_cache_tables",
    "migration_007_messages_metadata",
    "migration_008_add_media_group_support",
    "migration_009_remove_is_spammer_from_chat_users",
    "migration_010_add_updated_by_to_chat_settings",
    "migration_011_add_confidence_to_spam_messages",
    "migration_012_unify_cache_tables",
    "migration_013_remove_timestamp_defaults",
    "migration_014_add_user_preferences",  # Add here
]
```

---

## Best Practices

### DO ✅

- **Use `IF NOT EXISTS`** for CREATE statements
- **Use `IF EXISTS`** for DROP statements
- **Test both `up()` and `down()` methods** before deployment
- **Keep migrations small and focused** on one change
- **Add comments** explaining complex changes
- **Use transactions** (automatic via [`getCursor()`](../wrapper.py:103))
- **Version sequentially** (no gaps in version numbers)

### DON'T ❌

- **Never modify existing migration files** after deployment
- **Don't skip version numbers** (must be sequential)
- **Don't make migrations dependent on application code**
- **Don't mix data migrations with schema changes** (separate them)
- **Don't use database-specific features** (stick to SQLite standard)

---

## Migration Patterns

### Adding a Table

```python
def up(self, db: "DatabaseWrapper") -> None:
    with db.getCursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS new_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

def down(self, db: "DatabaseWrapper") -> None:
    with db.getCursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS new_table")
```

### Adding a Column

```python
def up(self, db: "DatabaseWrapper") -> None:
    with db.getCursor() as cursor:
        # Check if column exists first
        cursor.execute("PRAGMA table_info(existing_table)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "new_column" not in columns:
            cursor.execute("""
                ALTER TABLE existing_table 
                ADD COLUMN new_column TEXT
            """)

def down(self, db: "DatabaseWrapper") -> None:
    # SQLite doesn't support DROP COLUMN easily
    # Document that this migration is not reversible
    pass
```

### Adding an Index

```python
def up(self, db: "DatabaseWrapper") -> None:
    with db.getCursor() as cursor:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_table_column
            ON table_name(column_name)
        """)

def down(self, db: "DatabaseWrapper") -> None:
    with db.getCursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS idx_table_column")
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

All tests create temporary databases and clean up automatically, dood!

---

## Version Tracking

### Storage

Migration versions are stored in the [`settings`](../wrapper.py:127) table:

- **Key:** `db_migration_version` - Current version (integer)
- **Key:** `db_migration_last_run` - ISO timestamp of last migration

### Checking Current Version

```python
version = db.getSetting("db_migration_version", "0")
print(f"Current migration version: {version}")
```

---

## Error Handling

### Automatic Rollback

If a migration fails, the transaction is automatically rolled back, dood!

```python
try:
    migration.up(db)
    self._setVersion(migration.version)
except Exception as e:
    # Transaction automatically rolled back by context manager
    logger.error(f"Migration {migration.version} failed: {e}")
    raise MigrationError(f"Failed to apply migration {migration.version}") from e
```

### Recovery

If a migration fails:

1. **Fix the migration code**
2. **Restart the application** - it will retry the failed migration
3. **Check logs** for detailed error information

---

## Troubleshooting

### Migration Not Running

**Problem:** New migration not executing

**Solution:**
1. Check migration is registered in [`__init__.py`](__init__.py:1)
2. Verify version number is sequential
3. Check current version: `db.getSetting("db_migration_version")`

### Duplicate Version Error

**Problem:** `MigrationError: Duplicate migration versions detected`

**Solution:**
1. Check all migration files have unique version numbers
2. Ensure no gaps in version sequence

### Import Error

**Problem:** `ImportError: cannot import name 'migration_XXX'`

**Solution:**
1. Verify file name matches import: `migration_XXX_description.py`
2. Check file is in `versions/` directory
3. Ensure `versions/__init__.py` imports the migration

---

## Future Enhancements

Potential features for future versions, dood!

1. **Migration Status Command** - CLI tool to check status
2. **Data Migrations** - Separate support for data transformations
3. **Dry-run Mode** - Preview migrations without applying
4. **Migration Generator** - Auto-generate migration templates
5. **Migration Locking** - Prevent concurrent migrations

---

## References

### Internal Documentation

- [`internal/database/wrapper.py`](../wrapper.py:77) - Database wrapper
- [`internal/database/manager.py`](../manager.py:14) - Database manager
- [`internal/database/models.py`](../models.py:1) - Database models

### Implementation Plan

- [`docs/plans/database-migrations-implementation-plan.md`](../../../docs/plans/database-migrations-implementation-plan.md:1) - Full implementation plan

### External Resources

- [SQLite Documentation](https://www.sqlite.org/docs.html)
- [Alembic Migrations](https://alembic.sqlalchemy.org/) - Reference implementation
- [Django Migrations](https://docs.djangoproject.com/en/stable/topics/migrations/) - Design patterns

---

**End of Documentation, dood!**