"""Integration tests for DatabaseStatsStorage."""

import datetime
import uuid
from typing import Any
from unittest.mock import patch

from internal.database import utils as dbUtils
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


# ----------------------------------------------------------------------
# Purge tests
# ----------------------------------------------------------------------


async def testPurgeDeletesOnlyProcessedOldEvents(statsStorage: DatabaseStatsStorage) -> None:
    """Verify purge deletes only processed+old events.

    Seed:
    - Old processed (created 40 days ago) → should be deleted
    - Fresh processed (created now) → should survive
    - Old unprocessed (created 40 days ago) → should survive

    Returns:
        None
    """
    now = datetime.datetime.now(datetime.UTC)
    oldTimestamp = now - datetime.timedelta(days=40)

    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=False)

    # Insert old processed event
    await provider.execute(
        """INSERT INTO stat_events
           (event_id, event_type, event_time, data, labels,
            processed, processed_id, claimed_at, created_at)
           VALUES
           (:eventId1, :eventType, :eventTime, :data, :labels,
            1, NULL, NULL, :createdAt)""",
        {
            "eventId1": "old-processed-1",
            "eventType": "llm_request",
            "eventTime": oldTimestamp,
            "data": '{"tokens": 100}',
            "labels": '{"consumer":"test"}',
            "createdAt": oldTimestamp,
        },
    )

    # Insert fresh processed event
    await provider.execute(
        """INSERT INTO stat_events
           (event_id, event_type, event_time, data, labels,
            processed, processed_id, claimed_at, created_at)
           VALUES
           (:eventId2, :eventType, :eventTime, :data, :labels,
            1, NULL, NULL, :createdAt)""",
        {
            "eventId2": "fresh-processed-1",
            "eventType": "llm_request",
            "eventTime": now,
            "data": '{"tokens": 200}',
            "labels": '{"consumer":"test"}',
            "createdAt": now,
        },
    )

    # Insert old unprocessed event
    await provider.execute(
        """INSERT INTO stat_events
           (event_id, event_type, event_time, data, labels,
            processed, processed_id, claimed_at, created_at)
           VALUES
           (:eventId3, :eventType, :eventTime, :data, :labels,
            0, NULL, NULL, :createdAt)""",
        {
            "eventId3": "old-unprocessed-1",
            "eventType": "llm_request",
            "eventTime": oldTimestamp,
            "data": '{"tokens": 300}',
            "labels": '{"consumer":"test"}',
            "createdAt": oldTimestamp,
        },
    )

    # Purge with 30-day retention
    deleted = await statsStorage.purgeProcessed(retentionDays=30)

    # Should delete exactly 1 row (old processed)
    assert deleted == 1

    # Verify only old-processed-1 is gone
    remainingRows = await provider.executeFetchAll(
        """SELECT event_id FROM stat_events""",
    )
    remainingIds = {r["event_id"] for r in remainingRows}
    assert remainingIds == {"fresh-processed-1", "old-unprocessed-1"}


async def testPurgeReturnsCorrectCount(statsStorage: DatabaseStatsStorage) -> None:
    """Verify purge returns the correct count of deleted rows.

    Returns:
        None
    """
    now = datetime.datetime.now(datetime.UTC)
    oldTimestamp = now - datetime.timedelta(days=40)

    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=False)

    # Insert 5 old processed events
    for i in range(5):
        await provider.execute(
            """INSERT INTO stat_events
               (event_id, event_type, event_time, data, labels,
                processed, processed_id, claimed_at, created_at)
               VALUES
               (:eventId, :eventType, :eventTime, :data, :labels,
                1, NULL, NULL, :createdAt)""",
            {
                "eventId": f"old-processed-{i}",
                "eventType": "llm_request",
                "eventTime": oldTimestamp,
                "data": '{"tokens": 100}',
                "labels": '{"consumer":"test"}',
                "createdAt": oldTimestamp,
            },
        )

    # Purge with 30-day retention
    deleted = await statsStorage.purgeProcessed(retentionDays=30)

    assert deleted == 5

    # Verify all are gone
    remainingRows = await provider.executeFetchAll(
        """SELECT COUNT(*) AS cnt FROM stat_events""",
    )
    assert remainingRows[0]["cnt"] == 0


async def testPurgeRetentionZeroIsNoOp(statsStorage: DatabaseStatsStorage) -> None:
    """Verify retentionDays=0 is a no-op (returns 0, deletes nothing).

    Returns:
        None
    """
    now = datetime.datetime.now(datetime.UTC)
    oldTimestamp = now - datetime.timedelta(days=40)

    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=False)

    # Insert old processed event
    await provider.execute(
        """INSERT INTO stat_events
           (event_id, event_type, event_time, data, labels,
            processed, processed_id, claimed_at, created_at)
           VALUES
           (:eventId, :eventType, :eventTime, :data, :labels,
            1, NULL, NULL, :createdAt)""",
        {
            "eventId": "old-processed-1",
            "eventType": "llm_request",
            "eventTime": oldTimestamp,
            "data": '{"tokens": 100}',
            "labels": '{"consumer":"test"}',
            "createdAt": oldTimestamp,
        },
    )

    # Purge with 0-day retention (should be no-op)
    deleted = await statsStorage.purgeProcessed(retentionDays=0)

    assert deleted == 0

    # Verify row still exists
    remainingRows = await provider.executeFetchAll(
        """SELECT COUNT(*) AS cnt FROM stat_events""",
    )
    assert remainingRows[0]["cnt"] == 1


async def testPurgeRetentionNegativeIsNoOp(statsStorage: DatabaseStatsStorage) -> None:
    """Verify negative retentionDays is a no-op (returns 0, deletes nothing).

    Returns:
        None
    """
    now = datetime.datetime.now(datetime.UTC)
    oldTimestamp = now - datetime.timedelta(days=40)

    provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=False)

    # Insert old processed event
    await provider.execute(
        """INSERT INTO stat_events
           (event_id, event_type, event_time, data, labels,
            processed, processed_id, claimed_at, created_at)
           VALUES
           (:eventId, :eventType, :eventTime, :data, :labels,
            1, NULL, NULL, :createdAt)""",
        {
            "eventId": "old-processed-1",
            "eventType": "llm_request",
            "eventTime": oldTimestamp,
            "data": '{"tokens": 100}',
            "labels": '{"consumer":"test"}',
            "createdAt": oldTimestamp,
        },
    )

    # Purge with negative retention (should be no-op)
    deleted = await statsStorage.purgeProcessed(retentionDays=-5)

    assert deleted == 0

    # Verify row still exists
    remainingRows = await provider.executeFetchAll(
        """SELECT COUNT(*) AS cnt FROM stat_events""",
    )
    assert remainingRows[0]["cnt"] == 1


async def testPurgeBoundaryExactCutoffSurvives(statsStorage: DatabaseStatsStorage) -> None:
    """Verify row created during the boundary day survives (day-truncated cutoff).

    Uses a frozen clock to guarantee deterministic timing:
    - Monkeypatch internal.database.utils.getCurrentTimestamp to return fixedNow
    - Cutoff is UTC midnight of (fixedNow - 30 days) = boundaryDayMidnight
    - Row at midnight EXACTLY → survives (strict < comparison)
    - Row at 23:59:59 on the boundary day → survives (created during the boundary day)
    - Row 1 microsecond before midnight → DELETED (created on previous day)

    Day-truncated semantics: events are deleted only once they are beyond N
    **whole** days. A row created during the boundary day (any time-of-day)
    survives; only rows from whole days before the boundary are deleted.

    Returns:
        None
    """
    # Fixed UTC timestamp for the test: 2024-06-15 12:00:00 UTC
    fixedNow = datetime.datetime(2024, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)

    # The boundary day is 30 days ago: 2024-05-16
    # Cutoff is UTC midnight of the boundary day: 2024-05-16 00:00:00 UTC
    boundaryDayMidnight = datetime.datetime(2024, 5, 16, 0, 0, 0, tzinfo=datetime.UTC)

    # One microsecond before midnight (on previous day, 2024-05-15 23:59:59.999999) → DELETED
    oneMicrosecondBeforeMidnight = boundaryDayMidnight - datetime.timedelta(microseconds=1)

    # At 23:00:00 on the boundary day (2024-05-16 23:00:00) → SURVIVES
    lateInBoundaryDay = boundaryDayMidnight + datetime.timedelta(hours=23)

    with patch.object(dbUtils, "getCurrentTimestamp", return_value=fixedNow):
        provider = await statsStorage.db.manager.getProvider(dataSource=statsStorage.dataSource, readonly=False)

        # Insert row exactly at midnight (should SURVIVE - strict <)
        await provider.execute(
            """INSERT INTO stat_events
               (event_id, event_type, event_time, data, labels,
                processed, processed_id, claimed_at, created_at)
               VALUES
               (:eventId1, :eventType, :eventTime, :data, :labels,
                1, NULL, NULL, :createdAt)""",
            {
                "eventId1": "exact-midnight",
                "eventType": "llm_request",
                "eventTime": boundaryDayMidnight,
                "data": '{"tokens": 100}',
                "labels": '{"consumer":"test"}',
                "createdAt": boundaryDayMidnight,
            },
        )

        # Insert row 1 microsecond before midnight (should be DELETED)
        await provider.execute(
            """INSERT INTO stat_events
               (event_id, event_type, event_time, data, labels,
                processed, processed_id, claimed_at, created_at)
               VALUES
               (:eventId2, :eventType, :eventTime, :data, :labels,
                1, NULL, NULL, :createdAt)""",
            {
                "eventId2": "one-us-before-midnight",
                "eventType": "llm_request",
                "eventTime": oneMicrosecondBeforeMidnight,
                "data": '{"tokens": 200}',
                "labels": '{"consumer":"test"}',
                "createdAt": oneMicrosecondBeforeMidnight,
            },
        )

        # Insert row at 23:00 on boundary day (should SURVIVE)
        await provider.execute(
            """INSERT INTO stat_events
               (event_id, event_type, event_time, data, labels,
                processed, processed_id, claimed_at, created_at)
               VALUES
               (:eventId3, :eventType, :eventTime, :data, :labels,
                1, NULL, NULL, :createdAt)""",
            {
                "eventId3": "late-in-boundary-day",
                "eventType": "llm_request",
                "eventTime": lateInBoundaryDay,
                "data": '{"tokens": 300}',
                "labels": '{"consumer":"test"}',
                "createdAt": lateInBoundaryDay,
            },
        )

        # Purge with 30-day retention (cutoff is boundaryDayMidnight)
        # The predicate is created_at < cutoff
        deleted = await statsStorage.purgeProcessed(retentionDays=30)

        # Should delete exactly 1 (the one that's 1 microsecond before midnight)
        assert deleted == 1

        # Verify exact-midnight and late-in-boundary-day still exist
        remainingRows = await provider.executeFetchAll(
            """SELECT event_id FROM stat_events""",
        )
        remainingIds = {r["event_id"] for r in remainingRows}
        assert remainingIds == {"exact-midnight", "late-in-boundary-day"}
