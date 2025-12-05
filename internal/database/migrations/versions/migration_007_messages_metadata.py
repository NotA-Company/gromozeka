"""
Initial schema migration - creates all base tables, dood!

This migration extracts all table creation from the original _initDatabase() method.
"""

import sqlite3
from typing import Type
from ..base import BaseMigration


class Migration007(BaseMigration):
    """Initial database schema migration, dood!"""

    version = 7
    description = "Add markup and metadata columns to chat_messages table"

    def up(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            """
            ALTER TABLE chat_messages
            ADD COLUMN markup TEXT DEFAULT "" NOT NULL
        """
        )

        cursor.execute(
            """
            ALTER TABLE chat_messages
            ADD COLUMN metadata TEXT DEFAULT "" NOT NULL
        """
        )
        
        
    def down(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            """
            ALTER TABLE chat_messages
            DROP COLUMN markup
        """
        )
        cursor.execute(
            """
            ALTER TABLE chat_messages
            DROP COLUMN metadata
        """
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration007