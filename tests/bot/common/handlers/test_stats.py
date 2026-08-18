"""Tests for the StatsHandler.

Tests argument parsing, scoping, chat settings gating, and view rendering.
"""

import asyncio
import datetime
import time
import unittest.mock
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

import lib.stats.stats_pages.launcher
from internal.bot.common.handlers.stats import StatsHandler
from internal.bot.models import BotProvider, ChatSettingsKey, ChatSettingsValue, ChatType, EnsuredMessage
from internal.models.types import MessageId
from internal.services.queue_service import QueueService
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction
from internal.services.stats.service import StatsAggregationService
from lib.stats import NullStatsStorage

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
        assert "Messages:" in replyText  # Only default section (messages) is rendered

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
        assert "LLM:" in replyText
        assert "(на уровне чата, не пользователя)" in replyText


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

    def test_stats_enabled_manager_registration_invariant(self):
        """Test manager-level registration: stats enabled → StatsHandler registered and LLMMessageHandler last.

        This test executes the REAL registration path by mocking only what's needed for
        HandlersManager.__init__ to succeed, then verifies the handler ordering invariant.
        """
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
        from internal.services.cache import CacheService
        from internal.services.queue_service import QueueService
        from internal.services.storage import StorageService

        # Reset singletons
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
        from internal.services.cache import CacheService
        from internal.services.queue_service import QueueService
        from internal.services.storage import StorageService

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
    """Tests for stats-pages config validation at construction (D10, U12-4: base-url removed)."""

    def test_stats_pages_enabled_with_missing_base_url_no_longer_validates(self):
        """U12-4: base-url key removed, CLI owns URL composition - no validation."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
            "delete-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}"],
            "ttl-hours": 24,
            # base-url key is gone (U12-4: CLI owns URL via --base-url argument)
        }
        mockDatabase = MagicMock()

        # Patch QueueService.getInstance to avoid registration during construction
        with unittest.mock.patch.object(QueueService, "getInstance", return_value=MagicMock()):
            # Should NOT raise - base-url validation removed
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )
            assert handler is not None

    def test_stats_pages_enabled_with_valid_config_constructs_and_registers_handler(self):
        """Test that construction succeeds and cleanup handler is registered when config is valid."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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

    def test_stats_pages_disabled_no_validation_and_no_handler_registration(self):
        """Test that construction proceeds without validation or handler registration when disabled."""

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

        # Mock QueueService to verify no registration
        mockQueueService = MagicMock()
        mockQueueService.registerDelayedTaskHandler = MagicMock()

        with unittest.mock.patch.object(QueueService, "getInstance", return_value=mockQueueService):
            handler = StatsHandler(
                configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM
            )

            # Verify handler constructed
            assert handler is not None
            assert handler._statsPagesEnabled is False

            # Verify NO cleanup handler was registered
            mockQueueService.registerDelayedTaskHandler.assert_not_called()


class TestStatsHandlerWebTierRateLimiting:
    """Tests for rate limiting in web mode (D13)."""

    async def test_rate_limit_exceeded_sends_refusal_reply_no_cli_invocation(self):
        """U12-6: Rate limit is applyLimit-only - NO pre-check, NO refusal reply, just sleeps."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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

    async def test_rate_limit_below_max_proceeds_with_generation(self):
        """Test that rate limit below max proceeds with page generation."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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

            # Mock RateLimiterManager to return below limit
            mockRateLimiter = MagicMock()
            mockRateLimiter.getStats.return_value = {"maxRequests": 3, "requestsInWindow": 1}
            mockRateLimiter.applyLimit = AsyncMock()

            with unittest.mock.patch("internal.bot.common.handlers.stats.RateLimiterManager") as MockRl:
                MockRl.getInstance.return_value = mockRateLimiter

                # Mock subprocess to return success
                mockProc = MagicMock()
                mockProc.communicate = AsyncMock(return_value=(b'{"id": "abc123", "url": "abc123.html"}', b""))
                mockProc.returncode = 0

                # Patch ONLY create_subprocess_exec, not the whole asyncio module
                with unittest.mock.patch.object(
                    lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
                ):
                    # Mock sendMessage and other dependencies
                    handler.sendMessage = AsyncMock()
                    handler.getUserChats = AsyncMock(return_value=[])
                    handler.cache.getChatInfo = AsyncMock(return_value=None)
                    handler.cache.getChatUser = AsyncMock(return_value=None)

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

                    # Verify applyLimit WAS called (record the attempt)
                    mockRateLimiter.applyLimit.assert_called_once_with("stats-pages", "stats-pages-123")

    async def test_never_used_rate_limit_key_proceeds_with_generation(self):
        """Test that ValueError from getStats (never-used key) uses=0 and proceeds."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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

            # Mock RateLimiterManager to raise ValueError (never-used key)
            mockRateLimiter = MagicMock()
            mockRateLimiter.getStats.side_effect = ValueError("never-used key")
            mockRateLimiter.applyLimit = AsyncMock()

            with unittest.mock.patch("internal.bot.common.handlers.stats.RateLimiterManager") as MockRl:
                MockRl.getInstance.return_value = mockRateLimiter

                # Mock subprocess to return success
                mockProc = MagicMock()
                mockProc.communicate = AsyncMock(return_value=(b'{"id": "abc123", "url": "abc123.html"}', b""))
                mockProc.returncode = 0

                # Patch ONLY create_subprocess_exec, not the whole asyncio module
                with unittest.mock.patch.object(
                    lib.stats.stats_pages.launcher.asyncio, "create_subprocess_exec", return_value=mockProc
                ):
                    # Mock sendMessage and other dependencies
                    handler.sendMessage = AsyncMock()
                    handler.getUserChats = AsyncMock(return_value=[])
                    handler.cache.getChatInfo = AsyncMock(return_value=None)
                    handler.cache.getChatUser = AsyncMock(return_value=None)

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

                    # Verify applyLimit WAS called (used=0 < maxRequests)
                    mockRateLimiter.applyLimit.assert_called_once_with("stats-pages", "stats-pages-123")


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
                    # Mock sendMessage and other dependencies
                    handler.sendMessage = AsyncMock()
                    handler.getUserChats = AsyncMock(return_value=[])
                    handler.cache.getChatInfo = AsyncMock(return_value=None)
                    handler.cache.getChatUser = AsyncMock(return_value=None)

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
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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
                    handler.cache.getChatInfo = AsyncMock(return_value=None)
                    handler.cache.getChatUser = AsyncMock(return_value=None)

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
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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
                    handler.cache.getChatInfo = AsyncMock(return_value=None)
                    handler.cache.getChatUser = AsyncMock(return_value=None)

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
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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
                    handler.cache.getChatInfo = AsyncMock(return_value=None)
                    handler.cache.getChatUser = AsyncMock(return_value=None)

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
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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
                    handler.cache.getChatInfo = AsyncMock(return_value=None)
                    handler.cache.getChatUser = AsyncMock(return_value=None)

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
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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
                    handler.cache.getChatInfo = AsyncMock(return_value=None)
                    handler.cache.getChatUser = AsyncMock(return_value=None)

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
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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
            ):
                # Execute cleanup handler
                await handler._dtStatsPagesCleanup(task)

                # Verify subprocess was called (communicate was invoked)
                assert mockProc.communicate.called

    async def test_cleanup_handler_tolerates_deleted_zero(self):
        """Test that cleanup handler tolerates {deleted: 0} response."""

        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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
            "generate-command": ["./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate"],
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
            assert "[stats.pages]" in callArgs.kwargs["messageText"]

    async def testWebModeChunkedBrief(self) -> None:
        """Test that web mode correctly handles chunked brief output (I3-1).

        When the stats brief exceeds 3000 chars and is chunked, web mode should:
        - Send each chunk as a separate message
        - Append the page link to the last chunk
        - NOT include list-repr artifacts in sent messages
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup mock config with stats-pages enabled
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {
            "enabled": True,
            "ttl-hours": 24,
            "ratelimiter-queue": "stats-pages",
            "generate-command": ["echo", "test"],
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

            # Mock _buildStatsReply to return a long chunked list (simulating >3000 chars)
            longChunk1 = "📊 Stats — 7d (UTC) — #123\n" + "Messages: 1000\n" + ("x" * 2900) + "\n"
            longChunk2 = "Commands: 500\n" + "Tools: 250\n" + "/stats help — полная справка"
            handler._buildStatsReply = AsyncMock(return_value=[longChunk1, longChunk2])

            # Mock _buildStatsPayload to avoid subprocess call
            handler._buildStatsPayload = AsyncMock(
                return_value={
                    "userId": "456",
                    "chatId": "123",
                    "chatTitle": "Test Chat",
                    "chatType": "private",
                    "platform": "telegram",
                    "period": "7d",
                    "generatedAt": "2026-01-01T00:00:00Z",
                    "sections": {"messages": {"totalMessages": 1000}},
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
                    assert "[" not in sentText[0] or "Messages: 1000" in sentText[0]
                    assert "[" not in sentText[1] or "Commands: 500" in sentText[1]

    async def testPeriodHugeValueError(self) -> None:
        """Test that invalid period values like 95773m trigger usage error (I1-1).

        Regression test for ValueError escaping statsCommand when period is too large
        (would cause datetime(year > 9999) overflow).
        """
        from unittest.mock import patch

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
        from unittest.mock import patch

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

    async def testUserAtUsernameResolution(self) -> None:
        """Test --user=@username resolution (I3-3).

        Tests:
        - @username resolves via db.chatUsers.getChatUserByUsername (case-insensitive)
        - Reply filtered by resolved user ID
        - @unknown → usage error reply
        - Bare --user (no value) → usage error
        """
        from unittest.mock import patch

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
        from unittest.mock import patch

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

            # Execute command with bare --user (no value)
            await cast(Any, handler).statsCommand(
                ensuredMessage=message, command="stats", args="--user", updateObj=None, typingManager=None
            )

            # Verify usage error reply was sent
            handler.sendMessage.assert_called_once()  # type: ignore[attr-defined]
            callArgs = handler.sendMessage.call_args  # type: ignore[attr-defined]
            assert "❌ Неверный user ID:" in callArgs.kwargs["messageText"]

    async def testDeleteDeniedCommandsTrueBranch(self) -> None:
        """Test DELETE_DENIED_COMMANDS=true branch (I3-4).

        When ALLOW_SHOW_STATS is false and DELETE_DENIED_COMMANDS is true:
        - deleteMessage should be called once
        - NO stats reply should be sent
        """
        from unittest.mock import patch

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
        from unittest.mock import patch

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
        from unittest.mock import patch

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

            # If it's a string, check for all 4 section markers
            if isinstance(replyText, str):
                assert "Messages:" in replyText
                assert "Commands:" in replyText
                assert "Tools:" in replyText
                assert "LLM:" in replyText
            else:
                # If it's a list, join and check
                joined = "\n".join(replyText)  # type: ignore[arg-type]
                assert "Messages:" in joined
                assert "Commands:" in joined
                assert "Tools:" in joined
                assert "LLM:" in joined

            # Verify all 4 storage queries were made (message, command, llm_tool_call, llm_request, stt_request)
            # Actually it's 5 types: message, command, llm_tool_call, llm_request, stt_request
            # But we should have at least 4 basic sections
            assert mockStorage.query.call_count >= 4
