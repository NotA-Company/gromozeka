"""
Add metadata column to chat_users table, dood!

This migration adds a text column to store metadata for chat users.
"""

from typing import TYPE_CHECKING, Type
from ..base import BaseMigration

if TYPE_CHECKING:
    from ...wrapper import DatabaseWrapper


class Migration003AddMetadataToChatUsers(BaseMigration):
    """Add metadata column to chat_users table, dood!"""

    version = 3
    description = "Add metadata column to chat_users table"

    def up(self, db: "DatabaseWrapper") -> None:
        """
        Apply the migration - add metadata column to chat_users, dood!
        
        Adds a text column to store metadata for chat users.
        Default value is empty string.
        """
        with db.getCursor() as cursor:
            # Add metadata column to chat_users table
            cursor.execute(
                """
                ALTER TABLE chat_users 
                ADD COLUMN metadata TEXT DEFAULT '' NOT NULL
            """
            )

    def down(self, db: "DatabaseWrapper") -> None:
        """
        Rollback the migration - remove metadata column, dood!
        
        Note: SQLite doesn't support DROP COLUMN directly in older versions,
        but modern SQLite (3.35.0+) does support it.
        """
        with db.getCursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE chat_users
                DROP COLUMN metadata
            """
            )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration003AddMetadataToChatUsers