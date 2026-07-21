"""Tests for :class:`ChatSearchRepository`.

End-to-end behavioural coverage of the public chat-message search
dispatcher :meth:`ChatSearchRepository.searchChatMessages`:

- **Filter-only mode** (``queryEmbedding is None``): the SQL filter
  path that applies ``userFilter`` / ``categoryFilter`` /
  ``maxAgeDays`` / ``rootMessageId`` directly against
  ``chat_messages`` joined to ``chat_users``, ordered by ``date``
  descending.
- **Semantic mode** (``queryEmbedding is not None``): delegates
  cosine ranking to the provider's native vec0 virtual table
  (``vec_message_embeddings_{N}``). Post-``migration_025`` there is
  NO numpy in-process fallback — when vec0 is unavailable, raises,
  or yields no matches, semantic search returns ``[]`` (Decision D8).

The repository was split out of :class:`ChatMessagesRepository` and
:class:`ChatEmbeddingsRepository` so the search surface is cohesive
and free of cross-repository back-references. Embedding CRUD
(``saveMessageEmbedding``) and the backfill helper
(``getMessagesWithoutEmbeddings``) live in
:class:`ChatEmbeddingsRepository`; this repository only consumes the
stored vectors for ranking.

Uses the shared ``testDatabase`` fixture from ``tests/conftest.py`` so
each test gets a fresh in-memory SQLite database with all migrations
applied — no mocks.

Regression tests for the ``_filterMessageIds`` batching boundary logic
live in :class:`TestFilterMessageIdsBatching`.
"""

# pyright: reportTypedDictNotRequiredAccess=false

import datetime
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from internal.database import Database
from internal.database.models import MessageCategory
from internal.database.providers.base import BaseSQLProvider
from internal.database.providers.sqlite3 import _SQLITE_VEC_AVAILABLE
from internal.database.repositories.chat_search import _MESSAGE_ID_FILTER_BATCH_SIZE, ChatSearchRepository
from internal.models import MessageId


class TestSearchChatMessages:
    """End-to-end tests for ``ChatSearchRepository.searchChatMessages``.

    Pins the filter-only-mode contract and the semantic-mode vec0
    contract. The vec0-dispatch internals (resolver wiring, vec0 filter
    shape, post-filter composition, ``maxMessages`` cutoff query) are
    covered in ``test_chat_search_native.py``; this file drives the
    full repo through the real Database fixture.

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
        threadId: Optional[int] = None,
        rootMessageId: Optional[MessageId] = None,
    ) -> None:
        """Insert a chat_users row and a chat_messages row for the test seed.

        Args:
            db: Database to seed.
            chatId: Chat identifier.
            userId: Author user id (a matching ``chat_users`` row is upserted).
            messageId: Message id (numeric; wrapped in :class:`MessageId`).
            messageText: Message body text.
            messageCategory: Message category (default UNSPECIFIED).
            threadId: Optional thread/topic id. ``None`` falls through to
                :data:`DEFAULT_THREAD_ID` (``0`` = main) inside ``saveChatMessage``.
            rootMessageId: Optional thread-root message id.
        """
        await TestSearchChatMessages._seedUser(db, chatId=chatId, userId=userId)
        await db.chatMessages.saveChatMessage(
            date=datetime.datetime.now(datetime.timezone.utc),
            chatId=chatId,
            userId=userId,
            messageId=MessageId(messageId),
            messageText=messageText,
            messageCategory=messageCategory,
            threadId=threadId,
            rootMessageId=rootMessageId,
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

    async def test_semantic_mode_ranking(self, testDatabase: Database) -> None:
        """Semantic mode (``queryEmbedding`` provided) ranks by cosine similarity via vec0.

        Seeds two messages with known embeddings:
        - Message 1: embedding ``[1.0, 0.0]``
        - Message 2: embedding ``[0.0, 1.0]``

        Query embedding ``[1.0, 0.0]`` should rank message 1 first with score
        ≈ 1.0 (identical), then message 2 with score ≈ 0.0 (orthogonal).
        """
        if not _SQLITE_VEC_AVAILABLE:
            pytest.skip("sqlite-vec not installed")

        chatId = 1
        modelName = "test-model"

        await self._seedUser(testDatabase, chatId=chatId, userId=100)
        await self._seedUser(testDatabase, chatId=chatId, userId=200)
        await self._seedMessage(testDatabase, chatId=chatId, userId=100, messageId=1, messageText="apple")
        await self._seedMessage(testDatabase, chatId=chatId, userId=200, messageId=2, messageText="banana")

        # Save embeddings for both messages (dual-writes to vec0 when supported).
        await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=chatId, messageId=MessageId(1), embedding=[1.0, 0.0], model=modelName
        )
        await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=chatId, messageId=MessageId(2), embedding=[0.0, 1.0], model=modelName
        )

        results = await testDatabase.chatSearch.searchChatMessages(
            chatId=chatId,
            queryEmbedding=[1.0, 0.0],
            modelName=modelName,
            limit=10,
        )

        assert len(results) == 2
        # Message 1 (embedding [1.0, 0.0]) is identical to the query → score ≈ 1.0.
        assert results[0]["message_id"] == MessageId(1)
        assert results[0]["score"] == pytest.approx(1.0, abs=1e-6)
        # Message 2 (embedding [0.0, 1.0]) is orthogonal to the query → score ≈ 0.0.
        assert results[1]["message_id"] == MessageId(2)
        assert results[1]["score"] == pytest.approx(0.0, abs=1e-6)

    async def test_semanticModeThreadAndSubstringCombined(self, testDatabase: Database) -> None:
        """Semantic mode forwards ``threadId`` AND ``substring`` through the post-filter.

        Regression lock for the reviewer-flagged wiring gap: the ``threadId`` /
        ``substring`` filters were previously exercised only in filter-only mode
        (``queryEmbedding=None``). This test drives them THROUGH the semantic
        machinery so a future refactor that drops either kwarg from a forwarding
        call (``_semanticSearch`` → ``_nativeVectorSearch`` →
        ``_filterMessageIds``, or the ``needsPostFilter`` guard) fails here.

        With ``sqlite-vec`` available (the default in this repo's venv),
        ``saveMessageEmbedding`` dual-writes the vec0 table, so the native
        ``_nativeVectorSearch`` fast path runs and its ``needsPostFilter`` guard
        + ``_filterMessageIds`` forwarding are exercised end-to-end.

        Seeds four messages across two threads (0 and 5) whose text
        ``substring="foo"`` distinguishes:

        - msg 1: thread 0, "foo bar"  — excluded by the ``threadId`` filter.
        - msg 2: thread 5, "foo baz"  — kept (matches BOTH filters).
        - msg 3: thread 5, "qux zap"  — excluded by the ``substring`` filter.
        - msg 4: thread 0, "foo qux"  — excluded by the ``threadId`` filter.

        Asserts ``threadId=5, substring="foo"`` returns ONLY msg 2.
        """
        if not _SQLITE_VEC_AVAILABLE:
            pytest.skip("sqlite-vec not installed")

        chatId = 1
        modelName = "test-model"
        for messageId, messageText, threadId in (
            (1, "foo bar", 0),
            (2, "foo baz", 5),
            (3, "qux zap", 5),
            (4, "foo qux", 0),
        ):
            await self._seedMessage(
                testDatabase,
                chatId=chatId,
                userId=100,
                messageId=messageId,
                messageText=messageText,
                threadId=threadId,
            )
            await testDatabase.chatEmbeddings.saveMessageEmbedding(
                chatId=chatId, messageId=MessageId(messageId), embedding=[1.0, 0.0], model=modelName
            )

        results = await testDatabase.chatSearch.searchChatMessages(
            chatId=chatId,
            queryEmbedding=[1.0, 0.0],
            modelName=modelName,
            threadId=5,
            substring="foo",
            limit=10,
        )

        assert {r["message_id"].asInt() for r in results} == {2}
        assert results[0]["thread_id"] == 5
        assert "foo" in results[0]["message_text"]

    async def test_semanticModeReturnsEmptyWhenVec0Raises(self, testDatabase: Database) -> None:
        """Semantic search returns ``[]`` when ``_nativeVectorSearch`` raises (no fallback).

        Post-``migration_025`` contract (Decision D8): the legacy numpy
        fallback is gone. When vec0 raises, semantic search must return
        ``[]`` — it must NOT attempt any in-process fallback.

        This forces the contract by patching ``_nativeVectorSearch`` to
        raise; an empty list is the only acceptable result.
        """
        chatId = 1
        modelName = "test-model"
        await self._seedMessage(testDatabase, chatId=chatId, userId=100, messageId=1, messageText="apple")
        await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=chatId, messageId=MessageId(1), embedding=[1.0, 0.0], model=modelName
        )

        with patch.object(
            ChatSearchRepository, "_nativeVectorSearch", new=AsyncMock(side_effect=RuntimeError("vec0 boom"))
        ):
            results = await testDatabase.chatSearch.searchChatMessages(
                chatId=chatId,
                queryEmbedding=[1.0, 0.0],
                modelName=modelName,
                limit=10,
            )

        assert results == []

    async def test_semanticModeReturnsEmptyWhenNativeReturnsEmpty(self, testDatabase: Database) -> None:
        """Semantic search returns ``[]`` when ``_nativeVectorSearch`` yields no matches.

        Mirrors the vec0-empty case (table exists, no rows match the
        partition-key filter): the dispatcher returns ``[]`` rather than
        falling back to numpy.
        """
        chatId = 1
        modelName = "test-model"
        await self._seedMessage(testDatabase, chatId=chatId, userId=100, messageId=1, messageText="apple")
        await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=chatId, messageId=MessageId(1), embedding=[1.0, 0.0], model=modelName
        )

        with patch.object(ChatSearchRepository, "_nativeVectorSearch", new=AsyncMock(return_value=[])):
            results = await testDatabase.chatSearch.searchChatMessages(
                chatId=chatId,
                queryEmbedding=[1.0, 0.0],
                modelName=modelName,
                limit=10,
            )

        assert results == []

    async def test_semanticModeReturnsEmptyWhenModelNameIsNone(self, testDatabase: Database) -> None:
        """Semantic search with ``modelName=None`` short-circuits to ``[]``.

        The repo cannot resolve a ``model_id`` without a model name, so
        ``_nativeVectorSearch`` returns ``[]`` immediately. This is the
        pre-refactor behaviour (``modelName is None`` was always a no-op
        for semantic search) and it is preserved.
        """
        chatId = 1
        await self._seedMessage(testDatabase, chatId=chatId, userId=100, messageId=1, messageText="apple")

        results = await testDatabase.chatSearch.searchChatMessages(
            chatId=chatId,
            queryEmbedding=[1.0, 0.0],
            modelName=None,
            limit=10,
        )

        assert results == []

    async def test_semanticNativeNeedsPostFilterGuardThreadAndSubstring(self, testDatabase: Database) -> None:
        """``needsPostFilter`` guard in ``_nativeVectorSearch`` keeps each term.

        The ``needsPostFilter`` boolean is an OR over every post-filter. The
        companion ``...Combined`` test sets BOTH ``threadId`` and ``substring``,
        so dropping a single term from the guard is masked by the other (the
        guard stays True and ``_filterMessageIds`` still receives both kwargs).
        This test closes that hole: it runs each filter on its own through the
        native path (where the guard lives), so removing either
        ``or threadId is not None`` or ``or substring is not None`` from the
        guard collapses it to ``False``, skips the post-filter, and leaks
        unfiltered candidates.

        Same seed as the companion tests:

        - msg 1: thread 0, "foo bar"
        - msg 2: thread 5, "foo baz"
        - msg 3: thread 5, "qux zap"
        - msg 4: thread 0, "foo qux"

        ``threadId=5`` alone must yield the two thread-5 messages; ``substring="foo"``
        alone must yield the three "foo" messages.
        """
        if not _SQLITE_VEC_AVAILABLE:
            pytest.skip("sqlite-vec not installed")

        chatId = 1
        modelName = "test-model"
        for messageId, messageText, threadId in (
            (1, "foo bar", 0),
            (2, "foo baz", 5),
            (3, "qux zap", 5),
            (4, "foo qux", 0),
        ):
            await self._seedMessage(
                testDatabase,
                chatId=chatId,
                userId=100,
                messageId=messageId,
                messageText=messageText,
                threadId=threadId,
            )
            await testDatabase.chatEmbeddings.saveMessageEmbedding(
                chatId=chatId, messageId=MessageId(messageId), embedding=[1.0, 0.0], model=modelName
            )

        # threadId alone — a dropped ``or threadId is not None`` guard term
        # would skip the post-filter and return all four candidates.
        threadOnly = await testDatabase.chatSearch.searchChatMessages(
            chatId=chatId, queryEmbedding=[1.0, 0.0], modelName=modelName, threadId=5, limit=10
        )
        assert {r["message_id"].asInt() for r in threadOnly} == {2, 3}

        # substring alone — a dropped ``or substring is not None`` guard term
        # would skip the post-filter and return all four candidates.
        substringOnly = await testDatabase.chatSearch.searchChatMessages(
            chatId=chatId, queryEmbedding=[1.0, 0.0], modelName=modelName, substring="foo", limit=10
        )
        assert {r["message_id"].asInt() for r in substringOnly} == {1, 2, 4}

    async def test_filter_only_substring_case_insensitive(self, testDatabase: Database) -> None:
        """Substring filter matches case-insensitively; ``None`` returns all.

        Seeds three messages in one chat/user (text containing "MEETING",
        unrelated text, and lowercase "meeting"). A ``substring="meeting"``
        filter must return exactly the two messages whose text contains
        "meeting" regardless of case (``LIKE`` is case-insensitive for ASCII
        in SQLite). With ``substring=None`` all three are returned.
        """
        chatId = 1
        await self._seedMessage(
            testDatabase, chatId=chatId, userId=100, messageId=1, messageText="Team MEETING at noon"
        )
        await self._seedMessage(testDatabase, chatId=chatId, userId=100, messageId=2, messageText="standup notes")
        await self._seedMessage(testDatabase, chatId=chatId, userId=100, messageId=3, messageText="meeting again")

        matched = await testDatabase.chatSearch.searchChatMessages(
            chatId=chatId, queryEmbedding=None, substring="meeting", limit=10
        )
        assert {r["message_id"].asInt() for r in matched} == {1, 3}

        allRows = await testDatabase.chatSearch.searchChatMessages(
            chatId=chatId, queryEmbedding=None, substring=None, limit=10
        )
        assert {r["message_id"].asInt() for r in allRows} == {1, 2, 3}

    async def test_filter_only_thread_filter(self, testDatabase: Database) -> None:
        """``threadId`` filter restricts to that thread; ``None`` returns all; ``0`` returns main only.

        Seeds messages in the main thread (``thread_id=0``) and a topic
        (``thread_id=5``). The null-semantics clause
        ``(:threadId IS NULL OR c.thread_id = :threadId)`` means ``None``
        applies no filter, ``5`` selects the topic, and ``0`` selects only
        main-thread messages.
        """
        chatId = 1
        await self._seedMessage(
            testDatabase, chatId=chatId, userId=100, messageId=1, messageText="main one", threadId=0
        )
        await self._seedMessage(
            testDatabase, chatId=chatId, userId=100, messageId=2, messageText="main two", threadId=0
        )
        await self._seedMessage(
            testDatabase, chatId=chatId, userId=100, messageId=3, messageText="topic alpha", threadId=5
        )
        await self._seedMessage(
            testDatabase, chatId=chatId, userId=100, messageId=4, messageText="topic beta", threadId=5
        )

        topic = await testDatabase.chatSearch.searchChatMessages(
            chatId=chatId, queryEmbedding=None, threadId=5, limit=10
        )
        assert {r["message_id"].asInt() for r in topic} == {3, 4}
        assert all(r["thread_id"] == 5 for r in topic)

        allRows = await testDatabase.chatSearch.searchChatMessages(
            chatId=chatId, queryEmbedding=None, threadId=None, limit=10
        )
        assert {r["message_id"].asInt() for r in allRows} == {1, 2, 3, 4}

        mainOnly = await testDatabase.chatSearch.searchChatMessages(
            chatId=chatId, queryEmbedding=None, threadId=0, limit=10
        )
        assert {r["message_id"].asInt() for r in mainOnly} == {1, 2}

    async def test_filter_only_thread_and_substring_combined(self, testDatabase: Database) -> None:
        """``threadId`` and ``substring`` compose with AND.

        Seeds a thread-5 message containing "foo", a thread-5 message
        without "foo", and a main-thread message containing "foo". Filtering
        by ``threadId=5, substring="foo"`` returns only the thread-5 "foo"
        message — the main-thread "foo" is excluded by the thread filter and
        the thread-5 non-matching message is excluded by the substring filter.
        """
        chatId = 1
        await self._seedMessage(
            testDatabase, chatId=chatId, userId=100, messageId=1, messageText="foo in topic", threadId=5
        )
        await self._seedMessage(
            testDatabase, chatId=chatId, userId=100, messageId=2, messageText="bar in topic", threadId=5
        )
        await self._seedMessage(
            testDatabase, chatId=chatId, userId=100, messageId=3, messageText="foo in main", threadId=0
        )

        results = await testDatabase.chatSearch.searchChatMessages(
            chatId=chatId, queryEmbedding=None, threadId=5, substring="foo", limit=10
        )
        assert {r["message_id"].asInt() for r in results} == {1}
        assert results[0]["thread_id"] == 5
        assert "foo" in results[0]["message_text"]


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

    async def test_batching_with_over_1000_candidates(self, testDatabase: Database) -> None:
        """``_filterMessageIds`` batches candidate IDs across multiple queries.

        Seeds ``_MESSAGE_ID_FILTER_BATCH_SIZE * 2 - 1`` messages —
        enough that more than one batch is needed (default batch size is
        1024). Wraps ``executeFetchAll`` to count queries and verifies at
        least 2 batches were issued.

        This test would FAIL if the batching loop were removed (callCount
        would be 1) or if ``_MESSAGE_ID_FILTER_BATCH_SIZE`` were raised
        above 32766 (asserted explicitly below).
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
        # ``_MESSAGE_ID_FILTER_BATCH_SIZE * 2 - 1`` candidates / 1024 per batch = at least 2 SQL queries.
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
