"""Base migration class for database migrations.

This module provides the abstract base class that all database migrations
must inherit from. It defines the interface for applying and rolling back
migrations using SQL providers.

Key Components:
    - BaseMigration: Abstract base class defining the migration interface

Usage Example:
    .. code-block:: python

        from internal.database.migrations.base import BaseMigration
        from internal.database.providers import BaseSQLProvider

        class CreateUsersTable(BaseMigration):
            version = 1
            description = "Create users table"

            async def up(self, sqlProvider: BaseSQLProvider) -> None:
                await sqlProvider.execute('''
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL
                    )
                ''')

            async def down(self, sqlProvider: BaseSQLProvider) -> None:
                await sqlProvider.execute('DROP TABLE users')
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
    This class provides the contract that migration implementations must follow,
    ensuring consistency across the migration system.

    Attributes:
        version: The version number of this migration. Migrations are applied
            in ascending order based on this value.
        description: A human-readable description of what this migration does.
            This should clearly explain the schema changes being made.

    Note:
        Subclasses must implement both the up() and down() methods. The up()
        method should apply the migration changes, while the down() method should
        reverse those changes to allow for rollback.
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
        migration changes to the database schema. The implementation should
        be idempotent where possible and handle edge cases appropriately.

        Args:
            sqlProvider: The SQL provider instance to execute SQL commands.
                This provider handles database-specific SQL dialect differences
                and provides a consistent interface for executing queries.

        Returns:
            None

        Raises:
            Exception: May raise database-specific exceptions if the SQL
                execution fails. Implementations should document specific
                exceptions that may be raised.

        Note:
            This method is called when applying migrations in forward order.
            Ensure that the SQL commands are compatible with the target
            database system.
        """
        pass

    @abstractmethod
    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration from the database.

        This method should contain the SQL commands needed to reverse the
        changes made by the up() method, restoring the database to its
        previous state. The implementation should be the exact inverse of
        the up() method where possible.

        Args:
            sqlProvider: The SQL provider instance to execute SQL commands.
                This provider handles database-specific SQL dialect differences
                and provides a consistent interface for executing queries.

        Returns:
            None

        Raises:
            Exception: May raise database-specific exceptions if the SQL
                execution fails. Implementations should document specific
                exceptions that may be raised.

        Note:
            This method is called when rolling back migrations. Ensure that
            the rollback logic properly handles all edge cases and restores
            the database to its exact previous state.
        """
        pass
