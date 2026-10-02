"""Unit tests for NullStatsStorage."""

from lib.stats import NullStatsStorage


async def testNullRecordDoesNotRaise() -> None:
    """Verify record() on NullStatsStorage does not raise.

    Returns:
        None
    """
    storage = NullStatsStorage()
    await storage.record({"foo": 1}, consumerId="test")


async def testNullRecordWithLabelsDoesNotRaise() -> None:
    """Verify record() with labels does not raise.

    Returns:
        None
    """
    storage = NullStatsStorage()
    await storage.record(
        {"foo": 1},
        consumerId="test",
        labels={"model": "gpt-4o"},
    )


async def testNullAggregateReturnsZero() -> None:
    """Verify aggregate() returns 0 for NullStatsStorage.

    Returns:
        None
    """
    storage = NullStatsStorage()
    result = await storage.aggregate()
    assert result == 0


async def testNullAggregateWithLimit() -> None:
    """Verify aggregate() with custom limit returns 0.

    Returns:
        None
    """
    storage = NullStatsStorage()
    result = await storage.aggregate(limit=500)
    assert result == 0


async def testNullPurgeProcessedReturnsZero() -> None:
    """Verify purgeProcessed() returns 0 for NullStatsStorage.

    Returns:
        None
    """
    storage = NullStatsStorage()
    result = await storage.purgeProcessed(retentionDays=30)
    assert result == 0


async def testNullPurgeProcessedWithZeroRetention() -> None:
    """Verify purgeProcessed() with 0 retention returns 0.

    Returns:
        None
    """
    storage = NullStatsStorage()
    result = await storage.purgeProcessed(retentionDays=0)
    assert result == 0


async def testNullQueryReturnsEmptyList() -> None:
    """Verify query() on NullStatsStorage returns empty list.

    Returns:
        None
    """
    storage = NullStatsStorage()
    result = await storage.query(eventType="llm_request")

    assert result == []


async def testNullQueryWithFiltersReturnsEmptyList() -> None:
    """Verify query() with all filters on NullStatsStorage returns empty list.

    Returns:
        None
    """
    storage = NullStatsStorage()
    result = await storage.query(
        eventType="llm_request",
        periodType="daily",
        periodStartFrom="2024-01-01T00:00:00+00:00",
        periodStartTo="2024-01-31T23:59:59+00:00",
        limit=100,
    )

    assert result == []
