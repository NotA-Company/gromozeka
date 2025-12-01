"""
Add metadata column to chat_users table, dood!

This migration adds a text column to store metadata for chat users.
"""

import sqlite3
from typing import Type
from ..base import BaseMigration


class Migration003AddMetadataToChatUsers(BaseMigration):
    """Add metadata column to chat_users table, dood!"""

    version = 3
    description = "Add metadata column to chat_users table"

    def up(self, cursor: sqlite3.Cursor) -> None:
        """Apply the migration - add metadata column to chat_users, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # Add metadata column to chat_users table
        cursor.execute(
            """
            ALTER TABLE chat_users
            ADD COLUMN metadata TEXT DEFAULT '' NOT NULL
        """
        )

    def down(self, cursor: sqlite3.Cursor) -> None:
        """Rollback the migration - remove metadata column, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        cursor.execute(
            """
            ALTER TABLE chat_users
            DROP COLUMN metadata
        """
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration003AddMetadataToChatUsers