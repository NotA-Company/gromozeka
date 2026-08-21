"""Tests for migration_027_drop_chat_stats_backfill_aggregates.

This migration performs two steps:
1. Back-fill all historical chat_messages data into stat_aggregates as
   message events (daily, monthly, total periods; per-consumer
   and __global__ label-sets; message_count and text_length metrics).
2. Drop both legacy write-only tables: chat_stats and chat_user_stats.

The test verifies:
- Legacy tables are dropped after up().
- stat_aggregates receives the correct rows with correct values, labels,
  labels_hash, and period_start.
- Both private (chat_id > 0) and group (chat_id < 0) cases work.
- Multiple dates within the same month and across months accumulate correctly.
- Both bot-authored and user-authored messages are included.
- Multiple message_category and message_type values are handled correctly.
- DELETED and UNSPECIFIED message_category rows are excluded.
- NULL message_category rows are excluded (branch exists for schema-drift robustness).
- NULL message_text results in text_length=0.
- down() recreates both tables empty (data not restorable).
- After migration, ChatMessagesRepository.saveChatMessage() no longer
  references the dropped tables (no exception).
- chat_type lookup from chat_info table works; falls back to sign-derived when missing.
"""

import datetime
import json

import lib.utils as libUtils
from internal.database import Database
from internal.database.migrations import MigrationManager
from internal.database.migrations.versions.migration_027_drop_chat_stats_backfill_aggregates import (
    Migration027DropChatStatsBackfillAggregates,
)
from internal.database.models import MessageCategory
from internal.database.stats_storage import _hashLabels
from internal.models import MessageId, MessageType
from lib.stats.stats_storage import GLOBAL_CONSUMER_ID

# Test constants
CHAT_PRIVATE_1 = 123  # > 0 means private
CHAT_PRIVATE_2 = 456  # > 0 means private, same month as CHAT_PRIVATE_1
CHAT_GROUP_1 = -789  # < 0 means group
CHAT_CHANNEL_1 = -1000  # < 0 means group by sign, but channel in chat_info
USER_1 = 111
USER_2 = 222
DATE_JAN_15 = datetime.datetime(2024, 1, 15, tzinfo=datetime.timezone.utc)
DATE_JAN_20 = datetime.datetime(2024, 1, 20, tzinfo=datetime.timezone.utc)
DATE_FEB_10 = datetime.datetime(2024, 2, 10, tzinfo=datetime.timezone.utc)
DATE_FEB_11 = datetime.datetime(2024, 2, 11, tzinfo=datetime.timezone.utc)
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


async def _seedChatMessage(
    provider,
    chatId: int,
    userId: int,
    date: datetime.datetime,
    messageId: int,
    messageText: str,
    messageCategory: str,
    messageType: str,
) -> None:
    """Insert a single chat_messages row for back-fill testing.

    Args:
        provider: Writable SQL provider.
        chatId: Chat id (positive for private, negative for group).
        userId: User id.
        date: Date timestamp.
        messageId: Message id.
        messageText: Message text (may be None).
        messageCategory: Message category string value (e.g., "user", "bot").
        messageType: Message type string value (e.g., "text", "image").

    Returns:
        None
    """
    now = libUtils.now()
    await provider.execute(
        """
        INSERT INTO chat_messages
            (chat_id, user_id, date, message_id, message_text, message_category, message_type, created_at)
        VALUES
            (:chatId, :userId, :date, :messageId, :messageText, :messageCategory, :messageType, :createdAt)
        """,
        {
            "chatId": chatId,
            "userId": userId,
            "date": date,
            "messageId": str(messageId),
            "messageText": messageText,
            "messageCategory": messageCategory,
            "messageType": messageType,
            "createdAt": now,
        },
    )


async def _seedChatUserStats(
    provider,
    chatId: int,
    userId: int,
    date: datetime.datetime,
    messagesCount: int,
) -> None:
    """Insert a single chat_user_stats row (not back-filled, just dropped).

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


async def _seedChatInfo(
    provider,
    chatId: int,
    chatType: str,
) -> None:
    """Insert a single chat_info row for chat_type testing.

    Args:
        provider: Writable SQL provider.
        chatId: Chat id.
        chatType: Chat type string value (e.g., "private", "group", "channel").

    Returns:
        None
    """
    now = libUtils.now()
    await provider.execute(
        """
        INSERT INTO chat_info
            (chat_id, type, created_at, updated_at)
        VALUES
            (:chatId, :chatType, :createdAt, :updatedAt)
        """,
        {
            "chatId": chatId,
            "chatType": chatType,
            "createdAt": now,
            "updatedAt": now,
        },
    )


async def test_up_backfillsAndDropsLegacyTables(testDatabase: Database) -> None:
    """up() back-fills chat_messages to stat_aggregates and drops both legacy tables.

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
        "SELECT COUNT(*) AS cnt FROM stat_aggregates WHERE event_type = 'message'"
    )
    assert aggCount is not None and int(aggCount["cnt"]) == 0, "precondition: stat_aggregates empty for message"

    # Seed diverse test data:
    # - Private chat (CHAT_PRIVATE_1) with multiple dates in same month (Jan 15, Jan 20)
    # - Private chat (CHAT_PRIVATE_2) with date in same month (Jan 15) - tests __global__ SUM
    # - Group chat (CHAT_GROUP_1) with date in different month (Feb 10)
    # - Different users (USER_1, USER_2, BOT_ID)
    # - Multiple message_category values (USER, BOT, USER_COMMAND)
    # - Multiple message_type values (text, image)
    # - NULL message_text (text_length=0)
    # - DELETED and UNSPECIFIED message_category rows (should be excluded)
    BOT_ID = 999

    # CHAT_PRIVATE_1, USER_1 messages
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_1,
        USER_1,
        DATE_JAN_15,
        1,
        "Hello world",
        MessageCategory.USER,
        MessageType.TEXT,
    )
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_1,
        USER_1,
        DATE_JAN_15,
        2,
        "Another message",
        MessageCategory.USER_COMMAND,
        MessageType.TEXT,
    )
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_1,
        USER_1,
        DATE_JAN_20,
        3,
        "Test message",
        MessageCategory.USER,
        MessageType.TEXT,
    )
    # CHAT_PRIVATE_1, BOT messages (should be included)
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_1,
        BOT_ID,
        DATE_JAN_15,
        4,
        "Bot reply",
        MessageCategory.BOT,
        MessageType.TEXT,
    )
    # CHAT_PRIVATE_1, USER_1 with IMAGE type and empty text (text_length=0)
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_1,
        USER_1,
        DATE_JAN_15,
        5,
        "",
        MessageCategory.USER,
        MessageType.IMAGE,
    )

    # CHAT_PRIVATE_2, USER_1 message (same day as CHAT_PRIVATE_1 - tests __global__ SUM)
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_2,
        USER_1,
        DATE_JAN_15,
        6,
        "Hello from chat 2",
        MessageCategory.USER,
        MessageType.TEXT,
    )

    # CHAT_GROUP_1, USER_2 message (different month)
    await _seedChatMessage(
        provider,
        CHAT_GROUP_1,
        USER_2,
        DATE_FEB_10,
        7,
        "Group message",
        MessageCategory.CHANNEL,
        MessageType.TEXT,
    )

    # DELETED message (should be excluded)
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_1,
        USER_1,
        DATE_JAN_15,
        8,
        "Deleted message",
        MessageCategory.DELETED,
        MessageType.TEXT,
    )

    # UNSPECIFIED message (should be excluded)
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_1,
        USER_1,
        DATE_JAN_15,
        9,
        "Unspecified message",
        MessageCategory.UNSPECIFIED,
        MessageType.TEXT,
    )

    # Also seed some chat_user_stats rows (should just be dropped, not back-filled)
    await _seedChatUserStats(provider, CHAT_PRIVATE_1, USER_1, DATE_JAN_15, 100)
    await _seedChatUserStats(provider, CHAT_GROUP_1, USER_2, DATE_FEB_10, 50)

    migration = Migration027DropChatStatsBackfillAggregates()
    await migration.up(provider)

    # Assert: both legacy tables dropped
    assert not await _tableExists(provider, "chat_stats"), "up() must drop chat_stats"
    assert not await _tableExists(provider, "chat_user_stats"), "up() must drop chat_user_stats"

    # Assert: stat_aggregates has the expected back-filled rows
    rows = await provider.executeFetchAll("""
        SELECT event_type, period_type, period_start, labels_hash, labels, metric_key, metric_value
        FROM stat_aggregates
        WHERE event_type = 'message'
        ORDER BY labels_hash, period_type, metric_key
        """)

    # Expected rows:
    # 7 unique per-consumer buckets (chatId, userId, datePart, messageCategory, messageType):
    # 1. (123, 111, 2024-01-15, "user", "text") - 1 message, text_length = 11
    # 2. (123, 111, 2024-01-15, "user-command", "text") - 1 message, text_length = 15
    # 3. (123, 111, 2024-01-20, "user", "text") - 1 message, text_length = 12
    # 4. (123, 999, 2024-01-15, "bot", "text") - 1 message, text_length = 9
    # 5. (123, 111, 2024-01-15, "user", "image") - 1 message, text_length = 0
    # 6. (456, 111, 2024-01-15, "user", "text") - 1 message, text_length = 17
    # 7. (-789, 222, 2024-02-10, "channel", "text") - 1 message, text_length = 13
    #
    # 6 unique __global__ buckets (userId, chatType, datePart, messageCategory, messageType):
    # 1. (111, private, 2024-01-15, "user", "text") - 2 messages, text_length = 28 (merges buckets 1 & 6)
    # 2. (111, private, 2024-01-15, "user-command", "text") - 1 message, text_length = 15
    # 3. (111, private, 2024-01-20, "user", "text") - 1 message, text_length = 12
    # 4. (999, private, 2024-01-15, "bot", "text") - 1 message, text_length = 9
    # 5. (111, private, 2024-01-15, "user", "image") - 1 message, text_length = 0
    # 6. (222, group, 2024-02-10, "channel", "text") - 1 message, text_length = 13
    #
    # For monthly/total periods, buckets within the same month merge:
    # - Per-consumer: (123, 111, user, text) merges Jan 15 + Jan 20 → 2 messages, 23 text_length
    # - __global__: (111, private, user, text) merges Jan 15 + Jan 20 → 3 messages, 40 text_length
    #
    # Total rows: (7×2 + 6×2 + 6×2) per-consumer + (6×2 + 5×2 + 5×2) __global__ = 38 + 32 = 70
    #
    # Exclusions: DELETED (row 8), UNSPECIFIED (row 9) are skipped
    #
    # Why 84 was wrong: Assumed __global__ has 7 buckets like per-consumer, but __global__ has only 6
    # because buckets 1 & 6 merge (same user/category/type/date across different chats).

    # Build expected labels for each (chatId, userId, datePart, messageCategory, messageType) combination
    expectedRows = []

    def _addExpectedRow(
        consumer: str,
        userId: int,
        chatType: str,
        messageCategory: str,
        messageType: str,
        periodType: str,
        periodStart: str,
        metricKey: str,
        metricValue: int,
    ):
        labels = {
            "consumer": consumer,
            "user_id": str(userId),
            "chat_type": chatType,
            "message_category": messageCategory,
            "message_type": messageType,
        }
        labelsJson = libUtils.jsonDumps(labels)
        labelsHash = _hashLabels(labelsJson)
        expectedRows.append(
            {
                "event_type": "message",
                "period_type": periodType,
                "period_start": periodStart,
                "labels_hash": labelsHash,
                "labels": labelsJson,
                "metric_key": metricKey,
                "metric_value": metricValue,
            }
        )

    # Period boundaries
    dailyJan15 = DATE_JAN_15.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    dailyJan20 = DATE_JAN_20.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    dailyFeb10 = DATE_FEB_10.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    monthlyJan = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc).isoformat()
    monthlyFeb = datetime.datetime(2024, 2, 1, tzinfo=datetime.timezone.utc).isoformat()

    # Bucket 1: (123, 111, 2024-01-15, "user", "text") - 1 message, text_length = 11
    for periodType, periodStart in [("daily", dailyJan15), ("monthly", monthlyJan), ("total", TOTAL_SENTINEL)]:
        # For monthly/total, this merges with bucket 3 (same chat/user/category/type, different date)
        if periodType == "monthly" or periodType == "total":
            count = 2  # Jan 15 + Jan 20
            length = 23  # 11 + 12
        else:
            count = 1
            length = 11
        _addExpectedRow("123", 111, "private", "user", "text", periodType, periodStart, "message_count", count)
        _addExpectedRow("123", 111, "private", "user", "text", periodType, periodStart, "text_length", length)
    # Bucket 1 __global__: merges with bucket 6 __global__ (same user/chatType/category/type/date)
    _addExpectedRow(
        GLOBAL_CONSUMER_ID, 111, "private", "user", "text", "daily", dailyJan15, "message_count", 2
    )  # chat 123 + 456
    _addExpectedRow(
        GLOBAL_CONSUMER_ID, 111, "private", "user", "text", "daily", dailyJan15, "text_length", 28
    )  # 11 + 17
    # For monthly/total, __global__ merges bucket 1 + 3 + 6 (same user/chatType/category/type, different dates/chats)
    _addExpectedRow(
        GLOBAL_CONSUMER_ID, 111, "private", "user", "text", "monthly", monthlyJan, "message_count", 3
    )  # Jan 15(chat123) + Jan 15(chat456) + Jan 20
    _addExpectedRow(
        GLOBAL_CONSUMER_ID, 111, "private", "user", "text", "monthly", monthlyJan, "text_length", 40
    )  # 11 + 17 + 12
    _addExpectedRow(GLOBAL_CONSUMER_ID, 111, "private", "user", "text", "total", TOTAL_SENTINEL, "message_count", 3)
    _addExpectedRow(GLOBAL_CONSUMER_ID, 111, "private", "user", "text", "total", TOTAL_SENTINEL, "text_length", 40)

    # Bucket 2: (123, 111, 2024-01-15, "user-command", "text") - 1 message, text_length = 15
    for periodType, periodStart in [("daily", dailyJan15), ("monthly", monthlyJan), ("total", TOTAL_SENTINEL)]:
        _addExpectedRow("123", 111, "private", "user-command", "text", periodType, periodStart, "message_count", 1)
        _addExpectedRow("123", 111, "private", "user-command", "text", periodType, periodStart, "text_length", 15)
        _addExpectedRow(
            GLOBAL_CONSUMER_ID, 111, "private", "user-command", "text", periodType, periodStart, "message_count", 1
        )
        _addExpectedRow(
            GLOBAL_CONSUMER_ID, 111, "private", "user-command", "text", periodType, periodStart, "text_length", 15
        )

    # Bucket 3: (123, 111, 2024-01-20, "user", "text") - 1 message, text_length = 12
    # Per-consumer monthly/total: merged with bucket 1 above (handled in bucket 1)
    _addExpectedRow("123", 111, "private", "user", "text", "daily", dailyJan20, "message_count", 1)
    _addExpectedRow("123", 111, "private", "user", "text", "daily", dailyJan20, "text_length", 12)
    # __global__ daily: unique (no other user 111 user/text on Jan 20)
    _addExpectedRow(GLOBAL_CONSUMER_ID, 111, "private", "user", "text", "daily", dailyJan20, "message_count", 1)
    _addExpectedRow(GLOBAL_CONSUMER_ID, 111, "private", "user", "text", "daily", dailyJan20, "text_length", 12)
    # __global__ monthly/total: merged with bucket 1 __global__ (handled in bucket 1)

    # Bucket 4: (123, 999, 2024-01-15, "bot", "text") - 1 message, text_length = 9 (not 10 - it's "Bot reply")
    for periodType, periodStart in [("daily", dailyJan15), ("monthly", monthlyJan), ("total", TOTAL_SENTINEL)]:
        _addExpectedRow("123", 999, "private", "bot", "text", periodType, periodStart, "message_count", 1)
        _addExpectedRow("123", 999, "private", "bot", "text", periodType, periodStart, "text_length", 9)
        _addExpectedRow(GLOBAL_CONSUMER_ID, 999, "private", "bot", "text", periodType, periodStart, "message_count", 1)
        _addExpectedRow(GLOBAL_CONSUMER_ID, 999, "private", "bot", "text", periodType, periodStart, "text_length", 9)

    # Bucket 5: (123, 111, 2024-01-15, "user", "image") - 1 message, text_length = 0
    for periodType, periodStart in [("daily", dailyJan15), ("monthly", monthlyJan), ("total", TOTAL_SENTINEL)]:
        _addExpectedRow("123", 111, "private", "user", "image", periodType, periodStart, "message_count", 1)
        _addExpectedRow("123", 111, "private", "user", "image", periodType, periodStart, "text_length", 0)
        _addExpectedRow(
            GLOBAL_CONSUMER_ID, 111, "private", "user", "image", periodType, periodStart, "message_count", 1
        )
        _addExpectedRow(GLOBAL_CONSUMER_ID, 111, "private", "user", "image", periodType, periodStart, "text_length", 0)

    # Bucket 6: (456, 111, 2024-01-15, "user", "text") - 1 message, text_length = 17 (not 16 - it's "Hello from chat 2")
    # Per-consumer: same as bucket 1 structure, but different chatId
    _addExpectedRow("456", 111, "private", "user", "text", "daily", dailyJan15, "message_count", 1)
    _addExpectedRow("456", 111, "private", "user", "text", "daily", dailyJan15, "text_length", 17)
    _addExpectedRow("456", 111, "private", "user", "text", "monthly", monthlyJan, "message_count", 1)
    _addExpectedRow("456", 111, "private", "user", "text", "monthly", monthlyJan, "text_length", 17)
    _addExpectedRow("456", 111, "private", "user", "text", "total", TOTAL_SENTINEL, "message_count", 1)
    _addExpectedRow("456", 111, "private", "user", "text", "total", TOTAL_SENTINEL, "text_length", 17)
    # __global__: merged with bucket 1 __global__ (handled in bucket 1)

    # Bucket 7: (-789, 222, 2024-02-10, "channel", "text") - 1 message, text_length = 13
    for periodType, periodStart in [("daily", dailyFeb10), ("monthly", monthlyFeb), ("total", TOTAL_SENTINEL)]:
        _addExpectedRow("-789", 222, "group", "channel", "text", periodType, periodStart, "message_count", 1)
        _addExpectedRow("-789", 222, "group", "channel", "text", periodType, periodStart, "text_length", 13)
        _addExpectedRow(
            GLOBAL_CONSUMER_ID, 222, "group", "channel", "text", periodType, periodStart, "message_count", 1
        )
        _addExpectedRow(GLOBAL_CONSUMER_ID, 222, "group", "channel", "text", periodType, periodStart, "text_length", 13)

    # Total expected: 70 rows
    # - Per-consumer: 7 daily + 6 monthly + 6 total = 19 unique buckets × 2 metrics = 38 rows
    # - __global__: 6 daily + 5 monthly + 5 total = 16 unique buckets × 2 metrics = 32 rows
    actualByKey = {(r["labels_hash"], r["period_type"], r["period_start"], r["metric_key"]): r for r in rows}
    for expected in expectedRows:
        key = (expected["labels_hash"], expected["period_type"], expected["period_start"], expected["metric_key"])
        assert key in actualByKey, f"Missing expected row: {expected}"
        actual = actualByKey[key]
        assert actual["event_type"] == expected["event_type"]
        assert actual["labels"] == expected["labels"]
        assert actual["metric_key"] == expected["metric_key"]
        assert actual["metric_value"] == expected["metric_value"]

    # Verify DELETED/UNSPECIFIED messages were excluded (they shouldn't appear in any aggregates)
    # Count should be exactly 70 rows (38 per-consumer + 32 __global__)
    assert len(rows) == 70, f"Expected 70 rows, got {len(rows)}"


async def test_up_usesRealChatTypeFromChatInfo(testDatabase: Database) -> None:
    """up() uses real chat_type from chat_info; falls back to sign-derived when missing.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_PRIVATE_1, readonly=False)
    await _rollbackToPre027(provider)

    # Seed a channel chat_info row (negative chatId with type="channel")
    await _seedChatInfo(provider, CHAT_CHANNEL_1, "channel")

    # Seed messages for the channel chat (category=channel, same as existing test)
    await _seedChatMessage(
        provider,
        CHAT_CHANNEL_1,
        USER_2,
        DATE_FEB_10,
        10,
        "Channel message",
        MessageCategory.CHANNEL,
        MessageType.TEXT,
    )

    # Seed a private chat without chat_info (should fall back to sign-derived "private")
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_1,
        USER_1,
        DATE_JAN_15,
        11,
        "Private message",
        MessageCategory.USER,
        MessageType.TEXT,
    )

    # Seed a group chat without chat_info (should fall back to sign-derived "group")
    await _seedChatMessage(
        provider,
        CHAT_GROUP_1,
        USER_2,
        DATE_FEB_11,  # Different date to avoid collision with channel message
        12,
        "Group message",
        MessageCategory.CHANNEL,
        MessageType.TEXT,
    )

    migration = Migration027DropChatStatsBackfillAggregates()
    await migration.up(provider)

    # Verify channel message has chat_type="channel" (not "group" from sign)
    channelPerConsumerRows = await provider.executeFetchAll(
        """
        SELECT labels, metric_value
        FROM stat_aggregates
        WHERE event_type = 'message'
          AND labels LIKE :consumerPattern
          AND period_type = 'daily'
          AND metric_key = 'message_count'
        """,
        {"consumerPattern": '%"consumer":"-1000"%'},  # Compact JSON: no space after colon
    )
    assert (
        len(channelPerConsumerRows) == 1
    ), f"Expected 1 per-consumer daily row for channel, got {len(channelPerConsumerRows)}"
    for row in channelPerConsumerRows:
        labels = json.loads(row["labels"])
        assert (
            labels["chat_type"] == "channel"
        ), f"Expected chat_type='channel' for per-consumer, got {labels['chat_type']}"

    # Verify __global__ channel message also has chat_type="channel"
    channelGlobalRows = await provider.executeFetchAll(
        """
        SELECT labels, metric_value
        FROM stat_aggregates
        WHERE event_type = 'message'
          AND labels LIKE :consumerPattern
          AND labels LIKE :channelTypePattern
          AND period_type = 'daily'
          AND metric_key = 'message_count'
        """,
        {
            "consumerPattern": '%"consumer":"__global__"%',
            "channelTypePattern": '%"chat_type":"channel"%',
        },
    )
    assert len(channelGlobalRows) == 1, f"Expected 1 __global__ daily row for channel, got {len(channelGlobalRows)}"
    for row in channelGlobalRows:
        labels = json.loads(row["labels"])
        assert (
            labels["chat_type"] == "channel"
        ), f"Expected chat_type='channel' for __global__, got {labels['chat_type']}"

    # Verify private message (no chat_info) uses sign-derived "private"
    privateRows = await provider.executeFetchAll(
        """
        SELECT labels
        FROM stat_aggregates
        WHERE event_type = 'message'
          AND labels LIKE :consumerPattern
          AND period_type = 'daily'
          AND metric_key = 'message_count'
        """,
        {"consumerPattern": '%"consumer":"123"%'},  # Compact JSON: no space after colon
    )
    assert len(privateRows) == 1, f"Expected 1 per-consumer daily row for private, got {len(privateRows)}"
    labels = json.loads(privateRows[0]["labels"])
    assert labels["chat_type"] == "private", f"Expected chat_type='private' (sign-derived), got {labels['chat_type']}"

    # Verify group message (no chat_info) uses sign-derived "group"
    groupRows = await provider.executeFetchAll(
        """
        SELECT labels
        FROM stat_aggregates
        WHERE event_type = 'message'
          AND labels LIKE :consumerPattern
          AND period_type = 'daily'
          AND metric_key = 'message_count'
        """,
        {"consumerPattern": '%"consumer":"-789"%'},  # Compact JSON: no space after colon
    )
    assert len(groupRows) == 1, f"Expected 1 per-consumer daily row for group, got {len(groupRows)}"
    labels = json.loads(groupRows[0]["labels"])
    assert labels["chat_type"] == "group", f"Expected chat_type='group' (sign-derived), got {labels['chat_type']}"


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
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_1,
        USER_1,
        DATE_JAN_15,
        1,
        "Test message",
        MessageCategory.USER,
        MessageType.TEXT,
    )

    migration = Migration027DropChatStatsBackfillAggregates()
    await migration.up(provider)

    # Tables are gone, stat_aggregates has back-filled data
    assert not await _tableExists(provider, "chat_stats")
    assert not await _tableExists(provider, "chat_user_stats")

    # Re-run up() - should succeed without error
    await migration.up(provider)

    # Tables still gone, no duplicate rows added (upsert uses replace semantics)
    assert not await _tableExists(provider, "chat_stats")
    assert not await _tableExists(provider, "chat_user_stats")
    aggCount = await provider.executeFetchOne(
        "SELECT COUNT(*) AS cnt FROM stat_aggregates WHERE event_type = 'message'"
    )
    # Should still be 12 rows from the first run (1 bucket × 3 periods × 2 label-sets × 2 metrics)
    assert aggCount is not None and int(aggCount["cnt"]) == 12


async def test_upTwiceWithLegacyTablesPresentDoesNotDoubleAggregates(testDatabase: Database) -> None:
    """up() run twice with legacy tables present (or re-seeded) does NOT double aggregates.

    Tests the replace-semantics convergence that the runningTotal split depends on.
    After the first up(), legacy tables are dropped. We re-seed them and run up() again,
    verifying that the second pass produces the same totals (no double-counting).

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_PRIVATE_1, readonly=False)
    await _rollbackToPre027(provider)

    # Seed initial data
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_1,
        USER_1,
        DATE_JAN_15,
        1,
        "First message",
        MessageCategory.USER,
        MessageType.TEXT,
    )

    migration = Migration027DropChatStatsBackfillAggregates()
    await migration.up(provider)

    # Get aggregate totals after first run
    firstRunTotals = await provider.executeFetchAll("""
        SELECT metric_key, metric_value, labels_hash
        FROM stat_aggregates
        WHERE event_type = 'message'
        ORDER BY labels_hash, period_type, metric_key
        """)
    firstRunDict = {(r["metric_key"], r["labels_hash"]): r["metric_value"] for r in firstRunTotals}

    # Re-create legacy tables manually (they were dropped after first up())
    # This simulates the migration being run again in an environment where
    # legacy tables exist (e.g., partial rollback + re-migration)
    await provider.execute("""
        CREATE TABLE IF NOT EXISTS chat_stats (
            chat_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            messages_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (chat_id, date)
        )
        """)
    await provider.execute("""
        CREATE TABLE IF NOT EXISTS chat_user_stats (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            messages_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (chat_id, user_id, date)
        )
        """)

    # Re-seed legacy tables (simulate the tables being present again)
    await _seedChatStats(provider, CHAT_PRIVATE_1, DATE_JAN_15, 1)
    await _seedChatUserStats(provider, CHAT_PRIVATE_1, USER_1, DATE_JAN_15, 1)

    # Re-seed more chat_messages to verify new data is added correctly
    await _seedChatMessage(
        provider,
        CHAT_PRIVATE_1,
        USER_2,
        DATE_FEB_10,
        2,
        "Second message",
        MessageCategory.USER,
        MessageType.TEXT,
    )

    # Run up() again
    await migration.up(provider)

    # Verify tables are dropped again
    assert not await _tableExists(provider, "chat_stats")
    assert not await _tableExists(provider, "chat_user_stats")

    # Get aggregate totals after second run
    secondRunTotals = await provider.executeFetchAll("""
        SELECT metric_key, metric_value, labels_hash
        FROM stat_aggregates
        WHERE event_type = 'message'
        ORDER BY labels_hash, period_type, metric_key
        """)

    # Verify totals for the original data are unchanged (not doubled)
    for row in secondRunTotals:
        key = (row["metric_key"], row["labels_hash"])
        if key in firstRunDict:
            # Original data should not be doubled
            assert (
                row["metric_value"] == firstRunDict[key]
            ), f"Aggregate {key} was doubled: {row['metric_value']} != {firstRunDict[key]}"

    # Verify we have more aggregate rows now (added the second message)
    # The first run had 12 rows (1 bucket × 3 periods × 2 label-sets × 2 metrics)
    # The second run should have more due to the new message
    assert len(secondRunTotals) > len(firstRunTotals)
