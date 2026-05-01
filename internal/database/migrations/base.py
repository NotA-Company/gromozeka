"""Base migration class for database migrations.

This module provides the abstract base class that all database migrations
must inherit from. It defines the interface for applying and rolling back
migrations using SQL providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..providers import BaseSQLProvider


class BaseMigration(ABC):
    """Abstract base class for all database migrations.

    All migration classes must inherit from this class and implement the
    up() and down() methods to define how to apply and rollback the migration.
    """

    # Migration metadata
    version: int
    """The version number of this migration."""
    description: str
    """A human-readable description of what this migration does."""

    @abstractmethod
    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration to the database.

        This method should contain the SQL commands needed to apply the
        migration changes to the database schema.

        Args:
            sqlProvider: The SQL provider instance to execute SQL commands.

        Returns:
            None
        """
        pass

    @abstractmethod
    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration from the database.

        This method should contain the SQL commands needed to reverse the
        changes made by the up() method, restoring the database to its
        previous state.

        Args:
            sqlProvider: The SQL provider instance to execute SQL commands.

        Returns:
            None
        """
        pass
