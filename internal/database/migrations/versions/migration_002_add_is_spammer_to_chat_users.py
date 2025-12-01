"""
Add is_spammer column to chat_users table, dood!

This migration adds a boolean flag to track potential spammers in chats.
"""

import sqlite3
from typing import Type
from ..base import BaseMigration


class Migration002AddIsSpammerToChatUsers(BaseMigration):
    """Add is_spammer column to chat_users table, dood!"""

    version = 2
    description = "Add is_spammer column to chat_users table"

    def up(self, cursor: sqlite3.Cursor) -> None:
        """Apply the migration - add is_spammer column to chat_users, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # Add is_spammer column to chat_users table
        cursor.execute(
            """
            ALTER TABLE chat_users
            ADD COLUMN is_spammer BOOLEAN DEFAULT FALSE NOT NULL
        """
        )

    def down(self, cursor: sqlite3.Cursor) -> None:
        """Rollback the migration - remove is_spammer column, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        cursor.execute(
            """
            ALTER TABLE chat_users
            DROP COLUMN is_spammer
        """
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration002AddIsSpammerToChatUsers