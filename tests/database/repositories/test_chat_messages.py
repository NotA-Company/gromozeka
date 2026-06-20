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
from internal.database.manager import DatabaseManagerConfig
from internal.database.models import MessageCategory
from internal.models import MessageId


def _buildConfig() -> DatabaseManagerConfig:
    """Build a minimal in-memory SQLite DatabaseManagerConfig for tests."""
    return {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {"dbPath": ":memory:"},
            }
        },
    }


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
