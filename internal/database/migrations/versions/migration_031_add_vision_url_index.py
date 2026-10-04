"""Add composite index for the vision TTL-GC retained-keys lookup.

This migration (version 31) adds an index on ``(vision_url, updated_at)`` to
``media_attachments`` to support the vision TTL garbage collector
(``HandlersManager._visionGcCronJob``, hourly):

- The EXIST retention probe inside the GC's combined sweep-input statement
  (``MediaAttachmentsRepository.getExpiredVisionAttachmentsWithRetention``)
  checks, for every EXPIRED row (``updated_at < cutoff``,
  ``vision_url IS NOT NULL``), whether any LIVE row
  (``updated_at >= cutoff``) shares the same ``vision_url``. The composite
  index lets that probe find each expired key's live sharers without a full
  scan per candidate.
- The statement's expired-rows filter
  (``WHERE vision_url IS NOT NULL AND updated_at < cutoff``) gets a
  covering-check on its non-null subset from the same index.

The index follows the TTL-index precedent from migration_012
(``idx_cache_updated_at``, created specifically for cache cleanup) and
migration_028 (``idx_stat_events_retention``).

**Schema change:**

- Adds ``idx_media_attachments_vision_url_updated_at`` on
  ``media_attachments (vision_url, updated_at)``

**Backward compatibility:** Safe — the index is optional and only affects
query performance. The migration uses ``CREATE INDEX IF NOT EXISTS`` to be
idempotent.

**Reversible:** ``down()`` drops the index with ``DROP INDEX IF EXISTS``.
"""

from typing import Type

from lib.db.providers import BaseSQLProvider, ParametrizedQuery

from ..base import BaseMigration


class Migration031AddVisionUrlIndex(BaseMigration):
    """Add composite index for the vision TTL-GC retained-keys lookup.

    This migration adds an index on (vision_url, updated_at) to support the
    vision TTL garbage collector's combined snapshot statement
    (``getExpiredVisionAttachmentsWithRetention``): its EXIST retention
    probe and its expired-rows filter.

    Attributes:
        version: Migration version number (31).
        description: Human-readable description of the migration.
    """

    version: int = 31
    """The version number of this migration."""
    description: str = "Add index on media_attachments (vision_url, updated_at)"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create the composite vision-url index on media_attachments.

        Args:
            sqlProvider: SQL provider for executing the migration.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                # NOT stock-MySQL syntax (CREATE INDEX IF NOT EXISTS); kept for consistency
                # with the migration_028 house precedent — long-term fix: provider-level index hooks.
                ParametrizedQuery("""CREATE INDEX IF NOT EXISTS idx_media_attachments_vision_url_updated_at
                       ON media_attachments (vision_url, updated_at)"""),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop the composite vision-url index.

        Args:
            sqlProvider: SQL provider for executing the migration.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                # NOT stock-MySQL syntax (standalone DROP INDEX IF EXISTS); kept for consistency
                # with the migration_028 house precedent — long-term fix: provider-level index hooks.
                ParametrizedQuery("DROP INDEX IF EXISTS idx_media_attachments_vision_url_updated_at"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration031AddVisionUrlIndex
