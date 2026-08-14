"""Tests for command stats recording in HandlersManager.handleCommand.

These tests verify that:
    - Command stats are recorded exactly once on successful execution
    - Command stats with is_error=1 are recorded when handlers raise
    - No stats are recorded for permission-denied commands
    - No stats are recorded for category-denied commands
    - No stats are recorded for unknown/missing commands
    - NullStatsStorage works as a no-op
    - Owner-only commands are recorded when executed
    - Stats contain the correct metrics and labels per the D5 spec
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from internal.bot.common.handlers.base import BaseBotHandler
from internal.bot.common.handlers.manager import (
    CommandHandlerInfoV2,
    HandlerParallelism,
    HandlersManager,
)
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    CommandCategory,
    CommandPermission,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
)
from lib.stats import NullStatsStorage, StatsStorage


def _makeEnsuredMessage(
    *,
    chatId: int = 100,
    messageId: int = 42,
    userId: int = 7,
    senderName: str = "Alice",
) -> EnsuredMessage:
    """Build a minimal EnsuredMessage for command tests.

    Args:
        chatId: Recipient chat id.
        messageId: Originating message id.
        userId: Sender user id.
        senderName: Sender name.

    Returns:
        Fully constructed EnsuredMessage.
    """
    return EnsuredMessage(
        sender=MessageSender(id=userId, name=senderName, username=f"@user{userId}"),
        recipient=MessageRecipient(id=chatId, chatType=ChatType.PRIVATE),
        messageId=messageId,
        date=datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc),
        messageText="",
    )


class TestCommandStatsRecording:
    """Tests for command event recording via commandStatsStorage.

    These tests verify the D5 contract: stats are recorded after execution
    with is_error=0 on success and is_error=1 on exception. Permission-denied
    and not-a-command early returns produce no recording.
    """

    @pytest.fixture
    def mockCommandHandler(self) -> BaseBotHandler:
        """Build a minimal mock command handler that succeeds.

        Returns:
            A BaseBotHandler subclass with a no-op command method.
        """

        class MockHandler(BaseBotHandler):
            async def testCommand(
                self, ensuredMessage: EnsuredMessage, command: str, args: str, updateObj, typingManager
            ) -> None:
                """No-op command handler."""
                pass

        # Mock configManager methods to avoid coroutine issues
        configManager = Mock()
        configManager.getBotConfig = Mock(return_value={})
        configManager.getSttConfig = Mock(return_value={"enabled": False})

        handler = MockHandler(
            configManager=configManager,
            database=Mock(),
            botProvider=BotProvider.TELEGRAM,
        )
        # Mock the required methods
        handler.isAdmin = AsyncMock(return_value=False)
        handler.getChatSettings = AsyncMock(
            return_value={
                ChatSettingsKey.DELETE_DENIED_COMMANDS: ChatSettingsValue("false"),
                ChatSettingsKey.ALLOW_TOOLS_COMMANDS: ChatSettingsValue("false"),
                ChatSettingsKey.ALLOW_USER_SPAM_COMMAND: ChatSettingsValue("false"),
            }
        )
        handler.saveChatMessage = AsyncMock()
        handler.getBotUserName = AsyncMock(return_value="testbot")
        handler.sendMessage = AsyncMock(return_value=[])  # Mock sendMessage to avoid bot initialization errors

        return handler

    @pytest.fixture
    def mockHandlerManager(self, mockCommandHandler: BaseBotHandler) -> HandlersManager:
        """Build a minimal HandlersManager with a registered command.

        Args:
            mockCommandHandler: Mock handler to register.

        Returns:
            HandlersManager with a single command registered.
        """
        # Use __new__ to avoid the full __init__ which constructs all handlers
        manager = HandlersManager.__new__(HandlersManager)
        manager.db = AsyncMock()
        manager.configManager = AsyncMock()
        manager.botProvider = BotProvider.TELEGRAM
        manager.messageStatsStorage = NullStatsStorage()
        manager.commandStatsStorage = NullStatsStorage()
        manager.handlerTimeout = 60 * 30
        # Add mock handlers list so parseCommand works
        manager.handlers = [(mockCommandHandler, HandlerParallelism.SEQUENTIAL)]

        # Register the mock command
        info = CommandHandlerInfoV2(
            commands=["test"],
            shortDescription="Test command",
            helpMessage="Test command help",
            visibility=None,
            availableFor={CommandPermission.DEFAULT},
            category=CommandCategory.PRIVATE,
            typingAction=None,
            replyErrorOnException=True,
            handler=mockCommandHandler.testCommand,  # type: ignore[attr-defined]
        )
        info.boundHandler = mockCommandHandler.testCommand.__get__(  # type: ignore[attr-defined]
            mockCommandHandler, type(mockCommandHandler)
        )
        manager._commands = {"test": info}

        return manager

    async def testSuccessfulCommandRecordsOnce(self, mockHandlerManager: HandlersManager) -> None:
        """Successful command execution records stats exactly once with is_error=0.

        Args:
            mockHandlerManager: Minimal HandlersManager fixture.
        """
        mockStatsStorage = AsyncMock(spec=StatsStorage)
        mockHandlerManager.commandStatsStorage = mockStatsStorage

        ensuredMessage = _makeEnsuredMessage(userId=7, chatId=100)
        ensuredMessage.messageText = "/test"

        result = await mockHandlerManager.handleCommand(ensuredMessage, AsyncMock())

        assert result is True
        mockStatsStorage.record.assert_awaited_once_with(
            stats={"command_count": 1, "is_error": 0},
            consumerId="100",
            labels={"user_id": "7", "commandName": "test"},
        )

    async def testRaisingCommandRecordsIsErrorOne(self, mockHandlerManager: HandlersManager) -> None:
        """Command handler raising exception records stats with is_error=1.

        Args:
            mockHandlerManager: Minimal HandlersManager fixture.
        """
        # Replace the handler method with one that raises
        handler = mockHandlerManager.handlers[0][0]  # (handler, parallelism)

        # Replace with an async method that raises
        async def raisingCommand(
            self, ensuredMessage: EnsuredMessage, command: str, args: str, updateObj, typingManager
        ) -> None:
            raise RuntimeError("handler error")

        # Update both the instance method and the boundHandler
        handler.testCommand = raisingCommand  # type: ignore[attr-defined]
        mockHandlerManager._commands["test"].boundHandler = raisingCommand.__get__(  # type: ignore[attr-defined]
            handler, type(handler)
        )

        mockStatsStorage = AsyncMock(spec=StatsStorage)
        mockHandlerManager.commandStatsStorage = mockStatsStorage

        ensuredMessage = _makeEnsuredMessage(userId=7, chatId=100)
        ensuredMessage.messageText = "/test"

        result = await mockHandlerManager.handleCommand(ensuredMessage, AsyncMock())

        assert result is False
        mockStatsStorage.record.assert_awaited_once_with(
            stats={"command_count": 1, "is_error": 1},
            consumerId="100",
            labels={"user_id": "7", "commandName": "test"},
        )

    async def testPermissionDeniedNoRecord(self, mockHandlerManager: HandlersManager) -> None:
        """Permission-denied commands return False without recording stats.

        Args:
            mockHandlerManager: Minimal HandlersManager fixture.
        """
        # Make the handler return False for admin check (permission denied)
        handler = mockHandlerManager._commands["test"].boundHandler.__self__  # type: ignore[union-attr]
        handler.isAdmin = AsyncMock(return_value=False)

        # Make the command require BOT_OWNER permission
        info = mockHandlerManager._commands["test"]
        info.availableFor = {CommandPermission.BOT_OWNER}

        mockStatsStorage = AsyncMock(spec=StatsStorage)
        mockHandlerManager.commandStatsStorage = mockStatsStorage

        ensuredMessage = _makeEnsuredMessage(userId=7, chatId=100)
        ensuredMessage.messageText = "/test"

        result = await mockHandlerManager.handleCommand(ensuredMessage, AsyncMock())

        assert result is False
        mockStatsStorage.record.assert_not_awaited()

    async def testCategoryDeniedNoRecord(self, mockHandlerManager: HandlersManager) -> None:
        """Category-denied commands return False without recording stats.

        A PRIVATE command invoked in a GROUP chat is rejected at the category gate
        before execution, so no stats should be recorded.

        Args:
            mockHandlerManager: Minimal HandlersManager fixture.
        """
        # The mock command is already PRIVATE (set in mockHandlerManager fixture)
        # Send it from a GROUP chat
        mockStatsStorage = AsyncMock(spec=StatsStorage)
        mockHandlerManager.commandStatsStorage = mockStatsStorage

        ensuredMessage = _makeEnsuredMessage(userId=7, chatId=100)
        ensuredMessage.recipient = MessageRecipient(
            id=100,
            chatType=ChatType.GROUP,  # GROUP chat, not PRIVATE
        )
        ensuredMessage.messageText = "/test"

        result = await mockHandlerManager.handleCommand(ensuredMessage, AsyncMock())

        # Command is denied at the category gate (lines 1000-1026 in manager.py)
        assert result is False
        # Verify record was NOT awaited
        mockStatsStorage.record.assert_not_awaited()

    async def testNotACommandNoRecord(self, mockHandlerManager: HandlersManager) -> None:
        """Messages without commands return None without recording stats.

        Args:
            mockHandlerManager: Minimal HandlersManager fixture.
        """
        mockStatsStorage = AsyncMock(spec=StatsStorage)
        mockHandlerManager.commandStatsStorage = mockStatsStorage

        ensuredMessage = _makeEnsuredMessage(userId=7, chatId=100)
        ensuredMessage.messageText = "not a command"

        result = await mockHandlerManager.handleCommand(ensuredMessage, AsyncMock())

        assert result is None
        mockStatsStorage.record.assert_not_awaited()

    async def testUnknownCommandNoRecord(self, mockHandlerManager: HandlersManager) -> None:
        """Unknown commands return None without recording stats.

        Args:
            mockHandlerManager: Minimal HandlersManager fixture.
        """
        mockStatsStorage = AsyncMock(spec=StatsStorage)
        mockHandlerManager.commandStatsStorage = mockStatsStorage

        ensuredMessage = _makeEnsuredMessage(userId=7, chatId=100)
        ensuredMessage.messageText = "/unknown"

        result = await mockHandlerManager.handleCommand(ensuredMessage, AsyncMock())

        assert result is None
        mockStatsStorage.record.assert_not_awaited()

    async def testNullStatsStorageNoOp(self, mockHandlerManager: HandlersManager) -> None:
        """NullStatsStorage is a no-op; command execution proceeds normally.

        Args:
            mockHandlerManager: Minimal HandlersManager fixture.
        """
        # Use the actual NullStatsStorage (default)
        mockHandlerManager.commandStatsStorage = NullStatsStorage()

        ensuredMessage = _makeEnsuredMessage(userId=7, chatId=100)
        ensuredMessage.messageText = "/test"

        # Should not raise, should return True
        result = await mockHandlerManager.handleCommand(ensuredMessage, AsyncMock())
        assert result is True

    async def testOwnerOnlyCommandExecutedAndRecorded(self, mockHandlerManager: HandlersManager) -> None:
        """Owner-only command executed when permitted is recorded with correct labels.

        Args:
            mockHandlerManager: Minimal HandlersManager fixture.
        """
        # Make the handler return True for admin check (owner)
        handler = mockHandlerManager._commands["test"].boundHandler.__self__  # type: ignore[union-attr]
        handler.isAdmin = AsyncMock(return_value=True)

        # Make the command require BOT_OWNER permission
        info = mockHandlerManager._commands["test"]
        info.availableFor = {CommandPermission.BOT_OWNER}

        mockStatsStorage = AsyncMock(spec=StatsStorage)
        mockHandlerManager.commandStatsStorage = mockStatsStorage

        ensuredMessage = _makeEnsuredMessage(userId=999, chatId=100)
        ensuredMessage.messageText = "/test"

        result = await mockHandlerManager.handleCommand(ensuredMessage, AsyncMock())

        assert result is True
        mockStatsStorage.record.assert_awaited_once_with(
            stats={"command_count": 1, "is_error": 0},
            consumerId="100",
            labels={"user_id": "999", "commandName": "test"},
        )
