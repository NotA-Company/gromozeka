"""Add bot_status column and index to chat_info for accessibility tracking.

This migration adds a `bot_status` column to the `chat_info` table to track
the accessibility state of the bot in each chat. The column is of TEXT type,
is NOT NULL, and has a default value of 'active'. A supporting index is
also created to optimize queries filtering by bot_status.

Migration Details:
- Version: 26
- Table: chat_info
- Column: bot_status (TEXT, NOT NULL, DEFAULT 'active')
- Index: idx_chat_info_bot_status on bot_status
- Purpose: Track per-chat accessibility state for filtering dead chats

This migration is part of the chat accessibility tracking feature, enabling
the system to persist and query chats where the bot is no longer present
(kicked/blocked) and exclude them from chat listings by default.

The default value 'active' backfills all existing chat_info rows, so
pre-existing chats are assumed accessible until a probe fails.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration026ChatAccessibilityBotStatus(BaseMigration):
    """Add bot_status column and index to chat_info for accessibility tracking.

    This migration adds the `bot_status` column to track whether the bot is
    still present in a chat (ACTIVE) or has been kicked/blocked (INACCESSIBLE).
    A supporting index is created to optimize chat-list queries that filter
    by bot_status. The column defaults to 'active' for all existing rows.

    Attributes:
        version: The migration version number (26).
        description: Human-readable description of the migration.
    """

    version: int = 26
    description: str = "Add bot_status column and index to chat_info"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration to add bot_status column and index.

        This method adds the `bot_status` column to the `chat_info` table
        with a default value of 'active', then creates an index on this
        column. The default backfills all existing rows to 'active'.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        # Add column with default value 'active' (backfills existing rows)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    ALTER TABLE chat_info
                    ADD COLUMN bot_status TEXT NOT NULL DEFAULT 'active'
                """),
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_chat_info_bot_status
                    ON chat_info (bot_status)
                """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration to remove bot_status column and index.

        This method removes the index and the `bot_status` column from the
        `chat_info` table, reverting the schema to its previous state.
        Note that SQLite 3.35.0+ supports the DROP COLUMN operation.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None

        Note:
            This rollback operation requires SQLite 3.35.0 or later. For older
            versions, this will fail and require manual table recreation.
        """
        # Drop index first (required before dropping column on some RDBMS)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_chat_info_bot_status"),
                ParametrizedQuery("ALTER TABLE chat_info DROP COLUMN bot_status"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration026ChatAccessibilityBotStatus
