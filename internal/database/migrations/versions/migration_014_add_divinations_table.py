"""Migration: add divinations table - v014, dood!"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration014AddDivinationsTable(BaseMigration):
    """Add divinations table for tarot/runes readings, dood!

    The table uses a composite PK (chat_id, message_id) keyed off the
    originating /taro or /runes user-command message — same pattern as
    chat_messages.

    Attributes:
        version: Migration version number (14).
        description: Human-readable description.
    """

    version: int = 14
    description: str = "Add divinations table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create divinations table and supporting index, dood.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS divinations (
                        chat_id        INTEGER NOT NULL,
                        message_id     TEXT    NOT NULL,
                        user_id        INTEGER NOT NULL,
                        system_id      TEXT    NOT NULL,
                        deck_id        TEXT    NOT NULL,
                        layout_id      TEXT    NOT NULL,
                        question       TEXT    NOT NULL,
                        draws_json     TEXT    NOT NULL,
                        interpretation TEXT    NOT NULL,
                        image_prompt   TEXT,
                        invoked_via    TEXT    NOT NULL,              -- 'command' | 'llm_tool'
                        created_at     TIMESTAMP NOT NULL,
                        PRIMARY KEY (chat_id, message_id)
                    )
                """),
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_divinations_user_created
                    ON divinations (chat_id, user_id, created_at)
                """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop divinations table and its index, dood.

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_divinations_user_created"),
                ParametrizedQuery("DROP TABLE IF EXISTS divinations"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration014AddDivinationsTable
