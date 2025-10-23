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
from internal.database.migrations import MigrationManager, MIGRATIONS

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
                "example_features",  # From migration 002
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
        
        # Check that example_features table is gone
        with db.getCursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='example_features'"
            )
            result = cursor.fetchone()
            assert result is None, "example_features table should be dropped"
        
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


def main():
    """Run all tests, dood!"""
    logger.info("Starting migration tests, dood!")
    
    tests = [
        test_fresh_database,
        test_migration_status,
        test_rollback,
        test_existing_database,
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