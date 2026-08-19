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

    ALL = "all"


def mapPeriodArgToPeriodType(periodArg: str) -> str:
    """Map a period argument to its corresponding period type.

    Args:
        periodArg: The period argument (<N>h, <N>d, <N>m, or all).

    Returns:
        The corresponding period type (hourly, daily, monthly, or total).

    Raises:
        ValueError: If periodArg is not a valid value or out of range.
    """
    if periodArg == PeriodArg.ALL:
        return PeriodType.TOTAL

    # Parse <N><suffix> format
    if len(periodArg) < 2:
        raise ValueError(f"Invalid periodArg: {periodArg}")

    suffix = periodArg[-1]
    numberPart = periodArg[:-1]

    # Validate that numberPart consists only of ASCII digits (rejects +5d, 1_0h, unicode digits)
    if not (numberPart.isascii() and numberPart.isdigit()):
        raise ValueError(f"Invalid periodArg: {periodArg}")

    number = int(numberPart)

    if suffix == "h":
        if not 1 <= number <= 24:
            raise ValueError(f"Invalid periodArg: {periodArg} (hours must be 1..24)")
        return PeriodType.HOURLY
    elif suffix == "d":
        if not 1 <= number <= 31:
            raise ValueError(f"Invalid periodArg: {periodArg} (days must be 1..31)")
        return PeriodType.DAILY
    elif suffix == "m":
        if number < 1:
            raise ValueError(f"Invalid periodArg: {periodArg} (months must be >= 1)")
        return PeriodType.MONTHLY
    else:
        raise ValueError(f"Invalid periodArg: {periodArg}")


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
        periodArg: The period argument (<N>h, <N>d, <N>m, or all).

    Returns:
        A tuple of (periodStartFrom, periodStartTo). Both are ISO-8601 UTC
        strings, or None for the 'all' period.

    Raises:
        ValueError: If periodArg is invalid or out of range.
    """
    if periodArg == PeriodArg.ALL:
        return None, None

    now = datetime.datetime.now(datetime.timezone.utc)

    # Parse <N><suffix> format
    if len(periodArg) < 2:
        raise ValueError(f"Invalid periodArg: {periodArg}")

    suffix = periodArg[-1]
    numberPart = periodArg[:-1]

    # Validate that numberPart consists only of ASCII digits (rejects +5d, 1_0h, unicode digits)
    if not (numberPart.isascii() and numberPart.isdigit()):
        raise ValueError(f"Invalid periodArg: {periodArg}")

    number = int(numberPart)

    if suffix == "h":
        # <N>h: from = now - N hours, truncated to the hour
        if not 1 <= number <= 24:
            raise ValueError(f"Invalid periodArg: {periodArg} (hours must be 1..24)")
        periodStartFrom = (
            (now - datetime.timedelta(hours=number)).replace(minute=0, second=0, microsecond=0).isoformat()
        )
    elif suffix == "d":
        # <N>d: from = now - N days, truncated to the day
        if not 1 <= number <= 31:
            raise ValueError(f"Invalid periodArg: {periodArg} (days must be 1..31)")
        periodStartFrom = (
            (now - datetime.timedelta(days=number)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        )
    elif suffix == "m":
        # <N>m: from = first day of the month N calendar months back
        if number < 1:
            raise ValueError(f"Invalid periodArg: {periodArg} (months must be >= 1)")
        # Calculate the target month using year*12 + month arithmetic to avoid date clamp issues
        currentYear = now.year
        currentMonth = now.month
        currentMonthNumber = currentYear * 12 + (currentMonth - 1)
        targetMonthNumber = currentMonthNumber - number
        targetYear = targetMonthNumber // 12
        targetMonth = (targetMonthNumber % 12) + 1
        periodStartFrom = datetime.datetime(
            targetYear, targetMonth, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
        ).isoformat()
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

    @property
    def rows(self) -> list[StatsAggregateDict]:
        """Get the current rows.

        Returns:
            List of StatsAggregateDict rows currently in the analyzer.
        """
        return self._rows

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
