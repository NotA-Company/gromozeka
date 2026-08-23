"""TypedDict types for the stats library.

Provides type-hinted dictionaries for aggregated statistics data.
These types follow the camelCase convention for API-level structures
(per project conventions), distinct from snake_case DB row structures.
"""

from typing import TypedDict

# Default row limit for stats queries (10,000 rows balances memory usage and completeness)
STATS_QUERY_ROW_LIMIT: int = 10000


class StatsAggregateDict(TypedDict):
    """Single aggregated statistics row with parsed labels.

    Represents one row from the stat_aggregates table with labels parsed
    from JSON into a dict. Uses camelCase field names per project convention
    for API-level structures (vs snake_case DB row structures like StatsEventDict).

    Attributes:
        periodType: Period granularity ('hourly', 'daily', 'monthly', or 'total').
        periodStart: ISO-8601 UTC timestamp for the period start, or the epoch
            sentinel for 'total' periods.
        labels: Parsed labels dictionary (e.g., consumer, user_id, modelName).
        metricKey: Metric name (e.g., 'tokens', 'requests', 'elapsed_time').
        metricValue: Aggregated numeric value (sum over the period/label combo).
    """

    periodType: str
    periodStart: str
    labels: dict[str, str]
    metricKey: str
    metricValue: float
