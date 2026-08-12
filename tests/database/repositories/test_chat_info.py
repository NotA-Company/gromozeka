"""Tests for :class:`ChatInfoRepository`.

Covers the chat information repository methods including upsert behavior,
bot_status preservation, and retrieval operations. Uses the shared
``testDatabase`` fixture from ``tests/conftest.py`` so each test gets a
fresh in-memory SQLite database with all migrations applied — no mocks.
"""

import datetime

from internal.database import Database
from internal.database.models import ChatBotStatus


class TestUpdateChatInfoNonClobber:
    """Regression test for updateChatInfo bot_status preservation.

    The non-clobber invariant is critical: updateChatInfo's upsert must NOT
    reset bot_status to 'active' when updating title/username. The upsert
    excludes bot_status from both values and updateExpressions, so an
    existing INACCESSIBLE chat stays INACCESSIBLE after metadata updates.
    This behavior is load-bearing — it prevents reactivating dead chats when
    their metadata is refreshed.
    """

    async def test_updateChatInfo_nonClobberPreservesBotStatus(self, testDatabase: Database) -> None:
        """updateChatInfo does not clobber bot_status on existing rows.

        When a chat with bot_status='inaccessible' is updated via
        updateChatInfo (which only passes type/title/username/is_forum),
        the bot_status field must remain 'inaccessible'. The upsert excludes
        bot_status from both the INSERT and UPDATE clauses.

        Args:
            testDatabase: Fresh in-memory Database fixture.
        """
        # Arrange: Insert a chat with INACCESSIBLE bot_status
        await testDatabase.chatInfo.updateChatInfo(
            chatId=123,
            type="group",
            title="Old Title",
            username=None,
            isForum=False,
        )

        # Manually set bot_status to INACCESSIBLE (simulating a probe failure)
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            """
            UPDATE chat_info
            SET bot_status = :botStatus
            WHERE chat_id = :chatId
            """,
            {"botStatus": ChatBotStatus.INACCESSIBLE, "chatId": 123},
        )

        # Act: Update the chat info via updateChatInfo (does NOT pass bot_status)
        await testDatabase.chatInfo.updateChatInfo(
            chatId=123,
            type="group",
            title="New Title",
            username="newusername",
            isForum=True,
        )

        # Assert: bot_status is still INACCESSIBLE (not reset to ACTIVE)
        chatInfo = await testDatabase.chatInfo.getChatInfo(123)
        assert chatInfo is not None
        assert chatInfo.get("bot_status") == ChatBotStatus.INACCESSIBLE

        # Assert: Other fields were updated
        assert chatInfo["title"] == "New Title"
        assert chatInfo["username"] == "newusername"
        assert chatInfo["is_forum"] is True

    async def test_updateChatInfo_newRowDefaultsBotStatusToActive(self, testDatabase: Database) -> None:
        """updateChatInfo on a new chat defaults bot_status to 'active'.

        The bot_status column has a default value of 'active' in the schema
        (migration 026), so newly inserted chats start as ACTIVE unless
        explicitly set otherwise.

        Args:
            testDatabase: Fresh in-memory Database fixture.
        """
        # Act: Insert a new chat via updateChatInfo (does NOT pass bot_status)
        await testDatabase.chatInfo.updateChatInfo(
            chatId=456,
            type="private",
            title="Private Chat",
            username=None,
            isForum=False,
        )

        # Assert: bot_status defaults to ACTIVE
        chatInfo = await testDatabase.chatInfo.getChatInfo(456)
        assert chatInfo is not None
        assert chatInfo.get("bot_status") == ChatBotStatus.ACTIVE
        assert chatInfo["title"] == "Private Chat"


class TestGetChatInfo:
    """Tests for getChatInfo retrieval behavior."""

    async def test_getChatInfo_returnsChatInfoDict(self, testDatabase: Database) -> None:
        """getChatInfo returns a complete ChatInfoDict for existing chats.

        Args:
            testDatabase: Fresh in-memory Database fixture.
        """
        # Arrange: Insert a chat
        await testDatabase.chatInfo.updateChatInfo(
            chatId=789,
            type="supergroup",
            title="Super Group",
            username="supergroup",
            isForum=True,
        )

        # Act: Retrieve the chat info
        chatInfo = await testDatabase.chatInfo.getChatInfo(789)

        # Assert: All fields are present and correct
        assert chatInfo is not None
        assert chatInfo["chat_id"] == 789
        assert chatInfo["type"] == "supergroup"
        assert chatInfo["title"] == "Super Group"
        assert chatInfo["username"] == "supergroup"
        assert chatInfo["is_forum"] is True
        assert chatInfo.get("bot_status") == ChatBotStatus.ACTIVE
        assert isinstance(chatInfo["created_at"], datetime.datetime)
        assert isinstance(chatInfo["updated_at"], datetime.datetime)

    async def test_getChatInfo_returnsNoneForNonexistentChat(self, testDatabase: Database) -> None:
        """getChatInfo returns None when chat_id does not exist.

        Args:
            testDatabase: Fresh in-memory Database fixture.
        """
        # Act: Try to retrieve a non-existent chat
        chatInfo = await testDatabase.chatInfo.getChatInfo(999)

        # Assert: None is returned
        assert chatInfo is None

    async def test_getChatInfo_withDataSource(self, testDatabase: Database) -> None:
        """getChatInfo respects the dataSource parameter for routing.

        The dataSource parameter is passed to the provider for explicit
        routing to a specific data source.

        Args:
            testDatabase: Fresh in-memory Database fixture.
        """
        # Arrange: Insert a chat
        await testDatabase.chatInfo.updateChatInfo(
            chatId=111,
            type="channel",
            title="Test Channel",
            username="testchannel",
            isForum=False,
        )

        # Act: Retrieve with dataSource parameter
        chatInfo = await testDatabase.chatInfo.getChatInfo(111, dataSource="default")

        # Assert: Chat info is returned correctly
        assert chatInfo is not None
        assert chatInfo["chat_id"] == 111
        assert chatInfo["type"] == "channel"


class TestUpdateChatInfoUpsert:
    """Tests for updateChatInfo upsert behavior (insert vs update)."""

    async def test_updateChatInfo_insertsNewRow(self, testDatabase: Database) -> None:
        """updateChatInfo inserts a new row when chat_id does not exist.

        Args:
            testDatabase: Fresh in-memory Database fixture.
        """
        # Arrange: No chat with chatId=222 exists

        # Act: Insert a new chat
        result = await testDatabase.chatInfo.updateChatInfo(
            chatId=222,
            type="group",
            title="New Group",
            username="newgroup",
            isForum=False,
        )

        # Assert: Insertion succeeded
        assert result is True

        # Assert: Chat can be retrieved
        chatInfo = await testDatabase.chatInfo.getChatInfo(222)
        assert chatInfo is not None
        assert chatInfo["title"] == "New Group"

    async def test_updateChatInfo_updatesExistingRow(self, testDatabase: Database) -> None:
        """updateChatInfo updates an existing row when chat_id exists.

        Args:
            testDatabase: Fresh in-memory Database fixture.
        """
        # Arrange: Insert a chat
        await testDatabase.chatInfo.updateChatInfo(
            chatId=333,
            type="group",
            title="Original Title",
            username="original",
            isForum=False,
        )

        # Get original updated_at for comparison
        originalInfo = await testDatabase.chatInfo.getChatInfo(333)
        originalUpdatedAt = originalInfo["updated_at"] if originalInfo else None

        # Give time for timestamp to differ
        import asyncio

        await asyncio.sleep(0.01)

        # Act: Update the same chat
        result = await testDatabase.chatInfo.updateChatInfo(
            chatId=333,
            type="group",
            title="Updated Title",
            username="updated",
            isForum=True,
        )

        # Assert: Update succeeded
        assert result is True

        # Assert: Fields were updated
        chatInfo = await testDatabase.chatInfo.getChatInfo(333)
        assert chatInfo is not None
        assert chatInfo["title"] == "Updated Title"
        assert chatInfo["username"] == "updated"
        assert chatInfo["is_forum"] is True

        # Assert: updated_at was bumped (if we had a timestamp that differs)
        # Note: This might be flaky depending on timestamp resolution
        if originalUpdatedAt:
            assert chatInfo["updated_at"] >= originalUpdatedAt

    async def test_updateChatInfo_handlesNoneValues(self, testDatabase: Database) -> None:
        """updateChatInfo correctly handles None values for optional fields.

        Args:
            testDatabase: Fresh in-memory Database fixture.
        """
        # Arrange: Insert a chat with all fields set
        await testDatabase.chatInfo.updateChatInfo(
            chatId=444,
            type="group",
            title="Title",
            username="username",
            isForum=True,
        )

        # Act: Update with None values for optional fields
        result = await testDatabase.chatInfo.updateChatInfo(
            chatId=444,
            type="group",
            title=None,
            username=None,
            isForum=False,
        )

        # Assert: Update succeeded
        assert result is True

        # Assert: Fields were set to None
        chatInfo = await testDatabase.chatInfo.getChatInfo(444)
        assert chatInfo is not None
        assert chatInfo["title"] is None
        assert chatInfo["username"] is None
        assert chatInfo["is_forum"] is False


class TestUpdateChatInfoBotStatus:
    """Tests for updateChatInfo bot_status parameter behavior."""

    async def test_updateChatInfo_withBotStatus_writesIt(self, testDatabase: Database) -> None:
        """updateChatInfo with botStatus writes the provided value to the DB.

        When botStatus is provided, it must be included in both the INSERT and
        UPDATE clauses of the upsert, so the status change persists.

        Args:
            testDatabase: Fresh in-memory Database fixture.
        """
        # Arrange: Insert a chat (defaults to ACTIVE)
        await testDatabase.chatInfo.updateChatInfo(
            chatId=123,
            type="group",
            title="Test Group",
            username=None,
            isForum=False,
        )

        # Act: Update with botStatus=INACCESSIBLE
        await testDatabase.chatInfo.updateChatInfo(
            chatId=123,
            type="group",
            title="Test Group",
            username=None,
            isForum=False,
            botStatus=ChatBotStatus.INACCESSIBLE,
        )

        # Assert: bot_status is now INACCESSIBLE
        chatInfo = await testDatabase.chatInfo.getChatInfo(123)
        assert chatInfo is not None
        assert chatInfo.get("bot_status") == ChatBotStatus.INACCESSIBLE

    async def test_updateChatInfo_withBotStatus_activeFlipsBack(self, testDatabase: Database) -> None:
        """updateChatInfo with botStatus flips status back to ACTIVE.

        When a chat is INACCESSIBLE and updateChatInfo is called with
        botStatus=ACTIVE, the DB value must be flipped to "active".

        Args:
            testDatabase: Fresh in-memory Database fixture.
        """
        # Arrange: Insert a chat and set it to INACCESSIBLE
        await testDatabase.chatInfo.updateChatInfo(
            chatId=456,
            type="group",
            title="Test Group",
            username=None,
            isForum=False,
            botStatus=ChatBotStatus.INACCESSIBLE,
        )

        # Act: Flip back to ACTIVE
        await testDatabase.chatInfo.updateChatInfo(
            chatId=456,
            type="group",
            title="Test Group",
            username=None,
            isForum=False,
            botStatus=ChatBotStatus.ACTIVE,
        )

        # Assert: bot_status is now ACTIVE
        chatInfo = await testDatabase.chatInfo.getChatInfo(456)
        assert chatInfo is not None
        assert chatInfo.get("bot_status") == ChatBotStatus.ACTIVE

    async def test_updateChatInfo_insertWithBotStatus(self, testDatabase: Database) -> None:
        """updateChatInfo on a new chat with botStatus writes the provided value.

        When updateChatInfo is called on a non-existent chat WITH a botStatus
        parameter, the inserted row must have the specified bot_status (not
        the schema default 'active').

        Args:
            testDatabase: Fresh in-memory Database fixture.
        """
        # Act: Insert a new chat WITH botStatus=INACCESSIBLE
        await testDatabase.chatInfo.updateChatInfo(
            chatId=789,
            type="group",
            title="New Group",
            username=None,
            isForum=False,
            botStatus=ChatBotStatus.INACCESSIBLE,
        )

        # Assert: The inserted row has bot_status='inaccessible'
        chatInfo = await testDatabase.chatInfo.getChatInfo(789)
        assert chatInfo is not None
        assert chatInfo.get("bot_status") == ChatBotStatus.INACCESSIBLE
        assert chatInfo["title"] == "New Group"
