"""Migration to add media group support to the database schema.

This migration implements support for Telegram media groups, which allow multiple
media items (photos, videos, documents) to be sent together as a single group.
Media groups share a common media_group_id and are displayed together in the
Telegram client.

Schema changes:
- Adds media_group_id column to chat_messages table to link messages to media groups
- Creates media_groups table to track the relationship between media groups and
  individual media items

The media_groups table uses a composite primary key (media_group_id, media_id)
to ensure each media item belongs to exactly one media group.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration008AddMediaGroupSupport(BaseMigration):
    """Migration to add media group support to the database.

    This migration adds the necessary database schema to support Telegram media groups,
    which allow multiple media items to be sent together as a single group. Media groups
    are identified by a common media_group_id and are displayed together in the Telegram
    client.

    Attributes:
        version: The migration version number (8).
        description: A brief description of the migration purpose.
    """

    version: int = 8
    description: str = "Add media group support"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration to add media group support to the database.

        This method executes the following schema changes:
        1. Adds a media_group_id TEXT column to the chat_messages table to link
           individual messages to their media group
        2. Creates a media_groups table with the following structure:
           - media_group_id: The unique identifier for the media group
           - media_id: The unique identifier for an individual media item
           - created_at: Timestamp of when the media group was created
           - Composite primary key on (media_group_id, media_id) to ensure
             each media item belongs to exactly one media group

        Args:
            sqlProvider: SQL provider for executing database queries.

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
                created_at TIMESTAMP NOT NULL,
                PRIMARY KEY (media_group_id, media_id)
            )
        """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration to remove media group support from the database.

        This method reverses the schema changes made by the up() method:
        1. Drops the media_groups table, removing all media group relationship data
        2. Removes the media_group_id column from the chat_messages table

        Warning:
            This operation will permanently delete all media group data and cannot
            be undone without reapplying the migration.

        Args:
            sqlProvider: SQL provider for executing database queries.

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
