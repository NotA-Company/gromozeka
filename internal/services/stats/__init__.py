"""Stats aggregation service package.

Provides :class:`StatsAggregationService` (singleton) that registers a handler
on the shared CRON_JOB 60-second tick and gates on elapsed time. Owns the
storage factory + registry — the single construction seam for stats storages.

Usage::

    from internal.services.stats import StatsAggregationService
    StatsAggregationService.getInstance().initialize(configManager, database)
    llmStorage = StatsAggregationService.getInstance().createStatsStorage("llm_request")
"""

from .service import MAX_AGGREGATION_ROUNDS, StatsAggregationService

__all__ = [
    "StatsAggregationService",
    "MAX_AGGREGATION_ROUNDS",
]
