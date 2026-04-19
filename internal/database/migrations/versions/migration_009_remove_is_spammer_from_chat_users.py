"""
Remove is_spammer column from chat_users table, dood!

This migration reverts the changes from migration_002 by removing the is_spammer
boolean flag from the chat_users table.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration009RemoveIsSpammerFromChatUsers(BaseMigration):
    """Remove is_spammer column from chat_users table, dood!"""

    version = 9
    description = "Remove is_spammer column from chat_users table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration - remove is_spammer column from chat_users, dood!

        Args:
            sqlProvider: SQL provider for executing queries
        """
        # Remove is_spammer column from chat_users table
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            DROP COLUMN is_spammer
        """))

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration - add back is_spammer column, dood!

        Args:
            sqlProvider: SQL provider for executing queries
        """
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            ADD COLUMN is_spammer BOOLEAN DEFAULT FALSE NOT NULL
        """))


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration009RemoveIsSpammerFromChatUsers
