"""Migration to remove is_spammer column from chat_users table.

This migration reverts the changes from migration_002 by removing the is_spammer
boolean flag from the chat_users table. The is_spammer column was previously used
to track spammer status but is no longer needed in the current schema design.

The migration is reversible - the down() method will restore the column with
its original default value and constraints.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration009RemoveIsSpammerFromChatUsers(BaseMigration):
    """Migration to remove is_spammer column from chat_users table.

    This migration removes the is_spammer boolean column that was added in
    migration_002. The column is no longer needed in the current schema design.

    Attributes:
        version: The migration version number (9).
        description: Human-readable description of the migration.
    """

    version: int = 9
    description: str = "Remove is_spammer column from chat_users table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration by removing the is_spammer column from chat_users table.

        This method executes an ALTER TABLE statement to drop the is_spammer
        boolean column from the chat_users table.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        # Remove is_spammer column from chat_users table
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            DROP COLUMN is_spammer
        """))

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration by restoring the is_spammer column to chat_users table.

        This method executes an ALTER TABLE statement to add back the is_spammer
        boolean column with its original default value (FALSE) and NOT NULL constraint.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            ADD COLUMN is_spammer BOOLEAN DEFAULT FALSE NOT NULL
        """))


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    This function is used by the migration system to discover and load
    the migration class defined in this module.

    Returns:
        Type[BaseMigration]: The Migration009RemoveIsSpammerFromChatUsers class.
    """
    return Migration009RemoveIsSpammerFromChatUsers
