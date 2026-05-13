"""Migration to add updated_by column to chat_settings table.

This migration adds an `updated_by` column to the `chat_settings` table to track
which user last modified a chat setting. The column is of INTEGER type, is NOT NULL,
and has a default value of 0.

Migration Details:
- Version: 10
- Table: chat_settings
- Column: updated_by (INTEGER, NOT NULL, DEFAULT 0)
- Purpose: Track the user ID who last updated each chat setting

This migration is part of the database schema evolution for the Gromozeka project,
enabling audit trail functionality for chat configuration changes.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration010AddUpdatedByToChatSettings(BaseMigration):
    """Migration to add updated_by column to chat_settings table.

    This migration adds an `updated_by` column to track which user last modified
    a chat setting. The column is added as INTEGER type with NOT NULL constraint
    and a default value of 0 to ensure compatibility with existing records.

    Attributes:
        version: The migration version number (10).
        description: Human-readable description of the migration.
    """

    version: int = 10
    description: str = "Add updated_by column to chat_settings table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration to add updated_by column to chat_settings.

        This method adds the `updated_by` column to the `chat_settings` table.
        The column is defined as INTEGER type with NOT NULL constraint and a
        default value of 0. The default value is required for SQLite when adding
        a NOT NULL column to an existing table.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        # Add column with default value (SQLite requires default for NOT NULL)
        alterQuery: ParametrizedQuery = ParametrizedQuery("""
            ALTER TABLE chat_settings
            ADD COLUMN updated_by INTEGER NOT NULL DEFAULT 0
        """)
        await sqlProvider.execute(alterQuery)

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration to remove updated_by column.

        This method removes the `updated_by` column from the `chat_settings` table,
        reverting the schema to its previous state. Note that SQLite 3.35.0+ supports
        the DROP COLUMN operation. For older SQLite versions, this operation will fail
        and require manual table recreation to rollback.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None

        Note:
            This rollback operation requires SQLite 3.35.0 or later. For older
            versions, manual intervention with table recreation is necessary.
        """
        # SQLite 3.35.0+ supports DROP COLUMN
        # For older versions, this will fail and require table recreation
        dropQuery: ParametrizedQuery = ParametrizedQuery("ALTER TABLE chat_settings DROP COLUMN updated_by")
        await sqlProvider.execute(dropQuery)


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module
    """
    return Migration010AddUpdatedByToChatSettings
