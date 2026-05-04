"""Migration 003: Add metadata column to chat_users table.

This migration adds a TEXT column named 'metadata' to the chat_users table
to store additional metadata information for chat users. The column is
configured with a default empty string and NOT NULL constraint.

The metadata column allows storing flexible JSON or other text-based
metadata associated with chat users, enabling extensibility in user
data management without requiring schema changes for each new attribute.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration003AddMetadataToChatUsers(BaseMigration):
    """Migration to add metadata column to chat_users table.

    This migration adds a TEXT column named 'metadata' to the chat_users table.
    The column is configured with:
    - Type: TEXT
    - Default value: empty string ('')
    - Constraint: NOT NULL

    Attributes:
        version: The migration version number (3).
        description: Human-readable description of the migration.
    """

    version: int = 3
    description: str = "Add metadata column to chat_users table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration by adding the metadata column to chat_users table.

        This method executes an ALTER TABLE statement to add the metadata
        column with TEXT type, default empty string, and NOT NULL constraint.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        # Add metadata column to chat_users table
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            ADD COLUMN metadata TEXT DEFAULT '' NOT NULL
        """))

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration by removing the metadata column.

        This method executes an ALTER TABLE statement to drop the metadata
        column from the chat_users table, reverting the schema to its
        previous state.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            DROP COLUMN metadata
        """))


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    This function is used by the migration system to discover and load
    the migration class defined in this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration003AddMetadataToChatUsers
