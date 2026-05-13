"""Migration 007: Add markup and metadata columns to chat_messages table.

This migration adds two new TEXT columns to the chat_messages table:
- markup: Stores formatted markup content (e.g., Markdown, HTML) for messages
- metadata: Stores JSON metadata for additional message properties

Both columns are initialized with empty string defaults and are NOT NULL.
This enables storing rich formatting and extensible metadata for chat messages.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration007(BaseMigration):
    """Migration 007: Add markup and metadata columns to chat_messages table.

    This migration extends the chat_messages table schema to support:
    - Rich text markup storage (e.g., Markdown, HTML formatting)
    - Extensible JSON metadata for additional message properties

    Attributes:
        version: The migration version number (7).
        description: Human-readable description of the migration.
    """

    version: int = 7
    description: str = "Add markup and metadata columns to chat_messages table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration by adding markup and metadata columns to chat_messages.

        This method executes ALTER TABLE statements to add two new TEXT columns:
        - markup: Stores formatted markup content with empty string default
        - metadata: Stores JSON metadata with empty string default

        Args:
            sqlProvider: SQL provider for executing database queries.

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
        """Rollback the migration by removing markup and metadata columns.

        This method executes ALTER TABLE statements to drop the columns
        that were added in the up() migration.

        Args:
            sqlProvider: SQL provider for executing database queries.

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

    This function is used by the migration system to dynamically load
    the migration class.

    Returns:
        Type[BaseMigration]: The Migration007 class for this module.
    """
    return Migration007
