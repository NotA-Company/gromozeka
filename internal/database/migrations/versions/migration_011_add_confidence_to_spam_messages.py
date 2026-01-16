"""
Add confidence column to spam_messages table, dood!

This migration adds a confidence column to track the confidence level
of spam detection.
"""

import sqlite3
from typing import Type

from ..base import BaseMigration


class Migration011AddConfidenceToSpamMessages(BaseMigration):
    """Add confidence column to spam_messages table, dood!"""

    version = 11
    description = "Add confidence column to spam_messages table"

    def up(self, cursor: sqlite3.Cursor) -> None:
        """
        Apply the migration, dood!
        
        Adds confidence column to spam_messages table:
        - FLOAT type, NOT NULL with DEFAULT 1.0
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # Add column with default value (SQLite requires default for NOT NULL)
        cursor.execute(
            """
            ALTER TABLE spam_messages
            ADD COLUMN confidence FLOAT NOT NULL DEFAULT 1.0
        """
        )
        cursor.execute(
            """
            ALTER TABLE ham_messages
            ADD COLUMN confidence FLOAT NOT NULL DEFAULT 1.0
        """
        )

    def down(self, cursor: sqlite3.Cursor) -> None:
        """
        Rollback the migration, dood!
        
        Removes the confidence column from spam_messages table.
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # SQLite 3.35.0+ supports DROP COLUMN
        # For older versions, this will fail and require table recreation
        cursor.execute("ALTER TABLE spam_messages DROP COLUMN confidence")
        cursor.execute("ALTER TABLE ham_messages DROP COLUMN confidence")


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration011AddConfidenceToSpamMessages
