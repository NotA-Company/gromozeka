#!/usr/bin/env python3
"""
Test script for database migrations, dood!

This script tests:
- Fresh database initialization
- Migration execution
- Version tracking
- Rollback functionality
"""

import logging
import os
import sys
import tempfile

import pytest

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
        
        # Rollback to version 2 (to remove metadata column from migration 003)
        # This ensures the test works regardless of how many migrations exist
        targetVersion = 2
        stepsToRollback = initialVersion - targetVersion
        logger.info(f"Rolling back {stepsToRollback} migrations to reach version {targetVersion}")
        
        manager.rollback(steps=stepsToRollback)
        
        newVersion = manager.getCurrentVersion()
        logger.info(f"Version after rollback: {newVersion}")
        
        assert newVersion == targetVersion, \
            f"Expected version {targetVersion}, got {newVersion}"
        
        # Check that metadata column is gone (migration 003 should be rolled back)
        with db.getCursor() as cursor:
            cursor.execute("PRAGMA table_info(chat_users)")
            columns = [row[1] for row in cursor.fetchall()]
            assert "metadata" not in columns, "metadata column should be dropped"
        
        logger.info("✅ Rollback test PASSED, dood!")
        
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
        # Create database - __init__ now automatically runs migrations
        db = DatabaseWrapper(dbPath, maxConnections=5, timeout=30.0)
        
        # Verify migrations were run automatically by __init__
        manager = MigrationManager(db)
        manager.registerMigrations(MIGRATIONS)
        
        currentVersion = manager.getCurrentVersion()
        logger.info(f"Current version after init: {currentVersion}")
        
        # With new multi-source architecture, migrations run automatically in __init__
        assert currentVersion == len(MIGRATIONS), \
            f"Expected version {len(MIGRATIONS)} (auto-migrated), got {currentVersion}"
        
        logger.info("✅ Existing database upgrade test PASSED, dood!")
        
    finally:
        if os.path.exists(dbPath):
            os.unlink(dbPath)


def test_auto_discovery():
    """Test migration auto-discovery functionality, dood!"""
    logger.info("=" * 60)
    logger.info("TEST: Migration Auto-Discovery")
    logger.info("=" * 60)
    
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


def test_getMigration_functions():
    """Test that all migration files have getMigration() functions, dood!"""
    logger.info("=" * 60)
    logger.info("TEST: getMigration() Functions")
    logger.info("=" * 60)
    
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
        
    finally:
        if os.path.exists(dbPath):
            os.unlink(dbPath)

