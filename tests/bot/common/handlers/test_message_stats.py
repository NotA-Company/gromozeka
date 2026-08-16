"""Tests for message stats event recording in BaseBotHandler.saveChatMessage.

Covers the Phase 4b implementation of the stats-collecting-v1 design:
- Event recorded for both directions (inbound + outbound); direction via sender identity
- No record when save fails (UNKNOWN message type early return)
- No record for DELETED/UNSPECIFIED categories (rewrites/defaults)
- No record when getBotId fails (best-effort stats must never break message saving)
- Default NullStatsStorage path (stats disabled = zero behavior change)
- Correct stats/labels: message_count, text_length, user_id, chat_type, message_type, message_category, sent
- Media message → message_type=<non-TEXT enum value>, text_length=0
- Direction rule: sent=True when sender.id == botId, sent=False otherwise (not category-driven)

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


class TestMessageStatsRecording:
    """Test suite for message stats event recording."""

    async def test_inbound_user_message_records_with_sent_false(self, mockConfigManager, mockDatabaseWrapper):
        """Inbound USER message records with sent=False and correct labels."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

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
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)

        # Mock getBotId to return a different user ID (so sent=False)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1

        call = mockStatsStorage.record.call_args
        assert call.kwargs["stats"] == {"message_count": 1, "text_length": 11}  # "Hello world" length
        assert call.kwargs["consumerId"] == "100"
        labels = call.kwargs["labels"]
        assert labels["user_id"] == "42"
        assert labels["chat_type"] == "private"
        assert labels["message_type"] == MessageType.TEXT
        assert labels["message_category"] == MessageCategory.USER
        assert labels["sent"] == "False"  # sender (42) != bot (999)

    async def test_inbound_user_command_records_with_sent_false(self, mockConfigManager, mockDatabaseWrapper):
        """Inbound USER_COMMAND message records with sent=False and correct message_category."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

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
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER_COMMAND)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["message_category"] == MessageCategory.USER_COMMAND
        assert labels["sent"] == "False"

    async def test_inbound_user_spam_records_with_sent_false(self, mockConfigManager, mockDatabaseWrapper):
        """Inbound USER_SPAM message records with sent=False."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Spam",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER_SPAM)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["message_category"] == MessageCategory.USER_SPAM
        assert labels["sent"] == "False"

    async def test_inbound_user_config_answer_records_with_sent_false(self, mockConfigManager, mockDatabaseWrapper):
        """Inbound USER_CONFIG_ANSWER message records with sent=False."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Yes",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER_CONFIG_ANSWER)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["message_category"] == MessageCategory.USER_CONFIG_ANSWER
        assert labels["sent"] == "False"

    async def test_inbound_channel_records_with_sent_false(self, mockConfigManager, mockDatabaseWrapper):
        """Inbound CHANNEL message records with sent=False."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.CHANNEL),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Channel post",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.CHANNEL)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["message_category"] == MessageCategory.CHANNEL
        assert labels["sent"] == "False"
        assert labels["chat_type"] == "channel"

    async def test_outbound_bot_category_records_with_sent_true(self, mockConfigManager, mockDatabaseWrapper):
        """Outbound BOT message records with sent=True when sender is the bot."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=999, name="Bot", username="@bot"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Bot reply",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)  # Bot ID matches sender

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.BOT)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["message_category"] == MessageCategory.BOT
        assert labels["sent"] == "True"  # sender (999) == bot (999)

    async def test_outbound_bot_command_reply_records_with_sent_true(self, mockConfigManager, mockDatabaseWrapper):
        """Outbound BOT_COMMAND_REPLY message records with sent=True."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=999, name="Bot", username="@bot"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Command response",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.BOT_COMMAND_REPLY)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["message_category"] == MessageCategory.BOT_COMMAND_REPLY
        assert labels["sent"] == "True"

    async def test_outbound_bot_error_records_with_sent_true(self, mockConfigManager, mockDatabaseWrapper):
        """Outbound BOT_ERROR message records with sent=True."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=999, name="Bot", username="@bot"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Error",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.BOT_ERROR)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["message_category"] == MessageCategory.BOT_ERROR
        assert labels["sent"] == "True"

    async def test_outbound_bot_summary_records_with_sent_true(self, mockConfigManager, mockDatabaseWrapper):
        """Outbound BOT_SUMMARY message records with sent=True."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=999, name="Bot", username="@bot"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Summary",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.BOT_SUMMARY)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["message_category"] == MessageCategory.BOT_SUMMARY
        assert labels["sent"] == "True"

    async def test_outbound_bot_resended_records_with_sent_true(self, mockConfigManager, mockDatabaseWrapper):
        """Outbound BOT_RESENDED message records with sent=True."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=999, name="Bot", username="@bot"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Resended",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.BOT_RESENDED)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["message_category"] == MessageCategory.BOT_RESENDED
        assert labels["sent"] == "True"

    async def test_outbound_bot_spam_notification_records_with_sent_true(self, mockConfigManager, mockDatabaseWrapper):
        """Outbound BOT_SPAM_NOTIFICATION message records with sent=True."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=999, name="Bot", username="@bot"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Spam notification",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.BOT_SPAM_NOTIFICATION)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["message_category"] == MessageCategory.BOT_SPAM_NOTIFICATION
        assert labels["sent"] == "True"

    async def test_deleted_category_does_not_record(self, mockConfigManager, mockDatabaseWrapper):
        """MessageCategory.DELETED does NOT record stats (excluded)."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Deleted message",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.DELETED)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 0

    async def test_unspecified_category_does_not_record(self, mockConfigManager, mockDatabaseWrapper):
        """MessageCategory.UNSPECIFIED does NOT record stats (excluded)."""
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Default message",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.UNSPECIFIED)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 0

    async def test_direction_rule_sender_driven_not_category(self, mockConfigManager, mockDatabaseWrapper):
        """Direction is determined by sender.id == botId, NOT by messageCategory.

        BOT-category message from a user → sent=False.
        USER-category message from the bot → sent=True.
        """
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)  # Bot ID is 999

        # Case 1: BOT-category message from a USER (not the bot) → sent=False
        botCategoryFromUser = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),  # User ID
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Bot-category from user",
        )
        botCategoryFromUser.messageType = MessageType.TEXT

        result = await handler.saveChatMessage(botCategoryFromUser, MessageCategory.BOT)
        assert result is True
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["sent"] == "False", "BOT-category from user should have sent=False"

        # Case 2: USER-category message from the BOT → sent=True
        mockStatsStorage.reset_mock()
        userCategoryFromBot = EnsuredMessage(
            sender=MessageSender(id=999, name="Bot", username="@bot"),  # Bot ID
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(201),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="User-category from bot",
        )
        userCategoryFromBot.messageType = MessageType.TEXT

        result = await handler.saveChatMessage(userCategoryFromBot, MessageCategory.USER)
        assert result is True
        labels = mockStatsStorage.record.call_args.kwargs["labels"]
        assert labels["sent"] == "True", "USER-category from bot should have sent=True"

    async def test_getbotid_raises_records_as_not_sent(self, mockConfigManager, mockDatabaseWrapper):
        """When getBotId raises, stats are recorded with sent=False and message save still succeeds.

        Unknown bot identity counts as non-bot (belt-and-suspenders; shouldn't happen).
        """
        from internal.bot.common.handlers.base import BaseBotHandler

        mockStatsStorage = AsyncMock(spec=StatsStorage)
        mockStatsStorage.record = AsyncMock(return_value=None)

        message = EnsuredMessage(
            sender=MessageSender(id=42, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=MessageId(200),
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="Test",
        )
        message.messageType = MessageType.TEXT

        handler = BaseBotHandler(
            configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
        )
        handler.messageStatsStorage = mockStatsStorage
        handler.db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        # Mock getBotId to raise an exception
        handler.getBotId = AsyncMock(side_effect=RuntimeError("API error"))

        # Act - should not raise
        result = await handler.saveChatMessage(message, MessageCategory.USER)

        # Assert
        assert result is True, "Message save should succeed even if getBotId fails"
        assert mockStatsStorage.record.call_count == 1, "Stats should be recorded even when getBotId fails"
        # Verify the record call had sent="False"
        call_args = mockStatsStorage.record.call_args
        assert call_args is not None, "record() should have been called"
        labels = call_args.kwargs.get("labels") or call_args[1].get("labels")
        assert labels["sent"] == "False", "sent should be False when getBotId fails"

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
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

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
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

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
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

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
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.CHANNEL)

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
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER_COMMAND)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        # Commands are text messages, so message_type should be MessageType.TEXT
        call = mockStatsStorage.record.call_args
        assert call.kwargs["labels"]["message_type"] == MessageType.TEXT

    async def test_live_and_backfill_label_buckets_differ(self, mockConfigManager, mockDatabaseWrapper):
        """Live labels include sent; backfill labels never do → different labels_hash buckets.

        Verifies bucket separation: live recording emits labels with sent,
        while backfill rows (migration 027) never have this label. Their labels_hash
        values therefore differ, and no backfill-shape row exists among live aggregates.

        Both live and backfill now include message_category and message_type labels
        (changed in migration 027 rework to source from chat_messages instead of
        chat_user_stats), but only live adds the sent label.
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
        handler.updateChatInfo = AsyncMock(return_value=None)
        handler.cache.updateChatUser = AsyncMock(return_value=None)
        handler.getBotId = AsyncMock(return_value=999)

        # Act
        result = await handler.saveChatMessage(message, MessageCategory.USER)

        # Assert
        assert result is True
        assert mockStatsStorage.record.call_count == 1
        call = mockStatsStorage.record.call_args

        # Verify live labels include message_category, message_type, and sent
        liveLabels = call.kwargs["labels"]
        assert "message_category" in liveLabels
        assert "message_type" in liveLabels
        assert "sent" in liveLabels
        assert liveLabels["message_category"] == MessageCategory.USER
        assert liveLabels["message_type"] == MessageType.TEXT
        assert liveLabels["sent"] == "False"

        # Compute live labels hash
        liveLabelsJson = jsonDumps(liveLabels)
        liveLabelsHash = hashlib.md5(liveLabelsJson.encode("utf-8")).hexdigest()

        # Backfill-shape labels are the same but WITHOUT sent (message_category and message_type are now included)
        backfillLabels = {k: v for k, v in liveLabels.items() if k != "sent"}
        backfillLabelsJson = jsonDumps(backfillLabels)
        backfillLabelsHash = hashlib.md5(backfillLabelsJson.encode("utf-8")).hexdigest()

        # Assert hashes differ
        assert backfillLabelsHash != liveLabelsHash, "Backfill and live labels_hash must differ"

        # Since sent is always present in live labels and never in backfill labels,
        # their label-sets (and thus hashes) will always differ → no accidental merge/double-count.

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
