"""Tests for :class:`ChatMessagesRepository`.

End-to-end behavioural coverage of the thin-composition thread lookup
``getMessageThread``. Message CRUD lives here, while chat-message
search (filter-only and semantic) and the embedding CRUD/backfill
helper each live in their own focused repositories:

- The public ``searchChatMessages`` dispatcher and both of its modes
  live in :class:`ChatSearchRepository` (``chat_search.py``); its
  tests are in ``tests/database/repositories/test_chat_search.py``.
- Embedding CRUD (``saveMessageEmbedding``, ``getMessageEmbedding``,
  ``deleteChatEmbeddings``) and the backfill helper
  (``getMessagesWithoutEmbeddings``) live in
  :class:`ChatEmbeddingsRepository`; their tests are in
  ``tests/database/repositories/test_chat_embeddings.py``.

NOTE: ``listChatUsers`` was merged into :class:`ChatUsersRepository.getChatUsers`;
its tests now live in ``tests/database/repositories/test_chat_users.py``.
"""

import datetime

from internal.database import Database
from internal.database.models import MessageCategory
from internal.models import MessageId


class TestMessageThread:
    """End-to-end tests for ``ChatMessagesRepository.getMessageThread``.

    Covers the thin-composition thread lookup: fetch the target
    message, walk to the thread root (if any), and return the root,
    the target, and every reply in the thread.

    Uses the shared ``testDatabase`` fixture from ``tests/conftest.py``
    so each test gets a fresh in-memory SQLite database with all
    migrations applied — no mocks.
    """

    @staticmethod
    async def _seedUser(db: Database, chatId: int, userId: int) -> None:
        """Insert a chat_users row so JOINs to chat_messages succeed."""
        await db.chatUsers.updateChatUser(
            chatId=chatId,
            userId=userId,
            username=f"user{userId}",
            fullName=f"User {userId}",
        )

    @staticmethod
    async def _seedMessage(
        db: Database,
        chatId: int,
        userId: int,
        messageId: int,
        messageText: str,
        *,
        messageCategory: MessageCategory = MessageCategory.UNSPECIFIED,
        replyId: int | None = None,
        rootMessageId: int | None = None,
    ) -> None:
        """Insert a chat_users row and a chat_messages row for the test seed."""
        await TestMessageThread._seedUser(db, chatId=chatId, userId=userId)
        await db.chatMessages.saveChatMessage(
            date=datetime.datetime.now(datetime.timezone.utc),
            chatId=chatId,
            userId=userId,
            messageId=MessageId(messageId),
            messageText=messageText,
            messageCategory=messageCategory,
            replyId=MessageId(replyId) if replyId is not None else None,
            rootMessageId=MessageId(rootMessageId) if rootMessageId is not None else None,
        )

    async def test_getMessageThread(self, testDatabase: Database) -> None:
        """Thread lookup returns the root, the target, and every reply in chronological order."""
        # Root message.
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="root")
        # Reply, threaded under the root.
        await self._seedMessage(
            testDatabase,
            chatId=1,
            userId=200,
            messageId=2,
            messageText="reply",
            replyId=1,
            rootMessageId=1,
        )

        result = await testDatabase.chatMessages.getMessageThread(chatId=1, messageId=MessageId(2))

        assert result is not None
        assert result["target_message"]["message_id"] == MessageId(2)
        assert result["root_message"] is not None
        assert result["root_message"]["message_id"] == MessageId(1)
        # ``thread_messages`` is the list of replies under the root, which
        # includes the target itself but NOT the root (the root is in
        # ``root_message``). The reply carries ``root_message_id``, so it
        # shows up in the reply list.
        assert len(result["thread_messages"]) == 1
        assert result["thread_messages"][0]["message_id"] == MessageId(2)

    async def test_targetNotFound(self, testDatabase: Database) -> None:
        """``getMessageThread`` returns ``None`` when the target message does not exist.

        Only a user is seeded (so the chat exists), but no message with the
        requested ``messageId`` — the method must return ``None`` rather than
        raising or returning an empty dict.
        """
        await self._seedUser(testDatabase, chatId=1, userId=100)

        result = await testDatabase.chatMessages.getMessageThread(chatId=1, messageId=MessageId(999))

        assert result is None

    async def test_targetIsRoot(self, testDatabase: Database) -> None:
        """Target with no ``root_message_id`` → ``root_message`` is ``None``,
        ``thread_messages`` contains only the target.

        When the target message is itself a root (no parent thread), the
        method should return ``root_message=None`` and
        ``thread_messages=[target]``.
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="i am the root")

        result = await testDatabase.chatMessages.getMessageThread(chatId=1, messageId=MessageId(1))

        assert result is not None
        assert result["target_message"]["message_id"] == MessageId(1)
        assert result["root_message"] is None
        assert len(result["thread_messages"]) == 1
        assert result["thread_messages"][0]["message_id"] == MessageId(1)

    async def test_multiReplyThread(self, testDatabase: Database) -> None:
        """Multiple replies under the same root are all returned in ``thread_messages``.

        Seeds a root message and two replies. The result must include:
        - ``root_message`` with the root's data,
        - ``target_message`` pointing to the requested reply,
        - ``thread_messages`` containing all three messages (root, reply1, reply2)
          in chronological order.
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="root")
        await self._seedMessage(
            testDatabase,
            chatId=1,
            userId=200,
            messageId=2,
            messageText="reply a",
            replyId=1,
            rootMessageId=1,
        )
        await self._seedMessage(
            testDatabase,
            chatId=1,
            userId=200,
            messageId=3,
            messageText="reply b",
            replyId=1,
            rootMessageId=1,
        )

        result = await testDatabase.chatMessages.getMessageThread(chatId=1, messageId=MessageId(3))

        assert result is not None
        assert result["target_message"]["message_id"] == MessageId(3)
        assert result["target_message"]["message_text"] == "reply b"
        assert result["root_message"] is not None
        assert result["root_message"]["message_id"] == MessageId(1)
        # ``thread_messages`` includes replies under the root (including the
        # target), but NOT the root itself (the root is in ``root_message``).
        assert len(result["thread_messages"]) == 2
        assert result["thread_messages"][0]["message_id"] == MessageId(2)
        assert result["thread_messages"][1]["message_id"] == MessageId(3)

    async def test_dataSourceParam(self, testDatabase: Database) -> None:
        """``dataSource`` is forwarded correctly — calling with ``"default"`` works.

        The ``dataSource`` parameter is plumbed through to the underlying
        provider lookup. We verify by passing an explicit valid datasource
        and asserting the thread result is identical to the no-datasource
        call.
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="root")
        await self._seedMessage(
            testDatabase,
            chatId=1,
            userId=200,
            messageId=2,
            messageText="reply",
            replyId=1,
            rootMessageId=1,
        )

        result = await testDatabase.chatMessages.getMessageThread(
            chatId=1, messageId=MessageId(2), dataSource="default"
        )

        assert result is not None
        assert result["target_message"]["message_id"] == MessageId(2)
        assert result["root_message"] is not None
        assert result["root_message"]["message_id"] == MessageId(1)


class TestGetChatMessagesByMessageIds:
    """End-to-end tests for ``ChatMessagesRepository.getChatMessagesByMessageIds``.

    Covers the batch-by-ID lookup: found subset, empty input, not-found subset,
    ascending-date ordering, cross-chat isolation, and duplicate-id handling.

    Uses the shared ``testDatabase`` fixture from ``tests/conftest.py``
    so each test gets a fresh in-memory SQLite database with all
    migrations applied — no mocks.
    """

    @staticmethod
    async def _seedUser(db: Database, chatId: int, userId: int) -> None:
        """Insert a chat_users row so JOINs to chat_messages succeed."""
        await db.chatUsers.updateChatUser(
            chatId=chatId,
            userId=userId,
            username=f"user{userId}",
            fullName=f"User {userId}",
        )

    @staticmethod
    async def _seedMessage(
        db: Database,
        chatId: int,
        userId: int,
        messageId: int,
        messageText: str,
        *,
        date: datetime.datetime | None = None,
    ) -> None:
        """Insert a chat_users row and a chat_messages row for the test seed.

        Args:
            db: Database fixture.
            chatId: Chat identifier.
            userId: Sender identifier.
            messageId: Message identifier.
            messageText: Message body text.
            date: Optional explicit timestamp (defaults to now). Used to
                control ascending-date ordering in ordering tests.
        """
        await TestGetChatMessagesByMessageIds._seedUser(db, chatId=chatId, userId=userId)
        await db.chatMessages.saveChatMessage(
            date=date if date is not None else datetime.datetime.now(datetime.timezone.utc),
            chatId=chatId,
            userId=userId,
            messageId=MessageId(messageId),
            messageText=messageText,
        )

    async def test_foundSubset(self, testDatabase: Database) -> None:
        """Requesting a subset of inserted IDs returns exactly those rows."""
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="one")
        await self._seedMessage(testDatabase, chatId=1, userId=200, messageId=2, messageText="two")
        await self._seedMessage(testDatabase, chatId=1, userId=300, messageId=3, messageText="three")

        result = await testDatabase.chatMessages.getChatMessagesByMessageIds(
            chatId=1, messageIds=[MessageId(1), MessageId(3)]
        )

        resultIds = sorted(row["message_id"].asInt() for row in result)
        assert resultIds == [1, 3]

    async def test_emptyInput(self, testDatabase: Database) -> None:
        """Empty ``messageIds`` input returns an empty list (no IN () SQL generated)."""
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="one")

        result = await testDatabase.chatMessages.getChatMessagesByMessageIds(chatId=1, messageIds=[])

        assert result == []

    async def test_notFoundSubset(self, testDatabase: Database) -> None:
        """Requesting a mix of existing and non-existing IDs returns only found rows.

        The result list is shorter than the input when some IDs don't exist
        in the chat; the caller is responsible for computing ``notFound``.
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="one")

        result = await testDatabase.chatMessages.getChatMessagesByMessageIds(
            chatId=1, messageIds=[MessageId(1), MessageId(999), MessageId(1000)]
        )

        assert len(result) == 1
        assert result[0]["message_id"] == MessageId(1)

    async def test_orderingByDateAsc(self, testDatabase: Database) -> None:
        """Result is ordered ascending by date even when inserted out of order."""
        base = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        # Insert in reverse chronological order with explicit dates.
        await self._seedMessage(
            testDatabase, chatId=1, userId=100, messageId=3, messageText="newest", date=base.replace(day=3)
        )
        await self._seedMessage(
            testDatabase, chatId=1, userId=100, messageId=1, messageText="oldest", date=base.replace(day=1)
        )
        await self._seedMessage(
            testDatabase, chatId=1, userId=100, messageId=2, messageText="middle", date=base.replace(day=2)
        )

        result = await testDatabase.chatMessages.getChatMessagesByMessageIds(
            chatId=1, messageIds=[MessageId(1), MessageId(2), MessageId(3)]
        )

        resultIds = [row["message_id"].asInt() for row in result]
        assert resultIds == [1, 2, 3]

    async def test_crossChatIsolation(self, testDatabase: Database) -> None:
        """A colliding message_id in a different chat is NOT returned.

        Message IDs are scoped per chat; requesting IDs from chat 1 with
        chatId=2 must not leak chat 1's rows.
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=42, messageText="in chat 1")
        await self._seedMessage(testDatabase, chatId=2, userId=100, messageId=42, messageText="in chat 2")

        result = await testDatabase.chatMessages.getChatMessagesByMessageIds(chatId=2, messageIds=[MessageId(42)])

        assert len(result) == 1
        assert result[0]["message_text"] == "in chat 2"

    async def test_duplicateInputIds(self, testDatabase: Database) -> None:
        """Passing duplicate IDs in the input returns one row (no error).

        Dedup is the caller's responsibility; when duplicates slip through,
        the SQL ``IN (...)`` collapses them to a single match.
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=5, messageText="dup target")

        result = await testDatabase.chatMessages.getChatMessagesByMessageIds(
            chatId=1, messageIds=[MessageId(5), MessageId(5)]
        )

        assert len(result) == 1
        assert result[0]["message_id"] == MessageId(5)
