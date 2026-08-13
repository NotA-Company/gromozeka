"""Tests for message_received stats event recording in BaseBotHandler.saveChatMessage.

Covers the Phase 1b implementation of the stats-collecting-v1 design:
- Event recorded exactly once per saved message (text and media)
- No record when save fails (UNKNOWN message type early return)
- Default NullStatsStorage path (stats disabled = zero behavior change)
- Correct stats/labels: message_count, text_length, user_id, chat_type, has_media
- Media message → has_media="1", text_length=0
- Cross-compatibility: live aggregation matches backfill hash

All tests use real EnsuredMessage objects and follow the conftest.py pattern.
"""

import datetime
import hashlib
from typing import Optional
from unittest.mock import AsyncMock

from internal.bot.models import BotProvider, ChatType, MessageType
from internal.bot.models.ensured_message import EnsuredMessage, MessageRecipient, MessageSender
from internal.database.models import MessageCategory
from internal.database.stats_storage import DatabaseStatsStorage
from internal.models import MessageId
from lib.stats import GLOBAL_CONSUMER_ID, NullStatsStorage, StatsStorage
from lib.utils import jsonDumps


class TestMessageReceivedStatsRecording:
    """Test suite for message_received stats event recording."""

    async def test_records_event_on_successful_save_with_text(self, mockConfigManager, mockDatabaseWrapper):
        """Handler records event once per saved text message with correct stats/labels/consumerId."""
        # Arrange
        from internal.bot.common.handlers.base import BaseBotHandler

        # Create a mock StatsStorage with AsyncMock
        mockStatsStorage = AsyncMock(spec=StatsStorage)

        # Create a real EnsuredMessage for a text message in a private chat
        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Hello world",
        )
        message.messageType = MessageType.TEXT

        # Create a minimal handler instance with mocked database
        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)  # Mock to avoid bot requirement
        handler.cache.updateChatUser = AsyncMock(return_value=None)  # Mock cache call

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1

        # Verify the call arguments
        call = mockStatsStorage.record.call_args
        assert call.kwargs["stats"] == {"message_count": 1, "text_length": 11}  # "Hello world" length
        assert call.kwargs["consumerId"] == "100"  # chat.id as string
        labels = call.kwargs["labels"]
        assert labels["user_id"] == "42"
        assert labels["chat_type"] == "private"
        assert labels["has_media"] == "0"  # Text message

    async def test_no_record_when_save_fails_unknown_type(self, mockConfigManager, mockDatabaseWrapper):
        """No stats record when saveChatMessage returns False (UNKNOWN message type early return)."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        # Create an UNKNOWN type message (will early-return in saveChatMessage)
        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Unknown message",
        )
        message.messageType = MessageType.UNKNOWN

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER)

        # Assert
        assert result is False
        assert mockStatsStorage.record.call_count == 0

    async def test_null_stats_storage_path_no_explosions(self, mockConfigManager, mockDatabaseWrapper):
        """Default NullStatsStorage path: save works, nothing explodes (stats disabled = zero behavior change)."""
        from internal.bot.common.handlers.base import BaseBotHandler

        # Handler uses NullStatsStorage by default
        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        assert isinstance(handler.messageStatsStorage, NullStatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Test message",
        )
        message.messageType = MessageType.TEXT
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)  # Mock to avoid bot requirement
        handler.cache.updateChatUser = AsyncMock(return_value=None)  # Mock cache call

        # Act - should not raise
        result = await handler.saveChatMessage(message, MessageCategory.USER)

        # Assert
        assert result is True
        # NullStatsStorage.record is a no-op, so no calls were made

    async def test_media_message_has_media_flag_and_text_length_zero(self, mockConfigManager, mockDatabaseWrapper):
        """Media message → has_media="1", text_length=0 (media-only message)."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        # Create an IMAGE message (media)
        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="",  # Empty text for media-only message
        )
        message.messageType = MessageType.IMAGE
        message.mediaId = "media_123"

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)  # Mock to avoid bot requirement
        handler.cache.updateChatUser = AsyncMock(return_value=None)  # Mock cache call

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER)

        # Assert
        assert result is True
        call = mockStatsStorage.record.call_args
        assert call.kwargs["stats"] == {"message_count": 1, "text_length": 0}
        labels = call.kwargs["labels"]
        assert labels["has_media"] == "1"  # Media message

    async def test_group_chat_type_label(self, mockConfigManager, mockDatabaseWrapper):
        """Group chat message has chat_type="group" in labels."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        # Create a message in a GROUP chat
        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.GROUP),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Group message",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)  # Mock to avoid bot requirement
        handler.cache.updateChatUser = AsyncMock(return_value=None)  # Mock cache call

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER)

        # Assert
        assert result is True
        call = mockStatsStorage.record.call_args
        labels = call.kwargs["labels"]
        assert labels["chat_type"] == "group"

    async def test_channel_chat_type_label(self, mockConfigManager, mockDatabaseWrapper):
        """Channel chat message has chat_type="channel" in labels."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        # Create a message in a CHANNEL
        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.CHANNEL),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Channel message",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)  # Mock to avoid bot requirement
        handler.cache.updateChatUser = AsyncMock(return_value=None)  # Mock cache call

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER)

        # Assert
        assert result is True
        call = mockStatsStorage.record.call_args
        labels = call.kwargs["labels"]
        assert labels["chat_type"] == "channel"

    async def test_command_path_through_save_chat_message(self, mockConfigManager, mockDatabaseWrapper):
        """Command messages route through the same saveChatMessage wrapper (one test suffices).

        Commands are saved by HandlersManager.handleCommand which calls handler.saveChatMessage.
        This test verifies the wrapper works for the command path by invoking it directly.
        """
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        # Create a message that could be a command (e.g., "/help")
        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="/help",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)  # Mock to avoid bot requirement
        handler.cache.updateChatUser = AsyncMock(return_value=None)  # Mock cache call

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        # Commands are text messages, so has_media should be "0"
        call = mockStatsStorage.record.call_args
        labels = call.kwargs["labels"]
        assert labels["has_media"] == "0"


class TestBackfillCrossCompatibility:
    """Cross-compatibility test: live aggregation hash parity and backfill bucket separation.

    This test verifies that:
    - Live message_received events produce labels_hash that matches aggregation
    - Backfill-shape labels_hash (same labels minus has_media) differs from live hash
    This confirms live and backfilled rows occupy distinct buckets — no accidental merge/double-count.
    """

    async def test_hashMechanismParity_andLiveBackfillBucketSeparation(self, mockConfigManager, testDatabase):
        """Live aggregation hash parity and backfill bucket separation.

        Drives the live side through the PRODUCTION path (saveChatMessage),
        captures the exact labels dict production builds, runs aggregate(),
        and asserts:
        - md5(jsonDumps(productionLabels)) equals the labels_hash stored in the aggregated row
        - The backfill-shape hash (same labels minus has_media) DIFFERS from live hash

        This proves live and backfilled rows occupy distinct buckets.
        """
        from internal.bot.common.handlers.base import BaseBotHandler

        # Create storage for message_received events
        storage = DatabaseStatsStorage(db=testDatabase, eventType="message_received", dataSource="default")

        # Spy to capture production labels
        capturedProductionLabels: dict[str, str] | None = None

        originalRecord = storage.record

        async def spyRecord(
            stats: dict[str, float | int],
            *,
            consumerId: Optional[str] = None,
            labels: Optional[dict[str, str]] = None,
            eventTime: Optional[datetime.datetime] = None,
        ) -> None:
            nonlocal capturedProductionLabels
            # Capture the labels and merge consumerId exactly as production does
            capturedProductionLabels = dict(labels or {})
            capturedProductionLabels["consumer"] = consumerId or GLOBAL_CONSUMER_ID
            await originalRecord(stats, consumerId=consumerId, labels=labels, eventTime=eventTime)

        storage.record = spyRecord

        # Create a handler with the spied storage
        handler = BaseBotHandler(
            configManager=mockConfigManager, database=testDatabase, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = storage
        handler.updateChatInfo = AsyncMock(return_value=None)  # Mock to avoid bot requirement
        handler.cache.updateChatUser = AsyncMock(return_value=None)  # Mock cache call

        # Create a real EnsuredMessage and save via production path
        message = EnsuredMessage(
            sender=MessageSender(id=100, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=42, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Hello world",
        )
        message.messageType = MessageType.TEXT

        await handler.saveChatMessage(message, MessageCategory.USER)

        # Verify production labels were captured (includes has_media and consumer)
        assert capturedProductionLabels is not None, "Production labels should have been captured"
        assert "has_media" in capturedProductionLabels, "Production labels should include has_media"
        assert "consumer" in capturedProductionLabels, "Production labels should include consumer"
        assert capturedProductionLabels == {
            "user_id": "100",
            "chat_type": "private",
            "has_media": "0",
            "consumer": "42",
        }, "Production labels should match expected shape"

        # Compute production hash (same algorithm as _hashLabels in stats_storage.py)
        # Type: ignore for capturedProductionLabels - pyright doesn't narrow after assert
        productionLabelsJson = jsonDumps(capturedProductionLabels)  # type: ignore[arg-type]
        productionHash = hashlib.md5(productionLabelsJson.encode("utf-8")).hexdigest()

        # Run aggregation to roll up the event
        await storage.aggregate()

        # Query the stat_aggregates table for the daily row using the production hash
        # Filter to consumer="42" and metric_key="message_count" to exclude:
        #   - Global rollup (consumer="__global__")
        #   - Other metrics like text_length
        provider = await testDatabase.manager.getProvider()
        rows = await provider.executeFetchAll(
            """
            SELECT labels, labels_hash
            FROM stat_aggregates
            WHERE event_type = 'message_received'
              AND period_type = 'daily'
              AND labels_hash = :expectedHash
              AND metric_key = 'message_count'
              AND labels LIKE '%"consumer":"42"%'
            """,
            {"expectedHash": productionHash},
        )

        assert len(rows) == 1, "Expected exactly one aggregated row with production hash"
        row = rows[0]
        actualHash = row["labels_hash"]
        assert actualHash == productionHash, f"Hash mismatch: live={actualHash} vs expected={productionHash}"

        # Verify the labels JSON matches too
        actualLabelsJson = row["labels"]
        assert (
            actualLabelsJson == productionLabelsJson
        ), f"Labels JSON mismatch: live={actualLabelsJson} vs expected={productionLabelsJson}"

        # Now verify backfill-shape hash differs from production hash
        # Backfill shape is same labels MINUS has_media
        if capturedProductionLabels is None:
            raise AssertionError("capturedProductionLabels should not be None at this point")
        backfillLabels = {k: v for k, v in capturedProductionLabels.items() if k != "has_media"}
        backfillLabelsJson = jsonDumps(backfillLabels)
        backfillHash = hashlib.md5(backfillLabelsJson.encode("utf-8")).hexdigest()

        assert (
            backfillHash != productionHash
        ), f"Backfill hash should differ from production hash: backfill={backfillHash} vs production={productionHash}"

        # Verify no backfill-shape row exists in the aggregates (proving bucket separation)
        backfillRows = await provider.executeFetchAll(
            """
            SELECT labels_hash
            FROM stat_aggregates
            WHERE event_type = 'message_received'
              AND period_type = 'daily'
              AND labels_hash = :expectedHash
              AND metric_key = 'message_count'
            """,
            {"expectedHash": backfillHash},
        )

        assert (
            len(backfillRows) == 0
        ), f"No backfill-shape row should exist (it would merge incorrectly): found {len(backfillRows)} rows"
