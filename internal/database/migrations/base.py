"""
Base migration class for database migrations, dood!
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..wrapper import DatabaseWrapper


class BaseMigration(ABC):
    """Base class for all database migrations, dood!"""

    # Migration metadata
    version: int
    description: str

    @abstractmethod
    def up(self, db: "DatabaseWrapper") -> None:
        """
        Apply the migration, dood!
        
        Args:
            db: DatabaseWrapper instance to execute SQL commands
        """
        pass

    @abstractmethod
    def down(self, db: "DatabaseWrapper") -> None:
        """
        Rollback the migration, dood!
        
        Args:
            db: DatabaseWrapper instance to execute SQL commands
        """
        pass