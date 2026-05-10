"""Statistics collection library for Gromozeka.

Provides a generic, storage-agnostic interface for recording time-series
statistics events and aggregating them into periodic buckets.

Labels provide a generic dimension system for slicing aggregates by
consumer, model, provider, generation type, and any future dimensions.

    Example:
        >>> from lib.stats import StatsStorage, NullStatsStorage
        >>> storage = NullStatsStorage()
        >>> await storage.record(
        ...     {"tokens": 150},
        ...     consumerId="chat_123",
        ...     labels={"model": "gpt-4o", "provider": "openrouter"},
        ... )
"""

from .stats_storage import GLOBAL_CONSUMER_ID, NullStatsStorage, StatsStorage

__all__ = ["GLOBAL_CONSUMER_ID", "NullStatsStorage", "StatsStorage"]
