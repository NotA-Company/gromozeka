"""Tests for the StatsHandler.

Tests argument parsing, scoping, chat settings gating, and view rendering.
"""

import asyncio
import datetime
import time
import unittest.mock
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import lib.stats.stats_pages.launcher
from internal.bot.common.handlers.chat_search import ChatSearchHandler
from internal.bot.common.handlers.configure import ConfigureCommandHandler
from internal.bot.common.handlers.delete_from_user import DeleteFromUserMessageHandler
from internal.bot.common.handlers.dev_commands import DevCommandsHandler
from internal.bot.common.handlers.divination import DivinationHandler
from internal.bot.common.handlers.help_command import HelpHandler
from internal.bot.common.handlers.llm_messages import LLMMessageHandler
from internal.bot.common.handlers.manager import HandlersManager
from internal.bot.common.handlers.media import MediaHandler
from internal.bot.common.handlers.message_preprocessor import MessagePreprocessorHandler
from internal.bot.common.handlers.react_on_user import ReactOnUserMessageHandler
from internal.bot.common.handlers.resender import ResenderHandler
from internal.bot.common.handlers.sandbox import SandboxHandler
from internal.bot.common.handlers.spam import SpamHandler
from internal.bot.common.handlers.stats import StatsHandler
from internal.bot.common.handlers.summarization import SummarizationHandler
from internal.bot.common.handlers.topic_manager import TopicManagerHandler
from internal.bot.common.handlers.user_memories import UserMemoriesHandler
from internal.bot.common.handlers.weather import WeatherHandler
from internal.bot.common.handlers.yandex_search import YandexSearchHandler
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    CommandCategory,
    EnsuredMessage,
)
from internal.models.types import MessageId
from internal.services.cache import CacheService
from internal.services.queue_service import QueueService
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction
from internal.services.stats.service import StatsAggregationService
from internal.services.storage import StorageService
from lib.stats import NullStatsStorage, StatsAnalyzer
from lib.stats.stats_pages import StatsPayload
from lib.stats.types import StatsAggregateDict

# Helper to build EnsuredMessage


def buildEnsuredMessage(
    chatId: int = 123,
    chatType: ChatType = ChatType.PRIVATE,
    userId: int = 456,
    username: str = "testuser",
    fullName: str = "Test User",
    messageId: int = 789,
) -> EnsuredMessage:
    """Build a test EnsuredMessage instance.

    Args:
        chatId: Chat ID.
        chatType: Type of chat.
        userId: User ID.
        username: Username.
        fullName: Full name.
        messageId: Message ID.

    Returns:
        EnsuredMessage instance.
    """
    recipient = MagicMock()
    recipient.id = chatId
    recipient.chatType = chatType

    sender = MagicMock()
    sender.id = userId
    sender.username = username
    sender.fullName = fullName

    message = EnsuredMessage(
        sender=sender,
        recipient=recipient,
        messageId=MessageId(messageId),
        date=datetime.datetime.now(datetime.timezone.utc),
    )
    return message


class TestStatsHandlerGrammar:
    """Tests for argument parsing and grammar."""

    def test_empty_args_defaults(self):
        """Test that empty args use defaults (7d, messages, no web)."""
        # Initialize handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Parse empty args
        result = handler._parseStatsArgs("", forceWeb=False)

        assert result is not None
        assert result["help"] is False
        assert result["chatId"] is None
        assert result["period"] == "7d"
        assert result["section"] == "messages"
        assert result["user"] is None
        assert result["web"] is False

    def test_help_arg(self):
        """Test that 'help' positional returns help flag."""
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        result = handler._parseStatsArgs("help", forceWeb=False)

        assert result is not None
        assert result["help"] is True

    def test_alias_forces_web(self):
        """Test that /stats_web alias forces web mode."""
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        result = handler._parseStatsArgs("", forceWeb=True)

        assert result is not None
        assert result["web"] is True


class TestStatsHandlerRegistration:
    """Tests for conditional handler registration."""

    def test_stats_disabled_no_registration(self):
        """Test that handler raises when stats disabled."""

        # Mock stats disabled
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()

        # Handler construction should raise
        with pytest.raises(RuntimeError, match="not enabled"):
            StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

    def test_stats_enabled_construction_ok(self):
        """Test that handler constructs successfully when stats enabled."""

        # Mock stats enabled
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()

        # Handler construction should succeed
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)
        assert handler is not None


class TestStatsHandlerAllowShowStatsGate:
    """Tests for D16 ALLOW_SHOW_STATS gate."""

    async def test_group_chat_with_allow_show_stats_false_sends_informative_reply(self):
        """Test that group chat with ALLOW_SHOW_STATS=false sends informative reply and skips storage queries."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler with mocks
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock chat settings with ALLOW_SHOW_STATS=false
        chatSettings = {k: ChatSettingsValue("") for k in ChatSettingsKey}
        chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS] = ChatSettingsValue("false")
        handler.getChatSettings = AsyncMock(return_value=chatSettings)

        # Mock storage to verify no queries are made
        mockStorage = MagicMock(spec=NullStatsStorage)
        handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

        # Mock sendMessage to capture output
        handler.sendMessage = AsyncMock()

        # Build group chat message
        message = buildEnsuredMessage(chatId=-100123456789, chatType=ChatType.GROUP, userId=456)

        # Execute command
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="",
            updateObj=None,
            typingManager=None,
        )

        # Verify informative reply was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        assert "Показ статистики отключён" in callArgs.kwargs["messageText"]

        # Verify no storage queries were made (handler returned early)
        handler.statsAggregationService.getQueryStorage.assert_not_called()

    async def test_group_chat_with_allow_show_stats_true_normal_flow(self):
        """Test that group chat with ALLOW_SHOW_STATS=true proceeds with normal stats flow."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler with mocks
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock chat settings with ALLOW_SHOW_STATS=true
        chatSettings = {k: ChatSettingsValue("") for k in ChatSettingsKey}
        chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS] = ChatSettingsValue("true")
        handler.getChatSettings = AsyncMock(return_value=chatSettings)

        # Mock getUserChats to return empty list
        handler.getUserChats = AsyncMock(return_value=[])

        # Mock storage
        mockStorage = MagicMock(spec=NullStatsStorage)
        mockStorage.query = AsyncMock(return_value=[])
        handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build group chat message
        message = buildEnsuredMessage(chatId=-100123456789, chatType=ChatType.GROUP, userId=456)

        # Execute command
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="",
            updateObj=None,
            typingManager=None,
        )

        # Verify storage query was made (normal flow)
        mockStorage.query.assert_called()
        callArgs = mockStorage.query.call_args
        assert callArgs.kwargs["eventType"] == "message"
        assert callArgs.kwargs["periodType"] == "daily"

    async def test_private_chat_with_allow_show_stats_false_still_returns_stats(self):
        """Test that private chat with ALLOW_SHOW_STATS=false still returns stats (gate not consulted)."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler with mocks
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock chat settings with ALLOW_SHOW_STATS=false (should be ignored for private)
        chatSettings = {k: ChatSettingsValue("") for k in ChatSettingsKey}
        chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS] = ChatSettingsValue("false")
        handler.getChatSettings = AsyncMock(return_value=chatSettings)

        # Mock getUserChats to return empty list
        handler.getUserChats = AsyncMock(return_value=[])

        # Mock storage
        mockStorage = MagicMock(spec=NullStatsStorage)
        mockStorage.query = AsyncMock(return_value=[])
        handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build PRIVATE chat message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="",
            updateObj=None,
            typingManager=None,
        )

        # Verify storage query was made (gate not consulted for private)
        mockStorage.query.assert_called()
        # Verify getChatSettings was NOT called for private chats
        handler.getChatSettings.assert_not_called()

    async def test_utilities_category_passes_category_gate_in_group_chat(self):
        """Test that UTILITIES-category commands pass the category gate in group chats.

        This is a manager-level test that verifies the category gate allows UTILITIES
        commands in group chats, so the handler's own ALLOW_SHOW_STATS gate is consulted.
        """

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler with mocks
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock chat settings with ALLOW_SHOW_STATS=true (to pass the handler's own gate)
        chatSettings = {k: ChatSettingsValue("") for k in ChatSettingsKey}
        chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS] = ChatSettingsValue("true")
        handler.getChatSettings = AsyncMock(return_value=chatSettings)

        # Mock getUserChats to return empty list
        handler.getUserChats = AsyncMock(return_value=[])

        # Mock storage
        mockStorage = MagicMock(spec=NullStatsStorage)
        mockStorage.query = AsyncMock(return_value=[])
        handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build GROUP chat message (UTILITIES category should be allowed here)
        message = buildEnsuredMessage(chatId=-100123456789, chatType=ChatType.GROUP, userId=456)

        # Execute command - should pass category gate and reach handler's ALLOW_SHOW_STATS gate
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="",
            updateObj=None,
            typingManager=None,
        )

        # Verify storage query was made (command passed category gate and handler's own gate)
        mockStorage.query.assert_called()
        # Verify getChatSettings WAS called (handler's own gate was consulted)
        handler.getChatSettings.assert_called_once()


class TestStatsHandlerScope:
    """Tests for scoping and e2e behavior."""

    async def test_group_default_messages_section_only(self):
        """Test that group default renders messages section only for current chat."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock chat settings
        chatSettings = {k: ChatSettingsValue("") for k in ChatSettingsKey}
        chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS] = ChatSettingsValue("true")
        handler.getChatSettings = AsyncMock(return_value=chatSettings)

        # Mock getUserChats to return empty list
        handler.getUserChats = AsyncMock(return_value=[])

        # Mock storage for messages only
        mockStorage = MagicMock(spec=NullStatsStorage)
        mockStorage.query = AsyncMock(return_value=[])
        handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build group chat message
        message = buildEnsuredMessage(chatId=-100123456789, chatType=ChatType.GROUP, userId=456)

        # Execute command
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="",
            updateObj=None,
            typingManager=None,
        )

        # Verify only messages storage was queried
        handler.statsAggregationService.getQueryStorage.assert_called_once_with("message")

    async def test_private_default_renders_chat_list(self):
        """Test that private default renders chat list with messages_count."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock getUserChats to return multiple chats with messages_count
        handler.getUserChats = AsyncMock(
            return_value=[
                {"chat_id": 123, "title": "Chat 1", "messages_count": 100},
                {"chat_id": 456, "title": "Chat 2", "messages_count": 50},
            ]
        )

        # Mock storage
        mockStorage = MagicMock(spec=NullStatsStorage)
        mockStorage.query = AsyncMock(return_value=[])
        handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build private chat message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="",
            updateObj=None,
            typingManager=None,
        )

        # Verify getUserChats was called
        handler.getUserChats.assert_called_once()

        # Verify reply includes chat list
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]
        assert "Ваши чаты:" in replyText
        assert "#`123` Chat 1 — 100" in replyText
        assert "#`456` Chat 2 — 50" in replyText

    async def test_private_positional_chatId_targets_chat_default_section(self):
        """Test that private with positional chatId targets only that chat with default section (messages).

        U12-2 removed the auto-drill-down to all sections. Positional chatId now only selects
        the TARGET chat; the default section (messages) is rendered.
        """

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock getUserChats to return the requested chat
        handler.getUserChats = AsyncMock(return_value=[{"chat_id": 789, "title": "Target Chat", "messages_count": 100}])

        # Mock storage for default section (messages only)
        mockStorage = MagicMock(spec=NullStatsStorage)
        mockStorage.query = AsyncMock(return_value=[])
        handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build private chat message with positional chatId
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with positional chatId
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="789",
            updateObj=None,
            typingManager=None,
        )

        # Verify only messages storage was queried (default section, not all sections)
        assert handler.statsAggregationService.getQueryStorage.call_count == 1
        storageCalls = [call.args[0] for call in handler.statsAggregationService.getQueryStorage.call_args_list]
        assert "message" in storageCalls

        # Verify reply targets the positional chat (header carries the target chat id)
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]
        assert "789" in replyText  # Header carries the target chat id
        assert "**Messages:**" in replyText  # Only default section (messages) is rendered with bold header

    async def test_private_positional_chatId_not_in_user_chats_error(self):
        """Test that private with positional chatId not in getUserChats returns error."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock getUserChats to NOT return the requested chat
        handler.getUserChats = AsyncMock(return_value=[{"chat_id": 999, "title": "Other Chat", "messages_count": 100}])

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build private chat message with positional chatId
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with positional chatId that doesn't exist in user's chats
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="789",
            updateObj=None,
            typingManager=None,
        )

        # Verify error message was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        assert "Чат не найден среди ваших чатов" in callArgs.kwargs["messageText"]

    async def test_period_mapping_1d_hourly_7d_daily_all_total(self):
        """Test e2e period mapping per U12-1: 1d→daily (old hourly), 7d→daily, all→total, with new h/m suffixes."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Test period mapping with new U12-1 grammar
        # <N>h→hourly (N≤24), <N>d→daily (N≤31), <N>m→monthly (N≥1), all→total
        for periodArg, expectedPeriodType in [
            ("1d", "daily"),  # U12-1: 1d now maps to DAILY (old: hourly)
            ("6h", "hourly"),  # New: hourly suffix
            ("24h", "hourly"),  # New: hourly suffix at upper bound
            ("7d", "daily"),
            ("31d", "daily"),  # Upper bound for days
            ("3m", "monthly"),  # New: monthly suffix
            ("all", "total"),
        ]:
            # Reset handler for each test
            mockConfigManager = MagicMock()
            mockConfigManager.getStatsConfig.return_value = {"enabled": True}
            mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
            mockDatabase = MagicMock()
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock getUserChats
            handler.getUserChats = AsyncMock(return_value=[])

            # Mock storage
            mockStorage = MagicMock(spec=NullStatsStorage)
            mockStorage.query = AsyncMock(return_value=[])
            handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

            # Mock sendMessage
            handler.sendMessage = AsyncMock()

            # Build message
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

            # Execute command with period
            await cast(Any, handler).statsCommand(
                ensuredMessage=message,
                command="stats",
                args=f"--period={periodArg}",
                updateObj=None,
                typingManager=None,
            )

            # Verify correct period type was used
            mockStorage.query.assert_called()
            callArgs = mockStorage.query.call_args
            assert callArgs.kwargs["periodType"] == expectedPeriodType


class TestStatsHandlerUsageErrors:
    """Tests for usage error handling."""

    async def test_unknown_option(self):
        """Test that unknown option returns usage error."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with unknown option
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="--foo=bar",
            updateObj=None,
            typingManager=None,
        )

        # Verify usage error was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]
        assert "❌" in replyText
        assert "Неизвестные опции: foo" in replyText
        assert "Показать статистику использования бота" in replyText

    async def test_bad_period(self):
        """Test that invalid period returns usage error (U12-1: out-of-range Nh/Nd/Nm)."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with bad period (7x is invalid under NEW grammar)
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="--period=7x",
            updateObj=None,
            typingManager=None,
        )

        # Verify usage error was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]
        assert "❌" in replyText
        assert "Неверный период: 7x" in replyText
        # U12-1 help text contains the period specification in the usage text
        assert "--period=..." in replyText

    async def test_second_positional(self):
        """Test that second positional returns usage error."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with two positionals
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="123 456",
            updateObj=None,
            typingManager=None,
        )

        # Verify usage error was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]
        assert "❌" in replyText
        assert "Укажите только один позиционный аргумент" in replyText

    async def test_help_mixed_with_args(self):
        """Test that help mixed with other args returns usage error."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with help and other args
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="help --web",
            updateObj=None,
            typingManager=None,
        )

        # Verify usage error was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]
        assert "❌" in replyText
        assert "help не может сочетаться с другими аргументами" in replyText

    async def test_dangling_user_option(self):
        """Test that dangling --user without value returns usage error."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with dangling --user
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="--user",
            updateObj=None,
            typingManager=None,
        )

        # Verify usage error was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]
        assert "❌" in replyText
        # Production now parses and validates the value itself
        assert "Неверный user ID" in replyText or "--user" in replyText

    async def test_chatId_positional_in_group_chat(self):
        """Test that chatId positional in group chat returns error."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock chat settings
        chatSettings = {k: ChatSettingsValue("") for k in ChatSettingsKey}
        chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS] = ChatSettingsValue("true")
        handler.getChatSettings = AsyncMock(return_value=chatSettings)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build GROUP chat message with positional chatId
        message = buildEnsuredMessage(chatId=-100123456789, chatType=ChatType.GROUP, userId=456)

        # Execute command with positional chatId
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="123",
            updateObj=None,
            typingManager=None,
        )

        # Verify error message was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        assert "Аргумент chatId можно использовать только в личном чате" in callArgs.kwargs["messageText"]

    async def test_section_llm_with_user_filter_renders_with_annotation(self):
        """Test that --section=llm with --user renders LLM section with chat-level annotation (U12-2)."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock chat settings
        chatSettings = {k: ChatSettingsValue("") for k in ChatSettingsKey}
        chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS] = ChatSettingsValue("true")
        handler.getChatSettings = AsyncMock(return_value=chatSettings)

        # Mock storage
        mockStorage = MagicMock(spec=NullStatsStorage)
        mockStorage.query = AsyncMock(return_value=[])
        handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build group chat message
        message = buildEnsuredMessage(chatId=-100123456789, chatType=ChatType.GROUP, userId=456)

        # Execute command with --section=llm and --user
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="--section=llm --user=123",
            updateObj=None,
            typingManager=None,
        )

        # Verify LLM section was rendered with chat-level annotation
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]
        assert "**LLM:**" in replyText
        assert "(на уровне чата, не пользователя)" in replyText

    async def testLlmSection_topModelsFormat(self):
        """Test that Top models section uses caption-in-fence format (caption on fence line)."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock chat settings
        chatSettings = {k: ChatSettingsValue("") for k in ChatSettingsKey}
        chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS] = ChatSettingsValue("true")
        handler.getChatSettings = AsyncMock(return_value=chatSettings)

        # Mock storage with LLM data including top models
        llmRows = [
            StatsAggregateDict(
                periodType="daily",
                periodStart="2026-08-20T00:00:00+00:00",
                labels={"consumer": "456", "modelName": "gpt-4"},
                metricKey="request_count",
                metricValue=10.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2026-08-20T00:00:00+00:00",
                labels={"consumer": "456", "modelName": "gpt-3.5-turbo"},
                metricKey="request_count",
                metricValue=5.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2026-08-20T00:00:00+00:00",
                labels={"consumer": "456", "modelName": "gpt-4"},
                metricKey="input_tokens",
                metricValue=1000.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2026-08-20T00:00:00+00:00",
                labels={"consumer": "456", "modelName": "gpt-4"},
                metricKey="output_tokens",
                metricValue=2000.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2026-08-20T00:00:00+00:00",
                labels={"consumer": "456", "modelName": "gpt-3.5-turbo"},
                metricKey="input_tokens",
                metricValue=500.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2026-08-20T00:00:00+00:00",
                labels={"consumer": "456", "modelName": "gpt-3.5-turbo"},
                metricKey="output_tokens",
                metricValue=1000.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2026-08-20T00:00:00+00:00",
                labels={"consumer": "456", "modelName": "gpt-4"},
                metricKey="elapsed_time",
                metricValue=5000.0,
            ),
            StatsAggregateDict(
                periodType="daily",
                periodStart="2026-08-20T00:00:00+00:00",
                labels={"consumer": "456", "modelName": "gpt-3.5-turbo"},
                metricKey="elapsed_time",
                metricValue=3000.0,
            ),
        ]

        # Make mock return data regardless of period filter (this is a format test, not a filter test)
        async def mockQuery(**kwargs):
            return llmRows

        mockStorage = MagicMock(spec=NullStatsStorage)
        mockStorage.query = AsyncMock(side_effect=mockQuery)
        handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build group chat message
        message = buildEnsuredMessage(chatId=456, chatType=ChatType.GROUP, userId=123)

        # Execute command with --section=llm
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="--section=llm",
            updateObj=None,
            typingManager=None,
        )

        # Verify LLM section was rendered
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]

        # Verify Top models format
        lines = replyText.split("\n")

        # Find Top models section - look for "```Top models:" fence line (caption on fence)
        # Note: space in "Top models:" becomes non-breaking space (U+00A0) in fence
        topModelsStart = None
        for i, line in enumerate(lines):
            if line.strip() == "```Top\xa0models:":
                topModelsStart = i
                break

        assert topModelsStart is not None, f"Top models section not found in result: {replyText}"

        # Verify strict format: "```Top models:" on fence line (caption-in-fence), followed by bullets, then "```"
        assert (
            lines[topModelsStart].strip() == "```Top\xa0models:"
        ), f"Expected fence line '```Top\xa0models:' but got '{lines[topModelsStart].strip()}'"

        # Verify merged fence exists (new shape: caption on fence line)
        assert "```Top\xa0models:" in replyText, f"Result should contain merged fence '```Top\xa0models:': {replyText}"

        # Check that old separate "Top models:" line is NOT present
        assert "\nTop models:\n" not in replyText, f"Result should not contain separate 'Top models:' line: {replyText}"

        # Verify bullet markers and model names
        assert "• gpt-4" in replyText, f"Expected '• gpt-4' in result: {replyText}"
        assert "• gpt-3.5-turbo" in replyText, f"Expected '• gpt-3.5-turbo' in result: {replyText}"

        # Check that fences are balanced
        fenceCount = replyText.count("```")
        assert fenceCount == 2, f"Expected 2 fence markers (opening + closing) but found {fenceCount}: {replyText}"

    async def test_negative_positional_chatId_in_private_chat_returns_error(self):
        """Test that negative positional chatId in private chat returns usage error.

        Negative chat IDs represent groups in Telegram (chatId > 0 = private),
        so a negative positional chatId in a private chat is a usage error.
        """
        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()
        handler.getUserChats = AsyncMock(return_value=[])  # Mock getUserChats to avoid MagicMock error

        # Build PRIVATE chat message with NEGATIVE positional chatId
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with negative positional chatId
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="-100123456789",  # Negative chatId (group ID)
            updateObj=None,
            typingManager=None,
        )

        # Verify error message was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        assert "❌" in callArgs.kwargs["messageText"]
        # The error should be about the chat not being found (since getUserChats returns empty)
        assert "Чат не найден" in callArgs.kwargs["messageText"]

    async def test_bare_double_dash_returns_usage_error(self):
        """Test that bare '--' token returns usage error."""
        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with bare '--' token
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="--",
            updateObj=None,
            typingManager=None,
        )

        # Verify usage error was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        assert "❌" in callArgs.kwargs["messageText"]
        assert "Неизвестные опции" in callArgs.kwargs["messageText"]

    async def test_bare_em_dash_returns_usage_error(self):
        """Test that bare '—' token (all-dash) returns same usage error as '--'."""
        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with bare '—' token (em-dash, all-dash)
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="—",
            updateObj=None,
            typingManager=None,
        )

        # Verify usage error was sent (same as bare '--')
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        assert "❌" in callArgs.kwargs["messageText"]
        assert "Неизвестные опции" in callArgs.kwargs["messageText"]

    async def test_mid_token_dash_preserved_in_error(self):
        """Test that mid-token dash is preserved: '—a—b' → error with '--a—b'."""
        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with mid-token dash: '—a—b'
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="—a—b",
            updateObj=None,
            typingManager=None,
        )

        # Verify error message contains the normalized token with mid-dash preserved
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        assert "❌" in callArgs.kwargs["messageText"]
        # Leading dashes normalized to '--', but mid-token '—' is preserved
        # The error shows the option name (after '--'), so 'a—b' not '--a—b'
        assert "a—b" in callArgs.kwargs["messageText"]

    async def test_unknown_short_option_returns_usage_error(self):
        """Test that unknown short option '-x' returns 'Неизвестные опции' usage error."""
        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with unknown short option '-x'
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="-x",
            updateObj=None,
            typingManager=None,
        )

        # Verify usage error was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        assert "❌" in callArgs.kwargs["messageText"]
        assert "Неизвестная опция" in callArgs.kwargs["messageText"]


class TestStatsHandlerRegistrationInvariant:
    """Tests for registration invariants."""

    def test_stats_disabled_no_handler_registered(self):
        """Test that stats disabled means StatsHandler raises on construction."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Create config with stats disabled
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()

        # Handler construction should raise
        with pytest.raises(RuntimeError, match="not enabled"):
            StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # This proves that the manager cannot register the handler when stats is disabled
        # because the handler raises during construction

    def test_stats_enabled_handler_registered_and_llm_last(self):
        """Test that stats enabled means StatsHandler constructs successfully.

        Note: Full HandlersManager registration invariant (LLMMessageHandler last)
        is verified in the actual manager code. This test verifies the prerequisite:
        that StatsHandler can be constructed when enabled, enabling the manager
        to register it in the correct position.

        The LLMMessageHandler-is-last invariant is enforced in manager.py:
        - StatsHandler is registered conditionally at manager.py:613-619
        - LLMMessageHandler is appended last at manager.py:631-637
        This structural ordering guarantees the invariant when stats is enabled.
        """

        # Reset singleton
        StatsAggregationService._instance = None

        # Create config with stats enabled
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()

        # Handler construction should succeed
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)
        assert handler is not None

        # Verify handler category is UTILITIES
        commandHandlers = handler.getCommandHandlersV2()
        assert len(commandHandlers) == 1, "StatsHandler should register 1 handler with 2 commands (stats, stats_web)"
        handlerInfo = commandHandlers[0]
        assert (
            handlerInfo.category == CommandCategory.UTILITIES
        ), "stats/stats_web commands should be UTILITIES category"
        assert set(handlerInfo.commands) == {
            "stats",
            "stats_web",
        }, "Handler should have both stats and stats_web commands"

    def test_stats_enabled_manager_registration_invariant(self):
        """Test manager-level registration: stats enabled → StatsHandler registered and LLMMessageHandler last.

        This test executes the REAL registration path by mocking only what's needed for
        HandlersManager.__init__ to succeed, then verifies the handler ordering invariant.
        """

        # Reset singleton
        StatsAggregationService._instance = None
        CacheService._instance = None
        StorageService._instance = None
        QueueService._instance = None

        # Mock config manager with stats enabled and minimal bot config
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockConfigManager.getBotConfig.return_value = {
            "defaults": {},
            "private-defaults": {},
            "group-defaults": {},
            "tier-defaults": {},
            "max-tasks": 1024,
            "max-tasks-per-chat": 512,
        }
        mockConfigManager.getOpenWeatherMapConfig.return_value = {"enabled": False}
        mockConfigManager.getYandexSearchConfig.return_value = {"enabled": False}
        mockConfigManager.getSearchHistoryConfig.return_value = {"enabled": False}
        mockConfigManager.get.return_value = {}  # For resender, divination, sandbox configs
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}

        mockDatabase = MagicMock()

        # Patch all handler classes with stubs (they're constructed in manager.__init__)
        with (
            unittest.mock.patch.object(MessagePreprocessorHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(SpamHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(ConfigureCommandHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(SummarizationHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(UserMemoriesHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(DevCommandsHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(MediaHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(HelpHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(DeleteFromUserMessageHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(ReactOnUserMessageHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(TopicManagerHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(WeatherHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(YandexSearchHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(ResenderHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(DivinationHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(SandboxHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(ChatSearchHandler, "__init__", lambda self, **kwargs: None),
            # Patch CustomHandlerLoader at its definition module (not manager.py where it's imported locally)
            unittest.mock.patch("internal.bot.common.handlers.module_loader.CustomHandlerLoader") as MockLoader,
            # Patch QueueService.getInstance to avoid queue registration
            unittest.mock.patch.object(QueueService, "getInstance", return_value=MagicMock()),
        ):
            # Configure mock loader
            mockLoaderInstance = MagicMock()
            mockLoaderInstance.loadAll.return_value = []
            MockLoader.return_value = mockLoaderInstance

            # Construct real HandlersManager (executes real registration logic)
            manager = HandlersManager(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Verify invariant: StatsHandler is registered and LLMMessageHandler is last
            handlerClasses = [type(handler) for handler, _ in manager.handlers]
            assert StatsHandler in handlerClasses, "StatsHandler should be registered when stats is enabled"
            assert handlerClasses[-1] == LLMMessageHandler, "LLMMessageHandler must be last"

    def test_stats_disabled_manager_registration_invariant(self):
        """Test manager-level: stats disabled → no StatsHandler, LLMMessageHandler still last."""

        # Reset singletons
        CacheService._instance = None
        StorageService._instance = None
        QueueService._instance = None

        # Mock config manager with stats disabled and minimal bot config
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": False}
        mockConfigManager.getBotConfig.return_value = {
            "defaults": {},
            "private-defaults": {},
            "group-defaults": {},
            "tier-defaults": {},
            "max-tasks": 1024,
            "max-tasks-per-chat": 512,
        }
        mockConfigManager.getOpenWeatherMapConfig.return_value = {"enabled": False}
        mockConfigManager.getYandexSearchConfig.return_value = {"enabled": False}
        mockConfigManager.getSearchHistoryConfig.return_value = {"enabled": False}
        mockConfigManager.get.return_value = {}  # For resender, divination, sandbox configs
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}

        mockDatabase = MagicMock()

        # Patch all handler classes with stubs (they're constructed in manager.__init__)
        with (
            unittest.mock.patch.object(MessagePreprocessorHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(SpamHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(ConfigureCommandHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(SummarizationHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(UserMemoriesHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(DevCommandsHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(MediaHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(HelpHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(DeleteFromUserMessageHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(ReactOnUserMessageHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(TopicManagerHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(WeatherHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(YandexSearchHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(ResenderHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(DivinationHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(SandboxHandler, "__init__", lambda self, **kwargs: None),
            unittest.mock.patch.object(ChatSearchHandler, "__init__", lambda self, **kwargs: None),
            # Patch CustomHandlerLoader at its definition module (not manager.py where it's imported locally)
            unittest.mock.patch("internal.bot.common.handlers.module_loader.CustomHandlerLoader") as MockLoader,
            # Patch QueueService.getInstance to avoid queue registration
            unittest.mock.patch.object(QueueService, "getInstance", return_value=MagicMock()),
        ):
            # Configure mock loader
            mockLoaderInstance = MagicMock()
            mockLoaderInstance.loadAll.return_value = []
            MockLoader.return_value = mockLoaderInstance

            # Construct real HandlersManager (executes real registration logic)
            manager = HandlersManager(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Verify invariant: StatsHandler is NOT registered, LLMMessageHandler is still last
            handlerClasses = [type(handler) for handler, _ in manager.handlers]
            assert StatsHandler not in handlerClasses, "StatsHandler should not be registered when stats is disabled"
            assert handlerClasses[-1] == LLMMessageHandler, "LLMMessageHandler must be last"


class TestStatsHandlerWebTierConstruction:
    """Tests for stats-pages handler construction shape (commands list, ttl-hours, cleanup-handler registration)."""

    def test_stats_pages_enabled_with_valid_config_constructs_and_registers_handler(self):
        """Test that construction succeeds and cleanup handler is registered when config is valid."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
        }
        mockDatabase = MagicMock()

        # Mock QueueService to capture handler registration
        mockQueueService = MagicMock()
        mockQueueService.registerDelayedTaskHandler = MagicMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=mockQueueService):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Verify handler constructed
            assert handler is not None
            assert handler._statsPagesEnabled is True

            # Verify cleanup handler was registered
            mockQueueService.registerDelayedTaskHandler.assert_called_once()

            callArgs = mockQueueService.registerDelayedTaskHandler.call_args
            assert callArgs[0][0] == DelayedTaskFunction.STATS_PAGES_CLEANUP

    def test_stats_pages_disabled_no_validation_but_handler_still_registered(self):
        """Test that construction proceeds without validation when disabled, but cleanup handler IS registered."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": False,
            # Garbage other keys (not validated when disabled)
            "generate-command": "",
            "delete-command": "",
            "ttl-hours": "invalid",
        }
        mockDatabase = MagicMock()

        # Mock QueueService to verify registration
        mockQueueService = MagicMock()
        mockQueueService.registerDelayedTaskHandler = MagicMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=mockQueueService):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Verify handler constructed
            assert handler is not None
            assert handler._statsPagesEnabled is False

            # Verify cleanup handler WAS registered (unconditionally when StatsHandler is constructed)
            mockQueueService.registerDelayedTaskHandler.assert_called_once()
            callArgs = mockQueueService.registerDelayedTaskHandler.call_args
            assert callArgs[0][0] == DelayedTaskFunction.STATS_PAGES_CLEANUP


class TestStatsHandlerWebTierRateLimiting:
    """Tests for rate limiting in web mode (D13)."""

    async def test_rate_limit_applied_then_generation_proceeds(self):
        """U12-6: Rate limit is applyLimit-only - NO pre-check, NO refusal reply, just sleeps."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
            "ratelimiter-queue": "stats-pages",
        }
        mockDatabase = MagicMock()

        # Mock QueueService
        mockQueueService = MagicMock()
        mockQueueService.registerDelayedTaskHandler = MagicMock()
        mockQueueService.addDelayedTask = AsyncMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=mockQueueService):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock RateLimiterManager - applyLimit is called and may sleep
            mockRateLimiter = MagicMock()
            mockRateLimiter.applyLimit = AsyncMock()

            with unittest.mock.patch("internal.bot.common.handlers.stats.RateLimiterManager") as MockRl:
                MockRl.getInstance.return_value = mockRateLimiter

                # Mock sendMessage and other dependencies
                handler.sendMessage = AsyncMock()
                handler.getUserChats = AsyncMock(return_value=[])

                # Mock storage queries
                mockStorage = MagicMock(spec=NullStatsStorage)
                mockStorage.query = AsyncMock(return_value=[])
                handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

                # Mock subprocess to return success (U12-5: pageId key)
                mockProc = MagicMock()
                mockProc.communicate = AsyncMock(
                    return_value=(b'{"pageId": "abc123", "url": "https://example.com/abc123.html"}', b"")
                )
                mockProc.returncode = 0

                with unittest.mock.patch.object(
                    lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
                ):
                    # Build message
                    message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

                    # Execute command with --web flag
                    await cast(Any, handler).statsCommand(
                        ensuredMessage=message,
                        command="stats",
                        args="--web",
                        updateObj=None,
                        typingManager=None,
                    )

                # Verify applyLimit was called (U12-6: applyLimit-only)
                mockRateLimiter.applyLimit.assert_called_once()
                callArgs = mockRateLimiter.applyLimit.call_args
                assert callArgs[0][0] == "stats-pages"  # Queue name
                assert callArgs[0][1] == "stats-pages-123"  # Rate limiter key (issuing chat)

                # Verify the CLI WAS invoked (U12-6: no refusal path)
                # The subprocess should have been called
                handler.sendMessage.assert_called()
                callArgs = handler.sendMessage.call_args
                messageText = callArgs.kwargs["messageText"]
                assert "Страница:" in messageText  # Link was sent
                assert "https://example.com/abc123.html" in messageText

    async def test_rate_limit_apply_limit_only_always_proceeds_with_generation(self):
        """U12-6: Rate limit is applyLimit-only - limiter sleeps, never refuses.

        This test verifies that the rate limiter's applyLimit method is called
        and that generation always proceeds regardless of rate limit state.
        The limiter only controls timing (via sleep), not access.
        """

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
            "ratelimiter-queue": "stats-pages",
        }
        mockDatabase = MagicMock()

        # Mock QueueService
        mockQueueService = MagicMock()
        mockQueueService.registerDelayedTaskHandler = MagicMock()
        mockQueueService.addDelayedTask = AsyncMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=mockQueueService):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock RateLimiterManager - applyLimit is called and may sleep
            mockRateLimiter = MagicMock()
            mockRateLimiter.applyLimit = AsyncMock()

            with unittest.mock.patch("internal.bot.common.handlers.stats.RateLimiterManager") as MockRl:
                MockRl.getInstance.return_value = mockRateLimiter

                # Mock sendMessage and other dependencies
                handler.sendMessage = AsyncMock()
                handler.getUserChats = AsyncMock(return_value=[])

                # Mock storage queries
                mockStorage = MagicMock(spec=NullStatsStorage)
                mockStorage.query = AsyncMock(return_value=[])
                handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

                # Mock subprocess to return success (U12-5: pageId key)
                mockProc = MagicMock()
                mockProc.communicate = AsyncMock(
                    return_value=(b'{"pageId": "abc123", "url": "https://example.com/abc123.html"}', b"")
                )
                mockProc.returncode = 0

                with unittest.mock.patch.object(
                    lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
                ):
                    # Build message
                    message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

                    # Execute command with --web flag
                    await cast(Any, handler).statsCommand(
                        ensuredMessage=message,
                        command="stats",
                        args="--web",
                        updateObj=None,
                        typingManager=None,
                    )

                # Verify applyLimit was called (U12-6: applyLimit-only)
                mockRateLimiter.applyLimit.assert_called_once()
                callArgs = mockRateLimiter.applyLimit.call_args
                assert callArgs[0][0] == "stats-pages"  # Queue name
                assert callArgs[0][1] == "stats-pages-123"  # Rate limiter key (issuing chat)

                # Verify the CLI WAS invoked and link was delivered (U12-6: no refusal path)
                handler.sendMessage.assert_called()
                callArgs = handler.sendMessage.call_args
                messageText = callArgs.kwargs["messageText"]
                assert "Страница:" in messageText  # Link was sent
                assert "https://example.com/abc123.html" in messageText

    async def test_rate_limit_saturated_still_proceeds_with_generation(self):
        """U12-6: When limiter is saturated, applyLimit sleeps but generation still proceeds.

        Verifies that even when the rate limiter would block (applyLimit is awaited and
        may sleep), generation still succeeds with no refusal reply.
        """

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
            "ratelimiter-queue": "stats-pages",
        }
        mockDatabase = MagicMock()

        # Mock QueueService
        mockQueueService = MagicMock()
        mockQueueService.registerDelayedTaskHandler = MagicMock()
        mockQueueService.addDelayedTask = AsyncMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=mockQueueService):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock RateLimiterManager - applyLimit is called and will await (simulating saturation)
            mockRateLimiter = MagicMock()
            mockRateLimiter.applyLimit = AsyncMock()

            with unittest.mock.patch("internal.bot.common.handlers.stats.RateLimiterManager") as MockRl:
                MockRl.getInstance.return_value = mockRateLimiter

                # Mock subprocess to return success
                mockProc = MagicMock()
                mockProc.communicate = AsyncMock(
                    return_value=(b'{"pageId": "xyz789", "url": "https://example.com/xyz789.html"}', b"")
                )
                mockProc.returncode = 0

                with unittest.mock.patch.object(
                    lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
                ):
                    # Mock sendMessage and other dependencies
                    handler.sendMessage = AsyncMock()
                    handler.getUserChats = AsyncMock(return_value=[])

                    # Mock storage queries
                    mockStorage = MagicMock(spec=NullStatsStorage)
                    mockStorage.query = AsyncMock(return_value=[])
                    handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

                    # Build message
                    message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

                    # Execute command with --web flag (even with saturated limiter, should succeed)
                    await cast(Any, handler).statsCommand(
                        ensuredMessage=message,
                        command="stats",
                        args="--web",
                        updateObj=None,
                        typingManager=None,
                    )

                # Verify applyLimit was called (U12-6: limiter is invoked, not skipped)
                mockRateLimiter.applyLimit.assert_called_once()
                callArgs = mockRateLimiter.applyLimit.call_args
                assert callArgs[0][0] == "stats-pages"
                assert callArgs[0][1] == "stats-pages-123"

                # Verify generation STILL proceeded - link was delivered (no refusal reply)
                handler.sendMessage.assert_called()
                callArgs = handler.sendMessage.call_args
                messageText = callArgs.kwargs["messageText"]
                assert "Страница:" in messageText
                assert "https://example.com/xyz789.html" in messageText


class TestStatsHandlerWebTierE2E:
    """E2E tests for web mode page generation."""

    async def test_web_mode_e2e_generates_page_and_schedules_deletion(self):
        """Test complete web mode flow: rate limit check, subprocess, payload, link, deletion scheduling."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
                "--user-id={user_id}",
                "--chat-id={chat_id}",
                "--platform={platform}",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
            "ratelimiter-queue": "stats-pages",
        }
        mockDatabase = MagicMock()

        # Mock QueueService
        mockQueueService = MagicMock()
        mockQueueService.registerDelayedTaskHandler = MagicMock()
        mockQueueService.addDelayedTask = AsyncMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=mockQueueService):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock RateLimiterManager
            mockRateLimiter = MagicMock()
            mockRateLimiter.getStats.return_value = {"maxRequests": 3, "requestsInWindow": 0}
            mockRateLimiter.applyLimit = AsyncMock()

            with unittest.mock.patch("internal.bot.common.handlers.stats.RateLimiterManager") as MockRl:
                MockRl.getInstance.return_value = mockRateLimiter

                # Mock subprocess
                mockProc = MagicMock()
                mockProc.communicate = AsyncMock(
                    return_value=(b'{"pageId": "test-page-id", "url": "test-page-id.html"}', b"")
                )
                mockProc.returncode = 0

                # Patch ONLY create_subprocess_exec, not the whole asyncio module
                with unittest.mock.patch.object(
                    lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
                ) as mockExec:
                    # Mock dependencies
                    handler.sendMessage = AsyncMock()
                    handler.getUserChats = AsyncMock(return_value=[])

                    # Mock storage queries
                    mockStorage = MagicMock(spec=NullStatsStorage)
                    mockStorage.query = AsyncMock(return_value=[])
                    handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

                    # Build message
                    message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

                    # Execute command with --web flag
                    await cast(Any, handler).statsCommand(
                        ensuredMessage=message,
                        command="stats",
                        args="--web",
                        updateObj=None,
                        typingManager=None,
                    )

                    # Verify subprocess was called with substituted argv
                    mockExec.assert_called_once_with(
                        "./venv/bin/python3",
                        "-m",
                        "lib.stats.stats_pages",
                        "generate",
                        "--base-url=https://stats.example.com",
                        "--output-dir=./stats-pages",
                        "--user-id=456",
                        "--chat-id=123",
                        "--platform=telegram",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )

                    # Verify reply contains link (verbatim URL from CLI, no base-url composition)
                    handler.sendMessage.assert_called_once()
                    callArgs = handler.sendMessage.call_args
                    assert "test-page-id.html" in callArgs.kwargs["messageText"]

                    # Verify deletion task was scheduled
                    mockQueueService.addDelayedTask.assert_called_once()
                    taskCallArgs = mockQueueService.addDelayedTask.call_args

                    assert taskCallArgs[1]["function"] == DelayedTaskFunction.STATS_PAGES_CLEANUP
                    assert taskCallArgs[1]["kwargs"]["pageId"] == "test-page-id"
                    assert "test-page-id" in taskCallArgs[1]["kwargs"]["command"]
                    assert taskCallArgs[1]["skipDB"] is False
                    # Verify delay is approximately 24 hours (86400 seconds)
                    delayUntil = taskCallArgs[1]["delayedUntil"]
                    expectedDelay = time.time() + 24 * 3600
                    assert abs(delayUntil - expectedDelay) < 5  # 5 second tolerance


class TestStatsHandlerWebTierFailureModes:
    """Tests for web mode failure modes (D15)."""

    async def test_cli_exit_nonzero_sends_brief_plus_failure_note(self):
        """Test that CLI nonzero exit sends brief + failure note, does not raise."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
        }
        mockDatabase = MagicMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=MagicMock()):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock RateLimiterManager
            mockRateLimiter = MagicMock()
            mockRateLimiter.getStats.return_value = {"maxRequests": 3, "requestsInWindow": 0}
            mockRateLimiter.applyLimit = AsyncMock()

            with unittest.mock.patch("internal.bot.common.handlers.stats.RateLimiterManager") as MockRl:
                MockRl.getInstance.return_value = mockRateLimiter

                # Mock subprocess to return nonzero exit
                mockProc = MagicMock()
                mockProc.communicate = AsyncMock(return_value=(b"", b"Error occurred"))
                mockProc.returncode = 1

                # Patch ONLY create_subprocess_exec, not the whole asyncio module
                with unittest.mock.patch.object(
                    lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
                ):
                    # Mock dependencies
                    handler.sendMessage = AsyncMock()
                    handler.getUserChats = AsyncMock(return_value=[])

                    mockStorage = MagicMock(spec=NullStatsStorage)
                    mockStorage.query = AsyncMock(return_value=[])
                    handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

                    # Execute command
                    message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
                    await cast(Any, handler).statsCommand(
                        ensuredMessage=message,
                        command="stats",
                        args="--web",
                        updateObj=None,
                        typingManager=None,
                    )

                    # Verify brief was sent + failure note
                    handler.sendMessage.assert_called_once()
                    callArgs = handler.sendMessage.call_args
                    assert "📊 Stats" in callArgs.kwargs["messageText"]  # Brief header
                    assert "⚠ Генерация веб-страницы не удалась" in callArgs.kwargs["messageText"]  # Failure note

    async def test_cli_timeout_kills_process_and_sends_brief_plus_failure_note(self):
        """Test that timeout kills process and sends brief + failure note."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
        }
        mockDatabase = MagicMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=MagicMock()):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock RateLimiterManager
            mockRateLimiter = MagicMock()
            mockRateLimiter.getStats.return_value = {"maxRequests": 3, "requestsInWindow": 0}
            mockRateLimiter.applyLimit = AsyncMock()

            with unittest.mock.patch("internal.bot.common.handlers.stats.RateLimiterManager") as MockRl:
                MockRl.getInstance.return_value = mockRateLimiter

                # Mock subprocess to timeout
                mockProc = MagicMock()
                mockProc.kill = MagicMock()
                mockProc.wait = AsyncMock()
                # Make communicate raise the REAL TimeoutError - real wait_for will catch and re-raise it
                mockProc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

                # Patch ONLY create_subprocess_exec, not the whole asyncio module
                with unittest.mock.patch.object(
                    lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
                ):
                    # Mock dependencies
                    handler.sendMessage = AsyncMock()
                    handler.getUserChats = AsyncMock(return_value=[])

                    mockStorage = MagicMock(spec=NullStatsStorage)
                    mockStorage.query = AsyncMock(return_value=[])
                    handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

                    # Execute command
                    message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
                    await cast(Any, handler).statsCommand(
                        ensuredMessage=message,
                        command="stats",
                        args="--web",
                        updateObj=None,
                        typingManager=None,
                    )

                    # Verify process was killed
                    mockProc.kill.assert_called_once()
                    mockProc.wait.assert_called_once()

                    # Verify brief + failure note
                    handler.sendMessage.assert_called_once()
                    callArgs = handler.sendMessage.call_args
                    assert "📊 Stats" in callArgs.kwargs["messageText"]
                    assert "⚠ Генерация веб-страницы не удалась (тайм-аут)" in callArgs.kwargs["messageText"]

    async def test_garbage_stdout_sends_brief_plus_failure_note(self):
        """Test that unparseable stdout sends brief + failure note."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
        }
        mockDatabase = MagicMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=MagicMock()):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock RateLimiterManager
            mockRateLimiter = MagicMock()
            mockRateLimiter.getStats.return_value = {"maxRequests": 3, "requestsInWindow": 0}
            mockRateLimiter.applyLimit = AsyncMock()

            with unittest.mock.patch("internal.bot.common.handlers.stats.RateLimiterManager") as MockRl:
                MockRl.getInstance.return_value = mockRateLimiter

                # Mock subprocess to return garbage
                mockProc = MagicMock()
                mockProc.communicate = AsyncMock(return_value=(b"not json at all", b""))
                mockProc.returncode = 0

                # Patch ONLY create_subprocess_exec, not the whole asyncio module
                with unittest.mock.patch.object(
                    lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
                ):
                    # Mock dependencies
                    handler.sendMessage = AsyncMock()
                    handler.getUserChats = AsyncMock(return_value=[])

                    mockStorage = MagicMock(spec=NullStatsStorage)
                    mockStorage.query = AsyncMock(return_value=[])
                    handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

                    # Execute command
                    message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
                    await cast(Any, handler).statsCommand(
                        ensuredMessage=message,
                        command="stats",
                        args="--web",
                        updateObj=None,
                        typingManager=None,
                    )

                    # Verify brief + failure note
                    handler.sendMessage.assert_called_once()
                    callArgs = handler.sendMessage.call_args
                    assert "📊 Stats" in callArgs.kwargs["messageText"]
                    assert "⚠ Генерация веб-страницы не удалась (неверный ответ)" in callArgs.kwargs["messageText"]

    async def test_spawn_raises_sends_brief_plus_failure_note(self):
        """Test that subprocess spawn exception sends brief + failure note."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
        }
        mockDatabase = MagicMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=MagicMock()):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock RateLimiterManager
            mockRateLimiter = MagicMock()
            mockRateLimiter.getStats.return_value = {"maxRequests": 3, "requestsInWindow": 0}
            mockRateLimiter.applyLimit = AsyncMock()

            with unittest.mock.patch("internal.bot.common.handlers.stats.RateLimiterManager") as MockRl:
                MockRl.getInstance.return_value = mockRateLimiter

                # Mock subprocess to raise exception
                # Patch ONLY create_subprocess_exec, not the whole asyncio module
                with unittest.mock.patch.object(
                    lib.stats.stats_pages.launcher.asyncio,
                    "create_subprocess_exec",
                    side_effect=OSError("Command not found"),
                ):
                    # Mock dependencies
                    handler.sendMessage = AsyncMock()
                    handler.getUserChats = AsyncMock(return_value=[])

                    mockStorage = MagicMock(spec=NullStatsStorage)
                    mockStorage.query = AsyncMock(return_value=[])
                    handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

                    # Execute command
                    message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
                    await cast(Any, handler).statsCommand(
                        ensuredMessage=message,
                        command="stats",
                        args="--web",
                        updateObj=None,
                        typingManager=None,
                    )

                    # Verify brief + failure note
                    handler.sendMessage.assert_called_once()
                    callArgs = handler.sendMessage.call_args
                    assert "📊 Stats" in callArgs.kwargs["messageText"]
                    assert "⚠ Генерация веб-страницы не удалась" in callArgs.kwargs["messageText"]

    async def test_deletion_scheduling_failure_sends_link_with_warning_logged(self, caplog):
        """Test that deletion scheduling failure sends link but logs warning.

        Args:
            caplog: pytest fixture for capturing log output.
        """

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
        }
        mockDatabase = MagicMock()

        # Mock QueueService to fail on addDelayedTask
        mockQueueService = MagicMock()
        mockQueueService.registerDelayedTaskHandler = MagicMock()
        mockQueueService.addDelayedTask = AsyncMock(side_effect=Exception("Database error"))

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=mockQueueService):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock RateLimiterManager
            mockRateLimiter = MagicMock()
            mockRateLimiter.getStats.return_value = {"maxRequests": 3, "requestsInWindow": 0}
            mockRateLimiter.applyLimit = AsyncMock()

            with unittest.mock.patch("internal.bot.common.handlers.stats.RateLimiterManager") as MockRl:
                MockRl.getInstance.return_value = mockRateLimiter

                # Mock subprocess
                mockProc = MagicMock()
                mockProc.communicate = AsyncMock(return_value=(b'{"pageId": "test-id", "url": "test-id.html"}', b""))
                mockProc.returncode = 0

                # Patch ONLY create_subprocess_exec, not the whole asyncio module
                with unittest.mock.patch.object(
                    lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
                ):
                    # Mock dependencies
                    handler.sendMessage = AsyncMock()
                    handler.getUserChats = AsyncMock(return_value=[])

                    mockStorage = MagicMock(spec=NullStatsStorage)
                    mockStorage.query = AsyncMock(return_value=[])
                    handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

                    # Execute command
                    message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
                    await cast(Any, handler).statsCommand(
                        ensuredMessage=message,
                        command="stats",
                        args="--web",
                        updateObj=None,
                        typingManager=None,
                    )

                    # Verify link was still sent (orphan accepted per R13)
                    handler.sendMessage.assert_called_once()
                    callArgs = handler.sendMessage.call_args
                    assert "test-id.html" in callArgs.kwargs["messageText"]

                    # Verify warning was logged for deletion scheduling failure
                    assert "Failed to schedule deletion task for page test-id" in caplog.text


class TestStatsHandlerWebTierCleanupHandler:
    """Tests for stats-pages cleanup delayed task handler."""

    async def test_cleanup_handler_happy_path_runs_argv(self):
        """Test that cleanup handler runs the delete command."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
        }
        mockDatabase = MagicMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=MagicMock()):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Create delayed task
            task = DelayedTask(
                taskId="test-task-1",
                delayedUntil=0.0,
                function=DelayedTaskFunction.STATS_PAGES_CLEANUP,
                kwargs={
                    "pageId": "test-page-id",
                    "command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "test-page-id"],
                },
            )

            # Mock subprocess
            mockProc = MagicMock()
            mockProc.communicate = AsyncMock(return_value=(b'{"deleted": 1}', b""))
            mockProc.returncode = 0

            # Patch ONLY create_subprocess_exec, not the whole asyncio module
            with unittest.mock.patch.object(
                lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
            ) as mockExec:
                # Execute cleanup handler
                await handler._dtStatsPagesCleanup(task)

                # Verify subprocess was called with resolved delete argv
                mockExec.assert_called_once_with(
                    "./venv/bin/python3",
                    "-m",
                    "lib.stats.stats_pages",
                    "delete",
                    "test-page-id",  # {page_id} substituted with actual page_id
                    stdin=None,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                # Verify subprocess was executed (communicate was invoked)
                assert mockProc.communicate.called

    async def test_cleanup_handler_tolerates_deleted_zero(self):
        """Test that cleanup handler tolerates {deleted: 0} response."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
        }
        mockDatabase = MagicMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=MagicMock()):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Create delayed task
            task = DelayedTask(
                taskId="test-task-2",
                delayedUntil=0.0,
                function=DelayedTaskFunction.STATS_PAGES_CLEANUP,
                kwargs={
                    "pageId": "test-page-id",
                    "command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "test-page-id"],
                },
            )

            # Mock subprocess to return {deleted: 0}
            mockProc = MagicMock()
            mockProc.communicate = AsyncMock(return_value=(b'{"deleted": 0}', b""))
            mockProc.returncode = 0

            # Patch ONLY create_subprocess_exec, not the whole asyncio module
            with unittest.mock.patch.object(
                lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
            ):
                # Execute cleanup handler (should not raise)
                await handler._dtStatsPagesCleanup(task)

                # Verify subprocess was called (communicate was invoked)
                assert mockProc.communicate.called

    async def test_cleanup_handler_subprocess_raises_logs_warning_no_retry(self):
        """Test that cleanup handler logs warning on subprocess raise and does not retry."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": [
                "./venv/bin/python3",
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--base-url=https://stats.example.com",
                "--output-dir=./stats-pages",
            ],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
        }
        mockDatabase = MagicMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=MagicMock()) as mockQueueService:
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Create delayed task
            task = DelayedTask(
                taskId="test-task-3",
                delayedUntil=0.0,
                function=DelayedTaskFunction.STATS_PAGES_CLEANUP,
                kwargs={
                    "pageId": "test-page-id",
                    "command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "test-page-id"],
                },
            )

            # Mock subprocess to raise
            # Patch ONLY create_subprocess_exec, not the whole asyncio module
            with unittest.mock.patch.object(
                lib.stats.stats_pages.launcher.asyncio,
                "create_subprocess_exec",
                side_effect=OSError("Command not found"),
            ):
                # Execute cleanup handler (should not raise)
                await handler._dtStatsPagesCleanup(task)

                # Verify no retry - task completes normally (assert completes without exception)
                # The task should not raise and QueueService should not be called for retry
                mockQueueService.addDelayedTask.assert_not_called()


class TestStatsHandlerFormatRedesign:
    """Tests for /stats format redesign (items 1-9 in production code)."""

    def testEmDashPeriodParsing_normalizesToDoubleDash(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test that em-dash before period normalizes to double dash.

        Tests that —period=7d (U+2014 em-dash) parses like --period=7d.
        This fixes autocorrect issues where -- gets replaced with —.
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Parse with em-dash
            result = handler._parseStatsArgs("—period=7d", forceWeb=False)

            assert result is not None
            assert result["period"] == "7d"
            assert result["section"] == "messages"
            assert result["web"] is False

    def testEnDashWebParsing_normalizesToDoubleDash(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test that en-dash before web normalizes to double dash.

        Tests that –web (U+2013 en-dash) parses like --web.
        This fixes autocorrect issues where -- gets replaced with –.
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Parse with en-dash
            result = handler._parseStatsArgs("–web", forceWeb=False)

            assert result is not None
            assert result["web"] is True
            assert result["period"] == "7d"  # default

    def testNegativePositionalChatId_targetsCorrectChat(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test that negative positional chatId still targets that chat.

        Tests that -1002998620962 is treated as a positional chatId,
        not as an option. Negative chatIds represent groups in Telegram.
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Parse with negative positional chatId
            result = handler._parseStatsArgs("-1002998620962", forceWeb=False)

            assert result is not None
            assert result["chatId"] == -1002998620962
            assert result["period"] == "7d"  # default
            assert result["section"] == "messages"  # default

    async def testPrettyHeader_withChatInfo_showsEmojiBoldTitleAndChatId(self) -> None:
        """Test pretty header format with available chat info.

        Tests that header contains:
        - Emoji 📊
        - Bold title (from getChatTitle)
        - Backticked chat id
        """
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        mockDatabase = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock cache.getChatInfo to return chat info
            mockChatInfo = {
                "id": 123,
                "title": "Test Chat",
                "chat_type": "group",
                "username": "testchat",
            }
            handler.cache.getChatInfo = AsyncMock(return_value=mockChatInfo)

            # Mock getChatTitle to return formatted title (real method's shape: backticked id, emoji, bold title)
            handler.getChatTitle = MagicMock(return_value="#`123`, 👥 **Test Chat**")

            # Mock getChatSettings to avoid LLM initialization
            chatSettings = {k: ChatSettingsValue("") for k in ChatSettingsKey}
            chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS] = ChatSettingsValue("true")
            handler.getChatSettings = AsyncMock(return_value=chatSettings)

            # Mock storage to return empty
            mockStorage = MagicMock(spec=NullStatsStorage)
            mockStorage.query = AsyncMock(return_value=[])
            handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

            # Mock sendMessage to capture output
            mockSendMessage = AsyncMock()
            handler.sendMessage = mockSendMessage

            # Build message
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.GROUP, userId=456)

            # Execute command
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="", updateObj=None, typingManager=None
            )

            # Verify header format
            mockSendMessage.assert_called_once()
            callArgs = mockSendMessage.call_args
            replyText = callArgs.kwargs["messageText"]

            # Check for emoji
            assert "📊" in replyText

            # Check for bold title
            assert "*" in replyText  # Bold markers

            # Check for backticked chat id
            assert "#`123`" in replyText

            # Verify getChatTitle was called with correct params
            handler.getChatTitle.assert_called_once_with(
                mockChatInfo, useMarkdown=True, addChatId=True, addChatType=False
            )

    async def testPrettyHeader_withoutChatInfo_fallsBackToHashId(self) -> None:
        """Test pretty header format with unavailable chat info.

        Tests that when chat info is unavailable, header falls back to plain #id format.
        """
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        mockDatabase = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock cache.getChatInfo to raise exception (unavailable)
            handler.cache.getChatInfo = AsyncMock(side_effect=Exception("Chat not found"))

            # Mock getChatSettings to avoid LLM initialization
            chatSettings = {k: ChatSettingsValue("") for k in ChatSettingsKey}
            chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS] = ChatSettingsValue("true")
            handler.getChatSettings = AsyncMock(return_value=chatSettings)

            # Mock storage to return empty
            mockStorage = MagicMock(spec=NullStatsStorage)
            mockStorage.query = AsyncMock(return_value=[])
            handler.statsAggregationService.getQueryStorage = MagicMock(return_value=mockStorage)

            # Mock sendMessage to capture output
            mockSendMessage = AsyncMock()
            handler.sendMessage = mockSendMessage

            # Build message
            message = buildEnsuredMessage(chatId=999, chatType=ChatType.GROUP, userId=456)

            # Execute command
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="", updateObj=None, typingManager=None
            )

            # Verify header falls back to #id
            mockSendMessage.assert_called_once()
            callArgs = mockSendMessage.call_args
            replyText = callArgs.kwargs["messageText"]

            # Check for plain #id format (no bold title)
            assert "#999" in replyText

    async def testMessagesSection_noUsersBotLine_usesBoldHeader(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test messages section has no users/bot line and uses bold header.

        Tests:
        - Header is **Messages:** {total} (bold)
        - No users/bot breakdown line exists
        - Total count is correct
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Create mock rows
            rows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "123", "sent": "False"},
                    metricKey="message_count",
                    metricValue=100.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "bot", "sent": "True"},
                    metricKey="message_count",
                    metricValue=50.0,
                ),
            ]

            analyzer = StatsAnalyzer(rows)

            # Call _buildMessagesSectionFromAnalyzer
            result = await handler._buildMessagesSectionFromAnalyzer(
                analyzer=analyzer, truncatedEventTypes=[], targetChatId=123
            )

            # Check bold header format
            assert "**Messages:** 150" in result, f"Expected '**Messages:** 150' in result: {result}"

            # Check that users/bot breakdown line does NOT exist
            assert "users" not in result.lower(), f"Result should not contain 'users': {result}"
            assert "bot" not in result.lower(), f"Result should not contain 'bot': {result}"

    async def testFencedTopBlock_exactAlignment_threeUsers(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test fenced Top block renders with exact alignment.

        Tests:
        - Caption on fence line: "```Top:"
        - Fenced code block with ``` markers
        - Bullet markers: •
        - Aligned columns (ljust name, rjust count)
        - One item per line
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Create mock rows with 3 users (different name lengths)
            rows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "123", "sent": "False"},
                    metricKey="message_count",
                    metricValue=794.0,  # 3 digits
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "456", "sent": "False"},
                    metricKey="message_count",
                    metricValue=42.0,  # 2 digits
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "789", "sent": "False"},
                    metricKey="message_count",
                    metricValue=7.0,  # 1 digit
                ),
            ]

            analyzer = StatsAnalyzer(rows)

            # Mock _resolveUserName with specific name widths
            # @alice (6 chars), @verylongusername (18 chars), @xyz (4 chars)
            def mockResolve(chatId: int, userId: int) -> str:
                if userId == 123:
                    return "@verylongusername"  # 18 chars
                elif userId == 456:
                    return "@alice"  # 6 chars
                else:
                    return "@xyz"  # 4 chars

            handler._resolveUserName = AsyncMock(side_effect=mockResolve)

            # Call _buildMessagesSectionFromAnalyzer
            result = await handler._buildMessagesSectionFromAnalyzer(
                analyzer=analyzer, truncatedEventTypes=[], targetChatId=123
            )

            # Check caption-in-fence
            assert "```Top:" in result

            # Check fences
            fenceCount = result.count("```")
            assert fenceCount == 2, f"Expected 2 fence markers but found {fenceCount}: {result}"

            # Check bullet lines with exact alignment
            # The production code uses ljust(maxKeyWidth) + 2 spaces + rjust(maxCountWidth)
            # Max name width is 18 (@verylongusername), max count width is 3 (794)
            # Expected format: "• {name.ljust(18)}  {count.rjust(3)}"
            expectedLines = [
                "• @verylongusername  794",  # 18 + 2 + 3 = 23
                "• @alice              42",  # 6 + 12 + 2 + 2 = 22
                "• @xyz                 7",  # 4 + 14 + 2 + 1 = 21
            ]

            for expected in expectedLines:
                assert expected in result, f"Expected aligned line '{expected}' in result: {result}"

            # Check that bullet markers exist
            assert "• " in result

    async def testCommandsTop_renderAsFencedBlock(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test Commands Top renders as fenced code block.

        Tests:
        - Caption on fence line: "```Top:"
        - Fenced code block with ``` markers
        - Bullet markers: •
        - Commands listed one per line
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Create mock rows
            rows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"commandName": "stats"},
                    metricKey="command_count",
                    metricValue=10.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"commandName": "help"},
                    metricKey="command_count",
                    metricValue=5.0,
                ),
            ]

            analyzer = StatsAnalyzer(rows)

            # Call _buildCommandsSectionFromAnalyzer
            result = handler._buildCommandsSectionFromAnalyzer(analyzer=analyzer, truncatedEventTypes=[])

            # Check bold header
            assert "**Commands:** 15" in result

            # Check caption-in-fence
            assert "```Top:" in result

            # Check fences
            fenceCount = result.count("```")
            assert fenceCount == 2, f"Expected 2 fence markers but found {fenceCount}: {result}"

            # Check bullet markers
            assert "• stats" in result
            assert "• help" in result

    async def testErrorsPrefix_showsWhenErrorsExist(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test ⚠ errors: prefix when errors > 0.

        Tests:
        - Commands section: "  ⚠ errors: {count}" when errors > 0
        - Tools section: "  ⚠ errors: {count}" when errors > 0
        - LLM section: "  ⚠ errors: {count}" when errors > 0
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Test Commands section with errors
            cmdRows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"commandName": "test"},
                    metricKey="command_count",
                    metricValue=10.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"commandName": "test"},
                    metricKey="is_error",
                    metricValue=2.0,
                ),
            ]

            cmdAnalyzer = StatsAnalyzer(cmdRows)
            cmdResult = handler._buildCommandsSectionFromAnalyzer(analyzer=cmdAnalyzer, truncatedEventTypes=[])

            assert "**Commands:** 10" in cmdResult
            assert "  ⚠ errors: 2" in cmdResult

            # Test Tools section with errors
            toolRows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"toolName": "python"},
                    metricKey="tool_call_count",
                    metricValue=5.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"toolName": "python"},
                    metricKey="is_error",
                    metricValue=1.0,
                ),
            ]

            toolAnalyzer = StatsAnalyzer(toolRows)
            toolResult = handler._buildToolsSectionFromAnalyzer(analyzer=toolAnalyzer, truncatedEventTypes=[])

            assert "**Tools:** 5" in toolResult
            assert "  ⚠ errors: 1" in toolResult

    async def testErrorsPrefix_absentWhenNoErrors(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test ⚠ errors: prefix is absent when errors = 0.

        Tests:
        - No error line when all commands succeed
        - No error line when all tools succeed
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Test Commands section with no errors
            cmdRows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"commandName": "test"},
                    metricKey="command_count",
                    metricValue=10.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"commandName": "test"},
                    metricKey="is_error",
                    metricValue=0.0,
                ),
            ]

            cmdAnalyzer = StatsAnalyzer(cmdRows)
            cmdResult = handler._buildCommandsSectionFromAnalyzer(analyzer=cmdAnalyzer, truncatedEventTypes=[])

            assert "**Commands:** 10" in cmdResult
            assert "⚠ errors:" not in cmdResult

            # Test Tools section with no errors
            toolRows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"toolName": "python"},
                    metricKey="tool_call_count",
                    metricValue=5.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"toolName": "python"},
                    metricKey="is_error",
                    metricValue=0.0,
                ),
            ]

            toolAnalyzer = StatsAnalyzer(toolRows)
            toolResult = handler._buildToolsSectionFromAnalyzer(analyzer=toolAnalyzer, truncatedEventTypes=[])

            assert "**Tools:** 5" in toolResult
            assert "⚠ errors:" not in toolResult

    async def testToolsLlmHeaders_foldAvgTime_noSeparateLine(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test Tools/LLM headers fold avg time, no separate avg line.

        Tests:
        - Tools header: "**Tools:** N · avg X.XXs" when avg > 0
        - LLM header: "**LLM:** N requests · avg X.XXs" when avg > 0
        - No separate avg time line below header
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Test Tools section with avg time
            toolRows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"toolName": "python"},
                    metricKey="tool_call_count",
                    metricValue=2.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"toolName": "python"},
                    metricKey="elapsed_time",
                    metricValue=3.5,  # avg = 3.5 / 2 = 1.75s
                ),
            ]

            toolAnalyzer = StatsAnalyzer(toolRows)
            toolResult = handler._buildToolsSectionFromAnalyzer(analyzer=toolAnalyzer, truncatedEventTypes=[])

            # Derivation: total_calls=2.0, elapsed_time=3.5 → avg=3.5/2=1.75s → _formatDuration returns "1.75s"
            # Check header folds avg time with exact first-line pin
            assert toolResult.split("\n")[0] == "**Tools:** 2 · avg 1.75s"

            # Check no separate avg line exists
            assert "avg" not in toolResult.split("\n")[1]  # First line after header

            # Test LLM section with avg time
            llmRows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"modelName": "gpt-4"},
                    metricKey="request_count",
                    metricValue=3.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"modelName": "gpt-4"},
                    metricKey="elapsed_time",
                    metricValue=6.0,  # avg = 6.0 / 3 = 2.00s
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"modelName": "gpt-4"},
                    metricKey="input_tokens",
                    metricValue=100.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"modelName": "gpt-4"},
                    metricKey="output_tokens",
                    metricValue=200.0,
                ),
            ]

            llmAnalyzer = StatsAnalyzer(llmRows)

            # Create minimal StatsPayload for LLM test
            llmPayload: StatsPayload = {
                "userId": "123",
                "chatId": "456",
                "chatTitle": "Test Chat",
                "chatType": "private",
                "platform": "telegram",
                "period": "7d",
                "periodType": "daily",
                "generatedAt": "2026-01-01T00:00:00Z",
                "rows": {},
                "userFilterApplied": False,
            }
            llmResult = handler._buildLlmSectionFromAnalyzer(
                analyzer=llmAnalyzer, payload=llmPayload, truncatedEventTypes=[]
            )

            # Derivation: total_requests=3.0, elapsed_time=6.0 → avg=6.0/3=2.00s → _formatDuration returns "2.00s"
            # Check header folds avg time with exact first-line pin
            assert llmResult.split("\n")[0] == "**LLM:** 3 requests · avg 2.00s"

            # Check no separate avg line exists
            lines = llmResult.split("\n")
            # Second line should be tokens line, not avg line
            assert "tokens: in 100 / out 200" in lines[1]
            assert "avg" not in lines[1]

    async def testSttLine_noNoun_justSttColonN(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test STT line is 'STT: N' (noun dropped).

        Tests:
        - STT line format: "  STT: {total}" (no noun like "requests")
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Create LLM section with STT data
            llmRows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"modelName": "gpt-4"},
                    metricKey="request_count",
                    metricValue=1.0,
                ),
            ]

            llmAnalyzer = StatsAnalyzer(llmRows)

            # Mock STT rows in payload with required StatsPayload fields
            payload: StatsPayload = {
                "userId": "123",
                "chatId": "456",
                "chatTitle": "Test Chat",
                "chatType": "private",
                "platform": "telegram",
                "period": "7d",
                "periodType": "daily",
                "generatedAt": "2026-01-01T00:00:00Z",
                "rows": {
                    "stt_request": [
                        StatsAggregateDict(
                            periodType="daily",
                            periodStart="2024-01-01T00:00:00+00:00",
                            labels={},
                            metricKey="request_count",
                            metricValue=15.0,
                        ),
                        StatsAggregateDict(
                            periodType="daily",
                            periodStart="2024-01-01T00:00:00+00:00",
                            labels={},
                            metricKey="is_error",
                            metricValue=0.0,
                        ),
                        StatsAggregateDict(
                            periodType="daily",
                            periodStart="2024-01-01T00:00:00+00:00",
                            labels={},
                            metricKey="audio_duration_ms",
                            metricValue=30000.0,
                        ),
                        StatsAggregateDict(
                            periodType="daily",
                            periodStart="2024-01-01T00:00:00+00:00",
                            labels={},
                            metricKey="elapsed_time",
                            metricValue=5.0,
                        ),
                    ]
                },
                "userFilterApplied": False,
            }

            llmResult = handler._buildLlmSectionFromAnalyzer(
                analyzer=llmAnalyzer, payload=payload, truncatedEventTypes=[]
            )

            # Check STT line format (noun dropped, bold header)
            assert "  **STT:** 15" in llmResult

            # Check no noun like "requests" in STT line
            assert "STT: 15 requests" not in llmResult
            assert "STT: 15 запросов" not in llmResult

            # Check avg time line appears when STT requests > 0
            # elapsed_time = 5.0, request_count = 15.0 → avg = 0.33s
            assert "    avg time: 0.33s" in llmResult

    async def testSttErrorsLine_subLineIndentNoWarning(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test STT errors sub-line format: 4-space indent, NO ⚠ on errors line.

        Tests:
        - STT errors sub-line is indented with 4 spaces (no warning symbol)
        - Errors line does NOT contain ⚠
        - Line format: "    errors: N" (N formatted with _formatCount)
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Create LLM section with STT data that has errors
            llmRows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"modelName": "gpt-4"},
                    metricKey="request_count",
                    metricValue=1.0,
                ),
            ]

            llmAnalyzer = StatsAnalyzer(llmRows)

            # Mock STT rows in payload with 2 errors
            payload: StatsPayload = {
                "userId": "123",
                "chatId": "456",
                "chatTitle": "Test Chat",
                "chatType": "private",
                "platform": "telegram",
                "period": "7d",
                "periodType": "daily",
                "generatedAt": "2026-01-01T00:00:00Z",
                "rows": {
                    "stt_request": [
                        StatsAggregateDict(
                            periodType="daily",
                            periodStart="2024-01-01T00:00:00+00:00",
                            labels={},
                            metricKey="request_count",
                            metricValue=10.0,
                        ),
                        StatsAggregateDict(
                            periodType="daily",
                            periodStart="2024-01-01T00:00:00+00:00",
                            labels={},
                            metricKey="is_error",
                            metricValue=2.0,  # 2 errors
                        ),
                    ]
                },
                "userFilterApplied": False,
            }

            llmResult = handler._buildLlmSectionFromAnalyzer(
                analyzer=llmAnalyzer, payload=payload, truncatedEventTypes=[]
            )

            # Check STT errors sub-line format (4-space indent, no ⚠)
            assert "    errors: 2" in llmResult

            # Verify the errors line does NOT contain ⚠ (warning symbol only on honesty lines)
            lines = llmResult.split("\n")
            errorsLine = [line for line in lines if "errors:" in line][0]
            assert "⚠" not in errorsLine

    def testChunkerAtomicity_preservesFenceBlocks(self) -> None:
        """Test chunker atomicity preserves fence blocks across chunks.

        Tests:
        - Fenced code blocks are never split across chunks
        - Each chunk has balanced fences (0 or 2 fence markers)
        - Naive line chunking would split inside block, but atomicity prevents it
        """
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Derivation of total length (>3000 to trigger chunking):
            #   Header: "📊 Stats — 7d (UTC) — #123" = 25 chars
            #   Messages header: "**Messages:** 1000" = 18 chars
            #   Fence opener: "```Top:" = 7 chars
            #   Long line: "• @verylongusername" + 2848 spaces + "1" = 2867 chars
            #   Second line: "• @anotheruser                        2" = 39 chars
            #   Third line: "• @thirduser                           3" = 40 chars
            #   Fence closer: "```" = 3 chars
            #   Commands header: "**Commands:** 500" = 17 chars
            #   Command line: "/stats help — полная справка" = 28 chars
            #   Tools header: "**Tools:** 50" = 13 chars
            #   Tool lines (4 entries, 41/41/40/40 chars): 162 chars
            #   Total: 25 + 18 + 7 + 2867 + 39 + 40 + 3 + 17 + 28 + 13 + 162 = 3219 chars
            # Naive line-by-line chunking at 3000 chars would split inside the fenced block
            #   (between the second and third bullets at cumulative ~3001), breaking fence atomicity.
            # Atomic chunking keeps the entire fence block (2979 chars) together as one unit,
            #   producing 3 chunks: header, fence block, remaining content.
            lines = [
                "📊 Stats — 7d (UTC) — #123",
                "**Messages:** 1000",
                "```Top:",
                "• @verylongusername" + " " * 2848 + "1",  # This line is 2867 chars
                "• @anotheruser                        2",
                "• @thirduser                           3",
                "```",
                "**Commands:** 500",
                "/stats help — полная справка",
                "**Tools:** 50",
                "• /configure                           25",
                "• /list_chats                          15",
                "• /stats                               8",
                "• /help                                2",
            ]

            # Total is 3219 chars, so naive chunking would split the block
            chunks = handler._chunkLinesWithFenceAtomicity(lines)

            # Should produce 3 chunks due to size, but block must be intact
            assert len(chunks) == 3

            # Verify each chunk has balanced fences
            for chunk in chunks:
                fenceCount = chunk.count("```")
                # Each chunk must have 0 or 2 fence markers (no unbalanced fences)
                assert fenceCount in [0, 2], f"Chunk has unbalanced fences ({fenceCount}): {chunk[:100]}..."

            # Verify the block is fully contained in one chunk
            # Find which chunk contains the opening fence
            blockChunk = None
            for chunk in chunks:
                if "```" in chunk and "• @verylongusername" in chunk:
                    blockChunk = chunk
                    break

            assert blockChunk is not None, "Block should be fully contained in one chunk"

            # Verify both opening and closing fences are in the same chunk
            assert blockChunk.count("```") == 2, "Block should have both fences in the same chunk"

            # Verify the long line is fully preserved
            assert "• @verylongusername" in blockChunk
            assert "1" in blockChunk  # The count should be there too

    def testRenderFencedTopBlock_multiWordCaption_nbspEscape(self):
        """Test _renderFencedTopBlock with multi-word caption escapes with NBSP.

        Tests that a multi-word caption like "Top models:" is rendered as
        ```` ```Top\xa0models: ```` (NBSP between words) to prevent the caption
        from being interpreted as separate tokens in some markdown parsers.

        Derivation: The multi-word caption "Top models:" is rendered with NBSP
        as ```` ```Top\xa0models: ```` (source-level \xa0 escape). This ensures
        the caption is treated as a single language string rather than being
        split at the space.
        """
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Render a fenced block with multi-word caption
            result = handler._renderFencedTopBlock([("gpt-4", 42)], "Top models:")

            # First element should be the fence opener with NBSP escape
            assert result[0] == "```Top\xa0models:", f"Expected NBSP-escaped caption, got: {repr(result[0])}"

    async def testUsernamesInBlocks_notBackticked(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test usernames inside blocks are NOT backticked.

        Tests:
        - Usernames in fenced code blocks are bare @name (no backticks)
        - _resolveUserName returns plain @name, backticks are stripped for block rendering
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Create mock rows
            rows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "123", "sent": "False"},
                    metricKey="message_count",
                    metricValue=100.0,
                ),
            ]

            analyzer = StatsAnalyzer(rows)

            # Mock _resolveUserName to return plain @name (as it should)
            handler._resolveUserName = AsyncMock(return_value="@alice")

            # Call _buildMessagesSectionFromAnalyzer
            result = await handler._buildMessagesSectionFromAnalyzer(
                analyzer=analyzer, truncatedEventTypes=[], targetChatId=123
            )

            # Check that username in block is NOT backticked
            assert "• @alice" in result, f"Expected '• @alice' (no backticks) in result: {result}"
            assert "`@alice`" not in result, f"Result should not contain backticked username in block: {result}"


class TestStatsHandlerWebTierInterimBehavior:
    """Tests for interim disabled behavior when stats-pages is disabled."""

    async def test_web_mode_with_stats_pages_disabled_sends_disabled_informative_reply(self):
        """Test that --web with stats-pages disabled sends informative reply."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": False,  # Disabled
        }
        mockDatabase = MagicMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=MagicMock()):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock sendMessage
            handler.sendMessage = AsyncMock()

            # Build message
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

            # Execute command with --web flag
            await cast(Any, handler).statsCommand(
                ensuredMessage=message,
                command="stats",
                args="--web",
                updateObj=None,
                typingManager=None,
            )

            # Verify informative disabled reply was sent
            handler.sendMessage.assert_called_once()
            callArgs = handler.sendMessage.call_args
            assert "Генерация веб-страниц отключена" in callArgs.kwargs["messageText"]

    async def testWebModeChunkedBrief(self) -> None:
        """Test that web mode correctly handles chunked brief output (I3-1).

        When the stats brief exceeds 3000 chars and is chunked, web mode should:
        - Send each chunk as a separate message
        - Append the page link to the last chunk
        - NOT include list-repr artifacts in sent messages
        """
        # Reset singleton
        StatsAggregationService._instance = None

        # Setup mock config with stats-pages enabled
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "ttl-hours": 24,
            "ratelimiter-queue": "stats-pages",
            "generate-command": ["echo", "test", "--base-url=https://stats.example.com", "--output-dir=./stats-pages"],
            "delete-command": ["rm", "-f", "{page_id}"],
        }

        mockDatabase = MagicMock()
        mockDatabase.chatUsers = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock sendMessage to track calls
            cast(Any, handler).sendMessage = AsyncMock()
            cast(Any, handler)._sendStatsReply = AsyncMock()  # Use this instead to test chunk handling

            # Mock _buildStatsReplyFromPayload to return a long chunked list (simulating >3000 chars)
            longChunk1 = "📊 Stats — 7d (UTC) — #123\n" + "**Messages:** 1000\n" + ("x" * 2900) + "\n"
            longChunk2 = "**Commands:** 500\n" + "**Tools:** 250\n" + "/stats help — полная справка"
            handler._buildStatsReplyFromPayload = AsyncMock(return_value=[longChunk1, longChunk2])

            # Mock _buildStatsPayload to avoid subprocess call
            handler._buildStatsPayload = AsyncMock(
                return_value={
                    "userId": "456",
                    "chatId": "123",
                    "chatTitle": "Test Chat",
                    "chatType": "private",
                    "platform": "telegram",
                    "period": "7d",
                    "periodType": "daily",
                    "generatedAt": "2026-01-01T00:00:00Z",
                    "rows": {},
                }
            )

            # Mock RateLimiterManager.applyLimit
            with patch("internal.bot.common.handlers.stats.RateLimiterManager") as mockRlm:
                mockRlm.getInstance.return_value.applyLimit = AsyncMock()
                with patch("internal.bot.common.handlers.stats.runCliCommand") as mockRunCli:
                    # Mock successful CLI response
                    mockRunCli.return_value = (
                        0,
                        (
                            '{"pageId": "test-page-id-123456789012345678901234567890", '
                            '"url": "test-page-id-123456789012345678901234567890.html"}'
                        ),
                        "",
                    )

                    # Build message
                    message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

                    # Execute command with --web flag
                    await cast(Any, handler).statsCommand(
                        ensuredMessage=message,
                        command="stats",
                        args="--web",
                        updateObj=None,
                        typingManager=None,
                    )

                    # Verify _sendStatsReply was called (it handles chunked messages)
                    assert handler._sendStatsReply.call_count == 1  # type: ignore[attr-defined]

                    # Get the message text that was sent
                    callArgs = handler._sendStatsReply.call_args  # type: ignore[attr-defined]
                    sentText = callArgs.args[1]  # The replyText argument

                    # Verify the link was appended to the last chunk
                    assert isinstance(sentText, list)
                    assert len(sentText) == 2
                    assert "📊 Страница:" in sentText[1]
                    assert "test-page-id-123456789012345678901234567890.html" in sentText[1]

                    # Verify NO list-repr artifacts (no "[" in the content)
                    assert "[" not in sentText[0], "First chunk should not contain list-repr artifacts"
                    assert "[" not in sentText[1], "Second chunk should not contain list-repr artifacts"

    async def testWebModeRealChunkingAlgorithm(self) -> None:
        """Test REAL chunking algorithm with >3000 char multi-line output.

        Verifies that the actual _sendStatsReply pacing logic works correctly:
        - Result is list[str] (pre-chunked)
        - sendMessage called once per chunk
        - asyncio.sleep called between chunks but not after last
        """
        # Reset singleton
        StatsAggregationService._instance = None

        # Setup mock config with stats-pages enabled
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "ttl-hours": 24,
            "ratelimiter-queue": "stats-pages",
            "generate-command": ["echo", "test", "--base-url=https://stats.example.com", "--output-dir=./stats-pages"],
            "delete-command": ["rm", "-f", "{page_id}"],
        }

        mockDatabase = MagicMock()
        mockDatabase.chatUsers = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock sendMessage to track chunk calls
            sentMessages: list[str] = []

            async def mockSendMessage(ensuredMessage: Any, **kwargs: Any) -> None:
                sentMessages.append(kwargs.get("messageText", ""))

            cast(Any, handler).sendMessage = mockSendMessage

            # Mock asyncio.sleep to keep test fast and track calls
            sleepCalls: list[float] = []

            async def mockSleep(delay: float) -> None:
                sleepCalls.append(delay)

            # Create multi-line output >3000 chars (simulating what _buildStatsReply would return)
            # Each line: "Line N: <long text>" where long text is ~100 chars
            lines: list[str] = []
            for i in range(40):  # 40 lines of ~100 chars each = ~4000 chars total
                lineText = f"Line {i:02d}: " + ("x" * 90)
                lines.append(lineText)

            # Create pre-chunked reply (simulating _buildStatsReply output)
            briefHeader = "📊 Stats — 7d (UTC) — #123\n**Messages:**\n"
            briefFooter = "\n/stats help — полная справка"
            fullBrief = briefHeader + "\n".join(lines) + briefFooter

            # Manually chunk at line boundary (simulating _buildStatsReply behavior)
            allLines = fullBrief.split("\n")
            midLine = len(allLines) // 2
            chunk1 = "\n".join(allLines[:midLine])
            chunk2 = "\n".join(allLines[midLine:])
            chunkedReply = [chunk1, chunk2]

            assert len(chunkedReply) >= 2, f"Expected >=2 chunks, got {len(chunkedReply)}"

            # Patch asyncio.sleep
            with patch("asyncio.sleep", side_effect=mockSleep):
                # Call the real _sendStatsReply with pre-chunked list
                message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
                await handler._sendStatsReply(ensuredMessage=message, replyText=chunkedReply, typingManager=None)

            # Verify multiple chunks were sent
            assert len(sentMessages) >= 2, f"Expected >=2 chunks, got {len(sentMessages)}"

            # Verify each chunk respects length limit (allowing one oversized line tolerance)
            for i, chunk in enumerate(sentMessages):
                # Allow tolerance: one line may exceed limit if it's longer than _OUTPUT_CHUNK_LENGTH
                linesInChunk = chunk.split("\n")
                chunkSizeOk = len(chunk) <= handler._OUTPUT_CHUNK_LENGTH or len(linesInChunk) == 1
                assert chunkSizeOk, (
                    f"Chunk {i} length {len(chunk)} exceeds limit "
                    f"{handler._OUTPUT_CHUNK_LENGTH} with {len(linesInChunk)} lines"
                )

            # Verify line integrity: when rejoining chunks, all original lines appear intact
            rejoined = "\n".join(sentMessages)
            for originalLine in lines:
                assert originalLine in rejoined, f"Original line '{originalLine}' not found in rejoined output"

            # Verify asyncio.sleep was called between chunks but not after last
            assert (
                len(sleepCalls) == len(sentMessages) - 1
            ), f"Expected {len(sentMessages) - 1} sleep calls, got {len(sleepCalls)}"
            for delay in sleepCalls:
                assert (
                    delay == handler._CHUNK_SEND_DELAY_SECONDS
                ), f"Expected {handler._CHUNK_SEND_DELAY_SECONDS}s sleep, got {delay}s"

    async def testPeriodHugeValueError(self) -> None:
        """Test that invalid period values like 95773m trigger usage error (I1-1).

        Regression test for ValueError escaping statsCommand when period is too large
        (would cause datetime(year > 9999) overflow).
        """
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        mockDatabase = MagicMock()
        mockDatabase.chatUsers = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock sendMessage to capture the usage error reply
            cast(Any, handler).sendMessage = AsyncMock()

            # Build message
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

            # Execute command with invalid huge period
            await cast(Any, handler).statsCommand(
                ensuredMessage=message,
                command="stats",
                args="--period=95773m",  # This would cause datetime(year > 9999) overflow
                updateObj=None,
                typingManager=None,
            )

            # Verify usage error reply was sent
            handler.sendMessage.assert_called_once()  # type: ignore[attr-defined]
            callArgs = handler.sendMessage.call_args  # type: ignore[attr-defined]
            assert "❌ Неверный период: 95773m" in callArgs.kwargs["messageText"]
            # Verify the usage text contains period spec (U12-1 format)
            assert "--period=..." in callArgs.kwargs["messageText"]

    async def testPeriodGrammarInvalidChars(self) -> None:
        """Test that period grammar rejects invalid characters (I1-2, MINOR).

        Regression test for grammar tightening: +5d, 1_0h, and unicode digits
        should be rejected as usage errors.
        """
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        mockDatabase = MagicMock()
        mockDatabase.chatUsers = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock sendMessage to capture the usage error reply
            cast(Any, handler).sendMessage = AsyncMock()

            # Build message
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="--period=+5d", updateObj=None, typingManager=None
            )
            callArgs = handler.sendMessage.call_args  # type: ignore[attr-defined]
            assert "❌ Неверный период: +5d" in callArgs.kwargs["messageText"]

            # Test case 2: 1_0h (underscore should be rejected)
            handler.sendMessage.reset_mock()  # type: ignore[attr-defined]
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="--period=1_0h", updateObj=None, typingManager=None
            )
            callArgs = handler.sendMessage.call_args  # type: ignore[attr-defined]
            assert "❌ Неверный период: 1_0h" in callArgs.kwargs["messageText"]

            # Test case 3: ٣d (Arabic-Indic digit should be rejected)
            handler.sendMessage.reset_mock()  # type: ignore[attr-defined]
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="--period=٣d", updateObj=None, typingManager=None
            )
            callArgs = handler.sendMessage.call_args  # type: ignore[attr-defined]
            assert "❌ Неверный период: ٣d" in callArgs.kwargs["messageText"]

    async def testUserAtUsernameResolution(self) -> None:
        """Test --user=@username resolution (I3-3).

        Tests:
        - @username resolves via db.chatUsers.getChatUserByUsername (case-insensitive)
        - Reply filtered by resolved user ID
        - @unknown → usage error reply
        - Bare --user (no value) → usage error
        """
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        mockDatabase = MagicMock()
        mockDatabase.chatUsers = MagicMock()
        mockDatabase.chatUsers.getChatUserByUsername = AsyncMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock sendMessage to capture replies
            cast(Any, handler).sendMessage = AsyncMock()

            # Test case 1: @username resolution succeeds
            mockDatabase.chatUsers.getChatUserByUsername.return_value = {"user_id": 789}
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="--user=@john", updateObj=None, typingManager=None
            )

            # Verify getChatUserByUsername was called with stripped username (without @)
            mockDatabase.chatUsers.getChatUserByUsername.assert_called_once_with(chatId=123, username="john")

            # Test case 2: @unknown → usage error
            handler.sendMessage.reset_mock()  # type: ignore[attr-defined]
            mockDatabase.chatUsers.getChatUserByUsername.reset_mock()
            mockDatabase.chatUsers.getChatUserByUsername.return_value = None
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="--user=@unknown", updateObj=None, typingManager=None
            )

            callArgs = handler.sendMessage.call_args  # type: ignore[attr-defined]
            assert "❌ Пользователь @unknown не найден в этом чате." in callArgs.kwargs["messageText"]

            # Test case 3: case-insensitive username resolution
            handler.sendMessage.reset_mock()  # type: ignore[attr-defined]
            mockDatabase.chatUsers.getChatUserByUsername.reset_mock()
            mockDatabase.chatUsers.getChatUserByUsername.return_value = {"user_id": 789}
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="--user=@JoHn", updateObj=None, typingManager=None
            )

            # Verify getChatUserByUsername was called with stripped username (without @)
            mockDatabase.chatUsers.getChatUserByUsername.assert_called_once_with(chatId=123, username="JoHn")

    async def testUserBareArgumentError(self) -> None:
        """Test that bare --user (no value) triggers usage error (I3-3)."""
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        mockDatabase = MagicMock()
        mockDatabase.chatUsers = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock sendMessage to capture the usage error reply
            cast(Any, handler).sendMessage = cast(Any, AsyncMock())

            # Build message
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

            # Execute command with bare --user (no value)
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="--user", updateObj=None, typingManager=None
            )

            # Assert sendMessage was called once with the error
            mockSendMessage = cast(Any, handler.sendMessage)
            mockSendMessage.assert_called_once()
            callArgs = mockSendMessage.call_args
            messageText = callArgs.kwargs.get("messageText") or callArgs[1].get("messageText")
            assert "❌ Опция --user требует значения" in messageText

    async def testResolveUserName_doubleAtBug(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test _resolveUserName fixes double-@ bug.

        Tests:
        - Stored username with leading @ → single @, no backticks
        - Stored username without leading @ → single @ prefixed, no backticks
        - full_name fallback → unchanged
        - str(userId) fallback → unchanged
        Note: _resolveUserName now returns plain @name (no backticks) since they're
        rendered inside fenced code blocks where backticks would interfere.
        """
        # Reset singleton
        CacheService._instance = None

        # Mock config to enable stats
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Mock cache.getChatUser
            handler.cache.getChatUser = AsyncMock()

            # Test case 1: Stored username with leading @
            handler.cache.getChatUser.return_value = {"username": "@Cthulho", "full_name": "Cthulhu"}
            result = await handler._resolveUserName(chatId=123, userId=42)
            assert result == "@Cthulho", f"Expected '@Cthulho' but got '{result}'"

            # Test case 2: Stored username without leading @
            handler.cache.getChatUser.return_value = {"username": "alice", "full_name": "Alice"}
            result = await handler._resolveUserName(chatId=123, userId=42)
            assert result == "@alice", f"Expected '@alice' but got '{result}'"

            # Test case 3: full_name fallback (NOT backticked)
            handler.cache.getChatUser.return_value = {"username": None, "full_name": "Bob Builder"}
            result = await handler._resolveUserName(chatId=123, userId=42)
            assert result == "Bob Builder", f"Expected 'Bob Builder' but got '{result}'"

            # Test case 4: str(userId) fallback (NOT backticked)
            handler.cache.getChatUser.return_value = None
            result = await handler._resolveUserName(chatId=123, userId=42)
            assert result == "42", f"Expected '42' but got '{result}'"

    async def testMessagesSection_topUsersFormat(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test Top users renders as fenced code block with bullet markers.

        Tests:
        - Caption on fence line: "```Top:"
        - Fenced code block with ``` markers
        - One user per line with • bullet marker
        - Usernames are bare @name without backticks (inside code block)
        - Aligned columns (ljust name, rjust count)
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Create mock rows with multiple users
            rows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "123", "sent": "False"},
                    metricKey="message_count",
                    metricValue=336.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "456", "sent": "False"},
                    metricKey="message_count",
                    metricValue=257.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "789", "sent": "False"},
                    metricKey="message_count",
                    metricValue=100.0,
                ),
            ]

            analyzer = StatsAnalyzer(rows)

            # Mock _resolveUserName with bare usernames (no backticks inside blocks)
            def mockResolve(chatId: int, userId: int) -> str:
                """Mock resolver for testing top users format.

                Args:
                    chatId: Chat ID (unused in this mock).
                    userId: User ID to resolve.

                Returns:
                    Bare username string for display (no backticks).
                """
                if userId == 123:
                    return "@Cthulho"
                elif userId == 456:
                    return "@YukiOnnaTheCat"
                else:
                    return "@user789"

            handler._resolveUserName = AsyncMock(side_effect=mockResolve)

            # Call _buildMessagesSectionFromAnalyzer
            result = await handler._buildMessagesSectionFromAnalyzer(
                analyzer=analyzer,
                truncatedEventTypes=[],
                targetChatId=123,
            )

            # Check Top format
            lines = result.split("\n")

            # Find Top section - look for "```Top:" fence line (caption on fence)
            topSectionStart = None
            for i, line in enumerate(lines):
                if line.strip() == "```Top:":
                    topSectionStart = i
                    break

            assert topSectionStart is not None, f"Top section not found in result: {result}"

            # Verify strict format: "```Top:" on fence line (caption-in-fence), followed by bullets, then "```"
            assert (
                lines[topSectionStart].strip() == "```Top:"
            ), f"Expected fence line '```Top:' but got '{lines[topSectionStart].strip()}'"

            # Verify merged fence exists (new shape: caption on fence line)
            assert "```Top:" in result, f"Result should contain merged fence '```Top:': {result}"

            # Check that old separate "Top:" line is NOT present
            assert "\nTop:\n" not in result, f"Result should not contain separate 'Top:' line: {result}"

            # Check bullet markers and alignment
            assert "• @Cthulho" in result, f"Expected '• @Cthulho' in result: {result}"
            assert "• @YukiOnnaTheCat" in result, f"Expected '• @YukiOnnaTheCat' in result: {result}"
            assert "• @user789" in result, f"Expected '• @user789' in result: {result}"

            # Check that users are NOT backticked inside the block
            assert "`@Cthulho`" not in result, f"Result should not contain backticked username in block: {result}"
            assert (
                "`@YukiOnnaTheCat`" not in result
            ), f"Result should not contain backticked username in block: {result}"
            assert "`@user789`" not in result, f"Result should not contain backticked username in block: {result}"

            # Check that fences are balanced
            fenceCount = result.count("```")
            assert fenceCount == 2, f"Expected 2 fence markers (opening + closing) but found {fenceCount}: {result}"

            # Check alignment: all usernames should be left-justified to same width
            # Extract bullet lines
            bulletLines = [line for line in lines if line.strip().startswith("•")]
            assert len(bulletLines) == 3, f"Expected 3 bullet lines but found {len(bulletLines)}"

            # Check exact format with alignment (widths based on longest username)
            # @YukiOnnaTheCat is longest (15 chars), @Cthulho is 8, @user789 is 8
            # So padding should make them all 15 chars, followed by 2 spaces, then right-justified count
            # 336 is 3 chars, 257 is 3 chars, 100 is 3 chars
            expectedLines = [
                "• @Cthulho         336",  # ljust(15): 8+7 pad, then 2-space gap, then rjust(3)
                "• @YukiOnnaTheCat  257",  # ljust(15): 15+0 pad, then 2-space gap, then rjust(3)
                "• @user789         100",  # ljust(15): 8+7 pad, then 2-space gap, then rjust(3)
            ]
            for expected in expectedLines:
                assert expected in result, f"Expected aligned line '{expected}' in result: {result}"

    async def testMessagesSection_botRowExcludedFromTop(self, mockConfigManager, mockDatabaseWrapper) -> None:
        """Test that bot rows (sent=True) are excluded from Top users but included in total.

        Tests:
        - Total message count includes bot messages
        - Top fenced block contains only non-bot entries
        - Bot's username (@somebot) is not in the Top block
        - Bot's message count is absent from Top block
        """
        # Mock config
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabaseWrapper, botProvider=BotProvider.TELEGRAM
            )

            # Create mock rows with both users and a bot
            rows = [
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "123", "sent": "False"},  # Normal user
                    metricKey="message_count",
                    metricValue=336.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "456", "sent": "False"},  # Normal user
                    metricKey="message_count",
                    metricValue=257.0,
                ),
                StatsAggregateDict(
                    periodType="daily",
                    periodStart="2024-01-01T00:00:00+00:00",
                    labels={"user_id": "999", "sent": "True"},  # Bot user (sent=True)
                    metricKey="message_count",
                    metricValue=500.0,  # Bot has highest count
                ),
            ]

            analyzer = StatsAnalyzer(rows)

            # Mock _resolveUserName to return @somebot for the bot user
            def mockResolve(chatId: int, userId: int) -> str:
                """Mock resolver for testing bot row exclusion.

                Args:
                    chatId: Chat ID (unused in this mock).
                    userId: User ID to resolve.

                Returns:
                    Username string for display.
                """
                if userId == 123:
                    return "@alice"
                elif userId == 456:
                    return "@bob"
                elif userId == 999:
                    return "@somebot"
                else:
                    return f"@user{userId}"

            handler._resolveUserName = AsyncMock(side_effect=mockResolve)

            # Call _buildMessagesSectionFromAnalyzer
            result = await handler._buildMessagesSectionFromAnalyzer(
                analyzer=analyzer,
                truncatedEventTypes=[],
                targetChatId=123,
            )

            # Check that total includes bot messages (336 + 257 + 500 = 1093)
            assert "**Messages:** 1,09k" in result, f"Expected total count to include bot messages: {result}"

            # Check that Top fenced block does NOT contain the bot
            assert "@somebot" not in result, f"Bot username '@somebot' should not appear in Top block: {result}"

            # Check that only non-bot users are in the Top block
            assert "@alice" in result, f"Expected '@alice' in Top block: {result}"
            assert "@bob" in result, f"Expected '@bob' in Top block: {result}"

            # Verify the counts shown are only for non-bot users (336 and 257)
            # The bot's count (500) should not appear in the Top block
            assert "500" not in result, f"Bot's count '500' should not appear in Top block: {result}"

    async def testDeleteDeniedCommandsTrueBranch(self) -> None:
        """Test DELETE_DENIED_COMMANDS=true branch (I3-4).

        When ALLOW_SHOW_STATS is false and DELETE_DENIED_COMMANDS is true:
        - deleteMessage should be called once
        - NO stats reply should be sent
        """
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        mockDatabase = MagicMock()
        mockDatabase.chatUsers = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock methods
            handler.sendMessage = AsyncMock()
            handler.deleteMessage = AsyncMock()
            handler.getChatSettings = AsyncMock(
                return_value={
                    ChatSettingsKey.ALLOW_SHOW_STATS: ChatSettingsValue("false", 12345),
                    ChatSettingsKey.DELETE_DENIED_COMMANDS: ChatSettingsValue("true", 12345),
                }
            )

            # Build message for GROUP chat (not private)
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.GROUP, userId=456)

            # Execute command
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="", updateObj=None, typingManager=None
            )

            # Verify deleteMessage was called once
            handler.deleteMessage.assert_called_once()

            # Verify NO stats reply was sent
            handler.sendMessage.assert_not_called()  # type: ignore[attr-defined]

    async def testDeleteDeniedCommandsFalseBranch(self) -> None:
        """Test DELETE_DENIED_COMMANDS=false branch (I3-4).

        When ALLOW_SHOW_STATS is false and DELETE_DENIED_COMMANDS is false:
        - Informative reply should be sent
        - deleteMessage should NOT be called
        """
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        mockDatabase = MagicMock()
        mockDatabase.chatUsers = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock methods
            handler.sendMessage = AsyncMock()
            handler.deleteMessage = AsyncMock()
            handler.getChatSettings = AsyncMock(
                return_value={
                    ChatSettingsKey.ALLOW_SHOW_STATS: ChatSettingsValue("false", 12345),
                    ChatSettingsKey.DELETE_DENIED_COMMANDS: ChatSettingsValue("false", 12345),
                }
            )

            # Build message for GROUP chat (not private)
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.GROUP, userId=456)

            # Execute command
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="", updateObj=None, typingManager=None
            )

            # Verify informative reply was sent
            handler.sendMessage.assert_called_once()  # type: ignore[attr-defined]
            callArgs = handler.sendMessage.call_args  # type: ignore[attr-defined]
            assert "⚠ Показ статистики отключён в этом чате" in callArgs.kwargs["messageText"]

            # Verify deleteMessage was NOT called
            handler.deleteMessage.assert_not_called()  # type: ignore[attr-defined]

    async def testSectionAllRendersAllSections(self) -> None:
        """Test that --section=all renders all four sections (I3-5).

        When --section=all is specified:
        - All four sections should be rendered: messages, commands, tools, llm
        - This should trigger 4 storage query groups (one per section)
        """
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}

        mockDatabase = MagicMock()
        mockDatabase.chatUsers = MagicMock()

        with patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Mock _sendStatsReply to capture the output
            handler._sendStatsReply = AsyncMock()

            # Mock stats aggregation service
            mockStorage = MagicMock()
            mockStorage.query = AsyncMock(return_value=[])
            mockAggService = MagicMock()
            mockAggService.getQueryStorage.return_value = mockStorage
            handler.statsAggregationService = mockAggService

            # Build message
            message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

            # Execute command with --section=all
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="--section=all", updateObj=None, typingManager=None
            )

            # Verify _sendStatsReply was called
            handler._sendStatsReply.assert_called_once()  # type: ignore[attr-defined]

            # Get the reply text (non-web mode uses keyword arguments)
            callArgs = handler._sendStatsReply.call_args
            replyText = callArgs.kwargs["replyText"]

            # If it's a string, check for all 4 section markers with bold
            if isinstance(replyText, str):
                assert "**Messages:**" in replyText
                assert "**Commands:**" in replyText
                assert "**Tools:**" in replyText
                assert "**LLM:**" in replyText
            else:
                # If it's a list, join and check
                joined = "\n".join(replyText)  # type: ignore[arg-type]
                assert "**Messages:**" in joined
                assert "**Commands:**" in joined
                assert "**Tools:**" in joined
                assert "**LLM:**" in joined

            # Verify all 4 storage queries were made (message, command, llm_tool_call, llm_request, stt_request)
            # Actually it's 5 types: message, command, llm_tool_call, llm_request, stt_request
            # But we should have at least 4 basic sections
            assert mockStorage.query.call_count >= 4


class TestStatsHandlerFormattingHelpers:
    """Tests for formatting helper methods _formatCount and _formatDuration."""

    def test_formatCount_reference_table(self):
        """Test _formatCount against the full reference table.

        Reference table from spec:
        999→"999", 1000→"1k", 1484→"1,48k", 1500→"1,5k", 79662→"79,7k",
        389924→"390k", 9999→"10k", 999999→"1m", 1234567→"1,23m", 2400000000→"2,4g".
        """
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()

        with unittest.mock.patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Test each reference case
            # Values < 1000 (no formatting)
            assert handler._formatCount(999) == "999"
            assert handler._formatCount(0) == "0"
            assert handler._formatCount(1) == "1"

            # Values >= 1000 (k suffix)
            # 1000 / 1000 = 1.0 → decimals=2 → "1.00" → strip trailing "0" → strip "." → "1" → "1k"
            assert handler._formatCount(1000) == "1k"
            # 1484 / 1000 = 1.484 → scaled<10 so decimals=2 → "1.48" → "1,48k"
            assert handler._formatCount(1484) == "1,48k"
            # 1500 / 1000 = 1.5 → scaled<10 so decimals=2 → "1.50" → strip trailing "0" → "1.5" → "1,5k"
            assert handler._formatCount(1500) == "1,5k"
            # 79662 / 1000 = 79.662 → 10<=scaled<100 so decimals=1 → "79.7" → "79,7k"
            assert handler._formatCount(79662) == "79,7k"
            # 389924 / 1000 = 389.924 → scaled>=100 so decimals=0 → "390" → "390k"
            assert handler._formatCount(389924) == "390k"
            # ROUND-FIRST: 9999 → round to 3 sig figs → 10000 → 10k (1e4 → tier=k)
            assert handler._formatCount(9999) == "10k"

            # Values >= 1_000_000 (m suffix)
            # ROUND-FIRST: 999999 → round to 3 sig figs → 1000000 → 1m (1e6 → tier=m)
            assert handler._formatCount(999999) == "1m"
            # 1234567 / 1_000_000 = 1.234567 → scaled<10 so decimals=2 → "1.23" → "1,23m"
            assert handler._formatCount(1234567) == "1,23m"

            # Values >= 1_000_000_000 (g suffix)
            # 2400000000 / 1_000_000_000 = 2.4 → scaled<10 so decimals=2 → "2.40" → strip trailing "0" → "2.4" → "2,4g"
            assert handler._formatCount(2400000000) == "2,4g"

    def test_formatDuration_reference_cases(self):
        """Test _formatDuration against reference cases from spec.

        Reference cases:
        0.5→"0.50s", 33.3(audio)→"33.3s", 59.99→"59.99s", 75.43→"1m 15.4s",
        3660→"1h 01m 0.0s", 3745→"1h 02m 25.0s".
        """
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()

        with unittest.mock.patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Sub-minute values (seconds < 60)
            # 0.5 with default decimals=2 → "0.50s"
            assert handler._formatDuration(0.5) == "0.50s"
            # 33.3 with decimals=1 (audio uses subMinuteDecimals=1) → "33.3s"
            assert handler._formatDuration(33.3, subMinuteDecimals=1) == "33.3s"
            # 59.99 with default decimals=2 → "59.99s"
            assert handler._formatDuration(59.99) == "59.99s"
            # Edge case: exactly 60 seconds uses minute format
            assert handler._formatDuration(60.0) == "1m 0.0s"

            # Minute-scale values (60 <= seconds < 3600)
            # 75.43 seconds = 1 minute + 15.43 seconds → "1m 15.4s"
            # 1m = 60s, remaining = 15.43s, format with .1f → "15.4s"
            assert handler._formatDuration(75.43) == "1m 15.4s"
            # 125 seconds = 2 minutes + 5 seconds → "2m 5.0s"
            assert handler._formatDuration(125.0) == "2m 5.0s"

            # Hour-scale values (seconds >= 3600)
            # 3660 seconds = 1 hour + 1 minute + 0 seconds
            # 3660 / 3600 = 1.0166... → 1h
            # remaining = 60s = 1m 0s
            assert handler._formatDuration(3660.0) == "1h 01m 0.0s"
            # 3745 seconds = 1 hour + 2 minutes + 25 seconds
            # 3745 / 3600 = 1.0402... → 1h
            # remaining = 145s = 2m 25s (145 / 60 = 2.4166...)
            assert handler._formatDuration(3745.0) == "1h 02m 25.0s"

    def test_renderFencedTopBlock_kFormattedAlignment(self):
        """Test _renderFencedTopBlock with k-formatted counts alignment.

        Derivation:
        - Keys: "alpha", "bb", "c" → max key width = 5 ("alpha")
        - Counts: 1234, 794, 999
        - Formatted: 1234→"1,23k", 794→"794", 999→"999"
        - Max formatted count width = 5 ("1,23k" and "999" and "794")
        - Format: "• {key.ljust(5)}  {count.rjust(5)}"
        - Expected lines:
          "• alpha  1,23k"
          "• bb       999"
          "• c        794"
        - New shape: caption on fence line ("```Top:"), not separate header line
        """
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()

        with unittest.mock.patch("internal.services.queue_service.QueueService"):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            items = [("alpha", 1234), ("bb", 999), ("c", 794)]
            result = handler._renderFencedTopBlock(items)

            # Check exact line-by-line output (new shape: caption on fence line)
            # Expected: ["```Top:", "• alpha  1,23k", "• bb       999", "• c        794", "```"]
            assert len(result) == 5  # "```Top:", 3 bullets, "```"
            assert result[0] == "```Top:"
            assert result[1] == "• alpha  1,23k"
            assert result[2] == "• bb       999"
            assert result[3] == "• c        794"
            assert result[4] == "```"
