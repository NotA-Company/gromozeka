"""
Add media group support, dood!

This migration adds support for media groups by:
- Adding media_group_id column to chat_messages table
- Creating media_group table to track media group relationships
"""

import sqlite3
from typing import Type

from ..base import BaseMigration


class Migration008AddMediaGroupSupport(BaseMigration):
    """Add media group support, dood!"""

    version = 8
    description = "add media group support"

    def up(self, cursor: sqlite3.Cursor) -> None:
        """
        Apply the migration, dood!
        
        Adds media group support by:
        1. Adding media_group_id column to chat_messages table
        2. Creating media_group table to track media group relationships
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # Add media_group_id column to chat_messages table
        cursor.execute(
            """
            ALTER TABLE chat_messages
            ADD COLUMN media_group_id TEXT
        """
        )

        # Create media_group table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS media_group (
                media_group_id TEXT NOT NULL,
                media_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (media_group_id, media_id)
            )
        """
        )

    def down(self, cursor: sqlite3.Cursor) -> None:
        """
        Rollback the migration, dood!
        
        Removes media group support by:
        1. Dropping the media_group table
        2. Removing media_group_id column from chat_messages table
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # Drop media_group table
        cursor.execute("DROP TABLE IF EXISTS media_group")

        # Remove media_group_id column from chat_messages table
        cursor.execute(
            """
            ALTER TABLE chat_messages
            DROP COLUMN media_group_id
        """
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration008AddMediaGroupSupport
