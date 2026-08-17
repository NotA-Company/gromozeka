"""Add retention index for processed stat_events.

This migration (version 28) adds an index on ``(processed, created_at)`` to support
efficient deletion of processed events older than the retention window. The retention
purge query is ``WHERE processed = 1 AND created_at < :cutoff``, and this index
covers that predicate.

The index follows the TTL-index precedent from migration_012
(`idx_cache_updated_at` created specifically for cache cleanup).

**Schema change:**

- Adds ``idx_stat_events_retention`` on ``stat_events (processed, created_at)``

**Backward compatibility:** Safe — the index is optional and only affects query
performance. The migration uses ``CREATE INDEX IF NOT EXISTS`` to be idempotent.

**Reversible:** ``down()`` drops the index with ``DROP INDEX IF EXISTS``.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration028AddStatEventsRetentionIndex(BaseMigration):
    """Add retention index for processed stat_events.

    This migration adds an index on (processed, created_at) to support efficient
    deletion of processed events older than the retention window.

    Attributes:
        version: Migration version number (28).
        description: Human-readable description of the migration.
    """

    version: int = 28
    """The version number of this migration."""
    description: str = "Add retention index on stat_events (processed, created_at)"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create the retention index on stat_events.

        Args:
            sqlProvider: SQL provider for executing the migration.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""CREATE INDEX IF NOT EXISTS idx_stat_events_retention
                       ON stat_events (processed, created_at)"""),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop the retention index.

        Args:
            sqlProvider: SQL provider for executing the migration.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_stat_events_retention"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration028AddStatEventsRetentionIndex
