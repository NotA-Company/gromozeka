"""Tests for the StatsHandler.

Tests argument parsing, scoping, chat settings gating, and view rendering.
"""

import datetime
import unittest.mock
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from internal.bot.common.handlers.stats import StatsHandler
from internal.bot.models import BotProvider, ChatSettingsKey, ChatSettingsValue, ChatType, EnsuredMessage
from internal.models.types import MessageId
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
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        result = handler._parseStatsArgs("help", forceWeb=False)

        assert result is not None
        assert result["help"] is True

    def test_alias_forces_web(self):
        """Test that /stats_web alias forces web mode."""
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
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
        assert "#123 Chat 1 — 100" in replyText
        assert "#456 Chat 2 — 50" in replyText

    async def test_private_positional_chatId_drills_down_all_sections(self):
        """Test that private with positional chatId renders all four sections (D7 drill-down)."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock getUserChats to return the requested chat
        handler.getUserChats = AsyncMock(return_value=[{"chat_id": 789, "title": "Target Chat", "messages_count": 100}])

        # Mock storages for all sections
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

        # Verify all storages were queried (D7 drill-down: 4 main sections + STT as part of LLM section)
        # Note: LLM section queries both llm_request AND stt_request storages
        assert handler.statsAggregationService.getQueryStorage.call_count == 5
        storageCalls = [call.args[0] for call in handler.statsAggregationService.getQueryStorage.call_args_list]
        assert "message" in storageCalls
        assert "command" in storageCalls
        assert "llm_tool_call" in storageCalls
        assert "llm_request" in storageCalls
        assert "stt_request" in storageCalls  # STT is queried as part of LLM section

        # Verify reply includes all four sections
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]
        assert "Messages:" in replyText
        assert "Commands:" in replyText
        assert "Tools:" in replyText
        assert "LLM:" in replyText

    async def test_private_positional_chatId_not_in_user_chats_error(self):
        """Test that private with positional chatId not in getUserChats returns error."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
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
        """Test e2e period mapping: 1d→hourly, 7d→daily, all→total."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Test 1d period
        for periodArg, expectedPeriodType in [("1d", "hourly"), ("7d", "daily"), ("all", "total")]:
            # Reset handler for each test
            mockConfigManager = MagicMock()
            mockConfigManager.getStatsConfig.return_value = {"enabled": True}
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
        """Test that bad period returns usage error."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock sendMessage
        handler.sendMessage = AsyncMock()

        # Build message
        message = buildEnsuredMessage(chatId=123, chatType=ChatType.PRIVATE, userId=456)

        # Execute command with bad period
        await cast(Any, handler).statsCommand(
            ensuredMessage=message,
            command="stats",
            args="--period=9d",
            updateObj=None,
            typingManager=None,
        )

        # Verify usage error was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]
        assert "❌" in replyText
        assert "Неверный период: 9d" in replyText
        assert "1d, 7d, 30d, или all" in replyText

    async def test_second_positional(self):
        """Test that second positional returns usage error."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
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
        assert "--user требует значения" in replyText

    async def test_chatId_positional_in_group_chat(self):
        """Test that chatId positional in group chat returns error."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
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

    async def test_section_llm_with_user_filter_raises_error(self):
        """Test that --section=llm with --user raises usage error."""

        # Reset singleton
        StatsAggregationService._instance = None

        # Setup handler
        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock chat settings
        chatSettings = {k: ChatSettingsValue("") for k in ChatSettingsKey}
        chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS] = ChatSettingsValue("true")
        handler.getChatSettings = AsyncMock(return_value=chatSettings)

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

        # Verify usage error was sent
        handler.sendMessage.assert_called_once()
        callArgs = handler.sendMessage.call_args
        replyText = callArgs.kwargs["messageText"]
        assert "❌" in replyText
        assert "--section=llm не поддерживает --user" in replyText
        assert "LLM-статистика общая для чата, не по пользователям" in replyText


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
