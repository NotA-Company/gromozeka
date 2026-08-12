"""Add bot_status column to chat_info for accessibility tracking.

This migration adds a `bot_status` column to the `chat_info` table to track
the accessibility state of the bot in each chat. The column is of TEXT type,
is NOT NULL, and has a default value of 'active'.

Migration Details:
- Version: 26
- Table: chat_info
- Column: bot_status (TEXT, NOT NULL, DEFAULT 'active')
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
    """Add bot_status column to chat_info for accessibility tracking.

    This migration adds the `bot_status` column to track whether the bot is
    still present in a chat (ACTIVE) or has been kicked/blocked (INACCESSIBLE).
    The column defaults to 'active' for all existing rows.

    Attributes:
        version: The migration version number (26).
        description: Human-readable description of the migration.
    """

    version: int = 26
    description: str = "Add bot_status column to chat_info"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration to add bot_status column.

        This method adds the `bot_status` column to the `chat_info` table
        with a default value of 'active'. The default backfills all existing
        rows to 'active'.

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
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration to remove the bot_status column.

        This method removes the `bot_status` column from the
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
        # Drop the column (SQLite >= 3.35.0 supports DROP COLUMN)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("ALTER TABLE chat_info DROP COLUMN bot_status"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration026ChatAccessibilityBotStatus
