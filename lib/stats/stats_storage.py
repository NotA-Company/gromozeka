"""Abstract stats storage interface with null implementation."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

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


class NullStatsStorage(StatsStorage):
    """No-op storage — discards all events, ``aggregate()`` is a no-op.

    Use when statistics collection is disabled in configuration.
    """

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
