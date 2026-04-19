"""
Base migration class for database migrations, dood!
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..providers import BaseSQLProvider


class BaseMigration(ABC):
    """Base class for all database migrations, dood!"""

    # Migration metadata
    version: int
    description: str

    @abstractmethod
    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """
        Apply the migration, dood!

        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        pass

    @abstractmethod
    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """
        Rollback the migration, dood!

        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        pass
