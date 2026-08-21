"""Abstract stats storage interface with null implementation."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from .types import STATS_QUERY_ROW_LIMIT, StatsAggregateDict

# Sentinel consumer ID for global (all-consumer) aggregation
GLOBAL_CONSUMER_ID = "__global__"


class StatsStorage(ABC):
    """Abstract storage for time-series statistics with batch aggregation.

    Implementations may be backed by a database, file system, or nothing
    (NullStatsStorage). The interface separates raw event recording from
    batch aggregation, allowing callers to write events at high frequency
    and aggregate periodically.

    Labels provide a generic dimension system. For LLM events, labels
    should include at least: ``consumer`` (from consumerId), ``modelName``,
    ``modelId``, ``provider``, ``generationType``. The aggregation layer
    automatically produces a ``__global__`` rollup for each unique labels
    combination (substituting consumer with ``GLOBAL_CONSUMER_ID``).
    """

    @property
    @abstractmethod
    def dataSource(self) -> str:
        """Return the data source identifier for this storage.

        Multiple storages may share the same data source (e.g., multiple
        event types using the same database). The aggregation service uses
        this to deduplicate purge operations across storages on the same
        datasource.

        Returns:
            The data source identifier (e.g., 'default', 'custom_ds', 'null').
        """
        ...

    @abstractmethod
    async def record(
        self,
        stats: dict[str, float | int],
        *,
        consumerId: Optional[str] = None,
        labels: Optional[dict[str, str]] = None,
        eventTime: Optional[datetime] = None,
    ) -> None:
        """Append a raw stat event to the log.

        The ``consumerId`` is merged into ``labels`` as ``{"consumer": consumerId}``.
        If both ``consumerId`` and ``labels["consumer"]`` are provided, ``consumerId``
        takes precedence.

        Implementations SHOULD be best-effort: failures during recording must not
        propagate to the caller. Log and return silently on error.

        Args:
            stats: Metric key -> numeric value dict. All values must be finite float or int.
            consumerId: Consumer identifier (e.g. str(chatId)). Merged into labels.
            labels: Additional dimension labels (e.g. modelName, provider, generationType).
            eventTime: When the event occurred; defaults to now (UTC).

        Returns:
            None
        """
        ...

    @abstractmethod
    async def aggregate(self, *, limit: int = 1000, orphanTimeoutSeconds: int = 3600) -> int:
        """Claim up to ``limit`` unprocessed (or orphaned) events, aggregate into
        hourly/daily/monthly/total buckets, upsert into the aggregation table,
        and mark events as processed.

        The claim step uses a single UPDATE that picks rows where
        ``processed = 0 AND (processed_id IS NULL OR claimed_at < :orphanTimeout)``,
        so stale claims from a crashed prior aggregation are reclaimed in-place
        without a separate cleanup pass.

        For each event, aggregation produces rows for:
        - The event's own labels (per-consumer, per-model, etc.)
        - A global rollup where ``consumer`` is replaced with ``GLOBAL_CONSUMER_ID``

        Args:
            limit: Maximum number of unprocessed events to claim in one batch.
            orphanTimeoutSeconds: Age in seconds after which a claimed-but-unprocessed
                row is considered orphaned and eligible for reclaim. Default 3600 (1 hour).

        Returns:
            Number of events processed (0 if nothing to do).
        """
        ...

    @abstractmethod
    async def purgeProcessed(self, *, retentionDays: int) -> int:
        """Delete processed stat events older than the retention window.

        Deletes rows with ``processed = 1 AND created_at < truncateToDay(now -
        retentionDays)`` (UTC midnight of N days ago, day-truncated) through
        this storage's own data source. ``retentionDays <= 0`` is a no-op
        (keep forever). Errors propagate to the caller (matching ``aggregate()``'s
        contract — isolation is the coordinator's job); ``record()`` remains the
        only never-raise method.

        Note: The database implementation (DatabaseStatsStorage) purges
        type-agnostically across all event types on its datasource (no
        ``event_type`` filter in the DELETE predicate), so the first purge
        pass for a given datasource cleans all processed rows regardless of type.

        Args:
            retentionDays: Minimum age in days for a processed row to be deleted.

        Returns:
            Number of rows deleted (0 if nothing was eligible or retention is off).
        """
        ...

    @abstractmethod
    async def query(
        self,
        *,
        eventType: str,
        periodType: Optional[str] = None,
        periodStartFrom: Optional[str] = None,
        periodStartTo: Optional[str] = None,
        limit: int = STATS_QUERY_ROW_LIMIT,
        offset: int = 0,
    ) -> list[StatsAggregateDict]:
        """Read aggregated rows with parsed labels.

        Queries the ``stat_aggregates`` table for rows matching the given
        criteria and returns them with labels parsed from JSON into dicts.
        The ``eventType`` parameter is a query filter (not tied to this
        storage's per-instance eventType), enabling cross-eventType views.

        Args:
            eventType: Event type discriminator to filter on (required).
            periodType: Optional period type filter ('hourly', 'daily',
                'monthly', or 'total'). None = all period types.
            periodStartFrom: Optional ISO-8601 UTC timestamp lower bound
                (inclusive). String comparison works for lexicographic ordering.
            periodStartTo: Optional ISO-8601 UTC timestamp upper bound
                (inclusive). String comparison works for lexicographic ordering.
            limit: Maximum number of rows to return (default STATS_QUERY_ROW_LIMIT).
            offset: Number of rows to skip before returning results (default 0).

        Returns:
            List of StatsAggregateDict objects with parsed labels dicts.
            Empty list if no rows match.

        Raises:
            Database or provider errors on failure (raise-on-error contract,
            matching ``aggregate()`` and ``purgeProcessed()``).
        """
        ...


class NullStatsStorage(StatsStorage):
    """No-op storage — discards all events, ``aggregate()`` is a no-op.

    Use when statistics collection is disabled in configuration.
    """

    @property
    def dataSource(self) -> str:
        """Return 'null' as the data source identifier.

        Returns:
            The string 'null'.
        """
        return "null"

    async def record(
        self,
        stats: dict[str, float | int],
        *,
        consumerId: Optional[str] = None,
        labels: Optional[dict[str, str]] = None,
        eventTime: Optional[datetime] = None,
    ) -> None:
        """Discard the event (no-op).

        Args:
            stats: Ignored.
            consumerId: Ignored.
            labels: Ignored.
            eventTime: Ignored.

        Returns:
            None
        """
        pass

    async def aggregate(self, *, limit: int = 1000, orphanTimeoutSeconds: int = 3600) -> int:
        """No-op — returns 0.

        Args:
            limit: Ignored.
            orphanTimeoutSeconds: Ignored.

        Returns:
            0
        """
        return 0

    async def purgeProcessed(self, *, retentionDays: int) -> int:
        """No-op — returns 0.

        Args:
            retentionDays: Ignored.

        Returns:
            0
        """
        return 0

    async def query(
        self,
        *,
        eventType: str,
        periodType: Optional[str] = None,
        periodStartFrom: Optional[str] = None,
        periodStartTo: Optional[str] = None,
        limit: int = STATS_QUERY_ROW_LIMIT,
        offset: int = 0,
    ) -> list[StatsAggregateDict]:
        """No-op — returns empty list.

        Args:
            eventType: Ignored.
            periodType: Ignored.
            periodStartFrom: Ignored.
            periodStartTo: Ignored.
            limit: Ignored.
            offset: Ignored.

        Returns:
            Empty list.
        """
        return []
