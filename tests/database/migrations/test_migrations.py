#!/usr/bin/env python3
"""
Test suite for database migrations functionality.

This module provides comprehensive tests for the Gromozeka database migration system,
including fresh database initialization, migration execution, version tracking, rollback
functionality, auto-discovery of migrations, and migration status reporting.

Key Test Functions:
    - test_fresh_database: Tests initialization of a new database with all migrations
    - test_migration_status: Verifies migration status reporting functionality
    - test_rollback: Tests migration rollback to previous versions
    - test_rollbackTo_landsAtExactVersion: Tests target-version rollback (rollbackTo)
    - test_rollbackTo_edges: Tests rollbackTo no-op / validation behaviour
    - test_existing_database: Tests upgrading an existing database
    - test_auto_discovery: Verifies automatic migration discovery
    - test_getMigration_functions: Tests getMigration() functions in migration modules
    - test_loadMigrationsFromVersions: Tests MigrationManager.loadMigrationsFromVersions()
    - test_database_auto_discovery: Tests Database class auto-discovery integration

Usage:
    Run this script directly to execute all migration tests:
        ./venv/bin/pytest tests/database/migrations/test_migrations.py

    Or import and run specific test functions:
        from tests.database.migrations.test_migrations import test_fresh_database
        await test_fresh_database()

Note:
    All tests use temporary SQLite databases that are automatically cleaned up after
    each test. Tests are designed to be independent and can be run in any order.
"""

import logging
import os
import tempfile

import pytest

from internal.database import Database
from internal.database.manager import DatabaseManagerConfig
from internal.database.migrations import MigrationError, MigrationManager
from internal.database.migrations.versions import DISCOVERED_MIGRATIONS

# Use DISCOVERED_MIGRATIONS as MIGRATIONS for backward compatibility
MIGRATIONS = DISCOVERED_MIGRATIONS

# Setup logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def test_fresh_database() -> None:
    """Test fresh database initialization.

    Creates a temporary database, initializes it with migrations,
    and verifies that all expected tables and the correct migration
    version are present.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If migration version doesn't match expected version
        AssertionError: If expected tables are not found in the database
        Exception: If database initialization or migration execution fails
    """
    logger.info("=" * 60)
    logger.info("TEST: Fresh Database Initialization")
    logger.info("=" * 60)

    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath: str = f.name

    db: Database | None = None
    try:
        # Initialize database (should run migrations automatically)
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": dbPath,
                    },
                }
            },
        }
        db = Database(config)

        # Check migration version
        provider = await db.manager.getProvider()
        manager = MigrationManager()
        manager.registerMigrations(MIGRATIONS)
        currentVersion: int = await manager.getCurrentVersion(sqlProvider=provider)

        logger.info(f"Current migration version: {currentVersion}")
        logger.info(f"Expected version: {len(MIGRATIONS)}")

        assert currentVersion == len(MIGRATIONS), f"Expected version {len(MIGRATIONS)}, got {currentVersion}"

        # Check that tables exist
        provider = await db.manager.getProvider()
        tables = await provider.executeFetchAll("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tableNames: list[str] = [row["name"] for row in tables]
        logger.info(f"Created tables: {', '.join(tableNames)}")

        # Verify key tables exist
        expectedTables = [
            "settings",
            "chat_messages",
            "chat_users",
            "chat_info",
            "models",
        ]

        for table in expectedTables:
            assert table in tableNames, f"Table {table} not found"

        logger.info("✅ Fresh database test PASSED")

    finally:
        # Cleanup
        if db is not None:
            await db.manager.closeAll()
        if os.path.exists(dbPath):
            os.unlink(dbPath)


async def test_migration_status() -> None:
    """Test migration status reporting.

    Creates a temporary database, initializes it with migrations,
    and verifies that the migration status correctly reports the
    current version, latest version, and pending migrations.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If current version doesn't equal latest version
        AssertionError: If pending migrations count is not zero
        Exception: If database initialization or status retrieval fails
    """
    logger.info("=" * 60)
    logger.info("TEST: Migration Status")
    logger.info("=" * 60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath: str = f.name

    db: Database | None = None
    try:
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": dbPath,
                    },
                }
            },
        }
        db = Database(config)
        provider = await db.manager.getProvider()
        manager = MigrationManager()
        manager.registerMigrations(MIGRATIONS)

        status = await manager.getStatus(sqlProvider=provider)
        logger.info(f"Migration status: {status}")

        assert status["current_version"] == status["latest_version"], "Current version should equal latest version"
        assert status["pending_count"] == 0, "Should have no pending migrations"

        logger.info("✅ Migration status test PASSED")

    finally:
        if db is not None:
            await db.manager.closeAll()
        if os.path.exists(dbPath):
            os.unlink(dbPath)


async def test_rollback() -> None:
    """Test migration rollback functionality.

    Creates a temporary database, initializes it with migrations,
    rolls back to a specific version, and verifies that the
    rollback correctly removes schema changes (e.g., the metadata
    column from migration 003).

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If rollback version doesn't match target version
        AssertionError: If metadata column still exists after rollback
        Exception: If database initialization or rollback execution fails
    """
    logger.info("=" * 60)
    logger.info("TEST: Migration Rollback")
    logger.info("=" * 60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath: str = f.name

    db: Database | None = None
    try:
        # Initialize database
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": dbPath,
                    },
                }
            },
        }
        db = Database(config)
        provider = await db.manager.getProvider()
        manager = MigrationManager()
        manager.registerMigrations(MIGRATIONS)

        initialVersion: int = await manager.getCurrentVersion(sqlProvider=provider)
        logger.info(f"Initial version: {initialVersion}")

        # Rollback to version 2 (to remove metadata column from migration 003)
        # This ensures the test works regardless of how many migrations exist
        targetVersion: int = 2
        stepsToRollback: int = initialVersion - targetVersion
        logger.info(f"Rolling back {stepsToRollback} migrations to reach version {targetVersion}")

        await manager.rollback(steps=stepsToRollback, sqlProvider=provider)

        newVersion: int = await manager.getCurrentVersion(sqlProvider=provider)
        logger.info(f"Version after rollback: {newVersion}")

        assert newVersion == targetVersion, f"Expected version {targetVersion}, got {newVersion}"

        # Check that metadata column is gone (migration 003 should be rolled back)
        provider = await db.manager.getProvider(readonly=True)
        rows = await provider.executeFetchAll("PRAGMA table_info(chat_users)")
        columns: list[str] = [row["name"] for row in rows]  # type: ignore[index]
        assert "metadata" not in columns, "metadata column should be dropped"

        logger.info("✅ Rollback test PASSED")

    finally:
        if db is not None:
            await db.manager.closeAll()
        if os.path.exists(dbPath):
            os.unlink(dbPath)


async def test_rollbackTo_landsAtExactVersion() -> None:
    """``rollbackTo(targetVersion=N)`` lands the database at exactly version N.

    This is the target-version counterpart to ``rollback(steps=...)`` and the
    contract every per-migration test helper (``_rollbackToPreNNN``) relies on.
    The point of targeting a version rather than a step count is that the
    result is independent of how many migrations exist above ``N`` — adding a
    new migration on top must not shift the landing version. This test pins
    that property so the recurring "stale ``steps=N`` broke when migration
    M+1 landed" failure mode cannot recur for ``rollbackTo``.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If the version after rollback is not the target, if
            the schema does not reflect the rolled-back migration, or if the
            landing version depends on the number of migrations above target.
        Exception: If database initialisation or rollback execution fails.
    """
    logger.info("=" * 60)
    logger.info("TEST: rollbackTo lands at exact target version")
    logger.info("=" * 60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath: str = f.name

    db: Database | None = None
    try:
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": dbPath,
                    },
                }
            },
        }
        db = Database(config)
        provider = await db.manager.getProvider()
        manager = MigrationManager()
        manager.registerMigrations(MIGRATIONS)

        latestVersion: int = manager.getAvailableMigrations()[-1].version
        logger.info(f"Latest version: {latestVersion}")

        # Pick a low, stable target well below the latest version. The exact
        # number is irrelevant; what matters is that the landing version
        # equals the target regardless of how many migrations sit above it.
        targetVersion: int = 3
        assert latestVersion > targetVersion, "test requires migrations above the target"

        await manager.rollbackTo(targetVersion=targetVersion, sqlProvider=provider)

        newVersion: int = await manager.getCurrentVersion(sqlProvider=provider)
        logger.info(f"Version after rollbackTo({targetVersion}): {newVersion}")
        assert newVersion == targetVersion, f"Expected version {targetVersion}, got {newVersion}"

        # Migration 003 adds the ``metadata`` column to ``chat_users``; its
        # ``down()`` removes it. Reaching version 3 means 003 ran (metadata
        # present) but nothing above it did. Probing the column confirms the
        # schema genuinely reflects the target, not merely the version counter.
        provider = await db.manager.getProvider(readonly=True)
        rows = await provider.executeFetchAll("PRAGMA table_info(chat_users)")
        columns: list[str] = [row["name"] for row in rows]  # type: ignore[index]
        assert "metadata" in columns, "metadata column (added by migration 003) must be present at version 3"

        logger.info("✅ rollbackTo target-version test PASSED")

    finally:
        if db is not None:
            await db.manager.closeAll()
        if os.path.exists(dbPath):
            os.unlink(dbPath)


async def test_rollbackTo_edges() -> None:
    """``rollbackTo`` no-ops above the current version and rejects negatives.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If a target >= current version changes the version,
            or if a negative target does not raise ``MigrationError``.
        Exception: If database initialisation or rollback execution fails.
    """
    logger.info("=" * 60)
    logger.info("TEST: rollbackTo edge cases (no-op + validation)")
    logger.info("=" * 60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath: str = f.name

    db: Database | None = None
    try:
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": dbPath,
                    },
                }
            },
        }
        db = Database(config)
        provider = await db.manager.getProvider()
        manager = MigrationManager()
        manager.registerMigrations(MIGRATIONS)

        latestVersion: int = manager.getAvailableMigrations()[-1].version

        # Targeting the current version is a no-op: version unchanged.
        await manager.rollbackTo(targetVersion=latestVersion, sqlProvider=provider)
        assert (
            await manager.getCurrentVersion(sqlProvider=provider) == latestVersion
        ), "rollbackTo to the current version must be a no-op"

        # Targeting above the current version is also a no-op (no raise).
        await manager.rollbackTo(targetVersion=latestVersion + 5, sqlProvider=provider)
        assert (
            await manager.getCurrentVersion(sqlProvider=provider) == latestVersion
        ), "rollbackTo above the current version must be a no-op"

        # Rolling all the way down to 0 lands at version 0.
        await manager.rollbackTo(targetVersion=0, sqlProvider=provider)
        assert await manager.getCurrentVersion(sqlProvider=provider) == 0, "rollbackTo(0) must reach version 0"

        # Negative targets are rejected.
        with pytest.raises(MigrationError):
            await manager.rollbackTo(targetVersion=-1, sqlProvider=provider)

        # Negative steps are rejected.
        with pytest.raises(MigrationError):
            await manager.rollback(steps=-1, sqlProvider=provider)

        logger.info("✅ rollbackTo edge-case test PASSED")

    finally:
        if db is not None:
            await db.manager.closeAll()
        if os.path.exists(dbPath):
            os.unlink(dbPath)


async def test_existing_database() -> None:
    """Test upgrading existing database.

    Creates a temporary database and verifies that migrations
    run automatically during initialization, bringing the database
    to the latest version.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If current version doesn't match expected version
        Exception: If database initialization or migration execution fails
    """
    logger.info("=" * 60)
    logger.info("TEST: Existing Database Upgrade")
    logger.info("=" * 60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath: str = f.name

    db: Database | None = None
    try:
        # Create database - __init__ now automatically runs migrations
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": dbPath,
                    },
                }
            },
        }
        db = Database(config)
        provider = await db.manager.getProvider()

        # Verify migrations were run automatically by __init__
        manager = MigrationManager()
        manager.registerMigrations(MIGRATIONS)

        currentVersion: int = await manager.getCurrentVersion(sqlProvider=provider)
        logger.info(f"Current version after init: {currentVersion}")

        # With new multi-source architecture, migrations run automatically in __init__
        assert currentVersion == len(
            MIGRATIONS
        ), f"Expected version {len(MIGRATIONS)} (auto-migrated), got {currentVersion}"

        logger.info("✅ Existing database upgrade test PASSED")

    finally:
        if db is not None:
            await db.manager.closeAll()
        if os.path.exists(dbPath):
            os.unlink(dbPath)


async def test_auto_discovery() -> None:
    """Test migration auto-discovery functionality.

    Verifies that DISCOVERED_MIGRATIONS is properly populated,
    matches the manual migrations list, and that all migration
    versions and descriptions are correct.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If DISCOVERED_MIGRATIONS is empty
        AssertionError: If discovered migrations count doesn't match manual count
        AssertionError: If discovered versions don't match manual versions
        AssertionError: If migration descriptions don't match
    """
    logger.info("=" * 60)
    logger.info("TEST: Migration Auto-Discovery")
    logger.info("=" * 60)

    # Test that DISCOVERED_MIGRATIONS is populated
    assert len(DISCOVERED_MIGRATIONS) > 0, "DISCOVERED_MIGRATIONS should not be empty"
    logger.info(f"Found {len(DISCOVERED_MIGRATIONS)} discovered migrations")

    # Test that discovered migrations match manual migrations
    assert len(DISCOVERED_MIGRATIONS) == len(
        MIGRATIONS
    ), f"Discovered {len(DISCOVERED_MIGRATIONS)} migrations, expected {len(MIGRATIONS)}"

    # Test that versions are correct
    discoveredVersions: list[int] = [m.version for m in DISCOVERED_MIGRATIONS]
    manualVersions: list[int] = [m.version for m in MIGRATIONS]
    assert (
        discoveredVersions == manualVersions
    ), f"Discovered versions {discoveredVersions} don't match manual {manualVersions}"

    # Test that descriptions match
    for discovered, manual in zip(DISCOVERED_MIGRATIONS, MIGRATIONS):
        assert (
            discovered.description == manual.description
        ), f"Description mismatch: {discovered.description} vs {manual.description}"

    logger.info("✅ Auto-discovery test PASSED")


async def test_getMigration_functions() -> None:
    """Test that all migration files have getMigration() functions.

    Verifies that each migration module has a getMigration() function
    that returns the correct migration class with the proper version
    number.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If migration module is missing getMigration() function
        AssertionError: If getMigration() returns wrong class name
        AssertionError: If returned class has incorrect version number
        ImportError: If migration module cannot be imported
    """
    logger.info("=" * 60)
    logger.info("TEST: getMigration() Functions")
    logger.info("=" * 60)

    # Known migration modules and their classes
    expectedModules: dict[int, tuple[str, str]] = {
        1: ("migration_001_initial_schema", "Migration001InitialSchema"),
        2: ("migration_002_add_is_spammer_to_chat_users", "Migration002AddIsSpammerToChatUsers"),
        3: ("migration_003_add_metadata_to_chat_users", "Migration003AddMetadataToChatUsers"),
    }

    # Test each expected migration module
    for version, (moduleName, expectedClassName) in expectedModules.items():
        # Import the module
        module = __import__(f"internal.database.migrations.versions.{moduleName}", fromlist=[moduleName])

        # Check getMigration function exists
        assert hasattr(module, "getMigration"), f"Module {moduleName} missing getMigration() function"

        # Test that getMigration() returns the correct class
        returnedClass: type = module.getMigration()
        assert (
            returnedClass.__name__ == expectedClassName
        ), f"getMigration() in {moduleName} returned {returnedClass.__name__}, expected {expectedClassName}"

        # Test that the returned class has the correct version
        assert (
            returnedClass.version == version
        ), f"getMigration() in {moduleName} returned class with version {returnedClass.version}, expected {version}"

        logger.debug(f"✅ {moduleName}.getMigration() works correctly")

    logger.info("✅ getMigration() functions test PASSED")


async def test_loadMigrationsFromVersions() -> None:
    """Test MigrationManager.loadMigrationsFromVersions() method.

    Creates a temporary database, uses the MigrationManager to load
    migrations from the versions directory, and verifies that all
    migrations are loaded correctly with matching versions.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If no migrations are loaded
        AssertionError: If loaded migrations count doesn't match discovered count
        AssertionError: If loaded versions don't match discovered versions
        Exception: If database initialization or migration loading fails
    """
    logger.info("=" * 60)
    logger.info("TEST: loadMigrationsFromVersions() Method")
    logger.info("=" * 60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath: str = f.name

    db: Database | None = None
    try:
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": dbPath,
                    },
                }
            },
        }
        db = Database(config)
        manager = MigrationManager()

        # Test loadMigrationsFromVersions()
        manager.loadMigrationsFromVersions()

        # Check that migrations were loaded
        assert len(manager.migrations) > 0, "No migrations loaded"
        assert len(manager.migrations) == len(
            DISCOVERED_MIGRATIONS
        ), f"Loaded {len(manager.migrations)} migrations, expected {len(DISCOVERED_MIGRATIONS)}"

        # Check that versions are correct
        loadedVersions: list[int] = [m.version for m in manager.migrations]
        discoveredVersions: list[int] = [m.version for m in DISCOVERED_MIGRATIONS]
        assert (
            loadedVersions == discoveredVersions
        ), f"Loaded versions {loadedVersions} don't match discovered {discoveredVersions}"

        logger.info("✅ loadMigrationsFromVersions() test PASSED")

    finally:
        if db is not None:
            await db.manager.closeAll()
        if os.path.exists(dbPath):
            os.unlink(dbPath)


async def test_database_auto_discovery() -> None:
    """Test that Database uses auto-discovery.

    Creates a temporary database, initializes it, and verifies that
    the Database class uses auto-discovery to load and apply all
    migrations correctly.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If current version doesn't match expected version
        AssertionError: If expected tables are not found in the database
        Exception: If database initialization or migration execution fails
    """
    logger.info("=" * 60)
    logger.info("TEST: Database Auto-Discovery")
    logger.info("=" * 60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath: str = f.name

    db: Database | None = None
    try:
        # Initialize database (should use auto-discovery)
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": dbPath,
                    },
                }
            },
        }
        db = Database(config)
        provider = await db.manager.getProvider()

        # Check that all migrations were applied
        manager = MigrationManager()
        currentVersion: int = await manager.getCurrentVersion(sqlProvider=provider)

        assert currentVersion == len(
            DISCOVERED_MIGRATIONS
        ), f"Expected version {len(DISCOVERED_MIGRATIONS)}, got {currentVersion}"

        # Check that tables exist
        tables = await provider.executeFetchAll("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tableNames: list[str] = [row["name"] for row in tables]
        logger.info(f"Created tables: {', '.join(tableNames)}")

        # Verify key tables exist
        expectedTables = [
            "settings",
            "chat_messages",
            "chat_users",
            "chat_info",
            "models",
        ]

        for table in expectedTables:
            assert table in tableNames, f"Table {table} not found"

        logger.info("✅ Database auto-discovery test PASSED")

    finally:
        if db is not None:
            await db.manager.closeAll()
        if os.path.exists(dbPath):
            os.unlink(dbPath)


async def test_migration_026_chat_accessibility_bot_status() -> None:
    """Test migration 026: bot_status column and index on chat_info.

    Creates a temporary database, applies migration 026, and verifies that:
    - The bot_status column exists with correct type and default
    - The idx_chat_info_bot_status index exists
    - Existing rows are backfilled to 'active'
    - The down() method correctly removes column and index

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If bot_status column doesn't exist or has wrong properties
        AssertionError: If index doesn't exist
        AssertionError: If default value is incorrect
        AssertionError: If rollback doesn't remove column/index
        Exception: If database initialization or migration execution fails
    """
    logger.info("=" * 60)
    logger.info("TEST: Migration 026 - Chat Accessibility Bot Status")
    logger.info("=" * 60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath: str = f.name

    db: Database | None = None
    try:
        # Initialize database (should apply all migrations including 026)
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": dbPath,
                    },
                }
            },
        }
        db = Database(config)
        provider = await db.manager.getProvider()

        # Get migration 026 from discovered migrations
        migration_026 = None
        for migration in DISCOVERED_MIGRATIONS:
            if migration.version == 26:
                migration_026 = migration
                break

        assert migration_026 is not None, "Migration 026 not found"

        # Check that bot_status column exists
        columns = await provider.executeFetchAll("PRAGMA table_info(chat_info)")
        columnNames: list[str] = [row["name"] for row in columns]  # type: ignore[index]
        assert "bot_status" in columnNames, "bot_status column should exist"

        # Check column properties
        botStatusColumn = None
        for col in columns:
            if col["name"] == "bot_status":  # type: ignore[index]
                botStatusColumn = col
                break

        assert botStatusColumn is not None, "bot_status column not found in table_info"
        assert (
            botStatusColumn["type"] == "TEXT"
        ), f"bot_status type should be TEXT, got {botStatusColumn['type']}"  # type: ignore[index]
        assert botStatusColumn["notnull"] == 1, "bot_status should be NOT NULL"  # type: ignore[index]
        assert (
            botStatusColumn["dflt_value"] == "'active'"
        ), f"bot_status default should be 'active', got {botStatusColumn['dflt_value']}"  # type: ignore[index]

        logger.info("✅ bot_status column exists with correct properties")

        # Check that index exists
        indexes = await provider.executeFetchAll(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_chat_info_bot_status'"
        )
        assert len(indexes) == 1, "idx_chat_info_bot_status index should exist"
        logger.info("✅ idx_chat_info_bot_status index exists")

        # Test default value on a new row
        await provider.execute(
            "INSERT INTO chat_info (chat_id, title, username, type, is_forum, "
            "created_at, updated_at) VALUES (99999, 'Test Chat', 'testchat', 'group', "
            "0, datetime('now'), datetime('now'))"
        )
        rows = await provider.executeFetchOne("SELECT bot_status FROM chat_info WHERE chat_id = 99999")
        assert rows is not None, "Inserted row should exist"
        assert (
            rows["bot_status"] == "active"
        ), f"New row should have bot_status='active', got {rows['bot_status']}"  # type: ignore[index]
        logger.info("✅ Default value 'active' is applied to new rows")

        # Test rollback (down())
        migrationInstance = migration_026()
        await migrationInstance.down(sqlProvider=provider)

        # Check that index is dropped
        indexes = await provider.executeFetchAll(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_chat_info_bot_status'"
        )
        assert len(indexes) == 0, "idx_chat_info_bot_status index should be dropped"

        # Check that column is dropped
        columns = await provider.executeFetchAll("PRAGMA table_info(chat_info)")
        columnNames = [row["name"] for row in columns]  # type: ignore[index]
        assert "bot_status" not in columnNames, "bot_status column should be dropped"

        logger.info("✅ Rollback (down()) correctly removes index and column")
        logger.info("✅ Migration 026 test PASSED")

    finally:
        if db is not None:
            await db.manager.closeAll()
        if os.path.exists(dbPath):
            os.unlink(dbPath)
