"""
Add confidence column to spam_messages table, dood!

This migration adds a confidence column to track the confidence level
of spam detection.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration011AddConfidenceToSpamMessages(BaseMigration):
    """Add confidence column to spam_messages table, dood!"""

    version = 11
    description = "Add confidence column to spam_messages table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """
        Apply the migration, dood!

        Adds confidence column to spam_messages table:
        - FLOAT type, NOT NULL with DEFAULT 1.0

        Args:
            sqlProvider: SQL provider for executing queries
        """
        # Add column with default value (SQLite requires default for NOT NULL)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            ALTER TABLE spam_messages
            ADD COLUMN confidence FLOAT NOT NULL DEFAULT 1.0
        """),
                ParametrizedQuery("""
            ALTER TABLE ham_messages
            ADD COLUMN confidence FLOAT NOT NULL DEFAULT 1.0
        """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """
        Rollback the migration, dood!

        Removes the confidence column from spam_messages table.

        Args:
            sqlProvider: SQL provider for executing queries
        """
        # SQLite 3.35.0+ supports DROP COLUMN
        # For older versions, this will fail and require table recreation
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("ALTER TABLE spam_messages DROP COLUMN confidence"),
                ParametrizedQuery("ALTER TABLE ham_messages DROP COLUMN confidence"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration011AddConfidenceToSpamMessages
