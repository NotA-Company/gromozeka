"""
Initial schema migration - creates all base tables, dood!

This migration extracts all table creation from the original _initDatabase() method.
"""

import sqlite3
from typing import Type
from ..base import BaseMigration


class Migration005YandexSearchCache(BaseMigration):
    """Initial database schema migration, dood!"""

    version = 5
    description = "Add Yandex Search Cache"

    def up(self, cursor: sqlite3.Cursor) -> None:
        """Create all initial tables, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # Create all Cache Tables
        # Import CacheType here to avoid circular dependency
        from ...models import CacheType
        
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

    def down(self, cursor: sqlite3.Cursor) -> None:
        """Drop all tables created by this migration, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # Drop cache tables
        from ...models import CacheType
        
        for cacheType in [CacheType.YANDEX_SEARCH]:
            cursor.execute(f"DROP TABLE IF EXISTS cache_{cacheType}")


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration005YandexSearchCache