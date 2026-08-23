"""Add index on bayes_tokens(updated_at) to optimize age-based token cleanup.

``DatabaseBayesStorage.cleanupOldTokens`` (in
``internal/database/bayes_storage.py``) runs the age-based pruning of the
Bayesian-filter token table. For each ``(ttlSeconds, maxCount)`` rule in
``BAYES_TOKEN_CLEANUP_RULES`` it executes:

.. code-block:: sql

    DELETE FROM bayes_tokens
    WHERE updated_at < :cutoffTime AND total_count <= :maxCount

This DELETE is fired from ``HandlersManager._cleanupOldData()``, which runs
on a weekly cron **and** once at shutdown — so the cost of an unindexed full
table scan repeats for the lifetime of the database. The existing
``bayes_tokens_chat_idx(chat_id)`` and ``bayes_tokens_total_idx(total_count)``
do not help here: the cleanup deletes across ALL chats (no chat_id filter)
and ``updated_at`` is the selective range predicate.

The new ``idx_bayes_tokens_updated_at`` index lets SQLite (and any future
PostgreSQL/MySQL provider) seek directly to the stale rows, keeping the scan
bounded by the number of rows older than the cutoff rather than the full
table. ``total_count <= :maxCount`` remains a post-scan filter.

Schema notes (cross-RDBMS portability):
- Index name uses snake_case prefixed with ``idx_`` (project convention).
- ``IF NOT EXISTS`` / ``IF EXISTS`` guards for idempotency.
- No dialect-specific syntax — portable across SQLite/PostgreSQL/MySQL.
"""

from typing import Type

from lib.db.providers import BaseSQLProvider, ParametrizedQuery

from ..base import BaseMigration


class Migration024AddBayesTokensUpdatedAtIndex(BaseMigration):
    """Add secondary index on bayes_tokens (updated_at).

    Speeds up the ``cleanupOldTokens`` age-based DELETE that filters rows by
    ``updated_at < :cutoffTime``. Without this index, the weekly + on-shutdown
    cleanup scans the entire ``bayes_tokens`` table across all chats.

    Attributes:
        version: Migration version number (24).
        description: Human-readable description of the migration.
    """

    version: int = 24
    """The version number of this migration."""
    description: str = "Add secondary index on bayes_tokens (updated_at)"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create the idx_bayes_tokens_updated_at index.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_bayes_tokens_updated_at
                    ON bayes_tokens (updated_at)
                """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop the idx_bayes_tokens_updated_at index.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_bayes_tokens_updated_at"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration024AddBayesTokensUpdatedAtIndex
