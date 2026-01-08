"""
Remove is_spammer column from chat_users table, dood!

This migration reverts the changes from migration_002 by removing the is_spammer
boolean flag from the chat_users table.
"""

import sqlite3
from typing import Type
from ..base import BaseMigration


class Migration009RemoveIsSpammerFromChatUsers(BaseMigration):
    """Remove is_spammer column from chat_users table, dood!"""

    version = 9
    description = "Remove is_spammer column from chat_users table"

    def up(self, cursor: sqlite3.Cursor) -> None:
        """Apply the migration - remove is_spammer column from chat_users, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # Remove is_spammer column from chat_users table
        cursor.execute(
            """
            ALTER TABLE chat_users
            DROP COLUMN is_spammer
        """
        )

    def down(self, cursor: sqlite3.Cursor) -> None:
        """Rollback the migration - add back is_spammer column, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        cursor.execute(
            """
            ALTER TABLE chat_users
            ADD COLUMN is_spammer BOOLEAN DEFAULT FALSE NOT NULL
        """
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration009RemoveIsSpammerFromChatUsers
