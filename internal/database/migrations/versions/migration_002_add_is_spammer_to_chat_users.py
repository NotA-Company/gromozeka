"""
Add is_spammer column to chat_users table.

This migration adds a boolean flag to track potential spammers in chats.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration002AddIsSpammerToChatUsers(BaseMigration):
    """Add is_spammer column to chat_users table."""

    version = 2
    description = "Add is_spammer column to chat_users table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration - add is_spammer column to chat_users.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        # Add is_spammer column to chat_users table
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            ADD COLUMN is_spammer BOOLEAN DEFAULT FALSE NOT NULL
        """))

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration - remove is_spammer column.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            DROP COLUMN is_spammer
        """))


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module
    """
    return Migration002AddIsSpammerToChatUsers
