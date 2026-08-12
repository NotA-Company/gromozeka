"""Tests for CommonHandler commands including /list_chats with botStatus filtering.

The /list_chats command lists chats where the bot has seen the user. Bot owners
can use the 'all' parameter to see all chats, including those marked INACCESSIBLE.
This test class verifies that the botStatus=None parameter is correctly passed
on the owner-only 'all' branch.
"""

import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from internal.bot.common.handlers.common import CommonHandler
from internal.bot.models import (
    BotProvider,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
)
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import ChatBotStatus


class TestListChatsBotStatusFilter:
    """Tests for /list_chats with botStatus filtering (owner vs non-owner).

    The bot-owner /list_chats all branch passes botStatus=None to include
    INACCESSIBLE chats. Non-owner /list_chats (non-all) uses the default
    ACTIVE-only filter.
    """

    @pytest.fixture
    def mockDb(self) -> Mock:
        """Build a Database stub.

        Returns:
            Mock: A ``Database`` with mocked chatUsers methods.
        """
        db = Mock(spec=Database)
        db.chatUsers = Mock()
        db.chatUsers.getAllGroupChats = AsyncMock(return_value=[])  # type: ignore[method-assign]
        db.chatUsers.getUserChats = AsyncMock(return_value=[])  # type: ignore[method-assign]
        return db

    @pytest.fixture
    def mockConfig(self) -> Mock:
        """Build a ConfigManager stub.

        Returns:
            Mock: A ``ConfigManager`` with required methods mocked.
        """
        cm = Mock(spec=ConfigManager)
        cm.getBotConfig.return_value = {"token": "test_token", "owners": [123456]}
        return cm

    @pytest.fixture
    def handler(self, mockDb: Mock, mockConfig: Mock) -> CommonHandler:
        """Build a CommonHandler instance for testing.

        Args:
            mockDb: Mocked database.
            mockConfig: Mocked config manager.

        Returns:
            CommonHandler: Handler instance with mocked dependencies.
        """
        handler = CommonHandler(configManager=mockConfig, database=mockDb, botProvider=BotProvider.TELEGRAM)
        # Mock bot initialization to avoid ValueError.
        handler._bot = Mock()
        return handler

    async def test_listChats_ownerAll_includesInaccessible(self, handler: CommonHandler) -> None:
        """Bot owner issuing /list_chats all sees INACCESSIBLE chats.

        The listAll branch (gated on isBotOwner) passes botStatus=None to
        getAllGroupChats, so all chats including INACCESSIBLE are included.

        Args:
            handler: CommonHandler fixture.
        """
        # Mock isBotOwner to return True for the owner user.
        handler.isBotOwner = Mock(return_value=True)  # type: ignore[method-assign]

        # Mock sendMessage to avoid bot initialization check.
        handler.sendMessage = AsyncMock(return_value=[])  # type: ignore[method-assign]

        # Return empty list for all chats (load-bearing test is the botStatus=None assertion).
        handler.db.chatUsers.getAllGroupChats = AsyncMock(return_value=[])  # type: ignore[method-assign]

        # Create an /list_chats all command from a bot owner (id matches config owners).
        ownerSender = MessageSender(id=123456, name="Owner User", username="owner")
        ensuredMessage = EnsuredMessage(
            sender=ownerSender,
            recipient=MessageRecipient(id=123456, chatType=ChatType.PRIVATE),
            messageId=1,
            date=datetime.datetime.now(tz=datetime.timezone.utc),
            messageText="/list_chats all",
        )
        updateObj = Mock()

        # Execute the command.
        await handler.list_chats_command(ensuredMessage, "list_chats", "all", updateObj, None)

        # Verify getAllGroupChats was called with botStatus=None.
        handler.db.chatUsers.getAllGroupChats.assert_called_once_with(botStatus=None)  # type: ignore[attr-defined]

    async def test_listChats_nonOwner_excludesInaccessible(self, handler: CommonHandler) -> None:
        """Non-owner /list_chats (non-all) excludes INACCESSIBLE chats.

        The non-owner branch uses the default ACTIVE-only filter (botStatus
        defaults to ChatBotStatus.ACTIVE).

        Args:
            handler: CommonHandler fixture.
        """
        # Mock isBotOwner to return False for non-owner users.
        handler.isBotOwner = Mock(return_value=False)  # type: ignore[method-assign]

        # Mock sendMessage to avoid bot initialization check.
        handler.sendMessage = AsyncMock(return_value=[])  # type: ignore[method-assign]

        # Return empty list (load-bearing test is the botStatus=ACTIVE assertion).
        handler.db.chatUsers.getUserChats = AsyncMock(return_value=[])  # type: ignore[method-assign]

        # Create an /list_chats command from a non-owner user.
        normalSender = MessageSender(id=999999, name="Normal User", username="normal")
        ensuredMessage = EnsuredMessage(
            sender=normalSender,
            recipient=MessageRecipient(id=999999, chatType=ChatType.PRIVATE),
            messageId=2,
            date=datetime.datetime.now(tz=datetime.timezone.utc),
            messageText="/list_chats",
        )
        updateObj = Mock()

        # Execute the command.
        await handler.list_chats_command(ensuredMessage, "list_chats", "", updateObj, None)

        # Verify getUserChats was called with default botStatus (ACTIVE-only).
        handler.db.chatUsers.getUserChats.assert_called_once_with(
            999999, botStatus=ChatBotStatus.ACTIVE
        )  # type: ignore[attr-defined]
