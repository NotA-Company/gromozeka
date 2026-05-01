"""
Add metadata column to chat_users table.

This migration adds a text column to store metadata for chat users.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration003AddMetadataToChatUsers(BaseMigration):
    """Add metadata column to chat_users table."""

    version = 3
    description = "Add metadata column to chat_users table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration - add metadata column to chat_users.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        # Add metadata column to chat_users table
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            ADD COLUMN metadata TEXT DEFAULT '' NOT NULL
        """))

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration - remove metadata column.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            DROP COLUMN metadata
        """))


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module
    """
    return Migration003AddMetadataToChatUsers
