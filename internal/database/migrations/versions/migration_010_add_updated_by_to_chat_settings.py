"""
Add updated_by column to chat_settings table.

This migration adds a updated_by column to track which user last modified
a chat setting.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration010AddUpdatedByToChatSettings(BaseMigration):
    """Add updated_by column to chat_settings table."""

    version = 10
    description = "Add updated_by column to chat_settings table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration to add updated_by column to chat_settings.

        Adds updated_by column to chat_settings table:
        - INTEGER type, NOT NULL with DEFAULT 0

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        # Add column with default value (SQLite requires default for NOT NULL)
        await sqlProvider.execute(ParametrizedQuery("""
            ALTER TABLE chat_settings
            ADD COLUMN updated_by INTEGER NOT NULL DEFAULT 0
        """))

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration to remove updated_by column.

        Removes the updated_by column from chat_settings table.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        # SQLite 3.35.0+ supports DROP COLUMN
        # For older versions, this will fail and require table recreation
        await sqlProvider.execute(ParametrizedQuery("ALTER TABLE chat_settings DROP COLUMN updated_by"))


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module
    """
    return Migration010AddUpdatedByToChatSettings
