"""Tests for migration_027_drop_chat_stats_backfill_aggregates.

This migration performs two steps:
1. Back-fill all historical chat_user_stats data into stat_aggregates as
   message_received events (daily, monthly, total periods; per-consumer
   and __global__ label-sets).
2. Drop both legacy write-only tables: chat_stats and chat_user_stats.

The test verifies:
- Legacy tables are dropped after up().
- stat_aggregates receives the correct rows with correct values, labels,
  labels_hash, and period_start.
- Both private (chat_id > 0) and group (chat_id < 0) cases work.
- Multiple dates within the same month and across months accumulate correctly.
- down() recreates both tables empty (data not restorable).
- After migration, ChatMessagesRepository.saveChatMessage() no longer
  references the dropped tables (no exception).
"""

import datetime

import lib.utils as libUtils
from internal.database import Database
from internal.database.migrations import MigrationManager
from internal.database.migrations.versions.migration_027_drop_chat_stats_backfill_aggregates import (
    Migration027DropChatStatsBackfillAggregates,
)
from internal.database.stats_storage import _hashLabels
from internal.models import MessageId, MessageType
from lib.stats.stats_storage import GLOBAL_CONSUMER_ID

# Test constants
CHAT_PRIVATE_1 = 123  # > 0 means private
CHAT_PRIVATE_2 = 456  # > 0 means private, same month as CHAT_PRIVATE_1
CHAT_GROUP_1 = -789  # < 0 means group
USER_1 = 111
USER_2 = 222
DATE_JAN_15 = datetime.datetime(2024, 1, 15, tzinfo=datetime.timezone.utc)
DATE_JAN_20 = datetime.datetime(2024, 1, 20, tzinfo=datetime.timezone.utc)
DATE_FEB_10 = datetime.datetime(2024, 2, 10, tzinfo=datetime.timezone.utc)
TOTAL_SENTINEL = "1970-01-01T00:00:00+00:00"


async def _tableExists(provider, tableName: str) -> bool:
    """Check whether a table exists.

    Args:
        provider: SQL provider.
        tableName: Name of the table to check.

    Returns:
        True if the table exists, False otherwise.
    """
    row = await provider.executeFetchOne(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = :name",
        {"name": tableName},
    )
    return row is not None


async def _rollbackToPre027(provider) -> None:
    """Roll back to version 26 to reach the pre-027 state.

    Args:
        provider: Writable SQL provider.

    Returns:
        None
    """
    rollbackManager = MigrationManager()
    rollbackManager.loadMigrationsFromVersions()
    await rollbackManager.rollbackTo(targetVersion=26, sqlProvider=provider)


async def _seedChatUserStats(
    provider,
    chatId: int,
    userId: int,
    date: datetime.datetime,
    messagesCount: int,
) -> None:
    """Insert a single chat_user_stats row for back-fill testing.

    Args:
        provider: Writable SQL provider.
        chatId: Chat id (positive for private, negative for group).
        userId: User id.
        date: Date timestamp (midnight).
        messagesCount: Message count for the day.

    Returns:
        None
    """
    now = libUtils.now()
    await provider.execute(
        """
        INSERT INTO chat_user_stats
            (chat_id, user_id, date, messages_count, created_at, updated_at)
        VALUES
            (:chatId, :userId, :date, :messagesCount, :createdAt, :updatedAt)
        """,
        {
            "chatId": chatId,
            "userId": userId,
            "date": date,
            "messagesCount": messagesCount,
            "createdAt": now,
            "updatedAt": now,
        },
    )


async def _seedChatStats(
    provider,
    chatId: int,
    date: datetime.datetime,
    messagesCount: int,
) -> None:
    """Insert a single chat_stats row (not back-filled, just dropped).

    Args:
        provider: Writable SQL provider.
        chatId: Chat id.
        date: Date timestamp (midnight).
        messagesCount: Message count for the day.

    Returns:
        None
    """
    now = libUtils.now()
    await provider.execute(
        """
        INSERT INTO chat_stats
            (chat_id, date, messages_count, created_at, updated_at)
        VALUES
            (:chatId, :date, :messagesCount, :createdAt, :updatedAt)
        """,
        {
            "chatId": chatId,
            "date": date,
            "messagesCount": messagesCount,
            "createdAt": now,
            "updatedAt": now,
        },
    )


async def test_up_backfillsAndDropsLegacyTables(testDatabase: Database) -> None:
    """up() back-fills chat_user_stats to stat_aggregates and drops both legacy tables.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_PRIVATE_1, readonly=False)
    await _rollbackToPre027(provider)

    # Preconditions: legacy tables exist, stat_aggregates is empty
    assert await _tableExists(provider, "chat_stats"), "precondition: chat_stats exists"
    assert await _tableExists(provider, "chat_user_stats"), "precondition: chat_user_stats exists"
    aggCount = await provider.executeFetchOne(
        "SELECT COUNT(*) AS cnt FROM stat_aggregates WHERE event_type = 'message_received'"
    )
    assert (
        aggCount is not None and int(aggCount["cnt"]) == 0
    ), "precondition: stat_aggregates empty for message_received"

    # Seed diverse test data:
    # - Private chat (CHAT_PRIVATE_1) with multiple dates in same month (Jan 15, Jan 20)
    # - Private chat (CHAT_PRIVATE_2) with date in same month (Jan 15) - tests __global__ SUM
    # - Group chat (CHAT_GROUP_1) with date in different month (Feb 10)
    # - Different users (USER_1, USER_2)
    await _seedChatUserStats(provider, CHAT_PRIVATE_1, USER_1, DATE_JAN_15, 5)
    await _seedChatUserStats(provider, CHAT_PRIVATE_1, USER_1, DATE_JAN_20, 3)
    await _seedChatUserStats(provider, CHAT_PRIVATE_2, USER_1, DATE_JAN_15, 2)
    await _seedChatUserStats(provider, CHAT_GROUP_1, USER_2, DATE_FEB_10, 7)
    # Also seed some chat_stats rows (should just be dropped, not back-filled)
    await _seedChatStats(provider, CHAT_PRIVATE_1, DATE_JAN_15, 100)
    await _seedChatStats(provider, CHAT_GROUP_1, DATE_FEB_10, 50)

    migration = Migration027DropChatStatsBackfillAggregates()
    await migration.up(provider)

    # Assert: both legacy tables dropped
    assert not await _tableExists(provider, "chat_stats"), "up() must drop chat_stats"
    assert not await _tableExists(provider, "chat_user_stats"), "up() must drop chat_user_stats"

    # Assert: stat_aggregates has the expected back-filled rows
    rows = await provider.executeFetchAll("""
        SELECT event_type, period_type, period_start, labels_hash, labels, metric_key, metric_value
        FROM stat_aggregates
        WHERE event_type = 'message_received'
        ORDER BY labels_hash, period_type
        """)
    assert (
        len(rows) == 17
    ), f"Expected 17 rows (4 source rows → 17 unique due to __global__ daily collision), got {len(rows)}"

    # Build expected labels for each (chatId, userId, chatType) combination
    # Private chats: chatType = "private", Group chats: chatType = "group"
    expectedRows = []

    def _addExpectedRow(consumer: str, userId: int, chatType: str, periodType: str, periodStart: str, value: int):
        labels = {"consumer": consumer, "user_id": str(userId), "chat_type": chatType}
        labelsJson = libUtils.jsonDumps(labels)
        labelsHash = _hashLabels(labelsJson)
        expectedRows.append(
            {
                "event_type": "message_received",
                "period_type": periodType,
                "period_start": periodStart,
                "labels_hash": labelsHash,
                "labels": labelsJson,
                "metric_key": "message_count",
                "metric_value": value,
            }
        )

    # For CHAT_PRIVATE_1, USER_1: two dates in same month (Jan 15: 5, Jan 20: 3)
    # Daily: two separate rows
    # Monthly: SUM = 8
    # Total: SUM = 8
    dailyJan15 = DATE_JAN_15.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    dailyJan20 = DATE_JAN_20.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    monthlyJan = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc).isoformat()

    _addExpectedRow(str(CHAT_PRIVATE_1), USER_1, "private", "daily", dailyJan15, 5)
    _addExpectedRow(str(CHAT_PRIVATE_1), USER_1, "private", "daily", dailyJan20, 3)
    _addExpectedRow(str(CHAT_PRIVATE_1), USER_1, "private", "monthly", monthlyJan, 8)
    _addExpectedRow(str(CHAT_PRIVATE_1), USER_1, "private", "total", TOTAL_SENTINEL, 8)

    # __global__ rollup for same
    # Note: The daily 2024-01-15, monthly, and total rows will be SUMed later when CHAT_PRIVATE_2 is processed,
    # so we DON'T add them here. They will be added below with the SUMed values.
    _addExpectedRow(GLOBAL_CONSUMER_ID, USER_1, "private", "daily", dailyJan20, 3)

    # For CHAT_PRIVATE_2, USER_1: single date (Jan 15: 2)
    # Tests __global__ SUM across chats for same user: monthly total should be 5 + 2 = 7
    _addExpectedRow(str(CHAT_PRIVATE_2), USER_1, "private", "daily", dailyJan15, 2)
    _addExpectedRow(str(CHAT_PRIVATE_2), USER_1, "private", "monthly", monthlyJan, 2)
    _addExpectedRow(str(CHAT_PRIVATE_2), USER_1, "private", "total", TOTAL_SENTINEL, 2)

    # __global__ rollup for CHAT_PRIVATE_2, USER_1
    # Note: this will upsert and SUM with the previous __global__ rows for USER_1
    # The daily 2024-01-15 row from CHAT_PRIVATE_1 (value=5) will be SUMed with this one (value=2)
    # to produce a single row with value=7 - we DON'T expect a separate row with value=5
    # because the UNIQUE constraint on (event_type, period_start, period_type, labels_hash, metric_key)
    # causes them to collapse via upsert.
    _addExpectedRow(
        GLOBAL_CONSUMER_ID, USER_1, "private", "daily", dailyJan15, 7
    )  # 5 + 2 (collapsed from two source rows)
    _addExpectedRow(GLOBAL_CONSUMER_ID, USER_1, "private", "monthly", monthlyJan, 10)  # 8 + 2
    _addExpectedRow(GLOBAL_CONSUMER_ID, USER_1, "private", "total", TOTAL_SENTINEL, 10)  # 8 + 2

    # For CHAT_GROUP_1, USER_2: different month (Feb 10: 7)
    dailyFeb10 = DATE_FEB_10.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    monthlyFeb = datetime.datetime(2024, 2, 1, tzinfo=datetime.timezone.utc).isoformat()

    _addExpectedRow(str(CHAT_GROUP_1), USER_2, "group", "daily", dailyFeb10, 7)
    _addExpectedRow(str(CHAT_GROUP_1), USER_2, "group", "monthly", monthlyFeb, 7)
    _addExpectedRow(str(CHAT_GROUP_1), USER_2, "group", "total", TOTAL_SENTINEL, 7)

    # __global__ rollup for CHAT_GROUP_1, USER_2
    _addExpectedRow(GLOBAL_CONSUMER_ID, USER_2, "group", "daily", dailyFeb10, 7)
    _addExpectedRow(GLOBAL_CONSUMER_ID, USER_2, "group", "monthly", monthlyFeb, 7)
    _addExpectedRow(GLOBAL_CONSUMER_ID, USER_2, "group", "total", TOTAL_SENTINEL, 7)

    # Verify all expected rows exist
    actualByKey = {(r["labels_hash"], r["period_type"], r["period_start"]): r for r in rows}
    for expected in expectedRows:
        key = (expected["labels_hash"], expected["period_type"], expected["period_start"])
        assert key in actualByKey, f"Missing expected row: {expected}"
        actual = actualByKey[key]
        assert actual["event_type"] == expected["event_type"]
        assert actual["labels"] == expected["labels"]
        assert actual["metric_key"] == expected["metric_key"]
        assert actual["metric_value"] == expected["metric_value"]


async def test_down_recreatesLegacyTablesEmpty(testDatabase: Database) -> None:
    """down() recreates both legacy tables empty (original data not restorable).

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_PRIVATE_1, readonly=False)
    await _rollbackToPre027(provider)

    migration = Migration027DropChatStatsBackfillAggregates()
    await migration.up(provider)

    # Precondition: tables are gone after up()
    assert not await _tableExists(provider, "chat_stats")
    assert not await _tableExists(provider, "chat_user_stats")

    # Run down()
    await migration.down(provider)

    # Assert: both tables recreated
    assert await _tableExists(provider, "chat_stats"), "down() must recreate chat_stats"
    assert await _tableExists(provider, "chat_user_stats"), "down() must recreate chat_user_stats"

    # Assert: tables are empty (data loss expected and documented)
    chatStatsCount = await provider.executeFetchOne("SELECT COUNT(*) AS cnt FROM chat_stats")
    assert chatStatsCount is not None and int(chatStatsCount["cnt"]) == 0, "recreated chat_stats must be empty"

    chatUserStatsCount = await provider.executeFetchOne("SELECT COUNT(*) AS cnt FROM chat_user_stats")
    assert (
        chatUserStatsCount is not None and int(chatUserStatsCount["cnt"]) == 0
    ), "recreated chat_user_stats must be empty"


async def test_saveChatMessagePostMigration(testDatabase: Database) -> None:
    """After migration, saveChatMessage() succeeds without referencing dropped tables.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_PRIVATE_1, readonly=False)
    await _rollbackToPre027(provider)

    migration = Migration027DropChatStatsBackfillAggregates()
    await migration.up(provider)

    # Verify tables are gone
    assert not await _tableExists(provider, "chat_stats")
    assert not await _tableExists(provider, "chat_user_stats")

    # Seed chat_users row first (saveChatMessage increments it)
    now = libUtils.now()
    await provider.execute(
        """
        INSERT INTO chat_users
            (chat_id, user_id, username, full_name, messages_count, created_at, updated_at)
        VALUES
            (:chatId, :userId, 'testuser', 'Test User', 0, :now, :now)
        """,
        {"chatId": CHAT_PRIVATE_1, "userId": USER_1, "now": now},
    )

    # Use ChatMessagesRepository.saveChatMessage - should not raise
    # Regression guard: saveChatMessage's broad except returns False if it
    # touches a dropped table (e.g., legacy chat_stats/chat_user_stats), so a
    # future refactor that removes the except would silently expose the regression.
    result = await testDatabase.chatMessages.saveChatMessage(
        date=libUtils.now(),
        chatId=CHAT_PRIVATE_1,
        userId=USER_1,
        messageId=MessageId(999),
        messageText="test message after migration",
        messageType=MessageType.TEXT,
    )
    assert result is True, "saveChatMessage must succeed after migration"

    # Verify chat_messages was written
    msgRow = await provider.executeFetchOne(
        "SELECT message_text FROM chat_messages WHERE chat_id = :chatId AND message_id = :messageId",
        {"chatId": CHAT_PRIVATE_1, "messageId": 999},
    )
    assert msgRow is not None, "chat_messages row must exist"
    assert msgRow["message_text"] == "test message after migration"

    # Verify chat_users.messages_count was incremented
    userRow = await provider.executeFetchOne(
        "SELECT messages_count FROM chat_users WHERE chat_id = :chatId AND user_id = :userId",
        {"chatId": CHAT_PRIVATE_1, "userId": USER_1},
    )
    assert userRow is not None, "chat_users row must exist"
    assert userRow["messages_count"] == 1, "messages_count must be incremented"


async def test_up_idempotentWhenLegacyTablesGone(testDatabase: Database) -> None:
    """up() succeeds when legacy tables are already gone (partial re-run).

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_PRIVATE_1, readonly=False)
    await _rollbackToPre027(provider)

    # Seed data
    await _seedChatUserStats(provider, CHAT_PRIVATE_1, USER_1, DATE_JAN_15, 5)

    migration = Migration027DropChatStatsBackfillAggregates()
    await migration.up(provider)

    # Tables are gone, stat_aggregates has back-filled data
    assert not await _tableExists(provider, "chat_stats")
    assert not await _tableExists(provider, "chat_user_stats")

    # Re-run up() - should succeed without error
    await migration.up(provider)

    # Tables still gone, no duplicate rows added (source table empty now)
    assert not await _tableExists(provider, "chat_stats")
    assert not await _tableExists(provider, "chat_user_stats")
    aggCount = await provider.executeFetchOne(
        "SELECT COUNT(*) AS cnt FROM stat_aggregates WHERE event_type = 'message_received'"
    )
    # Should still be 6 rows from the first run (1 source row × 3 periods × 2 label-sets)
    assert aggCount is not None and int(aggCount["cnt"]) == 6
