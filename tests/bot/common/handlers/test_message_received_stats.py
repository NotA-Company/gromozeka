"""Tests for message_received stats event recording in BaseBotHandler.saveChatMessage.

Covers the Phase 1 implementation of the stats-collecting-v1 design:
- Event recorded exactly once per saved message (text and media)
- No record when save fails (UNKNOWN message type early return)
- Default NullStatsStorage path (stats disabled = zero behavior change)
- Correct stats/labels: message_count, text_length, user_id, chat_type, message_type
- Media message → message_type=<non-TEXT enum value>, text_length=0

All tests use real EnsuredMessage objects and follow the conftest.py pattern.
"""

import datetime
import hashlib
from unittest.mock import AsyncMock

from internal.bot.models import BotProvider, ChatType, MessageType
from internal.bot.models.ensured_message import EnsuredMessage, MessageRecipient, MessageSender
from internal.database.models import MessageCategory
from internal.models import MessageId
from lib.stats import NullStatsStorage, StatsStorage
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

    async def test_media_message_message_type_and_text_length_zero(self, mockConfigManager, mockDatabaseWrapper):
        """Media message → message_type=<non-TEXT enum value>, text_length=0 (media-only message)."""
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
        assert labels["message_type"] == MessageType.IMAGE  # Media message type

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
        # Commands are text messages, so message_type should be MessageType.TEXT
        call = mockStatsStorage.record.call_args
        assert call.kwargs["labels"]["message_type"] == MessageType.TEXT

    async def test_live_and_backfill_label_buckets_differ(self, mockConfigManager, mockDatabaseWrapper):
        """Live labels include message_type; backfill labels never do → different labels_hash buckets.

        Verifies bucket separation: live recording emits labels with message_type,
        while backfill rows (migration 027) never have this label. Their labels_hash
        values therefore differ, and no backfill-shape row exists among live aggregates.
        """
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        # Create a text message
        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Hello world",
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
        call = mockStatsStorage.record.call_args

        # Verify live labels include message_type
        liveLabels = call.kwargs["labels"]
        assert "message_type" in liveLabels
        assert liveLabels["message_type"] == MessageType.TEXT

        # Compute live labels hash
        liveLabelsJson = jsonDumps(liveLabels)
        liveLabelsHash = hashlib.md5(liveLabelsJson.encode("utf-8")).hexdigest()

        # Backfill-shape labels are the same but WITHOUT message_type
        backfillLabels = {k: v for k, v in liveLabels.items() if k != "message_type"}
        backfillLabelsJson = jsonDumps(backfillLabels)
        backfillLabelsHash = hashlib.md5(backfillLabelsJson.encode("utf-8")).hexdigest()

        # Assert hashes differ
        assert backfillLabelsHash != liveLabelsHash, "Backfill and live labels_hash must differ"

        # Since message_type is always present in live labels and never in backfill labels,
        # their label-sets (and thus hashes) will always differ → no accidental merge/double-count.
