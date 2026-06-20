"""Tests for :class:`ChatSearchRepository`.

End-to-end behavioural coverage of the public chat-message search
dispatcher :meth:`ChatSearchRepository.searchChatMessages`:

- **Filter-only mode** (``queryEmbedding is None``): the SQL filter
  path that applies ``userFilter`` / ``categoryFilter`` /
  ``maxAgeDays`` / ``rootMessageId`` directly against
  ``chat_messages`` joined to ``chat_users``, ordered by ``date``
  descending.
- **Semantic mode** (``queryEmbedding is not None``): would compute
  cosine similarity over the embeddings via ``numpy`` — not exercised
  end-to-end here (requires populating ``message_embeddings`` BLOB
  rows, which has its own dedicated test coverage in
  ``tests/database/repositories/test_chat_embeddings.py``).

The repository was split out of :class:`ChatMessagesRepository` and
:class:`ChatEmbeddingsRepository` so the search surface is cohesive
and free of cross-repository back-references. Embedding CRUD
(``saveMessageEmbedding``, ``getMessageEmbedding``,
``deleteChatEmbeddings``) and the backfill helper
(``getMessagesWithoutEmbeddings``) live in
:class:`ChatEmbeddingsRepository`; this repository only consumes the
embeddings for ranking.

Uses the shared ``testDatabase`` fixture from ``tests/conftest.py`` so
each test gets a fresh in-memory SQLite database with all migrations
applied — no mocks.
"""

# pyright: reportTypedDictNotRequiredAccess=false

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


class TestSearchChatMessages:
    """End-to-end tests for ``ChatSearchRepository.searchChatMessages``.

    Pins the filter-only-mode contract (the only mode covered
    end-to-end here without populating the embeddings table). The
    semantic-mode behaviour (numpy cosine similarity over
    ``message_embeddings``) is covered indirectly via
    ``tests/database/repositories/test_chat_embeddings.py`` (the
    ``message_embeddings`` CRUD round-trips) plus the handler-level
    tests in ``tests/bot/common/handlers/test_chat_search.py`` (the
    full ``/search`` command path).

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
    ) -> None:
        """Insert a chat_users row and a chat_messages row for the test seed."""
        await TestSearchChatMessages._seedUser(db, chatId=chatId, userId=userId)
        await db.chatMessages.saveChatMessage(
            date=datetime.datetime.now(datetime.timezone.utc),
            chatId=chatId,
            userId=userId,
            messageId=MessageId(messageId),
            messageText=messageText,
            messageCategory=messageCategory,
        )

    async def test_filter_only_returns_matching_user(self, testDatabase: Database) -> None:
        """Filter-only mode (no queryEmbedding) returns messages matching the user filter."""
        # Two users, three messages from user 100, one from user 200.
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="a")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=2, messageText="b")
        await self._seedMessage(testDatabase, chatId=1, userId=200, messageId=3, messageText="c")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=4, messageText="d")

        results = await testDatabase.chatSearch.searchChatMessages(
            chatId=1,
            queryEmbedding=None,
            userFilter=100,
            limit=10,
        )

        assert len(results) == 3
        assert {r["user_id"] for r in results} == {100}
        # Filter-only mode has no ranking, so score is 0.0 by design.
        assert all(r["score"] == 0.0 for r in results)

    async def test_filter_only_with_category(self, testDatabase: Database) -> None:
        """Category filter narrows filter-only results to matching category only."""
        await self._seedMessage(
            testDatabase,
            chatId=1,
            userId=100,
            messageId=1,
            messageText="bot-said-hi",
            messageCategory=MessageCategory.BOT,
        )
        await self._seedMessage(
            testDatabase,
            chatId=1,
            userId=100,
            messageId=2,
            messageText="user-said-hi",
            messageCategory=MessageCategory.USER,
        )
        await self._seedMessage(
            testDatabase,
            chatId=1,
            userId=100,
            messageId=3,
            messageText="bot-said-bye",
            messageCategory=MessageCategory.BOT,
        )

        results = await testDatabase.chatSearch.searchChatMessages(
            chatId=1,
            queryEmbedding=None,
            categoryFilter=[MessageCategory.BOT],
            limit=10,
        )

        assert len(results) == 2
        assert {r["message_category"] for r in results} == {MessageCategory.BOT}
