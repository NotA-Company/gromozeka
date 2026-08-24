"""Integration tests for DatabaseStatsStorage."""

import datetime
import json
import uuid
from typing import Any
from unittest.mock import patch

from internal.database import Database
from internal.database.migrations.versions.migration_016_add_stat_tables import getMigration
from internal.database.stats_storage import DatabaseStatsStorage
from lib.db import utils as dbUtils
from lib.db.manager import DatabaseManagerConfig
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
    - Monkeypatch lib.db.utils.getCurrentTimestamp to return fixedNow
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


# ----------------------------------------------------------------------
# Regression test for Gate-2 critical defect: multi-eventType isolation
# ----------------------------------------------------------------------


async def testMultiEventTypeIsolation(statsStorage: DatabaseStatsStorage) -> None:
    """Verify aggregate() claims only events of its own eventType.

    Regression test for Gate-2 critical defect: when multiple storages
    share one stat_events table, each aggregate() call must claim and
    process ONLY events matching its own eventType. Without this filter,
    the first storage to drain claims ALL unprocessed rows of ALL types
    and corrupts the stat_aggregates PK dimension (event_type becomes
    the first storage's type for all rows).

    Seed:
    - Two storages sharing one database: commandStorage (eventType="command")
      and messageStorage (eventType="message")
    - 3 command events (count metric)
    - 3 message events (tokens metric)

    Test sequence:
    1. commandStorage.aggregate() should process ONLY command events (return 3)
    2. stat_aggregates rows should have event_type='command' with count=3
    3. messageStorage.aggregate() should process ONLY message events (return 3)
    4. stat_aggregates rows should have event_type='message' with tokens=3

    The bug manifests as:
    - commandStorage.aggregate() returns 6 (claims both command AND message events)
    - stat_aggregates has event_type='command' rows containing both count and tokens
    - messageStorage.aggregate() returns 0 (nothing left to claim)

    Returns:
        None
    """
    from internal.database import Database
    from internal.database.migrations.versions.migration_016_add_stat_tables import (
        getMigration,
    )
    from lib.db.manager import DatabaseManagerConfig

    # Create a shared in-memory database
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            }
        },
    }
    sharedDb = Database(config)

    try:
        # Apply migration 016
        provider = await sharedDb.manager.getProvider(dataSource="default", readonly=False)
        migration = getMigration()()
        await migration.up(provider)

        # Create two storages with different eventTypes, same data source
        commandStorage = DatabaseStatsStorage(
            db=sharedDb,
            eventType="command",
            dataSource="default",
        )
        messageStorage = DatabaseStatsStorage(
            db=sharedDb,
            eventType="message",
            dataSource="default",
        )

        # Record 3 command events
        for i in range(3):
            await commandStorage.record(
                {"count": 1},
                consumerId=f"chat_{i}",
                labels={"cmd": f"/test{i}"},
            )

        # Record 3 message events
        for i in range(3):
            await messageStorage.record(
                {"tokens": 100},
                consumerId=f"chat_{i}",
                labels={"model": "gpt-4"},
            )

        # Verify 6 unprocessed events exist in stat_events
        allEvents = await provider.executeFetchAll(
            """SELECT event_type, COUNT(*) AS cnt FROM stat_events
               WHERE processed = 0
               GROUP BY event_type""",
        )
        eventTypeCounts = {r["event_type"]: r["cnt"] for r in allEvents}
        assert eventTypeCounts.get("command") == 3
        assert eventTypeCounts.get("message") == 3

        # --- BUG REPRODUCTION: commandStorage.aggregate() claims ALL events ---
        processedByCommand = await commandStorage.aggregate()

        # BUG: Without the fix, processedByCommand == 6 (claims both types)
        # FIX: With the fix, processedByCommand == 3 (claims only command events)
        assert processedByCommand == 3, f"Expected 3, got {processedByCommand} - bug reproduced!"

        # Verify aggregates have ONLY event_type='command' with count metric
        commandAggregates = await provider.executeFetchAll(
            """SELECT event_type, metric_key, metric_value, labels
               FROM stat_aggregates
               WHERE event_type = 'command' AND period_type = 'total' AND metric_key = 'count'
               ORDER BY labels""",
        )
        # 3 per-consumer (chat_0, chat_1, chat_2) + 3 global rollups (one per event)
        assert len(commandAggregates) == 6
        # All rows should have event_type='command' and metric_key='count'
        for row in commandAggregates:
            assert row["event_type"] == "command"
            assert row["metric_key"] == "count"
        # Sum all count values
        totalCount = sum(row["metric_value"] for row in commandAggregates)
        # 3 per-consumer (count=1 each) + 3 global rollups (count=1 each) = 6.0
        assert totalCount == 6.0

        # Verify NO message-type aggregates exist yet
        messageAggregates = await provider.executeFetchAll(
            """SELECT COUNT(*) AS cnt FROM stat_aggregates
               WHERE event_type = 'message'""",
        )
        assert messageAggregates[0]["cnt"] == 0

        # Verify remaining unprocessed events are ONLY message type
        remainingEvents = await provider.executeFetchAll(
            """SELECT event_type, COUNT(*) AS cnt FROM stat_events
               WHERE processed = 0
               GROUP BY event_type""",
        )
        remainingCounts = {r["event_type"]: r["cnt"] for r in remainingEvents}
        assert remainingCounts.get("command") is None
        assert remainingCounts.get("message") == 3

        # --- messageStorage.aggregate() should process remaining message events ---
        processedByMessage = await messageStorage.aggregate()

        # Should process exactly 3 message events
        assert processedByMessage == 3

        # Verify aggregates now have event_type='message' with tokens metric
        messageAggregates = await provider.executeFetchAll(
            """SELECT event_type, metric_key, metric_value, labels
               FROM stat_aggregates
               WHERE event_type = 'message' AND period_type = 'total' AND metric_key = 'tokens'
               ORDER BY labels""",
        )
        # 3 per-consumer (chat_0, chat_1, chat_2) + 1 global rollup (all same model label)
        assert len(messageAggregates) == 4
        # All rows should have event_type='message' and metric_key='tokens'
        for row in messageAggregates:
            assert row["event_type"] == "message"
            assert row["metric_key"] == "tokens"
        # Sum all tokens values
        totalTokens = sum(row["metric_value"] for row in messageAggregates)
        # 3 per-consumer (tokens=100 each) + 1 global rollup (tokens=300) = 600.0
        assert totalTokens == 600.0

        # Verify no unprocessed events remain
        allProcessed = await provider.executeFetchAll(
            """SELECT COUNT(*) AS cnt FROM stat_events WHERE processed = 0""",
        )
        assert allProcessed[0]["cnt"] == 0

    finally:
        await sharedDb.manager.closeAll()


# ----------------------------------------------------------------------
# Query API tests
# ----------------------------------------------------------------------


async def testQueryPeriodTypeFilter(statsStorage: DatabaseStatsStorage) -> None:
    """Verify query() filters by periodType correctly.

    Seed:
    - Record one event
    - Aggregate produces rows for hourly, daily, monthly, total
    - Query with periodType='daily' should return only daily rows

    Returns:
        None
    """
    await statsStorage.record(
        {"tokens": 100},
        consumerId="chat_1",
        labels={"model": "gpt-4"},
    )
    await statsStorage.aggregate()

    # Query only daily periods
    dailyRows = await statsStorage.query(eventType="llm_request", periodType="daily")

    # All returned rows should be daily
    assert len(dailyRows) > 0
    for row in dailyRows:
        assert row["periodType"] == "daily"

    # Verify no hourly or monthly rows returned
    periodTypes = {row["periodType"] for row in dailyRows}
    assert "hourly" not in periodTypes
    assert "monthly" not in periodTypes
    assert "total" not in periodTypes


async def testQueryPeriodStartRangeFilter(statsStorage: DatabaseStatsStorage) -> None:
    """Verify query() filters by periodStartFrom and periodStartTo correctly.

    Seed:
    - Record events at two different times (2024-06-15 and 2024-06-20)
    - Aggregate both
    - Query with periodStartFrom and periodStartTo should return rows in range

    Returns:
        None
    """
    eventTime1 = datetime.datetime(2024, 6, 15, 14, 30, 0, tzinfo=datetime.UTC)
    eventTime2 = datetime.datetime(2024, 6, 20, 10, 15, 0, tzinfo=datetime.UTC)

    await statsStorage.record(
        {"tokens": 100},
        consumerId="chat_1",
        eventTime=eventTime1,
        labels={"model": "gpt-4"},
    )
    await statsStorage.record(
        {"tokens": 200},
        consumerId="chat_1",
        eventTime=eventTime2,
        labels={"model": "gpt-4"},
    )
    await statsStorage.aggregate()

    # Query for daily periods in range [2024-06-15, 2024-06-20]
    fromBound = "2024-06-15T00:00:00+00:00"
    toBound = "2024-06-20T00:00:00+00:00"

    rows = await statsStorage.query(
        eventType="llm_request",
        periodType="daily",
        periodStartFrom=fromBound,
        periodStartTo=toBound,
    )

    # Seed arithmetic: 2 events → each creates 2 aggregates (per-consumer + global)
    # → 4 total daily rows at 2024-06-15 and 2024-06-20
    # Inclusive range [fromBound, toBound] should return all 4 rows
    assert len(rows) == 4

    # All returned rows should be in the inclusive range
    for row in rows:
        assert row["periodStart"] >= fromBound
        assert row["periodStart"] <= toBound

    # Assert boundary rows are PRESENT (inclusive bounds)
    assert any(r["periodStart"] == fromBound for r in rows), "fromBound boundary row should be present"
    assert any(r["periodStart"] == toBound for r in rows), "toBound boundary row should be present"

    # Query for a narrower range should return fewer rows
    # Narrow range [2024-06-18, 2024-06-20] includes only the 2024-06-20 rows
    narrowFrom = "2024-06-18T00:00:00+00:00"
    narrowRows = await statsStorage.query(
        eventType="llm_request",
        periodType="daily",
        periodStartFrom=narrowFrom,
        periodStartTo=toBound,
    )
    # Should have exactly 2 rows (per-consumer + global for 2024-06-20)
    assert len(narrowRows) == 2
    assert len(narrowRows) < len(rows)

    # All narrow rows should be >= narrowFrom
    for row in narrowRows:
        assert row["periodStart"] >= narrowFrom
        assert row["periodStart"] <= toBound

    # Narrow range should NOT include the fromBound row (2024-06-15)
    assert not any(
        r["periodStart"] == fromBound for r in narrowRows
    ), "fromBound row should be excluded in narrow query"
    # But should still include the toBound row (2024-06-20)
    assert any(r["periodStart"] == toBound for r in narrowRows), "toBound row should still be present in narrow query"


async def testQueryLimitViaApplyPagination(statsStorage: DatabaseStatsStorage) -> None:
    """Verify query() applies limit via provider.applyPagination.

    Seed:
    - Record multiple events with different labels
    - Aggregate produces many rows
    - Query with limit should return at most that many rows

    Returns:
        None
    """
    # Record 10 events with different labels
    for i in range(10):
        await statsStorage.record(
            {"tokens": 100},
            consumerId=f"chat_{i}",
            labels={"model": f"model_{i}"},
        )
    await statsStorage.aggregate()

    # Query with limit=5
    rows = await statsStorage.query(eventType="llm_request", limit=5)

    # Should return at most 5 rows
    assert len(rows) <= 5

    # Query with larger limit
    allRows = await statsStorage.query(eventType="llm_request", limit=10000)

    # Should return more rows
    assert len(allRows) > len(rows)


async def testQueryLabelsParsedToDicts(statsStorage: DatabaseStatsStorage) -> None:
    """Verify query() returns labels as parsed dicts, not JSON strings.

    Seed:
    - Record an event with labels
    - Aggregate
    - Query should return rows with labels as dict[str, str]

    Returns:
        None
    """
    await statsStorage.record(
        {"tokens": 150},
        consumerId="chat_42",
        labels={"modelName": "gpt-4o", "provider": "openai", "user_id": "123"},
    )
    await statsStorage.aggregate()

    rows = await statsStorage.query(eventType="llm_request")

    assert len(rows) > 0

    # Labels should be dict[str, str], not JSON strings
    for row in rows:
        assert isinstance(row["labels"], dict)
        assert "consumer" in row["labels"]
        assert isinstance(row["labels"]["consumer"], str)

        # Check for specific labels if present
        if "modelName" in row["labels"]:
            assert row["labels"]["modelName"] == "gpt-4o"
        if "provider" in row["labels"]:
            assert row["labels"]["provider"] == "openai"
        if "user_id" in row["labels"]:
            assert row["labels"]["user_id"] == "123"


async def testQueryEmptyTableReturnsEmptyList(statsStorage: DatabaseStatsStorage) -> None:
    """Verify query() on empty table returns empty list.

    Returns:
        None
    """
    # Don't record any events, just query
    rows = await statsStorage.query(eventType="llm_request")

    # Should return empty list
    assert rows == []


async def testQueryIsolationFromOtherEventTypes(statsStorage: DatabaseStatsStorage) -> None:
    """Verify query() is isolated from other eventTypes (same database).

    This is a regression test ensuring that query() only returns rows
    for the requested eventType, not all eventTypes in the table.

    Returns:
        None
    """
    # Create a shared in-memory database
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            }
        },
    }
    sharedDb = Database(config)

    try:
        # Apply migration 016
        provider = await sharedDb.manager.getProvider(dataSource="default", readonly=False)
        migration = getMigration()()
        await migration.up(provider)

        # Create three storages with different eventTypes
        commandStorage = DatabaseStatsStorage(
            db=sharedDb,
            eventType="command",
            dataSource="default",
        )
        messageStorage = DatabaseStatsStorage(
            db=sharedDb,
            eventType="message",
            dataSource="default",
        )
        llmStorage = DatabaseStatsStorage(
            db=sharedDb,
            eventType="llm_request",
            dataSource="default",
        )

        # Record and aggregate for all three eventTypes
        await commandStorage.record(
            {"count": 1},
            consumerId="chat_1",
            labels={"cmd": "/test"},
        )
        await commandStorage.aggregate()

        await messageStorage.record(
            {"tokens": 100},
            consumerId="chat_2",
            labels={"model": "gpt-4"},
        )
        await messageStorage.aggregate()

        await llmStorage.record(
            {"tokens": 50},
            consumerId="chat_3",
            labels={"modelName": "gpt-4o"},
        )
        await llmStorage.aggregate()

        # Query for command eventType should return ONLY command rows
        commandRows = await commandStorage.query(eventType="command")
        for row in commandRows:
            assert row["metricKey"] == "count"

        # Query for message eventType should return ONLY message rows
        messageRows = await messageStorage.query(eventType="message")
        for row in messageRows:
            assert row["metricKey"] == "tokens"

        # Query for llm_request eventType should return ONLY llm_request rows
        llmRows = await llmStorage.query(eventType="llm_request")
        for row in llmRows:
            assert row["metricKey"] == "tokens"

    finally:
        await sharedDb.manager.closeAll()


async def testQueryTotalSentinelPeriods(statsStorage: DatabaseStatsStorage) -> None:
    """Verify query() returns total sentinel rows correctly.

    Seed:
    - Record an event and aggregate it
    - Query for periodType='total' should return rows with periodStart='1970-01-01T00:00:00+00:00'
    - Query with periodStartFrom after the sentinel should exclude total rows

    Returns:
        None
    """
    await statsStorage.record(
        {"tokens": 150},
        consumerId="chat_42",
        labels={"modelName": "gpt-4o"},
    )
    await statsStorage.aggregate()

    # Query for total periods should return sentinel rows
    totalRows = await statsStorage.query(eventType="llm_request", periodType="total")
    assert len(totalRows) > 0
    for row in totalRows:
        assert row["periodType"] == "total"
        assert row["periodStart"] == "1970-01-01T00:00:00+00:00"

    # Query with periodStartFrom after the sentinel should exclude total rows
    rowsAfterSentinel = await statsStorage.query(
        eventType="llm_request",
        periodStartFrom="1970-01-02T00:00:00+00:00",
    )
    # Should only return non-total rows (hourly/daily/monthly), not total rows
    totalRowsAfter = [r for r in rowsAfterSentinel if r["periodType"] == "total"]
    assert len(totalRowsAfter) == 0


async def testQueryOffsetPaging(statsStorage: DatabaseStatsStorage) -> None:
    """Verify query() offset paging with deterministic order.

    Seed:
    - Record 15 events with different labels to create many aggregate rows
    - Aggregate produces rows ordered by period_start, labels_hash, metric_key
    - Query with limit=10 should return first 10 rows
    - Query with limit=10 offset=10 should return remaining rows (page2)
    - Verify no overlap between pages and deterministic ordering

    Returns:
        None
    """
    # Record 15 events with different labels to create many rows
    for i in range(15):
        await statsStorage.record(
            {"tokens": 100 + i},
            consumerId=f"chat_{i}",
            labels={"model": f"model_{i}", "provider": "openai"},
        )
    await statsStorage.aggregate()

    # Get all rows to determine total count
    allRows = await statsStorage.query(eventType="llm_request", limit=10000)
    assert len(allRows) > 10, "Need more than 10 rows for pagination test"

    # Query first page with limit=10
    page1 = await statsStorage.query(eventType="llm_request", limit=10, offset=0)
    assert len(page1) == 10, "First page should have exactly 10 rows"

    # Query second page with limit=10 offset=10
    page2 = await statsStorage.query(eventType="llm_request", limit=10, offset=10)
    assert len(page2) > 0, "Second page should have at least one row"

    # Verify no overlap between pages (rows should be distinct)
    page1Ids = {(r["periodStart"], r["metricKey"], str(r["labels"])) for r in page1}
    page2Ids = {(r["periodStart"], r["metricKey"], str(r["labels"])) for r in page2}
    overlap = page1Ids & page2Ids
    assert len(overlap) == 0, f"Pages should not overlap, found {len(overlap)} overlapping rows"

    # Verify deterministic order by checking that combined pages match allRows
    combinedPages = page1 + page2
    # The combined pages should be a prefix of allRows (ordered query)
    for i, row in enumerate(combinedPages):
        assert row == allRows[i], f"Row {i} doesn't match allRows at position {i}"

    # Verify deterministic ordering: same query twice returns same results
    page1Again = await statsStorage.query(eventType="llm_request", limit=10, offset=0)
    assert page1 == page1Again, "Same query should return same results (deterministic order)"

    # Verify second query returns different results from first query
    assert page1 != page2, "Different pages should return different results"

    # Verify that querying beyond the available rows returns empty list
    # Get total count and query way beyond it
    emptyPage = await statsStorage.query(eventType="llm_request", limit=10, offset=10000)
    assert emptyPage == [], "Querying beyond available rows should return empty list"
