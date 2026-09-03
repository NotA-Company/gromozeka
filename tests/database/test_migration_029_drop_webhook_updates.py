"""Tests for migration_029_drop_webhook_updates.

This migration drops the webhook_updates table and its index from the main bot
database as part of extracting the Max webhook receiver into its own standalone
process with its own database file.

The test verifies:
- Table and index are gone after up() (migrate to latest).
- Table and index are present after rollbackTo(targetVersion=28).
- Forward migration again drops them.
- Idempotent re-run works (up() can be called multiple times).
- Down() recreates via canonical DDL from lib.max_webhook_receiver.schema.
"""

import pytest

from internal.database import Database
from internal.database.migrations import MigrationManager
from internal.database.migrations.versions.migration_029_drop_webhook_updates import (
    Migration029DropWebhookUpdates,
)
from lib.db.manager import DatabaseManagerConfig
from lib.db.providers import BaseSQLProvider


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


async def _rollbackToPre029(provider: BaseSQLProvider) -> None:
    """Roll back to version 28 to reach the pre-029 state.

    Args:
        provider: Writable SQL provider.

    Returns:
        None
    """
    rollbackManager = MigrationManager()
    rollbackManager.loadMigrationsFromVersions()
    await rollbackManager.rollbackTo(targetVersion=28, sqlProvider=provider)


@pytest.fixture
async def migrationTestDatabase():
    """Create a test Database instance with in-memory SQLite for migration testing.

    Provides a fresh database and writable provider for each test. Ensures proper
    cleanup via try/finally. Each test gets isolated state, critical for idempotency
    tests that mutate table/index state.

    Yields:
        Tuple[Database, BaseSQLProvider]: Database instance and writable provider
    """
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
        yield db, provider
    finally:
        await db.manager.closeAll()


async def testMigration029UpDropsTableAndIndex(migrationTestDatabase) -> None:
    """Verify that up() drops the webhook_updates table and index.

    After migrating to latest (which includes migration_029), both the table
    and its index should be gone from the bot's database.

    Args:
        migrationTestDatabase: Fixture providing db and provider

    Returns:
        None
    """
    db, provider = migrationTestDatabase

    # Migrate to latest (includes migration_029)
    migrateManager = MigrationManager()
    migrateManager.loadMigrationsFromVersions()
    await migrateManager.migrate(sqlProvider=provider)

    # Verify both table and index are gone
    assert not await _tableExists(
        provider, "webhook_updates"
    ), "webhook_updates table should be gone after migration_029.up()"
    assert not await _indexExists(
        provider, "idx_webhook_updates_unprocessed"
    ), "idx_webhook_updates_unprocessed index should be gone after migration_029.up()"


async def testMigration029RollbackTo28RecreatesTableAndIndex(migrationTestDatabase) -> None:
    """Verify that rollbackTo(28) recreates the table and index.

    After rolling back to version 28, only migration_029.down() runs
    (rollbackTo(targetVersion=28) executes exactly one down migration),
    which recreates both table and index via the canonical DDL from
    lib.max_webhook_receiver.schema.

    Args:
        migrationTestDatabase: Fixture providing db and provider

    Returns:
        None
    """
    db, provider = migrationTestDatabase

    # Migrate to latest first
    migrateManager = MigrationManager()
    migrateManager.loadMigrationsFromVersions()
    await migrateManager.migrate(sqlProvider=provider)

    # Verify table and index are gone
    assert not await _tableExists(provider, "webhook_updates")
    assert not await _indexExists(provider, "idx_webhook_updates_unprocessed")

    # Roll back to version 28
    await _rollbackToPre029(provider)

    # Verify table and index are present again
    assert await _tableExists(
        provider, "webhook_updates"
    ), "webhook_updates table should be present after rollback to version 28"
    assert await _indexExists(
        provider, "idx_webhook_updates_unprocessed"
    ), "idx_webhook_updates_unprocessed index should be present after rollback to version 28"


async def testMigration029UpAndDownRoundtrip(migrationTestDatabase) -> None:
    """Verify that up() followed by down() restores the pre-migration state.

    This tests the round-trip: start with table+index present, run up() to
    drop them, run down() to recreate them, verify we're back to the start.

    Args:
        migrationTestDatabase: Fixture providing db and provider

    Returns:
        None
    """
    db, provider = migrationTestDatabase

    # Roll back to pre-029 state (table and index exist via migration_019)
    await _rollbackToPre029(provider)

    # Verify initial state: table and index present
    assert await _tableExists(
        provider, "webhook_updates"
    ), "webhook_updates table should be present before migration_029.up()"
    assert await _indexExists(
        provider, "idx_webhook_updates_unprocessed"
    ), "idx_webhook_updates_unprocessed index should be present before migration_029.up()"

    # Run up() to drop them
    migration = Migration029DropWebhookUpdates()
    await migration.up(provider)

    # Verify table and index are gone
    assert not await _tableExists(provider, "webhook_updates")
    assert not await _indexExists(provider, "idx_webhook_updates_unprocessed")

    # Run down() to recreate them
    await migration.down(provider)

    # Verify we're back to initial state
    assert await _tableExists(
        provider, "webhook_updates"
    ), "webhook_updates table should be present after migration_029.down()"
    assert await _indexExists(
        provider, "idx_webhook_updates_unprocessed"
    ), "idx_webhook_updates_unprocessed index should be present after migration_029.down()"


async def testMigration029IdempotentUp(migrationTestDatabase) -> None:
    """Verify that up() is idempotent (can be called multiple times).

    Args:
        migrationTestDatabase: Fixture providing db and provider

    Returns:
        None
    """
    db, provider = migrationTestDatabase

    # Roll back to pre-029 state
    await _rollbackToPre029(provider)

    # Run up() once
    migration = Migration029DropWebhookUpdates()
    await migration.up(provider)

    # Run up() again (should not raise)
    await migration.up(provider)

    # Run up() a third time (should not raise)
    await migration.up(provider)

    # Verify table and index are still gone
    assert not await _tableExists(provider, "webhook_updates")
    assert not await _indexExists(provider, "idx_webhook_updates_unprocessed")


async def testMigration029IdempotentDown(migrationTestDatabase) -> None:
    """Verify that down() is idempotent (can be called multiple times).

    Args:
        migrationTestDatabase: Fixture providing db and provider

    Returns:
        None
    """
    db, provider = migrationTestDatabase

    # Roll back to pre-029 state
    await _rollbackToPre029(provider)

    # Run up() to drop table and index
    migration = Migration029DropWebhookUpdates()
    await migration.up(provider)

    # Run down() once to recreate
    await migration.down(provider)

    # Run down() again (should not raise - IF NOT EXISTS DDL)
    await migration.down(provider)

    # Run down() a third time (should not raise)
    await migration.down(provider)

    # Verify table and index are still present
    assert await _tableExists(provider, "webhook_updates")
    assert await _indexExists(provider, "idx_webhook_updates_unprocessed")


async def testMigration029ForwardMigrationAfterRollback(migrationTestDatabase) -> None:
    """Verify forward migration works after rollback to 28.

    This tests the complete cycle: migrate to latest (drops table/index),
    rollback to 28 (recreates them), migrate to latest again (drops them again).

    Args:
        migrationTestDatabase: Fixture providing db and provider

    Returns:
        None
    """
    db, provider = migrationTestDatabase

    # Migrate to latest first
    migrateManager = MigrationManager()
    migrateManager.loadMigrationsFromVersions()
    await migrateManager.migrate(sqlProvider=provider)

    # Verify table and index are gone
    assert not await _tableExists(provider, "webhook_updates")
    assert not await _indexExists(provider, "idx_webhook_updates_unprocessed")

    # Roll back to version 28
    await _rollbackToPre029(provider)

    # Verify table and index are present
    assert await _tableExists(provider, "webhook_updates")
    assert await _indexExists(provider, "idx_webhook_updates_unprocessed")

    # Migrate to latest again
    await migrateManager.migrate(sqlProvider=provider)

    # Verify table and index are gone again
    assert not await _tableExists(
        provider, "webhook_updates"
    ), "webhook_updates table should be gone after forward migration"
    assert not await _indexExists(
        provider, "idx_webhook_updates_unprocessed"
    ), "idx_webhook_updates_unprocessed index should be gone after forward migration"
