"""Tests for the StatsAnalyzer class in lib/stats/analysis.

Tests cover the analysis module's filtering, grouping, aggregation, and
period computation functionality. All tests use synthetic StatsAggregateDict
rows to verify the Python-side analysis logic.
"""

import datetime
from unittest.mock import patch

from lib.stats.analysis import (
    PeriodArg,
    PeriodType,
    StatsAnalyzer,
    computePeriodRange,
    mapPeriodArgToPeriodType,
)
from lib.stats.types import StatsAggregateDict


class TestPeriodMapping:
    """Tests for period argument to period type mapping."""

    def testMapPeriodArgToPeriodType_hourlyMapsToHourly(self) -> None:
        """Verify that '<N>h' (1-24) maps to 'hourly' period type.

        Returns:
            None
        """
        assert mapPeriodArgToPeriodType("1h") == PeriodType.HOURLY
        assert mapPeriodArgToPeriodType("6h") == PeriodType.HOURLY
        assert mapPeriodArgToPeriodType("24h") == PeriodType.HOURLY

    def testMapPeriodArgToPeriodType_dailyMapsToDaily(self) -> None:
        """Verify that '<N>d' (1-31) maps to 'daily' period type.

        Returns:
            None
        """
        assert mapPeriodArgToPeriodType("1d") == PeriodType.DAILY
        assert mapPeriodArgToPeriodType("7d") == PeriodType.DAILY
        assert mapPeriodArgToPeriodType("31d") == PeriodType.DAILY

    def testMapPeriodArgToPeriodType_monthlyMapsToMonthly(self) -> None:
        """Verify that '<N>m' (N>=1) maps to 'monthly' period type.

        Returns:
            None
        """
        assert mapPeriodArgToPeriodType("1m") == PeriodType.MONTHLY
        assert mapPeriodArgToPeriodType("12m") == PeriodType.MONTHLY
        assert mapPeriodArgToPeriodType("24m") == PeriodType.MONTHLY

    def testMapPeriodArgToPeriodType_allMapsToTotal(self) -> None:
        """Verify that 'all' maps to 'total' period type.

        Returns:
            None
        """
        assert mapPeriodArgToPeriodType(PeriodArg.ALL) == PeriodType.TOTAL

    def testMapPeriodArgToPeriodType_invalidRaisesValueError(self) -> None:
        """Verify that an invalid period arg raises ValueError.

        Returns:
            None
        """
        # Invalid suffix
        try:
            mapPeriodArgToPeriodType("7x")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass

        # Out of range hours (0h, 25h)
        try:
            mapPeriodArgToPeriodType("0h")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass
        try:
            mapPeriodArgToPeriodType("25h")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass

        # Out of range days (0d, 32d)
        try:
            mapPeriodArgToPeriodType("0d")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass
        try:
            mapPeriodArgToPeriodType("32d")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass

        # Negative months (0m)
        try:
            mapPeriodArgToPeriodType("0m")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass

        # Invalid format (no number)
        try:
            mapPeriodArgToPeriodType("h")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass


class TestPeriodRangeComputation:
    """Tests for period range computation in UTC."""

    def testComputePeriodRange_allReturnsNoneNone(self) -> None:
        """Verify that 'all' period returns (None, None) for no range.

        Returns:
            None
        """
        periodStartFrom, periodStartTo = computePeriodRange(PeriodArg.ALL)
        assert periodStartFrom is None
        assert periodStartTo is None

    def testComputePeriodRange_sixHoursReturnsHourlyRange(self) -> None:
        """Verify that '6h' returns a range with hour-truncated from-bound.

        Returns:
            None
        """
        # Fixed time for deterministic testing
        fixedNow = datetime.datetime(2024, 1, 2, 14, 30, 45, 123456, tzinfo=datetime.UTC)

        with patch("lib.stats.analysis.datetime") as mockDatetime:
            mockDatetime.datetime.now.return_value = fixedNow
            mockDatetime.datetime.side_effect = lambda *args, **kwargs: datetime.datetime(*args, **kwargs)
            mockDatetime.timezone = datetime.timezone
            mockDatetime.timedelta = datetime.timedelta

            periodStartFrom, periodStartTo = computePeriodRange("6h")

        # periodStartTo should be the fixed now
        assert periodStartTo is not None
        actualTo = datetime.datetime.fromisoformat(periodStartTo)
        assert actualTo == fixedNow

        # periodStartFrom should be 6 hours ago, truncated to the hour
        assert periodStartFrom is not None
        actualFrom = datetime.datetime.fromisoformat(periodStartFrom)
        # (2024-01-02 14:30:45 - 6 hours) = 2024-01-02 08:30:45, truncated to hour = 2024-01-02 08:00:00
        expectedFrom = datetime.datetime(2024, 1, 2, 8, 0, 0, tzinfo=datetime.UTC)
        assert actualFrom == expectedFrom

    def testComputePeriodRange_sevenDaysReturnsSevenDayRange(self) -> None:
        """Verify that '7d' returns a range with day-truncated from-bound.

        The range is 7 full days plus the partial current day.

        Returns:
            None
        """
        # Fixed time for deterministic testing
        fixedNow = datetime.datetime(2024, 1, 8, 14, 30, 45, 123456, tzinfo=datetime.UTC)

        with patch("lib.stats.analysis.datetime") as mockDatetime:
            mockDatetime.datetime.now.return_value = fixedNow
            mockDatetime.datetime.side_effect = lambda *args, **kwargs: datetime.datetime(*args, **kwargs)
            mockDatetime.timezone = datetime.timezone
            mockDatetime.timedelta = datetime.timedelta

            periodStartFrom, periodStartTo = computePeriodRange("7d")

        # Verify both bounds are set
        assert periodStartFrom is not None
        assert periodStartTo is not None

        actualFrom = datetime.datetime.fromisoformat(periodStartFrom)
        actualTo = datetime.datetime.fromisoformat(periodStartTo)

        # periodStartTo should be the fixed now
        assert actualTo == fixedNow

        # periodStartFrom should be 7 days ago, truncated to the day
        # (2024-01-08 14:30:45 - 7 days) = 2024-01-01 14:30:45, truncated to day = 2024-01-01 00:00:00
        expectedFrom = datetime.datetime(2024, 1, 1, 0, 0, 0, tzinfo=datetime.UTC)
        assert actualFrom == expectedFrom

        # Range should be 7 days plus the partial current day (14:30:45.123456)
        # Calculate the partial day: 14h 30m 45.123456s = 52245.123456 seconds
        partialDaySeconds = (14 * 3600) + (30 * 60) + 45 + 0.123456
        expectedRangeSeconds = 7 * 24 * 60 * 60 + partialDaySeconds
        actualRangeSeconds = (actualTo - actualFrom).total_seconds()
        assert actualRangeSeconds == expectedRangeSeconds

    def testComputePeriodRange_twoMonthsReturnsMonthlyRange(self) -> None:
        """Verify that '2m' returns a range with month-truncated from-bound.

        This tests the calendar month arithmetic including a year-underflow case.

        Returns:
            None
        """
        # Fixed time for deterministic testing (Jan 15, 2024)
        fixedNow = datetime.datetime(2024, 1, 15, 14, 30, 45, 123456, tzinfo=datetime.UTC)

        with patch("lib.stats.analysis.datetime") as mockDatetime:
            mockDatetime.datetime.now.return_value = fixedNow
            mockDatetime.datetime.side_effect = lambda *args, **kwargs: datetime.datetime(*args, **kwargs)
            mockDatetime.timezone = datetime.timezone
            mockDatetime.timedelta = datetime.timedelta

            periodStartFrom, periodStartTo = computePeriodRange("2m")

        # Verify both bounds are set
        assert periodStartFrom is not None
        assert periodStartTo is not None

        actualFrom = datetime.datetime.fromisoformat(periodStartFrom)
        actualTo = datetime.datetime.fromisoformat(periodStartTo)

        # periodStartTo should be the fixed now
        assert actualTo == fixedNow

        # periodStartFrom should be first day of 2 calendar months back
        # 2024-01 - 2 months = 2023-11-01
        expectedFrom = datetime.datetime(2023, 11, 1, 0, 0, 0, tzinfo=datetime.UTC)
        assert actualFrom == expectedFrom

        # Range should be from 2023-11-01 to 2024-01-15 14:30:45
        # This spans parts of Nov, Dec, and Jan
        assert actualFrom.year == 2023
        assert actualFrom.month == 11
        assert actualFrom.day == 1

    def testComputePeriodRange_invalidRaisesValueError(self) -> None:
        """Verify that an invalid period arg raises ValueError.

        Returns:
            None
        """
        # Invalid suffix
        try:
            computePeriodRange("7x")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass

        # Out of range hours (0h, 25h)
        try:
            computePeriodRange("0h")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass
        try:
            computePeriodRange("25h")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass

        # Out of range days (0d, 32d)
        try:
            computePeriodRange("0d")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass
        try:
            computePeriodRange("32d")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass

        # Negative months (0m)
        try:
            computePeriodRange("0m")
            assert False, "Expected ValueError for invalid period arg"
        except ValueError:
            pass


class TestStatsAnalyzerConsumerFilter:
    """Tests for consumer filtering to exclude __global__ rows."""

    def testFilterByLabelIn_excludesGlobalRows(self) -> None:
        """Verify that filtering by consumer excludes __global__ rows.

        This tests the D3 requirement: the analyzer must filter to the target
        consumer to avoid double-counting.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"consumer": "123", "user_id": "456"},
                metricKey="message_count",
                metricValue=100.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"consumer": "__global__", "user_id": "456"},
                metricKey="message_count",
                metricValue=50.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"consumer": "789", "user_id": "456"},
                metricKey="message_count",
                metricValue=75.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        filtered = analyzer.filterByLabelIn("consumer", {"123", "789"})

        # Should exclude the __global__ row
        assert len(filtered._rows) == 2
        consumerValues = [row["labels"]["consumer"] for row in filtered._rows]
        assert "__global__" not in consumerValues
        assert "123" in consumerValues
        assert "789" in consumerValues

    def testFilterByLabel_singleConsumer(self) -> None:
        """Verify that filtering by a single consumer value works.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"consumer": "123"},
                metricKey="message_count",
                metricValue=100.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"consumer": "456"},
                metricKey="message_count",
                metricValue=200.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        filtered = analyzer.filterByLabel("consumer", "123")

        assert len(filtered._rows) == 1
        assert filtered._rows[0]["labels"]["consumer"] == "123"


class TestStatsAnalyzerSumMetric:
    """Tests for metric summing functionality."""

    def testSumMetric_sumsMatchingMetrics(self) -> None:
        """Verify that sumMetric correctly sums values for a metric key.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="message_count",
                metricValue=100.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-02T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="message_count",
                metricValue=150.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "456"},
                metricKey="command_count",
                metricValue=50.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        total = analyzer.sumMetric("message_count")

        assert total == 250.0

    def testSumMetric_noMatchingMetricsReturnsZero(self) -> None:
        """Verify that sumMetric returns 0.0 when no rows match.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="command_count",
                metricValue=50.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        total = analyzer.sumMetric("message_count")

        assert total == 0.0


class TestStatsAnalyzerGroupSum:
    """Tests for grouping and summing functionality."""

    def testGroupSum_groupsByLabelAndSums(self) -> None:
        """Verify that groupSum correctly groups by label and sums metrics.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="message_count",
                metricValue=100.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-02T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="message_count",
                metricValue=50.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "456"},
                metricKey="message_count",
                metricValue=75.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        grouped = analyzer.groupSum("user_id", "message_count")

        # Should return sorted by sum descending
        assert len(grouped) == 2
        assert grouped[0] == ("123", 150.0)
        assert grouped[1] == ("456", 75.0)

    def testGroupSum_missingLabelUsesEmptyString(self) -> None:
        """Verify that missing label values are treated as empty strings.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={},
                metricKey="message_count",
                metricValue=100.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="message_count",
                metricValue=50.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        grouped = analyzer.groupSum("user_id", "message_count")

        assert len(grouped) == 2
        # Empty string should be one of the groups
        groupValues = [g[0] for g in grouped]
        assert "" in groupValues
        assert "123" in groupValues


class TestStatsAnalyzerTopN:
    """Tests for top-N functionality."""

    def testTopN_returnsTopNGroups(self) -> None:
        """Verify that topN returns the top N groups by sum.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="message_count",
                metricValue=100.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "456"},
                metricKey="message_count",
                metricValue=75.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "789"},
                metricKey="message_count",
                metricValue=50.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "000"},
                metricKey="message_count",
                metricValue=25.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        top2 = analyzer.topN("user_id", "message_count", 2)

        assert len(top2) == 2
        assert top2[0] == ("123", 100.0)
        assert top2[1] == ("456", 75.0)

    def testTopN_nLargerThanGroupsReturnsAll(self) -> None:
        """Verify that topN returns all groups when N exceeds group count.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="message_count",
                metricValue=100.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        top10 = analyzer.topN("user_id", "message_count", 10)

        assert len(top10) == 1
        assert top10[0] == ("123", 100.0)


class TestStatsAnalyzerAverage:
    """Tests for weighted average computation."""

    def testAverage_computesWeightedAverage(self) -> None:
        """Verify that average computes Σvalue / Σcount correctly.

        This tests the D5 requirement: averages are Σvalue/Σcount, not
        an average of averages.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"toolName": "tool1"},
                metricKey="elapsed_time",
                metricValue=100.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"toolName": "tool1"},
                metricKey="tool_call_count",
                metricValue=10.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-02T00:00:00+00:00",
                labels={"toolName": "tool1"},
                metricKey="elapsed_time",
                metricValue=200.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-02T00:00:00+00:00",
                labels={"toolName": "tool1"},
                metricKey="tool_call_count",
                metricValue=20.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        avg = analyzer.average("elapsed_time", "tool_call_count")

        # (100 + 200) / (10 + 20) = 300 / 30 = 10.0
        assert avg == 10.0

    def testAverage_zeroCountReturnsZero(self) -> None:
        """Verify that average returns 0.0 when count is zero.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"toolName": "tool1"},
                metricKey="elapsed_time",
                metricValue=100.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        avg = analyzer.average("elapsed_time", "tool_call_count")

        assert avg == 0.0

    def testAverage_noMatchingRowsReturnsZero(self) -> None:
        """Verify that average returns 0.0 when no rows match.

        Returns:
            None
        """
        rows = []

        analyzer = StatsAnalyzer(rows)
        avg = analyzer.average("elapsed_time", "tool_call_count")

        assert avg == 0.0


class TestStatsAnalyzerThreeBucketSent:
    """Tests for three-bucket 'sent' rendering (D6)."""

    def testThreeBucketSent_groupsIntoUsersBotHistory(self) -> None:
        """Verify that sent label groups into three buckets: True/False/absent.

        This tests the D6 three-bucket rendering requirement for the messages
        section. Backfill rows lack the sent label, live rows always have it.

        Returns:
            None
        """
        rows = [
            # User messages (sent=False)
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "123", "sent": "False"},
                metricKey="message_count",
                metricValue=100.0,
            ),
            # Bot messages (sent=True)
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "bot", "sent": "True"},
                metricKey="message_count",
                metricValue=50.0,
            ),
            # Backfill/history (no sent label)
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "456"},
                metricKey="message_count",
                metricValue=25.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)

        # User messages (sent=False)
        userMessages = analyzer.filterByLabel("sent", "False")
        userCount = userMessages.sumMetric("message_count")
        assert userCount == 100.0

        # Bot messages (sent=True)
        botMessages = analyzer.filterByLabel("sent", "True")
        botCount = botMessages.sumMetric("message_count")
        assert botCount == 50.0

        # History (no sent label) - need to filter by absence
        # This is done by subtracting the sent=True and sent=False counts from total
        totalCount = analyzer.sumMetric("message_count")
        historyCount = totalCount - userCount - botCount
        assert historyCount == 25.0

    def testThreeBucketSent_totalIsSumOfAllBuckets(self) -> None:
        """Verify that total count is the sum of all three disjoint buckets.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"sent": "False"},
                metricKey="message_count",
                metricValue=100.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"sent": "True"},
                metricKey="message_count",
                metricValue=50.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={},
                metricKey="message_count",
                metricValue=25.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        total = analyzer.sumMetric("message_count")

        assert total == 175.0


class TestStatsAnalyzerUserDrillDown:
    """Tests for user drill-down functionality (D7)."""

    def testUserDrillDown_filtersByUserId(self) -> None:
        """Verify that user drill-down filters by user_id label.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="message_count",
                metricValue=100.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "456"},
                metricKey="message_count",
                metricValue=75.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="command_count",
                metricValue=10.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        user123Analyzer = analyzer.filterByLabel("user_id", "123")

        # Should only include user 123's rows
        assert len(user123Analyzer._rows) == 2
        assert all(row["labels"]["user_id"] == "123" for row in user123Analyzer._rows)

        # Verify metrics are only for user 123
        messages = user123Analyzer.sumMetric("message_count")
        commands = user123Analyzer.sumMetric("command_count")
        assert messages == 100.0
        assert commands == 10.0

    def testUserDrillDown_excludesLlmRequest(self) -> None:
        """Verify that llm_request events are excluded from user drill-down.

        This tests the D7 requirement: llm_request carries no user_id label
        and is therefore excluded from user drill-downs.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="message_count",
                metricValue=100.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"user_id": "123"},
                metricKey="llm_tool_call_count",
                metricValue=10.0,
            ),
            # llm_request has no user_id label - should be excluded
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"modelName": "gpt-4o"},
                metricKey="request_count",
                metricValue=50.0,
            ),
            # stt_request also has no user_id label - should be excluded
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"provider": "yandex"},
                metricKey="request_count",
                metricValue=25.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        user123Analyzer = analyzer.filterByLabel("user_id", "123")

        # Should only include rows with user_id label
        assert len(user123Analyzer._rows) == 2
        assert all("user_id" in row["labels"] for row in user123Analyzer._rows)

        # llm_request and stt_request rows should be excluded
        metricKeys = [row["metricKey"] for row in user123Analyzer._rows]
        assert "request_count" not in metricKeys  # llm_request/stt_request metric


class TestStatsAnalyzerImmutability:
    """Tests for analyzer immutability."""

    def testFilterByLabel_returnsNewInstance(self) -> None:
        """Verify that filtering returns a new analyzer instance.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"consumer": "123"},
                metricKey="message_count",
                metricValue=100.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        filtered = analyzer.filterByLabel("consumer", "123")

        # Should be different instances
        assert analyzer is not filtered

        # Original should be unchanged
        assert len(analyzer._rows) == 1

    def testMultipleFilters_chainsCorrectly(self) -> None:
        """Verify that multiple filters can be chained.

        Returns:
            None
        """
        rows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"consumer": "123", "user_id": "456", "sent": "False"},
                metricKey="message_count",
                metricValue=100.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"consumer": "123", "user_id": "789", "sent": "False"},
                metricKey="message_count",
                metricValue=75.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2024-01-01T00:00:00+00:00",
                labels={"consumer": "123", "user_id": "456", "sent": "True"},
                metricKey="message_count",
                metricValue=50.0,
            ),
        ]

        analyzer = StatsAnalyzer(rows)
        filtered = (
            analyzer.filterByLabel("consumer", "123").filterByLabel("user_id", "456").filterByLabel("sent", "False")
        )

        # Should only match the first row
        assert len(filtered._rows) == 1
        assert filtered._rows[0]["metricValue"] == 100.0
