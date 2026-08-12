"""Tests for ChatInfoRepository status methods.

Tests for:
- setChatBotStatus: Conditional UPDATE to set bot accessibility status
- getInactiveChatIds: Read-only query for INACCESSIBLE chats
- updateChatInfo non-clobber: Verify bot_status is preserved during refresh

Uses the shared testDatabase fixture from tests/conftest.py so each test
gets a fresh in-memory SQLite database with all migrations applied — no mocks.
"""

import logging

from internal.database import Database
from internal.database.models import ChatBotStatus

logger = logging.getLogger(__name__)


class TestChatBotStatusMethods:
    """Test bot_status read/write methods in ChatInfoRepository."""

    async def test_setChatBotStatus_flipsStatus(self, testDatabase: Database) -> None:
        """setChatBotStatus flips ACTIVE -> INACCESSIBLE -> ACTIVE."""
        # First insert a chat with default ACTIVE status
        await testDatabase.chatInfo.updateChatInfo(
            chatId=99991,
            type="group",
            title="Test Chat",
            username="testchat",
            isForum=False,
        )

        # Verify default status is ACTIVE
        chatInfo = await testDatabase.chatInfo.getChatInfo(99991)
        assert chatInfo is not None, "Chat should exist after updateChatInfo"
        assert chatInfo.get("bot_status") == ChatBotStatus.ACTIVE.value, "Default status should be ACTIVE"

        # Flip to INACCESSIBLE
        result = await testDatabase.chatInfo.setChatBotStatus(99991, ChatBotStatus.INACCESSIBLE)
        assert result is True, "setChatBotStatus should return True when status changes"

        chatInfo = await testDatabase.chatInfo.getChatInfo(99991)
        assert chatInfo is not None
        assert chatInfo.get("bot_status") == ChatBotStatus.INACCESSIBLE.value, "Status should be INACCESSIBLE"

        # Flip back to ACTIVE
        result = await testDatabase.chatInfo.setChatBotStatus(99991, ChatBotStatus.ACTIVE)
        assert result is True, "setChatBotStatus should return True when status changes back"

        chatInfo = await testDatabase.chatInfo.getChatInfo(99991)
        assert chatInfo is not None
        assert chatInfo.get("bot_status") == ChatBotStatus.ACTIVE.value, "Status should be ACTIVE again"

    async def test_setChatBotStatus_noopWhenAlreadyTarget(self, testDatabase: Database) -> None:
        """setChatBotStatus returns True when status is already the target (chat exists)."""
        # Insert a chat and set to INACCESSIBLE
        await testDatabase.chatInfo.updateChatInfo(
            chatId=99992,
            type="group",
            title="Test Chat",
            username="testchat2",
            isForum=False,
        )
        await testDatabase.chatInfo.setChatBotStatus(99992, ChatBotStatus.INACCESSIBLE)

        # Calling again with same status should return True (chat exists, is at target)
        result = await testDatabase.chatInfo.setChatBotStatus(99992, ChatBotStatus.INACCESSIBLE)
        assert result is True, "setChatBotStatus should return True when chat exists and is at target status"

        # Status should still be INACCESSIBLE
        chatInfo = await testDatabase.chatInfo.getChatInfo(99992)
        assert chatInfo is not None
        assert chatInfo.get("bot_status") == ChatBotStatus.INACCESSIBLE.value

    async def test_setChatBotStatus_returnsFalseForNonexistentChat(self, testDatabase: Database) -> None:
        """setChatBotStatus returns False for a chat that doesn't exist."""
        result = await testDatabase.chatInfo.setChatBotStatus(99999, ChatBotStatus.INACCESSIBLE)
        assert result is False, "setChatBotStatus should return False for non-existent chat"

    async def test_getInactiveChatIds_returnsInaccessibleChats(self, testDatabase: Database) -> None:
        """getInactiveChatIds returns only INACCESSIBLE chats."""
        # Insert three chats with different statuses
        await testDatabase.chatInfo.updateChatInfo(
            chatId=10001, type="group", title="Chat 1", username="chat1", isForum=False
        )
        await testDatabase.chatInfo.updateChatInfo(
            chatId=10002, type="group", title="Chat 2", username="chat2", isForum=False
        )
        await testDatabase.chatInfo.updateChatInfo(
            chatId=10003, type="group", title="Chat 3", username="chat3", isForum=False
        )

        # Mark chat 2 as INACCESSIBLE
        await testDatabase.chatInfo.setChatBotStatus(10002, ChatBotStatus.INACCESSIBLE)

        # getInactiveChatIds should only return chat 10002
        inactiveChats = await testDatabase.chatInfo.getInactiveChatIds()
        chatIds = [chat["chat_id"] for chat in inactiveChats]
        assert chatIds == [10002], "Should only return INACCESSIBLE chat"

    async def test_getInactiveChatIds_returnsEmptyWhenNone(self, testDatabase: Database) -> None:
        """getInactiveChatIds returns empty list when no INACCESSIBLE chats."""
        # Insert chats, leave them as ACTIVE (default)
        await testDatabase.chatInfo.updateChatInfo(
            chatId=10004, type="group", title="Chat 4", username="chat4", isForum=False
        )
        await testDatabase.chatInfo.updateChatInfo(
            chatId=10005, type="group", title="Chat 5", username="chat5", isForum=False
        )

        inactiveChats = await testDatabase.chatInfo.getInactiveChatIds()
        assert inactiveChats == [], "Should return empty list when no INACCESSIBLE chats"

    async def test_updateChatInfo_nonClobberPreservesBotStatus(self, testDatabase: Database) -> None:
        """updateChatInfo does NOT clobber bot_status during refresh (non-clobber invariant).

        This is the critical regression test for §3.4 of the design doc.
        The accessibility subsystem owns the bot_status column; the routine
        chat-info refresh path must not touch it. This test pins that
        invariant: marking a chat INACCESSIBLE, then calling the normal
        every-message upsert, should leave it INACCESSIBLE.
        """
        # Insert a chat
        await testDatabase.chatInfo.updateChatInfo(
            chatId=10006,
            type="group",
            title="Original Title",
            username="original",
            isForum=False,
        )

        # Mark it INACCESSIBLE
        await testDatabase.chatInfo.setChatBotStatus(10006, ChatBotStatus.INACCESSIBLE)

        # Verify it's INACCESSIBLE
        chatInfo = await testDatabase.chatInfo.getChatInfo(10006)
        assert chatInfo is not None
        assert chatInfo.get("bot_status") == ChatBotStatus.INACCESSIBLE.value

        # Call updateChatInfo (the routine refresh path that happens on every message)
        await testDatabase.chatInfo.updateChatInfo(
            chatId=10006,
            type="group",
            title="Updated Title",
            username="updated",
            isForum=False,
        )

        # Verify bot_status is STILL INACCESSIBLE (non-clobber invariant)
        chatInfo = await testDatabase.chatInfo.getChatInfo(10006)
        assert chatInfo is not None
        assert (
            chatInfo.get("bot_status") == ChatBotStatus.INACCESSIBLE.value
        ), "updateChatInfo must NOT reset bot_status to ACTIVE (non-clobber invariant)"

        # Other fields should be updated though
        assert chatInfo.get("title") == "Updated Title"
        assert chatInfo.get("username") == "updated"
