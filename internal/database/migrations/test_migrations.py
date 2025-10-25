#!/usr/bin/env python3
"""
Test script for database migrations, dood!

This script tests:
- Fresh database initialization
- Migration execution
- Version tracking
- Rollback functionality
"""

import os
import sys
import tempfile
import logging

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from internal.database.wrapper import DatabaseWrapper
from internal.database.migrations import MigrationManager
from internal.database.migrations.versions import DISCOVERED_MIGRATIONS, discoverMigrations

# Use DISCOVERED_MIGRATIONS as MIGRATIONS for backward compatibility
MIGRATIONS = DISCOVERED_MIGRATIONS

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_fresh_database():
    """Test fresh database initialization, dood!"""
    logger.info("=" * 60)
    logger.info("TEST: Fresh Database Initialization")
    logger.info("=" * 60)
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath = f.name
    
    try:
        # Initialize database (should run migrations automatically)
        db = DatabaseWrapper(dbPath)
        
        # Check migration version
        manager = MigrationManager(db)
        manager.registerMigrations(MIGRATIONS)
        currentVersion = manager.getCurrentVersion()
        
        logger.info(f"Current migration version: {currentVersion}")
        logger.info(f"Expected version: {len(MIGRATIONS)}")
        
        assert currentVersion == len(MIGRATIONS), \
            f"Expected version {len(MIGRATIONS)}, got {currentVersion}"
        
        # Check that tables exist
        with db.getCursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cursor.fetchall()]
            logger.info(f"Created tables: {', '.join(tables)}")
            
            # Verify key tables exist
            expectedTables = [
                "settings",
                "chat_messages",
                "chat_users",
                "chat_info",
            ]
            
            for table in expectedTables:
                assert table in tables, f"Table {table} not found"
        
        logger.info("✅ Fresh database test PASSED, dood!")
        return True
        
    finally:
        # Cleanup
        if os.path.exists(dbPath):
            os.unlink(dbPath)


def test_migration_status():
    """Test migration status reporting, dood!"""
    logger.info("=" * 60)
    logger.info("TEST: Migration Status")
    logger.info("=" * 60)
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath = f.name
    
    try:
        db = DatabaseWrapper(dbPath)
        manager = MigrationManager(db)
        manager.registerMigrations(MIGRATIONS)
        
        status = manager.getStatus()
        logger.info(f"Migration status: {status}")
        
        assert status["current_version"] == status["latest_version"], \
            "Current version should equal latest version"
        assert status["pending_count"] == 0, \
            "Should have no pending migrations"
        
        logger.info("✅ Migration status test PASSED, dood!")
        return True
        
    finally:
        if os.path.exists(dbPath):
            os.unlink(dbPath)


def test_rollback():
    """Test migration rollback, dood!"""
    logger.info("=" * 60)
    logger.info("TEST: Migration Rollback")
    logger.info("=" * 60)
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath = f.name
    
    try:
        # Initialize database
        db = DatabaseWrapper(dbPath)
        manager = MigrationManager(db)
        manager.registerMigrations(MIGRATIONS)
        
        initialVersion = manager.getCurrentVersion()
        logger.info(f"Initial version: {initialVersion}")
        
        # Rollback one migration
        manager.rollback(steps=1)
        
        newVersion = manager.getCurrentVersion()
        logger.info(f"Version after rollback: {newVersion}")
        
        assert newVersion == initialVersion - 1, \
            f"Expected version {initialVersion - 1}, got {newVersion}"
        
        # Check that metadata column is gone (from migration 003)
        with db.getCursor() as cursor:
            cursor.execute("PRAGMA table_info(chat_users)")
            columns = [row[1] for row in cursor.fetchall()]
            assert "metadata" not in columns, "metadata column should be dropped"
        
        logger.info("✅ Rollback test PASSED, dood!")
        return True
        
    finally:
        if os.path.exists(dbPath):
            os.unlink(dbPath)


def test_existing_database():
    """Test upgrading existing database, dood!"""
    logger.info("=" * 60)
    logger.info("TEST: Existing Database Upgrade")
    logger.info("=" * 60)
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath = f.name
    
    try:
        # Create database with only settings table (simulating old database)
        db = DatabaseWrapper.__new__(DatabaseWrapper)
        db.dbPath = dbPath
        db.maxConnections = 5
        db.timeout = 30.0
        db._local = __import__("threading").local()
        
        with db.getCursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        
        # Now run migrations
        manager = MigrationManager(db)
        manager.registerMigrations(MIGRATIONS)
        
        initialVersion = manager.getCurrentVersion()
        logger.info(f"Initial version: {initialVersion}")
        assert initialVersion == 0, "Should start at version 0"
        
        manager.migrate()
        
        finalVersion = manager.getCurrentVersion()
        logger.info(f"Final version: {finalVersion}")
        assert finalVersion == len(MIGRATIONS), \
            f"Expected version {len(MIGRATIONS)}, got {finalVersion}"
        
        logger.info("✅ Existing database upgrade test PASSED, dood!")
        return True
        
    finally:
        if os.path.exists(dbPath):
            os.unlink(dbPath)


def test_auto_discovery():
    """Test migration auto-discovery functionality, dood!"""
    logger.info("=" * 60)
    logger.info("TEST: Migration Auto-Discovery")
    logger.info("=" * 60)
    
    try:
        # Test that DISCOVERED_MIGRATIONS is populated
        assert len(DISCOVERED_MIGRATIONS) > 0, "DISCOVERED_MIGRATIONS should not be empty"
        logger.info(f"Found {len(DISCOVERED_MIGRATIONS)} discovered migrations")
        
        # Test that discovered migrations match manual migrations
        assert len(DISCOVERED_MIGRATIONS) == len(MIGRATIONS), \
            f"Discovered {len(DISCOVERED_MIGRATIONS)} migrations, expected {len(MIGRATIONS)}"
        
        # Test that versions are correct
        discoveredVersions = [m.version for m in DISCOVERED_MIGRATIONS]
        manualVersions = [m.version for m in MIGRATIONS]
        assert discoveredVersions == manualVersions, \
            f"Discovered versions {discoveredVersions} don't match manual {manualVersions}"
        
        # Test that descriptions match
        for discovered, manual in zip(DISCOVERED_MIGRATIONS, MIGRATIONS):
            assert discovered.description == manual.description, \
                f"Description mismatch: {discovered.description} vs {manual.description}"
        
        logger.info("✅ Auto-discovery test PASSED, dood!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Auto-discovery test FAILED: {e}")
        logger.exception(e)
        return False


def test_getMigration_functions():
    """Test that all migration files have getMigration() functions, dood!"""
    logger.info("=" * 60)
    logger.info("TEST: getMigration() Functions")
    logger.info("=" * 60)
    
    try:
        # Known migration modules and their classes
        expectedModules = {
            1: ("migration_001_initial_schema", "Migration001InitialSchema"),
            2: ("migration_002_add_is_spammer_to_chat_users", "Migration002AddIsSpammerToChatUsers"),
            3: ("migration_003_add_metadata_to_chat_users", "Migration003AddMetadataToChatUsers"),
        }
        
        # Test each expected migration module
        for version, (moduleName, expectedClassName) in expectedModules.items():
            # Import the module
            module = __import__(f"internal.database.migrations.versions.{moduleName}",
                              fromlist=[moduleName])
            
            # Check getMigration function exists
            assert hasattr(module, "getMigration"), \
                f"Module {moduleName} missing getMigration() function"
            
            # Test that getMigration() returns the correct class
            returnedClass = module.getMigration()
            assert returnedClass.__name__ == expectedClassName, \
                f"getMigration() in {moduleName} returned {returnedClass.__name__}, expected {expectedClassName}"
            
            # Test that the returned class has the correct version
            assert returnedClass.version == version, \
                f"getMigration() in {moduleName} returned class with version {returnedClass.version}, expected {version}"
            
            logger.debug(f"✅ {moduleName}.getMigration() works correctly")
        
        logger.info("✅ getMigration() functions test PASSED, dood!")
        return True
        
    except Exception as e:
        logger.error(f"❌ getMigration() functions test FAILED: {e}")
        logger.exception(e)
        return False


def test_loadMigrationsFromVersions():
    """Test MigrationManager.loadMigrationsFromVersions() method, dood!"""
    logger.info("=" * 60)
    logger.info("TEST: loadMigrationsFromVersions() Method")
    logger.info("=" * 60)
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath = f.name
    
    try:
        db = DatabaseWrapper(dbPath)
        manager = MigrationManager(db)
        
        # Test loadMigrationsFromVersions()
        manager.loadMigrationsFromVersions()
        
        # Check that migrations were loaded
        assert len(manager.migrations) > 0, "No migrations loaded"
        assert len(manager.migrations) == len(DISCOVERED_MIGRATIONS), \
            f"Loaded {len(manager.migrations)} migrations, expected {len(DISCOVERED_MIGRATIONS)}"
        
        # Check that versions are correct
        loadedVersions = [m.version for m in manager.migrations]
        discoveredVersions = [m.version for m in DISCOVERED_MIGRATIONS]
        assert loadedVersions == discoveredVersions, \
            f"Loaded versions {loadedVersions} don't match discovered {discoveredVersions}"
        
        logger.info("✅ loadMigrationsFromVersions() test PASSED, dood!")
        return True
        
    finally:
        if os.path.exists(dbPath):
            os.unlink(dbPath)


def test_database_wrapper_auto_discovery():
    """Test that DatabaseWrapper uses auto-discovery, dood!"""
    logger.info("=" * 60)
    logger.info("TEST: DatabaseWrapper Auto-Discovery")
    logger.info("=" * 60)
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath = f.name
    
    try:
        # Initialize database (should use auto-discovery)
        db = DatabaseWrapper(dbPath)
        
        # Check that all migrations were applied
        manager = MigrationManager(db)
        currentVersion = manager.getCurrentVersion()
        
        assert currentVersion == len(DISCOVERED_MIGRATIONS), \
            f"Expected version {len(DISCOVERED_MIGRATIONS)}, got {currentVersion}"
        
        # Check that tables exist
        with db.getCursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cursor.fetchall()]
            logger.info(f"Created tables: {', '.join(tables)}")
            
            # Verify key tables exist
            expectedTables = [
                "settings",
                "chat_messages",
                "chat_users",
                "chat_info",
            ]
            
            for table in expectedTables:
                assert table in tables, f"Table {table} not found"
        
        logger.info("✅ DatabaseWrapper auto-discovery test PASSED, dood!")
        return True
        
    finally:
        if os.path.exists(dbPath):
            os.unlink(dbPath)


def main():
    """Run all tests, dood!"""
    logger.info("Starting migration tests, dood!")
    
    tests = [
        test_fresh_database,
        test_migration_status,
        test_rollback,
        test_existing_database,
        test_auto_discovery,
        test_getMigration_functions,
        test_loadMigrationsFromVersions,
        test_database_wrapper_auto_discovery,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            logger.error(f"❌ Test {test.__name__} FAILED: {e}")
            logger.exception(e)
            failed += 1
    
    logger.info("=" * 60)
    logger.info(f"Test Results: {passed} passed, {failed} failed")
    logger.info("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)