"""Integration tests for DatabaseStatsStorage."""

import datetime
import uuid
from typing import Any

from internal.database.stats_storage import DatabaseStatsStorage
from lib.stats.stats_storage import GLOBAL_CONSUMER_ID


async def testRecordAndAggregateSingleEvent(statsStorage: DatabaseStatsStorage) -> None:
    """Record one event, aggregate, verify per-consumer and global rows exist.

    Returns:
        None
    """
    await statsStorage.record(
        {"tokens": 150, "requests": 1},
        consumerId="chat_42",
        labels={"modelName": "gpt-4o", "provider": "openai"},
    )
    processed = await statsStorage.aggregate()
    assert processed == 1

    # Read back from stat_aggregates directly
    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=True)
    rows = await provider.executeFetchAll(
        "SELECT * FROM stat_aggregates WHERE event_type = :eventType",
        {"eventType": "llm_request"},
    )
    assert len(rows) > 0

    # Should have at least hourly, daily, monthly, total for per-consumer AND global
    # Each period appears twice (per-consumer + global rollup), so 8 rows minimum
    assert len(rows) >= 8

    # Check that we have rows for both consumer-specific and global labels
    consumerRows = [r for r in rows if GLOBAL_CONSUMER_ID not in r["labels"]]
    globalRows = [r for r in rows if GLOBAL_CONSUMER_ID in r["labels"]]
    assert len(consumerRows) >= 4
    assert len(globalRows) >= 4


async def testAggregateEmptyReturnsZero(statsStorage: DatabaseStatsStorage) -> None:
    """No events recorded, aggregate returns 0.

    Returns:
        None
    """
    result = await statsStorage.aggregate()
    assert result == 0


async def testAggregateRespectsLimit(statsStorage: DatabaseStatsStorage) -> None:
    """Claim limit is honored across multiple aggregate calls.

    Returns:
        None
    """
    # Record 3 events
    for i in range(3):
        await statsStorage.record(
            {"count": 1},
            consumerId="chat_1",
            labels={"i": str(i)},
        )
    # Aggregate with limit=2
    first = await statsStorage.aggregate(limit=2)
    assert first == 2
    # Second call should claim remaining 1
    second = await statsStorage.aggregate(limit=2)
    assert second == 1
    # Third call should find nothing
    third = await statsStorage.aggregate(limit=2)
    assert third == 0


async def testOrphanReclaim(statsStorage: DatabaseStatsStorage) -> None:
    """Manually set old claimed_at, verify aggregate picks them up.

    Returns:
        None
    """
    await statsStorage.record(
        {"tokens": 10},
        consumerId="chat_42",
    )

    # Manually claim the event with an old timestamp
    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=False)
    oldClaimed = datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC)
    batchId = str(uuid.uuid4())
    await provider.execute(
        """UPDATE stat_events
           SET processed_id = :batchId,
               claimed_at = :oldClaimed
           WHERE processed = 0""",
        {"batchId": batchId, "oldClaimed": oldClaimed},
    )

    # aggregate should reclaim the orphaned event (orphanTimeoutSeconds=1)
    processed = await statsStorage.aggregate(orphanTimeoutSeconds=1)
    assert processed == 1


async def testOrphanNotReclaimedWhenFresh(statsStorage: DatabaseStatsStorage) -> None:
    """Recent claim is not reclaimed - verify orphan timeout is respected.

    Returns:
        None
    """
    await statsStorage.record(
        {"tokens": 10},
        consumerId="chat_42",
    )

    # Claim normally (fresh timestamp)
    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=False)
    now = datetime.datetime.now(datetime.UTC)
    batchId = str(uuid.uuid4())
    await provider.execute(
        """UPDATE stat_events
           SET processed_id = :batchId,
               claimed_at = :now
           WHERE processed = 0""",
        {"batchId": batchId, "now": now},
    )

    # aggregate with a large orphan timeout should NOT reclaim the fresh claim
    processed = await statsStorage.aggregate(orphanTimeoutSeconds=3600)
    assert processed == 0  # fresh claim is not an orphan


async def testMultiplePeriods(statsStorage: DatabaseStatsStorage) -> None:
    """Event at 14:30 produces hourly (14:00), daily (00:00), monthly (day 1), total (epoch).

    Returns:
        None
    """
    eventTime = datetime.datetime(2024, 6, 15, 14, 30, 0, tzinfo=datetime.UTC)
    await statsStorage.record(
        {"tokens": 100},
        consumerId="chat_1",
        eventTime=eventTime,
    )
    processed = await statsStorage.aggregate()
    assert processed == 1

    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=True)
    rows = await provider.executeFetchAll(
        """SELECT period_type, period_start, labels_hash FROM stat_aggregates
           WHERE event_type = :eventType AND metric_key = 'tokens'
           GROUP BY period_type, period_start, labels_hash""",
        {"eventType": "llm_request"},
    )

    periodTypes = {r["period_type"] for r in rows}
    assert periodTypes == {"hourly", "daily", "monthly", "total"}

    # Find hourly rows and verify truncation
    expectedHourly = datetime.datetime(2024, 6, 15, 14, 0, 0, tzinfo=datetime.UTC).isoformat()
    expectedDaily = datetime.datetime(2024, 6, 15, 0, 0, 0, tzinfo=datetime.UTC).isoformat()

    hourlyStarts = {r["period_start"] for r in rows if r["period_type"] == "hourly"}
    dailyStarts = {r["period_start"] for r in rows if r["period_type"] == "daily"}

    assert expectedHourly in hourlyStarts
    assert expectedDaily in dailyStarts


async def testMultipleConsumers(statsStorage: DatabaseStatsStorage) -> None:
    """Verify aggregates are separated by labels_hash (different consumers).

    Returns:
        None
    """
    await statsStorage.record(
        {"tokens": 10},
        consumerId="chat_A",
        labels={"model": "m1"},
    )
    await statsStorage.record(
        {"tokens": 20},
        consumerId="chat_B",
        labels={"model": "m1"},
    )
    processed = await statsStorage.aggregate()
    assert processed == 2

    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=True)
    rows = await provider.executeFetchAll(
        """SELECT labels, metric_value FROM stat_aggregates
           WHERE event_type = :eventType AND metric_key = 'tokens' AND period_type = 'total'
           ORDER BY labels""",
        {"eventType": "llm_request"},
    )

    # Should have at least 2 separate consumer entries + 1 global entry
    consumerValues = [r for r in rows if GLOBAL_CONSUMER_ID not in r["labels"]]
    assert len(consumerValues) >= 2

    # Each consumer's tokens should be correct
    import json

    valuesByConsumer = {}
    for r in consumerValues:
        labels = json.loads(r["labels"])
        consumer = labels.get("consumer", "")
        valuesByConsumer[consumer] = r["metric_value"]
    assert valuesByConsumer.get("chat_A") == 10.0
    assert valuesByConsumer.get("chat_B") == 20.0

    # Global should sum both
    globalRows = [r for r in rows if GLOBAL_CONSUMER_ID in r["labels"]]
    assert len(globalRows) >= 1
    # Global might sum both consumer rows or each consumer row creates its own global
    # depending on label differences
    globalSum = sum(r["metric_value"] for r in globalRows)
    assert globalSum == 30.0


async def testGlobalRollup(statsStorage: DatabaseStatsStorage) -> None:
    """Verify __global__ consumer rollup is produced for every event.

    Returns:
        None
    """
    await statsStorage.record(
        {"tokens": 50},
        consumerId="chat_X",
        labels={"modelName": "test-model"},
    )
    processed = await statsStorage.aggregate()
    assert processed == 1

    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=True)
    rows = await provider.executeFetchAll(
        """SELECT labels, metric_value FROM stat_aggregates
           WHERE event_type = :eventType AND metric_key = 'tokens' AND period_type = 'total'""",
        {"eventType": "llm_request"},
    )

    globalRows = [r for r in rows if GLOBAL_CONSUMER_ID in r["labels"]]
    assert len(globalRows) >= 1
    assert globalRows[0]["metric_value"] == 50.0


async def testTimestampNormalization(statsStorage: DatabaseStatsStorage) -> None:
    """ISO string from DB is correctly parsed by _normalizeDatetime.

    Returns:
        None
    """
    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=False)
    eventId = testTimestampNormalization.__name__  # Use test name as unique ID
    now = datetime.datetime.now(datetime.UTC)

    await provider.execute(
        """INSERT INTO stat_events
           (event_id, event_type, event_time, data, labels,
            processed, processed_id, claimed_at, created_at)
           VALUES
           (:eventId, :eventType, :eventTime, :data, :labels,
            0, NULL, NULL, :createdAt)""",
        {
            "eventId": eventId,
            "eventType": "llm_request",
            "eventTime": "2024-06-15T14:30:00+00:00",
            "data": '{"tokens": 1}',
            "labels": '{"consumer":"test"}',
            "createdAt": now,
        },
    )

    processed = await statsStorage.aggregate(limit=100)
    assert processed == 1

    # Verify it was aggregated
    readProvider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=True)
    rows = await readProvider.executeFetchAll(
        """SELECT * FROM stat_aggregates WHERE event_type = :eventType""",
        {"eventType": "llm_request"},
    )
    assert len(rows) > 0


async def testRecordNonFiniteValues(statsStorage: DatabaseStatsStorage) -> None:
    """NaN/Inf values are skipped during aggregation without crashes.

    Returns:
        None
    """
    await statsStorage.record(
        {"normal": 10, "infinite": float("inf"), "nan": float("nan")},
        consumerId="chat_1",
    )
    processed = await statsStorage.aggregate()
    assert processed == 1

    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=True)
    rows = await provider.executeFetchAll(
        """SELECT metric_key, metric_value FROM stat_aggregates
           WHERE event_type = :eventType""",
        {"eventType": "llm_request"},
    )

    metricKeys = {r["metric_key"] for r in rows}
    assert "normal" in metricKeys
    assert "infinite" not in metricKeys
    assert "nan" not in metricKeys


async def testRecordHandlesDataError(statsStorage: DatabaseStatsStorage) -> None:
    """Test that record() handles non-serializable data gracefully.

    When stats contains data that can't be serialized to JSON, record()
    should catch the exception and not raise.

    Returns:
        None
    """
    # Record with stats that contain a circular reference
    # This should trigger a JSON serialization error inside record()
    # The error should be caught and logged, not raised

    # Create a dict with a circular reference
    circular_dict: dict[str, Any] = {"tokens": 1}
    circular_dict["self"] = circular_dict  # type: ignore[assignment]

    # This should not raise - record() catches all exceptions
    await statsStorage.record(
        circular_dict,  # type: ignore[arg-type]
        consumerId="chat_error",
    )

    # If we reach here without exception, the test passes
    assert True
