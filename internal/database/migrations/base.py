"""
Base migration class for database migrations, dood!
"""

import sqlite3
from abc import ABC, abstractmethod


class BaseMigration(ABC):
    """Base class for all database migrations, dood!"""

    # Migration metadata
    version: int
    description: str

    @abstractmethod
    def up(self, cursor: sqlite3.Cursor) -> None:
        """
        Apply the migration, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        pass

    @abstractmethod
    def down(self, cursor: sqlite3.Cursor) -> None:
        """
        Rollback the migration, dood!
        
        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        pass