"""Migration 011: Add confidence column to spam_messages and ham_messages tables.

This migration adds a confidence column to track the confidence level of spam
detection for both spam and ham messages. The confidence column is a FLOAT
type with NOT NULL constraint and a default value of 1.0, representing the
certainty level of the spam classification.

The migration applies to:
- spam_messages table: Stores messages classified as spam
- ham_messages table: Stores messages classified as ham (non-spam)

This enhancement allows the system to track and utilize confidence scores
for spam detection, enabling more nuanced filtering and analysis.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration011AddConfidenceToSpamMessages(BaseMigration):
    """Migration to add confidence column to spam_messages and ham_messages tables.

    This migration adds a FLOAT column named 'confidence' to both spam_messages
    and ham_messages tables. The column stores the confidence level of spam
    detection, ranging from 0.0 (least confident) to 1.0 (most confident).

    Attributes:
        version: The migration version number (11).
        description: A brief description of the migration purpose.
    """

    version: int = 11
    description: str = "Add confidence column to spam_messages table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration to add confidence column.

        Adds a confidence column to both spam_messages and ham_messages tables.
        The column is defined as FLOAT type with NOT NULL constraint and a
        default value of 1.0. The default value is required for SQLite when
        adding a NOT NULL column to an existing table.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
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
        """Rollback the migration to remove confidence column.

        Removes the confidence column from both spam_messages and ham_messages
        tables. This operation uses the DROP COLUMN syntax which is supported
        in SQLite 3.35.0 and later. For older SQLite versions, this operation
        will fail and require manual table recreation.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
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
    """Return the migration class for this module.

    This function is used by the migration system to dynamically load and
    instantiate the migration class.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration011AddConfidenceToSpamMessages
