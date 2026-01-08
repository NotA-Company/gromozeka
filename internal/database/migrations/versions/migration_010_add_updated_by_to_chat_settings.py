"""
Add updated_by column to chat_settings table, dood!

This migration adds a updated_by column to track which user last modified
a chat setting.
"""

import sqlite3
from typing import Type

from ..base import BaseMigration


class Migration010AddUpdatedByToChatSettings(BaseMigration):
    """Add updated_by column to chat_settings table, dood!"""

    version = 10
    description = "Add updated_by column to chat_settings table"

    def up(self, cursor: sqlite3.Cursor) -> None:
        """
        Apply the migration, dood!
        
        Adds updated_by column to chat_settings table:
        - INTEGER type, NOT NULL with DEFAULT 0
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # Add column with default value (SQLite requires default for NOT NULL)
        cursor.execute(
            """
            ALTER TABLE chat_settings
            ADD COLUMN updated_by INTEGER NOT NULL DEFAULT 0
        """
        )

    def down(self, cursor: sqlite3.Cursor) -> None:
        """
        Rollback the migration, dood!
        
        Removes the updated_by column from chat_settings table.
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # SQLite 3.35.0+ supports DROP COLUMN
        # For older versions, this will fail and require table recreation
        cursor.execute("ALTER TABLE chat_settings DROP COLUMN updated_by")


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration010AddUpdatedByToChatSettings
