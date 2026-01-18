"""
Unify cache tables migration - consolidates all cache tables into one, dood!

This migration replaces the 6 separate cache_{type} tables with a single
unified_cache table that uses a namespace column to distinguish cache types.
"""

import sqlite3
from typing import Type
from ..base import BaseMigration


class Migration012UnifyCacheTables(BaseMigration):
    """Unify all cache tables into a single unified_cache table, dood!"""

    version = 12
    description = "Unify cache tables into single unified_cache table"

    def up(self, cursor: sqlite3.Cursor) -> None:
        """Create unified_cache table and drop old cache tables, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # Create generic cache table with namespace support
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (namespace, key)
            )
            """
        )
        
        # Add index on namespace column for efficient filtering
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cache_namespace_key
            ON cache (namespace, key)
            """
        )
        
        # Add index on updated_at column for TTL cleanup
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cache_updated_at 
            ON cache (updated_at)
            """
        )
        from ...models import CacheType
        
        # Drop old cache tables
        for cacheType in CacheType:
            cursor.execute(f"DROP TABLE IF EXISTS cache_{cacheType}")

    def down(self, cursor: sqlite3.Cursor) -> None:
        """Revert to separate cache tables, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """  
        from ...models import CacheType
        
        # Recreate old cache tables
        for cacheType in CacheType:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS cache_{cacheType} (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        
        # Drop unified cache table
        cursor.execute("DROP TABLE IF EXISTS cache")


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration012UnifyCacheTables
