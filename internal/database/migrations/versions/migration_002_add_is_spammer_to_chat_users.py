"""
Add is_spammer column to chat_users table, dood!

This migration adds a boolean flag to track potential spammers in chats.
"""

from typing import TYPE_CHECKING, Type
from ..base import BaseMigration

if TYPE_CHECKING:
    from ...wrapper import DatabaseWrapper


class Migration002AddIsSpammerToChatUsers(BaseMigration):
    """Add is_spammer column to chat_users table, dood!"""

    version = 2
    description = "Add is_spammer column to chat_users table"

    def up(self, db: "DatabaseWrapper") -> None:
        """
        Apply the migration - add is_spammer column to chat_users, dood!
        
        Adds a boolean column to track users flagged as potential spammers.
        Default value is FALSE (not a spammer).
        """
        with db.getCursor() as cursor:
            # Add is_spammer column to chat_users table
            cursor.execute(
                """
                ALTER TABLE chat_users 
                ADD COLUMN is_spammer BOOLEAN DEFAULT FALSE NOT NULL
            """
            )

    def down(self, db: "DatabaseWrapper") -> None:
        """
        Rollback the migration - remove is_spammer column, dood!
        
        Note: SQLite doesn't support DROP COLUMN directly in older versions,
        but modern SQLite (3.35.0+) does support it.
        """
        with db.getCursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE chat_users
                DROP COLUMN is_spammer
            """
            )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration002AddIsSpammerToChatUsers