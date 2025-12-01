"""
Add_cache_storage_table, dood!

TODO: Implement the migration logic below
"""

import sqlite3
from typing import Type
from ..base import BaseMigration


class Migration004Add_cache_storage_table(BaseMigration):
    """Add_cache_storage_table, dood!"""

    version = 4
    description = "add_cache_storage_table"

    def up(self, cursor: sqlite3.Cursor) -> None:
        """Create cache_storage table for CacheService persistence, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_storage (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (namespace, key)
            )
            """
        )
        
        # Create index for faster lookups by namespace
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cache_namespace
            ON cache_storage(namespace)
            """
        )

    def down(self, cursor: sqlite3.Cursor) -> None:
        """Drop cache_storage table and its index, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        cursor.execute("DROP INDEX IF EXISTS idx_cache_namespace")
        cursor.execute("DROP TABLE IF EXISTS cache_storage")


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration004Add_cache_storage_table
