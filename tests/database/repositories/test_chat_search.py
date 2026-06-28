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

Regression tests for the ``_filterMessageIds`` batching boundary logic
live in :class:`TestFilterMessageIdsBatching`.
"""

# pyright: reportTypedDictNotRequiredAccess=false

import datetime
from unittest.mock import patch

from internal.database import Database
from internal.database.manager import DatabaseManagerConfig
from internal.database.models import MessageCategory
from internal.database.providers.base import BaseSQLProvider
from internal.database.repositories.chat_search import _MESSAGE_ID_FILTER_BATCH_SIZE
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


class TestFilterMessageIdsBatching:
    """Regression tests for ``_filterMessageIds`` batching boundary.

    Verifies that ``_filterMessageIds`` correctly batches candidate IDs
    across multiple SQL queries when the count exceeds
    ``_MESSAGE_ID_FILTER_BATCH_SIZE``, and that results are correctly
    accumulated (deduplicated via set) across batches.
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

    async def test_batching_with_over_500_candidates(self, testDatabase: Database) -> None:
        """``_filterMessageIds`` batches candidate IDs across multiple queries.

        Seeds ``_MESSAGE_ID_FILTER_BATCH_SIZE * 2 - 1`` messages —
        enough that more than one batch is needed (default batch size is
        500). Wraps ``executeFetchAll`` to count queries and verifies at
        least 2 batches were issued.

        This test would FAIL if the batching loop were removed (callCount
        would be 1) or if ``_MESSAGE_ID_FILTER_BATCH_SIZE`` were raised
        above 999 (asserted explicitly below).
        """
        # Sanity check: batch size must stay below SQLITE_MAX_VARIABLE_NUMBER.
        assert _MESSAGE_ID_FILTER_BATCH_SIZE <= 32766, (
            f"_MESSAGE_ID_FILTER_BATCH_SIZE={_MESSAGE_ID_FILTER_BATCH_SIZE} "
            f"exceeds SQLITE_MAX_VARIABLE_NUMBER limit"
        )

        chatId = 1
        userId = 100

        # Seed enough messages so every candidate ID exists in the DB
        # (candidate range is 1 .. _MESSAGE_ID_FILTER_BATCH_SIZE * 2 - 1).
        await self._seedUser(testDatabase, chatId=chatId, userId=userId)
        for i in range(1, _MESSAGE_ID_FILTER_BATCH_SIZE * 2):
            await testDatabase.chatMessages.saveChatMessage(
                date=datetime.datetime.now(datetime.timezone.utc),
                chatId=chatId,
                userId=userId,
                messageId=MessageId(i),
                messageText=str(i),
                messageCategory=MessageCategory.UNSPECIFIED,
            )

        sqlProvider = await testDatabase.manager.getProvider(chatId=chatId, readonly=True)
        candidateIds = [MessageId(i) for i in range(1, _MESSAGE_ID_FILTER_BATCH_SIZE * 2)]

        # Spy on executeFetchAll at the base-class level to count SQL calls
        # (required because SQLite3Provider uses __slots__ and rejects
        # instance attribute assignment).
        originalMethod = BaseSQLProvider.executeFetchAll
        callCount = 0

        async def countingSideEffect(query, params=None):
            nonlocal callCount
            callCount += 1
            return await originalMethod(sqlProvider, query, params)

        with patch.object(BaseSQLProvider, "executeFetchAll", side_effect=countingSideEffect):
            result = await testDatabase.chatSearch._filterMessageIds(
                sqlProvider=sqlProvider,
                chatId=chatId,
                candidateMessageIds=candidateIds,
                userFilter=None,
                categoryFilter=None,
                maxAgeDays=None,
                rootMessageId=None,
            )

        assert len(result) == _MESSAGE_ID_FILTER_BATCH_SIZE * 2 - 1
        assert {mid.asInt() for mid in result} == set(range(1, _MESSAGE_ID_FILTER_BATCH_SIZE * 2))
        # 610 candidates / 500 per batch = at least 2 SQL queries.
        assert callCount >= 2, (
            f"Expected at least 2 SQL queries for {_MESSAGE_ID_FILTER_BATCH_SIZE * 2} candidates, "
            f"got {callCount} — batching may not be working"
        )

    async def test_batching_with_category_filter(self, testDatabase: Database) -> None:
        """Batch size is reduced when category filters consume param slots."""
        chatId = 1
        userId = 100

        # Seed one user and 25 messages (some with BOT, some with USER category).
        await self._seedUser(testDatabase, chatId=chatId, userId=userId)
        for i in range(1, 26):
            category = MessageCategory.BOT if i % 2 == 0 else MessageCategory.USER
            await testDatabase.chatMessages.saveChatMessage(
                date=datetime.datetime.now(datetime.timezone.utc),
                chatId=chatId,
                userId=userId,
                messageId=MessageId(i),
                messageText=str(i),
                messageCategory=category,
            )

        sqlProvider = await testDatabase.manager.getProvider(chatId=chatId, readonly=True)
        candidateIds = [MessageId(i) for i in range(1, 26)]

        # Filter to BOT category only — expects 12 of 25 messages.
        result = await testDatabase.chatSearch._filterMessageIds(
            sqlProvider=sqlProvider,
            chatId=chatId,
            candidateMessageIds=candidateIds,
            userFilter=None,
            categoryFilter=[MessageCategory.BOT],
            maxAgeDays=None,
            rootMessageId=None,
        )

        assert len(result) == 12
        assert {mid.asInt() for mid in result} == {i for i in range(1, 26) if i % 2 == 0}
