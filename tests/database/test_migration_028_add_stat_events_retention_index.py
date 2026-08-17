"""Tests for migration_028_add_stat_events_retention_index.

This migration adds an index on (processed, created_at) to support efficient
deletion of processed events older than the retention window.

The test verifies:
- Index exists after up().
- Index is gone after down().
- Idempotent re-run works (up() can be called multiple times).
"""

from internal.database import Database
from internal.database.manager import DatabaseManagerConfig
from internal.database.migrations import MigrationManager
from internal.database.migrations.versions.migration_028_add_stat_events_retention_index import (
    Migration028AddStatEventsRetentionIndex,
)
from internal.database.providers import BaseSQLProvider


async def _tableExists(provider: BaseSQLProvider, tableName: str) -> bool:
    """Check whether a table exists.

    Args:
        provider: SQL provider.
        tableName: Name of the table to check.

    Returns:
        True if the table exists, False otherwise.
    """
    row = await provider.executeFetchOne(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = :name",
        {"name": tableName},
    )
    return row is not None


async def _indexExists(provider: BaseSQLProvider, indexName: str) -> bool:
    """Check whether an index exists.

    Args:
        provider: SQL provider.
        indexName: Name of the index to check.

    Returns:
        True if the index exists, False otherwise.
    """
    row = await provider.executeFetchOne(
        "SELECT name FROM sqlite_master WHERE type='index' AND name = :name",
        {"name": indexName},
    )
    return row is not None


async def _rollbackToPre028(provider: BaseSQLProvider) -> None:
    """Roll back to version 27 to reach the pre-028 state.

    Args:
        provider: Writable SQL provider.

    Returns:
        None
    """
    rollbackManager = MigrationManager()
    rollbackManager.loadMigrationsFromVersions()
    await rollbackManager.rollbackTo(targetVersion=27, sqlProvider=provider)


async def testMigration028UpCreatesIndex() -> None:
    """Verify that up() creates the retention index.

    Returns:
        None
    """
    # Create a test Database instance with in-memory SQLite
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            }
        },
    }
    db = Database(config)

    try:
        provider = await db.manager.getProvider(dataSource="default", readonly=False)

        # First, roll back to pre-028 state (ensure stat_events table exists)
        await _rollbackToPre028(provider)

        # Verify stat_events table exists (from migration 016)
        assert await _tableExists(provider, "stat_events")

        # Verify the index does NOT exist before up()
        assert not await _indexExists(provider, "idx_stat_events_retention")

        # Run the migration
        migration = Migration028AddStatEventsRetentionIndex()
        await migration.up(provider)

        # Verify the index now exists
        assert await _indexExists(provider, "idx_stat_events_retention")

    finally:
        await db.manager.closeAll()


async def testMigration028DownDropsIndex() -> None:
    """Verify that down() drops the retention index.

    Returns:
        None
    """
    # Create a test Database instance with in-memory SQLite
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            }
        },
    }
    db = Database(config)

    try:
        provider = await db.manager.getProvider(dataSource="default", readonly=False)

        # Roll back to pre-028 state
        await _rollbackToPre028(provider)

        # Run up() to create the index
        migration = Migration028AddStatEventsRetentionIndex()
        await migration.up(provider)

        # Verify the index exists
        assert await _indexExists(provider, "idx_stat_events_retention")

        # Run down() to drop the index
        await migration.down(provider)

        # Verify the index is gone
        assert not await _indexExists(provider, "idx_stat_events_retention")

    finally:
        await db.manager.closeAll()


async def testMigration028IdempotentUp() -> None:
    """Verify that up() is idempotent (can be called multiple times).

    Returns:
        None
    """
    # Create a test Database instance with in-memory SQLite
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            }
        },
    }
    db = Database(config)

    try:
        provider = await db.manager.getProvider(dataSource="default", readonly=False)

        # Roll back to pre-028 state
        await _rollbackToPre028(provider)

        # Run up() once
        migration = Migration028AddStatEventsRetentionIndex()
        await migration.up(provider)

        # Run up() again (should not raise)
        await migration.up(provider)

        # Run up() a third time (should not raise)
        await migration.up(provider)

        # Verify the index exists
        assert await _indexExists(provider, "idx_stat_events_retention")

    finally:
        await db.manager.closeAll()


async def testMigration028IdempotentDown() -> None:
    """Verify that down() is idempotent (can be called multiple times).

    Returns:
        None
    """
    # Create a test Database instance with in-memory SQLite
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            }
        },
    }
    db = Database(config)

    try:
        provider = await db.manager.getProvider(dataSource="default", readonly=False)

        # Roll back to pre-028 state
        await _rollbackToPre028(provider)

        # Run up() to create the index
        migration = Migration028AddStatEventsRetentionIndex()
        await migration.up(provider)

        # Run down() once
        await migration.down(provider)

        # Run down() again (should not raise)
        await migration.down(provider)

        # Run down() a third time (should not raise)
        await migration.down(provider)

        # Verify the index is gone
        assert not await _indexExists(provider, "idx_stat_events_retention")

    finally:
        await db.manager.closeAll()


async def testMigration028UpAndDownRoundtrip() -> None:
    """Verify that up() followed by down() restores the pre-migration state.

    Returns:
        None
    """
    # Create a test Database instance with in-memory SQLite
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            }
        },
    }
    db = Database(config)

    try:
        provider = await db.manager.getProvider(dataSource="default", readonly=False)

        # Roll back to pre-028 state
        await _rollbackToPre028(provider)

        # Verify initial state
        assert not await _indexExists(provider, "idx_stat_events_retention")

        # Run up()
        migration = Migration028AddStatEventsRetentionIndex()
        await migration.up(provider)

        # Verify index exists
        assert await _indexExists(provider, "idx_stat_events_retention")

        # Run down()
        await migration.down(provider)

        # Verify we're back to initial state
        assert not await _indexExists(provider, "idx_stat_events_retention")

    finally:
        await db.manager.closeAll()
