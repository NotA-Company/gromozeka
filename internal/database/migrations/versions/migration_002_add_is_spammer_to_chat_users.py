"""Migration to add is_spammer column to chat_users table.

This migration adds a boolean flag to track potential spammers in chats.
The is_spammer column is added with a default value of FALSE and is set to NOT NULL,
ensuring all existing and new chat users have a spammer status defined.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration002AddIsSpammerToChatUsers(BaseMigration):
    """Migration that adds an is_spammer column to the chat_users table.

    This migration adds a boolean column to track whether a chat user has been
    identified as a spammer. The column is added with a default value of FALSE
    and is set to NOT NULL to ensure data integrity.

    Attributes:
        version: The migration version number (2).
        description: A human-readable description of the migration.
    """

    version: int = 2
    description: str = "Add is_spammer column to chat_users table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration by adding the is_spammer column to chat_users table.

        This method executes an ALTER TABLE statement to add a boolean column
        named is_spammer with a default value of FALSE and NOT NULL constraint.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        # Add is_spammer column to chat_users table
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            ADD COLUMN is_spammer BOOLEAN DEFAULT FALSE NOT NULL
        """))

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration by removing the is_spammer column from chat_users table.

        This method executes an ALTER TABLE statement to drop the is_spammer column,
        reverting the schema to its previous state.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_users
            DROP COLUMN is_spammer
        """))


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    This function is used by the migration system to discover and load
    the migration class defined in this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration002AddIsSpammerToChatUsers
