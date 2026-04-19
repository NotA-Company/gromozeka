"""
Add metadata column to chat_users table, dood!

This migration adds a text column to store metadata for chat users.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration003AddMetadataToChatUsers(BaseMigration):
    """Add metadata column to chat_users table, dood!"""

    version = 3
    description = "Add metadata column to chat_users table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration - add metadata column to chat_users, dood!

        Args:
            sqlProvider: SQL provider for executing queries
        """
        # Add metadata column to chat_users table
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            ADD COLUMN metadata TEXT DEFAULT '' NOT NULL
        """))

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration - remove metadata column, dood!

        Args:
            sqlProvider: SQL provider for executing queries
        """
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            DROP COLUMN metadata
        """))


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration003AddMetadataToChatUsers
