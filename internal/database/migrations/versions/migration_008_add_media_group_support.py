"""
Add media group support.

This migration adds support for media groups by:
- Adding media_group_id column to chat_messages table
- Creating media_group table to track media group relationships
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration008AddMediaGroupSupport(BaseMigration):
    """Add media group support."""

    version = 8
    description = "Add media group support"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration to add media group support.

        Adds media group support by:
        1. Adding media_group_id column to chat_messages table
        2. Creating media_group table to track media group relationships

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                # Add media_group_id column to chat_messages table
                ParametrizedQuery("""
            ALTER TABLE chat_messages
            ADD COLUMN media_group_id TEXT
        """),
                # Create media_group table
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS media_groups (
                media_group_id TEXT NOT NULL,
                media_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (media_group_id, media_id)
            )
        """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration to remove media group support.

        Removes media group support by:
        1. Dropping the media_group table
        2. Removing media_group_id column from chat_messages table

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                # Drop media_group table
                ParametrizedQuery("DROP TABLE IF EXISTS media_groups"),
                # Remove media_group_id column from chat_messages table
                ParametrizedQuery("""
            ALTER TABLE chat_messages
            DROP COLUMN media_group_id
        """),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module
    """
    return Migration008AddMediaGroupSupport
