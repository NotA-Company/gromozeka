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
