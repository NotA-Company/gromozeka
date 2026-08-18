"""Statistics analysis module for aggregated stats data.

Provides the StatsAnalyzer class for filtering, grouping, and aggregating
statistics data. All analysis happens in pure Python — no SQL label filtering.
This module is reusable and has no bot dependencies.
"""

import datetime
from typing import Optional

from .types import StatsAggregateDict


class PeriodType:
    """Period type constants for stat aggregation."""

    HOURLY = "hourly"
    DAILY = "daily"
    MONTHLY = "monthly"
    TOTAL = "total"


class PeriodArg:
    """Period argument constants for the /stats command."""

    ONE_DAY = "1d"
    SEVEN_DAYS = "7d"
    THIRTY_DAYS = "30d"
    ALL = "all"


def mapPeriodArgToPeriodType(periodArg: str) -> str:
    """Map a period argument to its corresponding period type.

    Args:
        periodArg: The period argument (1d, 7d, 30d, or all).

    Returns:
        The corresponding period type (hourly, daily, or total).

    Raises:
        ValueError: If periodArg is not a valid value.
    """
    mapping = {
        PeriodArg.ONE_DAY: PeriodType.HOURLY,
        PeriodArg.SEVEN_DAYS: PeriodType.DAILY,
        PeriodArg.THIRTY_DAYS: PeriodType.DAILY,
        PeriodArg.ALL: PeriodType.TOTAL,
    }
    if periodArg not in mapping:
        raise ValueError(f"Invalid periodArg: {periodArg}")
    return mapping[periodArg]


def computePeriodRange(
    periodArg: str,
) -> tuple[Optional[str], Optional[str]]:
    """Compute the period start/from/to range for a given period arg in UTC.

    Returns ISO-8601 UTC strings for the query. For 'all' period, returns
    (None, None) since the total bucket has no range. For other periods,
    returns (periodStartFrom, periodStartTo) where both are ISO-8601 strings.

    The periodStartFrom is truncated to the period start boundary to ensure
    the boundary bucket is included (e.g., 7d → 8 daily buckets including the
    current partial day).

    Args:
        periodArg: The period argument (1d, 7d, 30d, or all).

    Returns:
        A tuple of (periodStartFrom, periodStartTo). Both are ISO-8601 UTC
        strings, or None for the 'all' period.
    """
    if periodArg == PeriodArg.ALL:
        return None, None

    now = datetime.datetime.now(datetime.timezone.utc)

    if periodArg == PeriodArg.ONE_DAY:
        periodStartFrom = (now - datetime.timedelta(days=1)).replace(minute=0, second=0, microsecond=0).isoformat()
    elif periodArg == PeriodArg.SEVEN_DAYS:
        periodStartFrom = (
            (now - datetime.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        )
    elif periodArg == PeriodArg.THIRTY_DAYS:
        periodStartFrom = (
            (now - datetime.timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        )
    else:
        raise ValueError(f"Invalid periodArg: {periodArg}")

    # periodStartTo is the current time (exclusive upper bound)
    periodStartTo = now.isoformat()

    return periodStartFrom, periodStartTo


class StatsAnalyzer:
    """Analyzer for aggregated statistics data.

    Provides methods for filtering, grouping, and aggregating statistics
    data in pure Python. All operations work on the in-memory row set
    passed to __init__ and return new analyzer instances or computed values.

    The analyzer is immutable — filtering methods return new instances.
    """

    def __init__(self, rows: list[StatsAggregateDict]) -> None:
        """Initialize the analyzer with a set of aggregate rows.

        Args:
            rows: List of StatsAggregateDict rows to analyze.
        """
        self._rows = rows

    def filterByLabelIn(self, key: str, values: set[str]) -> "StatsAnalyzer":
        """Filter rows where a label's value is in the given set.

        Args:
            key: The label key to filter on (e.g., 'consumer').
            values: Set of allowed values for the label.

        Returns:
            A new StatsAnalyzer with filtered rows.
        """
        filteredRows = [row for row in self._rows if row["labels"].get(key) in values]
        return StatsAnalyzer(filteredRows)

    def filterByLabel(self, key: str, value: str) -> "StatsAnalyzer":
        """Filter rows where a label has a specific value.

        Args:
            key: The label key to filter on (e.g., 'user_id').
            value: The exact value to match.

        Returns:
            A new StatsAnalyzer with filtered rows.
        """
        return self.filterByLabelIn(key, {value})

    def sumMetric(self, metricKey: str) -> float:
        """Sum the values of a metric across all rows.

        Args:
            metricKey: The metric key to sum (e.g., 'message_count').

        Returns:
            The sum of all metric values (0.0 if no matching rows).
        """
        return sum(row["metricValue"] for row in self._rows if row["metricKey"] == metricKey)

    def groupSum(self, groupLabel: str, metricKey: str) -> list[tuple[str, float]]:
        """Group by a label value and sum a metric for each group.

        Args:
            groupLabel: The label key to group by (e.g., 'user_id').
            metricKey: The metric key to sum within each group.

        Returns:
            A list of (groupValue, sum) tuples sorted by sum descending.
        """
        groups: dict[str, float] = {}
        for row in self._rows:
            if row["metricKey"] == metricKey:
                groupValue = row["labels"].get(groupLabel, "")
                groups[groupValue] = groups.get(groupValue, 0.0) + row["metricValue"]
        # Sort by sum descending
        return sorted(groups.items(), key=lambda x: x[1], reverse=True)

    def topN(self, groupLabel: str, metricKey: str, n: int) -> list[tuple[str, float]]:
        """Get the top N groups by sum of a metric.

        Args:
            groupLabel: The label key to group by (e.g., 'user_id').
            metricKey: The metric key to sum within each group.
            n: Maximum number of top groups to return.

        Returns:
            A list of (groupValue, sum) tuples for the top N groups,
            sorted by sum descending.
        """
        grouped = self.groupSum(groupLabel, metricKey)
        return grouped[:n]

    def average(self, valueKey: str, countKey: str) -> float:
        """Compute the weighted average: Σvalue / Σcount.

        This is the correct way to compute averages across groups,
        not an average of averages.

        Args:
            valueKey: The metric key for values to sum (e.g., 'elapsed_time').
            countKey: The metric key for counts to sum (e.g., 'tool_call_count').

        Returns:
            The weighted average (0.0 if count is 0 or no matching rows).
        """
        totalValue = 0.0
        totalCount = 0.0

        for row in self._rows:
            if row["metricKey"] == valueKey:
                totalValue += row["metricValue"]
            elif row["metricKey"] == countKey:
                totalCount += row["metricValue"]

        if totalCount == 0:
            return 0.0
        return totalValue / totalCount
