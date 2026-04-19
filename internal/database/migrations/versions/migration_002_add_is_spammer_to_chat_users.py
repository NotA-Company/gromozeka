"""
Add is_spammer column to chat_users table, dood!

This migration adds a boolean flag to track potential spammers in chats.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration002AddIsSpammerToChatUsers(BaseMigration):
    """Add is_spammer column to chat_users table, dood!"""

    version = 2
    description = "Add is_spammer column to chat_users table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration - add is_spammer column to chat_users, dood!

        Args:
            sqlProvider: SQL provider for executing queries
        """
        # Add is_spammer column to chat_users table
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            ADD COLUMN is_spammer BOOLEAN DEFAULT FALSE NOT NULL
        """))

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration - remove is_spammer column, dood!

        Args:
            sqlProvider: SQL provider for executing queries
        """
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            DROP COLUMN is_spammer
        """))


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration002AddIsSpammerToChatUsers
