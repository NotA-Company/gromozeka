"""
Add markup and metadata columns to chat_messages table.

This migration adds markup and metadata columns to store additional
information about chat messages.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration007(BaseMigration):
    """Add markup and metadata columns to chat_messages table."""

    version = 7
    description = "Add markup and metadata columns to chat_messages table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration - add markup and metadata columns to chat_messages.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            ALTER TABLE chat_messages
            ADD COLUMN markup TEXT DEFAULT "" NOT NULL
        """),
                ParametrizedQuery("""
            ALTER TABLE chat_messages
            ADD COLUMN metadata TEXT DEFAULT "" NOT NULL
        """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration - remove markup and metadata columns.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            ALTER TABLE chat_messages
            DROP COLUMN markup
        """),
                ParametrizedQuery("""
            ALTER TABLE chat_messages
            DROP COLUMN metadata
        """),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module
    """
    return Migration007
