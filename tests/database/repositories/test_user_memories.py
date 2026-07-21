"""Tests for :class:`UserMemoriesRepository`.

Covers the full lifecycle on the ``user_memories`` table:

- Phase 1a relational CRUD: ``addMemory`` / ``deleteMemory`` /
  ``getPermanentMemories`` / ``getLatestMemories``.
- Memory-compaction-v1 Phase 1: soft-delete (``deleteMemory`` sets
  ``deleted_at``; live reads skip it) + ``getMemoriesByIds`` (no
  ``deleted_at`` filter — returns soft-deleted for historical reads).
- Phase 1b vector layer: ``searchMemories`` (filter-only + semantic
  modes), ``saveMemoryEmbedding`` (lazy vec0 creation),
  ``deleteMemoryEmbedding``, ``getMemoriesWithoutEmbeddings`` /
  ``deleteObsoleteMemoryEmbeddings`` (model-drift regeneration).

Uses the shared ``testDatabase`` fixture from ``tests/conftest.py`` so
each test gets a fresh in-memory SQLite database with all migrations
(including ``migration_020``) applied — no mocks. Semantic-mode tests
skip cleanly when sqlite-vec is not available (mirrors
``test_chat_embeddings.py``).
"""

# pyright: reportTypedDictNotRequiredAccess=false

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from internal.database import Database
from internal.database.manager import DatabaseManager
from internal.database.models import MemoryType, UserMemorySource
from internal.database.providers.sqlite3 import _SQLITE_VEC_AVAILABLE, SQLite3Provider
from internal.database.repositories.user_memories import UserMemoriesRepository, UserMemoryDict

CHAT_ID = 1
USER_ID = 100


def _newMemoryId() -> str:
    """Generate a fresh app-side memory id (UUID hex, mirroring the migration)."""
    return uuid.uuid4().hex


class TestUserMemoriesRepository:
    """Phase-1a behavioural coverage for the unified ``user_memories`` store."""

    @staticmethod
    async def _add(
        db: Database,
        *,
        chatId: int = CHAT_ID,
        userId: int = USER_ID,
        memoryType: str = MemoryType.FACT,
        content: str = "some content",
        tags: list[str] | None = None,
        permanent: bool = False,
        threadId: int | None = None,
        source: UserMemorySource = UserMemorySource.REFINEMENT,
        embedding: list[float] | None = None,
        embeddingModel: str | None = None,
    ) -> str:
        """Insert a memory and return its generated id."""
        memoryId = _newMemoryId()
        await db.userMemories.addMemory(
            chatId=chatId,
            userId=userId,
            memoryId=memoryId,
            type=memoryType,
            content=content,
            tags=tags if tags is not None else [],
            permanent=permanent,
            threadId=threadId,
            source=source,
            embedding=embedding,
            embeddingModel=embeddingModel,
        )
        return memoryId

    ###
    # Round-trip: add → getPermanentMemories / getLatestMemories
    ###
    async def test_addMemory_getPermanentMemories_roundTrip(self, testDatabase: Database) -> None:
        """A permanent cross-thread fact round-trips through getPermanentMemories with full dict shape."""
        memoryId = await self._add(
            testDatabase,
            content="lives in Berlin",
            tags=["geo"],
            permanent=True,
            threadId=None,
            memoryType=MemoryType.FACT,
            source=UserMemorySource.REFINEMENT,
        )

        result = await testDatabase.userMemories.getPermanentMemories(CHAT_ID, USER_ID, threadId=0)

        assert len(result) == 1
        row: UserMemoryDict = result[0]
        assert row["chat_id"] == CHAT_ID
        assert row["user_id"] == USER_ID
        assert row["memory_id"] == memoryId
        assert row["type"] == MemoryType.FACT
        assert row["content"] == "lives in Berlin"
        assert row["tags"] == ["geo"]
        assert row["permanent"] is True
        assert row["source"] == "refinement"
        assert row["thread_id"] is None
        assert row["model_id"] is None
        assert row["created_at"] is not None
        assert row["updated_at"] is not None

    async def test_addMemory_getLatestMemories_roundTrip(self, testDatabase: Database) -> None:
        """getLatestMemories returns ONLY ephemeral memories, newest-first; permanent is excluded.

        A permanent row in the same thread must NOT surface in
        getLatestMemories (it is served by getPermanentMemories) — this
        locks the ephemeral-only contract so a thread-scoped permanent
        bio never renders twice in the injection layer.
        """
        await self._add(testDatabase, content="older", permanent=False, threadId=5)
        await self._add(testDatabase, content="newer", permanent=False, threadId=5)
        # Permanent row in the SAME thread — must be excluded from getLatestMemories.
        await self._add(
            testDatabase,
            content="permanent bio",
            permanent=True,
            threadId=5,
            memoryType=MemoryType.BIO,
        )

        latest = await testDatabase.userMemories.getLatestMemories(CHAT_ID, USER_ID, threadId=5)
        permanent = await testDatabase.userMemories.getPermanentMemories(CHAT_ID, USER_ID, threadId=5)

        # getLatestMemories is ephemeral-only: the permanent row is excluded.
        assert len(latest) == 2
        # Newest-updated-first.
        assert latest[0]["content"] == "newer"
        assert latest[1]["content"] == "older"
        for row in latest:
            assert row["thread_id"] == 5
            assert row["permanent"] is False

        # getPermanentMemories serves the permanent row.
        assert len(permanent) == 1
        assert permanent[0]["content"] == "permanent bio"
        assert permanent[0]["permanent"] is True

    async def test_getLatestMemories_threadScoped(self, testDatabase: Database) -> None:
        """getLatestMemories only returns memories for the requested thread."""
        await self._add(testDatabase, content="thread5", threadId=5)
        await self._add(testDatabase, content="thread9", threadId=9)

        result5 = await testDatabase.userMemories.getLatestMemories(CHAT_ID, USER_ID, threadId=5)
        result9 = await testDatabase.userMemories.getLatestMemories(CHAT_ID, USER_ID, threadId=9)

        assert len(result5) == 1 and result5[0]["content"] == "thread5"
        assert len(result9) == 1 and result9[0]["content"] == "thread9"

    ###
    # getPermanentMemories: cross-thread + this-thread merge
    ###
    async def test_getPermanentMemories_crossAndThreadMerge(self, testDatabase: Database) -> None:
        """getPermanentMemories merges cross-thread permanent (NULL thread_id) with this-thread permanent.

        A thread-scoped permanent bio for a DIFFERENT thread must NOT surface.
        """
        # Cross-thread permanent fact (thread_id NULL).
        await self._add(
            testDatabase,
            content="cross-thread fact",
            permanent=True,
            threadId=None,
            memoryType=MemoryType.FACT,
        )
        # Permanent bio scoped to thread 5.
        await self._add(
            testDatabase,
            content="bio for thread 5",
            permanent=True,
            threadId=5,
            memoryType=MemoryType.BIO,
        )
        # Permanent bio scoped to thread 9 (must NOT surface for thread 5).
        await self._add(
            testDatabase,
            content="bio for thread 9",
            permanent=True,
            threadId=9,
            memoryType=MemoryType.BIO,
        )

        thread5 = await testDatabase.userMemories.getPermanentMemories(CHAT_ID, USER_ID, threadId=5)
        thread9 = await testDatabase.userMemories.getPermanentMemories(CHAT_ID, USER_ID, threadId=9)

        thread5Contents = {r["content"] for r in thread5}
        assert thread5Contents == {"cross-thread fact", "bio for thread 5"}

        thread9Contents = {r["content"] for r in thread9}
        assert thread9Contents == {"cross-thread fact", "bio for thread 9"}

    async def test_getPermanentMemories_excludesEphemeral(self, testDatabase: Database) -> None:
        """getPermanentMemories never returns non-permanent rows."""
        await self._add(testDatabase, content="permanent", permanent=True, threadId=None)
        await self._add(testDatabase, content="ephemeral", permanent=False, threadId=5)

        result = await testDatabase.userMemories.getPermanentMemories(CHAT_ID, USER_ID, threadId=5)
        assert {r["content"] for r in result} == {"permanent"}

    ###
    # deleteMemory
    ###
    async def test_deleteMemory(self, testDatabase: Database) -> None:
        """deleteMemory soft-deletes the row; live reads no longer return it. Re-deleting returns False."""
        memoryId = await self._add(testDatabase, content="bye", threadId=5)

        ok = await testDatabase.userMemories.deleteMemory(CHAT_ID, USER_ID, memoryId)
        assert ok is True

        rows = await testDatabase.userMemories.getLatestMemories(CHAT_ID, USER_ID, threadId=5)
        assert rows == []

        # Re-delete the same id.
        ok2 = await testDatabase.userMemories.deleteMemory(CHAT_ID, USER_ID, memoryId)
        assert ok2 is False

    async def test_deleteMemory_canTargetPermanent(self, testDatabase: Database) -> None:
        """Explicit by-id deleteMemory is unrestricted — it soft-deletes a permanent memory; live reads skip it."""
        memoryId = await self._add(testDatabase, content="permanent", permanent=True, threadId=None)
        ok = await testDatabase.userMemories.deleteMemory(CHAT_ID, USER_ID, memoryId)
        assert ok is True
        assert await testDatabase.userMemories.getPermanentMemories(CHAT_ID, USER_ID, threadId=0) == []

    ###
    # getDistinctTags (Phase 5b — tag-filter picker source)
    ###
    async def test_getDistinctTags_returnsUniqueSortedTags(self, testDatabase: Database) -> None:
        """Distinct tags across rows are returned as a sorted, de-duplicated list.

        Seeds 3 memories with overlapping tags ``["a","b"]``, ``["b","c"]``,
        ``["a"]`` and asserts ``getDistinctTags`` returns ``["a","b","c"]``
        (unique + sorted).
        """
        await self._add(testDatabase, content="m1", tags=["b", "a"])
        await self._add(testDatabase, content="m2", tags=["c", "b"])
        await self._add(testDatabase, content="m3", tags=["a"])

        result = await testDatabase.userMemories.getDistinctTags(CHAT_ID, USER_ID)

        assert result == ["a", "b", "c"]

    async def test_getDistinctTags_filteredByType(self, testDatabase: Database) -> None:
        """The optional ``memoryType`` filter narrows the tag set to that type.

        Seeds ``FACT`` memories tagged ``["geo"]`` and ``PREFERENCE`` memories
        tagged ``["vegan"]``, then asserts ``getDistinctTags(memoryType=FACT)``
        returns only ``["geo"]`` and ``getDistinctTags(memoryType=PREFERENCE)``
        returns only ``["vegan"]``.
        """
        await self._add(
            testDatabase,
            content="fact-geo",
            tags=["geo"],
            memoryType=MemoryType.FACT,
        )
        await self._add(
            testDatabase,
            content="pref-vegan",
            tags=["vegan"],
            memoryType=MemoryType.PREFERENCE,
        )

        factTags = await testDatabase.userMemories.getDistinctTags(CHAT_ID, USER_ID, MemoryType.FACT)
        assert factTags == ["geo"]

        prefTags = await testDatabase.userMemories.getDistinctTags(CHAT_ID, USER_ID, MemoryType.PREFERENCE)
        assert prefTags == ["vegan"]

        # No type filter → union of both.
        allTags = await testDatabase.userMemories.getDistinctTags(CHAT_ID, USER_ID)
        assert allTags == ["geo", "vegan"]

    async def test_getDistinctTags_emptyReturnsEmptyList(self, testDatabase: Database) -> None:
        """No memories (or only tag-less memories) → empty list, never raises."""
        # No memories at all.
        assert await testDatabase.userMemories.getDistinctTags(CHAT_ID, USER_ID) == []

        # Memory with empty tags list.
        await self._add(testDatabase, content="tagless", tags=[])
        assert await testDatabase.userMemories.getDistinctTags(CHAT_ID, USER_ID) == []

    async def test_getDistinctTags_scopedToUserAndChat(self, testDatabase: Database) -> None:
        """getDistinctTags never leaks tags across users or chats."""
        await self._add(testDatabase, chatId=1, userId=100, content="a", tags=["alpha"])
        await self._add(testDatabase, chatId=1, userId=200, content="b", tags=["beta"])
        await self._add(testDatabase, chatId=2, userId=100, content="c", tags=["gamma"])

        assert await testDatabase.userMemories.getDistinctTags(1, 100) == ["alpha"]
        assert await testDatabase.userMemories.getDistinctTags(1, 200) == ["beta"]
        assert await testDatabase.userMemories.getDistinctTags(2, 100) == ["gamma"]

    async def test_getDistinctTags_skipsMalformedJsonTags(self, testDatabase: Database) -> None:
        """Rows with a non-JSON ``tags`` value are skipped, not crashed on.

        Seeds a valid memory tagged ``["a", "b"]``, then corrupts a second
        row's ``tags`` column to the literal string ``'not-json'`` via raw
        SQL (simulating a backfill gone wrong / hand-edited row). Asserts
        ``getDistinctTags`` returns only the valid tags and does not raise.
        """
        await self._add(testDatabase, content="good", tags=["a", "b"])
        badId = await self._add(testDatabase, content="corrupted", tags=["x", "y"])

        # Corrupt the second row's tags column to a non-JSON string.
        sqlProvider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
        await sqlProvider.execute(
            "UPDATE user_memories SET tags = :tags WHERE memory_id = :memoryId",
            {"tags": "not-json", "memoryId": badId},
        )

        result = await testDatabase.userMemories.getDistinctTags(CHAT_ID, USER_ID)

        assert result == ["a", "b"]

    async def test_getDistinctTags_skipsNullTags(self, testDatabase: Database) -> None:
        """Rows with an empty ``tags`` value are skipped gracefully.

        Seeds a valid memory tagged ``["a", "b"]``, then blanks a second
        row's ``tags`` column to ``''`` via raw SQL (the column is ``NOT
        NULL``, so this exercises the realistic empty-string case rather
        than a literal NULL). Asserts ``getDistinctTags`` returns only the
        valid tags and does not raise.
        """
        await self._add(testDatabase, content="good", tags=["a", "b"])
        nullId = await self._add(testDatabase, content="blanked", tags=["x", "y"])

        # Blank the second row's tags column to an empty string.
        sqlProvider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
        await sqlProvider.execute(
            "UPDATE user_memories SET tags = :tags WHERE memory_id = :memoryId",
            {"tags": "", "memoryId": nullId},
        )

        result = await testDatabase.userMemories.getDistinctTags(CHAT_ID, USER_ID)

        assert result == ["a", "b"]


class TestUserMemoriesVectorLayer:
    """Phase-1b behavioural coverage: search, embedding persistence, regeneration.

    These tests exercise the vec0 vector layer (``searchMemories``
    semantic mode, ``saveMemoryEmbedding``, ``deleteMemoryEmbedding``,
    ``getMemoriesWithoutEmbeddings``, ``deleteObsoleteMemoryEmbeddings``).
    Tests that need vec0 skip cleanly when sqlite-vec is not available
    (mirror ``test_chat_embeddings.py:244-247``). Filter-only
    ``searchMemories`` and the regeneration queries work without vec0
    and run unconditionally.
    """

    @staticmethod
    async def _add(
        db: Database,
        *,
        chatId: int = CHAT_ID,
        userId: int = USER_ID,
        memoryType: str = MemoryType.FACT,
        content: str = "some content",
        tags: list[str] | None = None,
        permanent: bool = False,
        threadId: int | None = None,
        source: UserMemorySource = UserMemorySource.REFINEMENT,
        embedding: list[float] | None = None,
        embeddingModel: str | None = None,
    ) -> str:
        """Insert a memory and return its generated id."""
        memoryId = _newMemoryId()
        await db.userMemories.addMemory(
            chatId=chatId,
            userId=userId,
            memoryId=memoryId,
            type=memoryType,
            content=content,
            tags=tags if tags is not None else [],
            permanent=permanent,
            threadId=threadId,
            source=source,
            embedding=embedding,
            embeddingModel=embeddingModel,
        )
        return memoryId

    @staticmethod
    def _vecAvailable(testDatabase: Database, chatId: int = CHAT_ID) -> bool:
        """Check whether vec0 is usable in this test environment (sync wrapper)."""
        return _SQLITE_VEC_AVAILABLE

    ###
    # searchMemories — filter-only mode
    ###
    async def test_searchMemories_filterOnly(self, testDatabase: Database) -> None:
        """Filter-only mode returns matching rows with score = 0.0; works without vec0.

        Seeds memories with different type/tags/threadId, then queries
        with ``queryEmbedding=None`` and various filter combinations.
        Every returned row must have ``score == 0.0``.
        """
        await self._add(
            testDatabase,
            content="pref1",
            tags=["vegan"],
            memoryType=MemoryType.PREFERENCE,
            threadId=5,
        )
        await self._add(
            testDatabase,
            content="fact1",
            tags=["geo"],
            memoryType=MemoryType.FACT,
            threadId=5,
        )
        await self._add(
            testDatabase,
            content="pref2",
            tags=["dark-mode"],
            memoryType=MemoryType.PREFERENCE,
            threadId=9,
        )

        # Filter by type.
        prefs = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, type=MemoryType.PREFERENCE, embeddingModel=None, limit=10
        )
        assert len(prefs) == 2
        assert {r["content"] for r in prefs} == {"pref1", "pref2"}
        for r in prefs:
            assert r["score"] == 0.0

        # Filter by tag.
        vegan = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, tags=["vegan"], embeddingModel=None, limit=10
        )
        assert len(vegan) == 1
        assert vegan[0]["content"] == "pref1"
        assert vegan[0]["score"] == 0.0

        # Filter by threadId.
        thread5 = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, threadId=5, embeddingModel=None, limit=10
        )
        assert {r["content"] for r in thread5} == {"pref1", "fact1"}

        # Filter by permanent.
        await self._add(
            testDatabase,
            content="permanent-fact",
            permanent=True,
            threadId=None,
            memoryType=MemoryType.FACT,
        )
        permOnly = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, permanent=True, embeddingModel=None, limit=10
        )
        assert len(permOnly) == 1
        assert permOnly[0]["content"] == "permanent-fact"

    async def test_searchMemories_scoping(self, testDatabase: Database) -> None:
        """searchMemories never leaks across users or chats."""
        # User A in chat 1.
        await self._add(testDatabase, chatId=1, userId=100, content="userA-chat1", threadId=5)
        # User B in the same chat.
        await self._add(testDatabase, chatId=1, userId=200, content="userB-chat1", threadId=5)
        # User A in a different chat.
        await self._add(testDatabase, chatId=2, userId=100, content="userA-chat2", threadId=5)

        # User A in chat 1 sees only their own memory.
        resultA = await testDatabase.userMemories.searchMemories(1, 100, embeddingModel=None, limit=10)
        assert len(resultA) == 1
        assert resultA[0]["content"] == "userA-chat1"

        # User B in chat 1 sees only their own memory.
        resultB = await testDatabase.userMemories.searchMemories(1, 200, embeddingModel=None, limit=10)
        assert len(resultB) == 1
        assert resultB[0]["content"] == "userB-chat1"

        # User A in chat 2 sees only their chat-2 memory.
        resultA2 = await testDatabase.userMemories.searchMemories(2, 100, embeddingModel=None, limit=10)
        assert len(resultA2) == 1
        assert resultA2[0]["content"] == "userA-chat2"

    async def test_searchMemories_offsetPaginates(self, testDatabase: Database) -> None:
        """``offset`` skips the first N rows; combined with ``limit`` it pages results.

        Seeds 12 fact memories (all same type/thread) and asserts that
        ``offset=0, limit=8`` returns the first 8 and ``offset=8, limit=8``
        returns the remaining 4 — proving the offset threads through to the
        ``applyPagination`` call in the filter-only path.
        """
        for i in range(12):
            await self._add(testDatabase, content=f"fact-{i:02d}", memoryType=MemoryType.FACT, threadId=5)

        firstPage = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, type=MemoryType.FACT, threadId=5, embeddingModel=None, limit=8, offset=0
        )
        assert len(firstPage) == 8

        secondPage = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, type=MemoryType.FACT, threadId=5, embeddingModel=None, limit=8, offset=8
        )
        assert len(secondPage) == 4
        # No overlap between the two pages.
        firstIds = {r["memory_id"] for r in firstPage}
        secondIds = {r["memory_id"] for r in secondPage}
        assert firstIds.isdisjoint(secondIds)

    async def test_searchMemories_threadIdNoneReturnsAllThreads(self, testDatabase: Database) -> None:
        """``threadId=None`` returns memories from ALL threads (no thread filter).

        Seeds memories in three thread scopes — thread 0, thread 99, and
        cross-thread ``None`` — then asserts a single ``threadId=None``
        query returns all three. This is the scoping the
        ``/memory_config`` wizard relies on (it has no thread picker).
        """
        await self._add(testDatabase, content="thread-0", memoryType=MemoryType.FACT, threadId=0)
        await self._add(testDatabase, content="thread-99", memoryType=MemoryType.FACT, threadId=99)
        await self._add(testDatabase, content="cross-thread", memoryType=MemoryType.FACT, threadId=None)

        allThreads = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, threadId=None, embeddingModel=None, limit=10
        )
        contents = {r["content"] for r in allThreads}
        assert contents == {"thread-0", "thread-99", "cross-thread"}

    async def test_getMemoryReturnsRowByPk(self, testDatabase: Database) -> None:
        """``getMemory`` fetches a single row by the full (chat, user, memoryId) key.

        Returns the matching ``UserMemoryDict`` or ``None`` when absent.
        """
        memId = await self._add(testDatabase, content="fetchable", memoryType=MemoryType.PREFERENCE, threadId=7)

        fetched = await testDatabase.userMemories.getMemory(CHAT_ID, USER_ID, memId)
        assert fetched is not None
        assert fetched["memory_id"] == memId
        assert fetched["content"] == "fetchable"
        assert fetched["type"] == MemoryType.PREFERENCE

        # Wrong user → None.
        assert await testDatabase.userMemories.getMemory(CHAT_ID, 999, memId) is None
        # Wrong memoryId → None.
        assert await testDatabase.userMemories.getMemory(CHAT_ID, USER_ID, "nope") is None

    ###
    # searchMemories — semantic mode (requires vec0)
    ###
    async def test_searchMemories_semantic(self, testDatabase: Database) -> None:
        """Semantic mode ranks by cosine similarity; top match has the highest score.

        Embeds 3 memories with distinct orthogonal-ish vectors, queries
        with one vector, and asserts the matching memory ranks first
        with ``score > 0`` and results are ordered descending.
        """
        if not self._vecAvailable(testDatabase):
            pytest.skip("sqlite-vec not installed")

        chatId = CHAT_ID
        userId = USER_ID
        model = "test-embed"

        # Three memories with distinct content vectors.
        idA = await self._add(testDatabase, content="apples", threadId=5)
        idB = await self._add(testDatabase, content="bananas", threadId=5)
        idC = await self._add(testDatabase, content="cherries", threadId=5)

        # Embed A with [1,0,0], B with [0,1,0], C with [0,0,1].
        okA = await testDatabase.userMemories.saveMemoryEmbedding(chatId, userId, idA, [1.0, 0.0, 0.0], model)
        okB = await testDatabase.userMemories.saveMemoryEmbedding(chatId, userId, idB, [0.0, 1.0, 0.0], model)
        okC = await testDatabase.userMemories.saveMemoryEmbedding(chatId, userId, idC, [0.0, 0.0, 1.0], model)
        assert okA and okB and okC

        # Query for A's vector → A should rank first with score ≈ 1.0.
        results = await testDatabase.userMemories.searchMemories(
            chatId, userId, queryEmbedding=[1.0, 0.0, 0.0], embeddingModel=model, limit=3
        )

        assert len(results) == 3
        # Top match is A.
        assert results[0]["memory_id"] == idA
        assert results[0]["score"] == pytest.approx(1.0, abs=1e-6)
        # Scores are in descending order.
        assert results[0]["score"] >= results[1]["score"] >= results[2]["score"]
        # All scores are in [0, 1].
        for r in results:
            assert 0.0 <= r["score"] <= 1.0

    async def test_searchMemories_semanticWithTags(self, testDatabase: Database) -> None:
        """Regression (C1): semantic search + tags filter returns ONLY matching memories.

        Seeds two memories with identical content ("vegan") but different
        tags ("diet" vs "other"), embeds both with the same vector, then
        queries semantic mode with ``tags=["diet"]``. Before the C1 fix
        the tag params were bound into ``filterParams`` (the vec0 dict)
        instead of ``fetchParams`` (the JOIN-query dict), causing a
        sqlite3 ProgrammingError that was swallowed by the broad
        ``except Exception`` — the method returned ``[]`` instead of the
        correctly-filtered non-empty result.
        """
        if not self._vecAvailable(testDatabase):
            pytest.skip("sqlite-vec not installed")

        chatId = CHAT_ID
        userId = USER_ID
        model = "m"

        # Two memories with identical content but different tags.
        idDiet = await self._add(testDatabase, content="vegan", tags=["diet"], threadId=5)
        idOther = await self._add(testDatabase, content="vegan", tags=["other"], threadId=5)

        # Both embedded with the same vector — without the tag filter both would match.
        okDiet = await testDatabase.userMemories.saveMemoryEmbedding(chatId, userId, idDiet, [1.0, 0.0], model)
        okOther = await testDatabase.userMemories.saveMemoryEmbedding(chatId, userId, idOther, [1.0, 0.0], model)
        assert okDiet and okOther

        # Semantic search filtered by tags=["diet"] must return ONLY the diet memory.
        results = await testDatabase.userMemories.searchMemories(
            chatId, userId, queryEmbedding=[1.0, 0.0], tags=["diet"], embeddingModel=model, limit=5
        )

        assert len(results) == 1, f"Expected 1 result, got {len(results)} (C1: tag params bound to wrong dict)"
        assert results[0]["memory_id"] == idDiet
        assert results[0]["score"] > 0.0

    async def test_searchMemories_semantic_scoping(self, testDatabase: Database) -> None:
        """Semantic mode honours (chat, user) scoping — no cross-user leaks.

        Embeds memories for two users in the same chat; querying as user
        A must not surface user B's memories even when the query vector
        is identical.
        """
        if not self._vecAvailable(testDatabase):
            pytest.skip("sqlite-vec not installed")

        chatId = CHAT_ID
        model = "test-embed"

        idA = await self._add(testDatabase, chatId=chatId, userId=100, content="A", threadId=5)
        idB = await self._add(testDatabase, chatId=chatId, userId=200, content="B", threadId=5)

        await testDatabase.userMemories.saveMemoryEmbedding(chatId, 100, idA, [1.0, 0.0], model)
        await testDatabase.userMemories.saveMemoryEmbedding(chatId, 200, idB, [1.0, 0.0], model)

        resultsA = await testDatabase.userMemories.searchMemories(
            chatId, 100, queryEmbedding=[1.0, 0.0], embeddingModel=model, limit=5
        )
        resultsB = await testDatabase.userMemories.searchMemories(
            chatId, 200, queryEmbedding=[1.0, 0.0], embeddingModel=model, limit=5
        )

        assert len(resultsA) == 1 and resultsA[0]["memory_id"] == idA
        assert len(resultsB) == 1 and resultsB[0]["memory_id"] == idB

    async def test_searchMemories_semantic_returnsEmptyWhenUnsupported(self, testDatabase: Database) -> None:
        """When vec0 is unsupported, semantic mode returns [] (never raises).

        This test patches ``isVectorSearchSupported`` to False on the
        CONCRETE provider class to verify the guard path unconditionally
        (even when sqlite-vec IS installed in the test environment).
        Patching must target ``SQLite3Provider``, not ``BaseSQLProvider``:
        the concrete class overrides the method, so a base-class patch is
        shadowed by the subclass's own binding via the MRO.
        """
        idA = await self._add(testDatabase, content="x", threadId=5)
        # Write an embedding (this will be skipped if vec0 isn't
        # available; the test still validates the search guard).
        if self._vecAvailable(testDatabase):
            await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idA, [1.0, 0.0], "m")

        # Patch on the concrete provider class — the repository resolves
        # the provider via ``manager.getProvider(...).isVectorSearchSupported()``,
        # and the instance is a ``SQLite3Provider`` whose own method
        # binding wins over any base-class patch.
        with patch.object(
            SQLite3Provider,
            "isVectorSearchSupported",
            new=AsyncMock(return_value=False),
        ):
            results = await testDatabase.userMemories.searchMemories(
                CHAT_ID, USER_ID, queryEmbedding=[1.0, 0.0], embeddingModel="m", limit=5
            )

        assert results == []

    async def test_semanticSearchMemories_forwardsDataSourceToResolver(self, testDatabase: Database) -> None:
        """``_semanticSearchMemories`` (via ``searchMemories``) forwards ``dataSource`` to the resolver.

        Pins the multi-source routing contract on the semantic search
        path: when ``searchMemories`` is given a ``queryEmbedding`` it
        routes to ``_semanticSearchMemories``, which must forward the
        ``dataSource`` kwarg to the injected resolver so the underlying
        ``getOrCreateModelId`` can route its provider acquisition. The
        resolver is invoked before the vec0 table check, so this test
        is robust to the ``vec_user_memories_{dim}`` table being absent
        — but it still requires vec0 to be advertised as supported by
        the provider (otherwise the path short-circuits earlier).

        Args:
            testDatabase: Fresh in-memory database with migrations applied.
        """
        if not self._vecAvailable(testDatabase):
            pytest.skip("sqlite-vec not available; semantic-mode tests require vec0")

        # Seed at least one user_memories row so the search has context.
        await self._add(testDatabase, content="route-me", threadId=5)
        resolverMock = AsyncMock(return_value=42)
        repo = UserMemoriesRepository(testDatabase.manager, modelIdResolver=resolverMock)

        # dim=2 — no vec0 table is ever created at this dimension, so
        # the search returns [] AFTER the resolver is invoked.
        await repo.searchMemories(
            CHAT_ID, USER_ID, queryEmbedding=[0.1, 0.2], embeddingModel="m", dataSource="custom-src"
        )

        resolverMock.assert_awaited_once_with("m", 2, dataSource="custom-src")

    ###
    # saveMemoryEmbedding — lazy vec0 creation + provenance columns
    ###
    async def test_saveMemoryEmbedding_lazyVec0Create(self, testDatabase: Database) -> None:
        """First write creates the vec0 table; second write reuses it; columns set."""
        if not self._vecAvailable(testDatabase):
            pytest.skip("sqlite-vec not installed")

        idA = await self._add(testDatabase, content="A", threadId=5)
        idB = await self._add(testDatabase, content="B", threadId=5)

        sqlProvider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=True)

        # Before first write: no vec0 table exists.
        tablesBefore = await sqlProvider.listTables("vec_user_memories_%")
        realTablesBefore = [t for t in tablesBefore if t.startswith("vec_user_memories_")]
        assert not any("vec_user_memories_3" in t for t in realTablesBefore)

        # First write → table created, embedding columns set.
        ok = await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idA, [1.0, 0.0, 0.0], "modelA")
        assert ok is True

        tablesAfter = await sqlProvider.listTables("vec_user_memories_%")
        realTablesAfter = [t for t in tablesAfter if "vec_user_memories_3" in t]
        assert realTablesAfter, "Expected vec_user_memories_3 table to exist after first write"

        # Provenance column set on user_memories: model_id resolves ("modelA", 3).
        expectedModelId = await testDatabase.embeddingModels.getOrCreateModelId("modelA", 3)
        rows = await testDatabase.userMemories.getLatestMemories(CHAT_ID, USER_ID, threadId=5)
        rowA = next(r for r in rows if r["memory_id"] == idA)
        assert rowA["model_id"] == expectedModelId

        # Second write → table reused (no new table created).
        ok2 = await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idB, [0.0, 1.0, 0.0], "modelA")
        assert ok2 is True

        tablesAfterSecond = await sqlProvider.listTables("vec_user_memories_%")
        realTablesAfterSecond = [t for t in tablesAfterSecond if "vec_user_memories_3" in t]
        assert len(realTablesAfterSecond) == len(realTablesAfter), "No duplicate vec0 tables"

        rows2 = await testDatabase.userMemories.getLatestMemories(CHAT_ID, USER_ID, threadId=5)
        rowB2 = next(r for r in rows2 if r["memory_id"] == idB)
        assert rowB2["model_id"] == expectedModelId

    async def test_saveMemoryEmbedding_crossThreadNullThreadId(self, testDatabase: Database) -> None:
        """A memory with ``thread_id IS NULL`` must be embeddable and searchable.

        Cross-thread permanent memories (``thread_id IS NULL`` — e.g.
        migration_020 backfill A from the legacy ``user_data`` table) must
        survive the vec0 upsert and remain semantically searchable. The
        vec0 table no longer carries a ``thread_id`` column (it was
        write-only and never read back), so ``thread_id`` is never
        involved in the vec0 write path; the authoritative
        ``user_memories.thread_id`` stays ``NULL`` and the JOIN step on
        ``user_memories.thread_id`` remains the filter source.
        """
        if not self._vecAvailable(testDatabase):
            pytest.skip("sqlite-vec not installed")

        # Cross-thread permanent fact — thread_id NULL (mirrors migration_020 backfill A).
        memoryId = await self._add(
            testDatabase,
            content="cross-thread fact",
            permanent=True,
            threadId=None,
        )

        ok = await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, memoryId, [1.0, 0.0, 0.0], "modelA")
        assert ok is True, "saveMemoryEmbedding must succeed for NULL-thread memories"

        # Provenance column set on user_memories (only happens on vec0 success).
        expectedModelId = await testDatabase.embeddingModels.getOrCreateModelId("modelA", 3)
        perm = await testDatabase.userMemories.getPermanentMemories(CHAT_ID, USER_ID, threadId=0)
        row = next(r for r in perm if r["memory_id"] == memoryId)
        assert row["thread_id"] is None, "relational thread_id must remain NULL (vec0 no longer touches thread_id)"
        assert row["model_id"] == expectedModelId

        # Semantic search (no thread filter) must find the cross-thread memory.
        results = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, queryEmbedding=[1.0, 0.0, 0.0], embeddingModel="modelA", limit=5
        )
        assert any(r["memory_id"] == memoryId for r in results), "cross-thread memory must be searchable"

    ###
    # deleteMemoryEmbedding
    ###
    async def test_deleteMemoryEmbedding(self, testDatabase: Database) -> None:
        """deleteMemoryEmbedding removes the vec0 row; returns True."""
        if not self._vecAvailable(testDatabase):
            pytest.skip("sqlite-vec not installed")

        idA = await self._add(testDatabase, content="A", threadId=5)
        await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idA, [1.0, 0.0, 0.0], "modelA")

        # Semantic search finds it.
        before = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, queryEmbedding=[1.0, 0.0, 0.0], embeddingModel="modelA", limit=5
        )
        assert len(before) == 1

        ok = await testDatabase.userMemories.deleteMemoryEmbedding(CHAT_ID, USER_ID, idA)
        assert ok is True

        # After delete, semantic search returns [] (vec0 row gone).
        after = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, queryEmbedding=[1.0, 0.0, 0.0], embeddingModel="modelA", limit=5
        )
        assert after == []

    async def test_deleteMemoryEmbedding_noTable(self, testDatabase: Database) -> None:
        """deleteMemoryEmbedding returns True (no-op) when no vec0 table exists."""
        if not self._vecAvailable(testDatabase):
            pytest.skip("sqlite-vec not installed")

        idA = await self._add(testDatabase, content="A", threadId=5)
        # No saveMemoryEmbedding call → no vec0 table created.

        ok = await testDatabase.userMemories.deleteMemoryEmbedding(CHAT_ID, USER_ID, idA)
        assert ok is True

    ###
    # getMemoriesWithoutEmbeddings
    ###
    async def test_getMemoriesWithoutEmbeddings(self, testDatabase: Database) -> None:
        """Returns never-embedded + stale-model memories; not current-model."""
        idFresh = await self._add(testDatabase, content="fresh", threadId=5)
        idStale = await self._add(testDatabase, content="stale", threadId=5)
        idCurrent = await self._add(testDatabase, content="current", threadId=5)

        if self._vecAvailable(testDatabase):
            # Embed stale with old model, current with new model. The repo
            # resolves the model name to ``model_id`` internally via the
            # injected resolver (``testDatabase.embeddingModels.getOrCreateModelId``).
            await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idStale, [1.0, 0.0], "old-model")
            await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idCurrent, [1.0, 0.0], "new-model")
        else:
            # Without vec0, stamp ``model_id`` directly via raw SQL (the
            # repo resolves the same id through ``testDatabase.embeddingModels``).
            staleId = await testDatabase.embeddingModels.getOrCreateModelId("old-model", 2)
            currentId = await testDatabase.embeddingModels.getOrCreateModelId("new-model", 2)
            sqlProvider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
            await sqlProvider.execute(
                "UPDATE user_memories SET model_id = :mid "
                "WHERE chat_id = :c AND user_id = :u AND memory_id = :memoryId",
                {"c": CHAT_ID, "u": USER_ID, "memoryId": idStale, "mid": staleId},
            )
            await sqlProvider.execute(
                "UPDATE user_memories SET model_id = :mid "
                "WHERE chat_id = :c AND user_id = :u AND memory_id = :memoryId",
                {"c": CHAT_ID, "u": USER_ID, "memoryId": idCurrent, "mid": currentId},
            )

        # Query with currentModel="new-model": surfaces fresh (NULL) + stale ("old-model").
        stale = await testDatabase.userMemories.getMemoriesWithoutEmbeddings(
            CHAT_ID, modelName="new-model", dimensions=2, limit=10
        )
        staleIds = {r["memory_id"] for r in stale}
        assert idFresh in staleIds  # never embedded
        assert idStale in staleIds  # stale model
        assert idCurrent not in staleIds  # current model

    async def test_getMemoriesWithoutEmbeddings_filtersByDimensions(self, testDatabase: Database) -> None:
        """Pin dimension-mismatch detection independent of embedding model.

        Two memories share the same ``models.model`` name ("modelA") but
        differ in ``models.dimensions`` (384 vs 1024). Passing
        ``dimensions=1024`` must surface only the 384-dim row as stale;
        passing ``dimensions=None`` (the default) omits the dimension
        check, so a matching-model row is never returned even when its
        dimensions differ. This pins the ``None``-default
        behaviour-preserving property and guards against the
        dimension-filter clause regressing out of the WHERE ``OR(...)``.
        """
        idLow = await self._add(testDatabase, content="low-dim", threadId=5)
        idHigh = await self._add(testDatabase, content="high-dim", threadId=5)

        if self._vecAvailable(testDatabase):
            # Same model, different embedding lengths -> different dimensions.
            await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idLow, [0.0] * 384, "modelA")
            await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idHigh, [0.0] * 1024, "modelA")
        else:
            # Without vec0, stamp ``model_id`` directly via raw SQL.
            lowId = await testDatabase.embeddingModels.getOrCreateModelId("modelA", 384)
            highId = await testDatabase.embeddingModels.getOrCreateModelId("modelA", 1024)
            sqlProvider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
            await sqlProvider.execute(
                "UPDATE user_memories SET model_id = :mid "
                "WHERE chat_id = :c AND user_id = :u AND memory_id = :memoryId",
                {"c": CHAT_ID, "u": USER_ID, "memoryId": idLow, "mid": lowId},
            )
            await sqlProvider.execute(
                "UPDATE user_memories SET model_id = :mid "
                "WHERE chat_id = :c AND user_id = :u AND memory_id = :memoryId",
                {"c": CHAT_ID, "u": USER_ID, "memoryId": idHigh, "mid": highId},
            )

        # dimensions=1024: the 384-dim row is stale (mismatch); the 1024-dim row is current.
        staleLow = await testDatabase.userMemories.getMemoriesWithoutEmbeddings(
            CHAT_ID, modelName="modelA", dimensions=1024, limit=10
        )
        staleLowIds = {r["memory_id"] for r in staleLow}
        assert idLow in staleLowIds  # dimension mismatch -> stale
        assert idHigh not in staleLowIds  # dimensions match -> current

        # dimensions=None: dimension check omitted; both rows match the model -> neither stale.
        noneStale = await testDatabase.userMemories.getMemoriesWithoutEmbeddings(
            CHAT_ID, modelName="modelA", dimensions=None, limit=10
        )
        noneStaleIds = {r["memory_id"] for r in noneStale}
        assert idLow not in noneStaleIds
        assert idHigh not in noneStaleIds

    async def test_getMemoriesWithoutEmbeddings_forwardsDataSourceToResolver(self, testDatabase: Database) -> None:
        """``getMemoriesWithoutEmbeddings`` forwards ``dataSource`` to the resolver.

        Pins the multi-source routing contract on the (modelName,
        dimensions) branch — the only branch that resolves a model_id
        via the injected resolver. A future regression that drops the
        ``dataSource=dataSource`` kwarg from the resolver call breaks
        the multi-source deployment model silently; this test catches
        that.

        Args:
            testDatabase: Fresh in-memory database with migrations applied.
        """
        # Seed at least one user_memories row so the query has something to scan.
        await self._add(testDatabase, content="route-me", threadId=5)
        resolverMock = AsyncMock(return_value=42)
        repo = UserMemoriesRepository(testDatabase.manager, modelIdResolver=resolverMock)

        await repo.getMemoriesWithoutEmbeddings(CHAT_ID, modelName="m", dimensions=2, dataSource="custom-src")

        resolverMock.assert_awaited_once_with("m", 2, dataSource="custom-src")

    ###
    # deleteObsoleteMemoryEmbeddings
    ###
    async def test_deleteObsoleteMemoryEmbeddings(self, testDatabase: Database) -> None:
        """Stale rows have ``model_id`` reset; current-model rows untouched."""
        idStale = await self._add(testDatabase, content="stale", threadId=5)
        idCurrent = await self._add(testDatabase, content="current", threadId=5)

        sqlProvider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)

        if self._vecAvailable(testDatabase):
            await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idStale, [1.0, 0.0], "old-model")
            await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idCurrent, [1.0, 0.0], "new-model")
        else:
            # Manually stamp ``model_id`` via raw SQL.
            staleId = await testDatabase.embeddingModels.getOrCreateModelId("old-model", 2)
            currentId = await testDatabase.embeddingModels.getOrCreateModelId("new-model", 2)
            await sqlProvider.execute(
                "UPDATE user_memories SET model_id = :mid "
                "WHERE chat_id = :c AND user_id = :u AND memory_id = :memoryId",
                {"c": CHAT_ID, "u": USER_ID, "memoryId": idStale, "mid": staleId},
            )
            await sqlProvider.execute(
                "UPDATE user_memories SET model_id = :mid "
                "WHERE chat_id = :c AND user_id = :u AND memory_id = :memoryId",
                {"c": CHAT_ID, "u": USER_ID, "memoryId": idCurrent, "mid": currentId},
            )

        # Call with currentModel="new-model", currentDimensions=2.
        # Stale (model="old-model") should be reset; current untouched.
        count = await testDatabase.userMemories.deleteObsoleteMemoryEmbeddings(
            CHAT_ID, "new-model", currentDimensions=2
        )
        assert count == 1

        # Verify columns: stale reset, current preserved.
        expectedCurrentId = await testDatabase.embeddingModels.getOrCreateModelId("new-model", 2)
        rows = await testDatabase.userMemories.getLatestMemories(CHAT_ID, USER_ID, threadId=5)
        staleRow = next(r for r in rows if r["memory_id"] == idStale)
        currentRow = next(r for r in rows if r["memory_id"] == idCurrent)
        assert staleRow["model_id"] is None
        assert currentRow["model_id"] == expectedCurrentId

        # After reset, getMemoriesWithoutEmbeddings picks up the stale row.
        stale = await testDatabase.userMemories.getMemoriesWithoutEmbeddings(CHAT_ID, modelName="new-model", limit=10)
        staleIds = {r["memory_id"] for r in stale}
        assert idStale in staleIds
        assert idCurrent not in staleIds

    async def test_deleteObsoleteMemoryEmbeddings_unknownModelClearsAll(self, testDatabase: Database) -> None:
        """When *currentModel* is unseen by ``models``, every previously-stored ``model_id`` is stale.

        ``deleteObsoleteMemoryEmbeddings`` resolves
        ``(currentModel, currentDimensions)`` via
        :meth:`getOrCreateModelId`, which is probe-then-insert: an
        unseen model name *allocates* a brand-new ``model_id`` rather
        than returning no match. The stale-row predicate is then
        ``model_id != newId``, so every live row whose provenance is
        the previously-seeded ``"some-model"`` matches and gets reset.
        The never-embedded row (``model_id IS NULL``) is excluded by
        the non-NULL predicate and left untouched.
        """
        idA = await self._add(testDatabase, content="embedded-A", threadId=5)
        idB = await self._add(testDatabase, content="embedded-B", threadId=5)
        idFresh = await self._add(testDatabase, content="fresh", threadId=5)

        someId = await testDatabase.embeddingModels.getOrCreateModelId("some-model", 3)
        sqlProvider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
        for memoryId in (idA, idB):
            await sqlProvider.execute(
                "UPDATE user_memories SET model_id = :mid "
                "WHERE chat_id = :c AND user_id = :u AND memory_id = :memoryId",
                {"c": CHAT_ID, "u": USER_ID, "memoryId": memoryId, "mid": someId},
            )

        # "never-seen-model" is allocated a fresh model_id by getOrCreateModelId;
        # the predicate ``model_id != newId`` then matches both seeded "some-model" rows.
        count = await testDatabase.userMemories.deleteObsoleteMemoryEmbeddings(
            CHAT_ID, "never-seen-model", currentDimensions=1
        )
        assert count == 2, f"both embedded rows should be reset, got {count}"

        async def _modelId(mid: str) -> int | None:
            row = await sqlProvider.executeFetchOne(
                "SELECT model_id FROM user_memories WHERE memory_id = :mid",
                {"mid": mid},
            )
            return int(row["model_id"]) if (row is not None and row["model_id"] is not None) else None

        assert await _modelId(idA) is None
        assert await _modelId(idB) is None
        # The never-embedded row is untouched (already NULL, not counted).
        assert await _modelId(idFresh) is None

    async def test_getMemoriesWithoutEmbeddings_modelNameNone(self, testDatabase: Database) -> None:
        """With ``modelName=None``, the helper returns memories where ``model_id IS NULL``.

        This is the "fresh backfill" case — memories that have never been
        embedded under any model. Memories with a non-NULL ``model_id``
        are excluded regardless of which model produced them. Mirrors
        ``test_chat_embeddings.py::test_getMessagesWithoutEmbeddings_modelNameNone``.
        """
        idFresh = await self._add(testDatabase, content="fresh", threadId=5)
        idAlsoFresh = await self._add(testDatabase, content="also-fresh", threadId=5)
        idEmbedded = await self._add(testDatabase, content="embedded", threadId=5)

        # Stamp the third one as embedded.
        someId = await testDatabase.embeddingModels.getOrCreateModelId("anything", 3)
        sqlProvider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
        await sqlProvider.execute(
            "UPDATE user_memories SET model_id = :mid " "WHERE chat_id = :c AND user_id = :u AND memory_id = :memoryId",
            {"c": CHAT_ID, "u": USER_ID, "memoryId": idEmbedded, "mid": someId},
        )

        results = await testDatabase.userMemories.getMemoriesWithoutEmbeddings(CHAT_ID, modelName=None, limit=10)
        resultIds = {r["memory_id"] for r in results}
        assert resultIds == {idFresh, idAlsoFresh}
        assert idEmbedded not in resultIds

    ###
    # Gate-1 regression tests
    ###
    async def test_saveMemoryEmbedding_vec0WriteFailure_strandProof(self, testDatabase: Database) -> None:
        """Regression (Fix 1): a vec0 write failure leaves ``model_id`` NULL.

        When the vec0 INSERT/table-create fails, ``saveMemoryEmbedding``
        must return ``False`` WITHOUT setting the provenance column. If it
        set ``model_id`` anyway, the memory would be marked
        embedded but carry no searchable vector — and
        ``getMemoriesWithoutEmbeddings`` would never surface it (vec0 is
        the sole embedding store). Leaving ``model_id = NULL``
        makes the regen cron retry.
        """
        if not self._vecAvailable(testDatabase):
            pytest.skip("sqlite-vec not installed")

        idA = await self._add(testDatabase, content="A", threadId=5)

        # Force the vec0 lazy-table creation to fail so the whole vec0
        # write path raises inside _upsertVecMemoryEmbedding.
        with patch.object(
            SQLite3Provider,
            "createVectorTable",
            new=AsyncMock(side_effect=RuntimeError("vec0 table creation failed")),
        ):
            ok = await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idA, [1.0, 0.0, 0.0], "modelA")

        assert ok is False

        # Provenance NOT set — stays NULL so regen retries.
        rows = await testDatabase.userMemories.getLatestMemories(CHAT_ID, USER_ID, threadId=5)
        rowA = next(r for r in rows if r["memory_id"] == idA)
        assert rowA["model_id"] is None

    async def test_deleteMemoryEmbedding_returnsFalseWhenNoMatch(self, testDatabase: Database) -> None:
        """Regression (Fix 5): returns False when a vec0 table exists but the memory was never embedded.

        Earlier the bool was set True whenever the companion SELECT found
        a row — regardless of whether a DELETE actually ran. Now it is
        True only inside the successful DELETE branches. A vec0 table
        that exists (seeded by embedding a DIFFERENT memory) with no row
        for this memory_id must therefore return ``False``.
        """
        if not self._vecAvailable(testDatabase):
            pytest.skip("sqlite-vec not installed")

        # Embed a DIFFERENT memory so the vec0 table exists.
        idEmbedded = await self._add(testDatabase, content="embedded", threadId=5)
        await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idEmbedded, [1.0, 0.0], "modelA")

        # A memory that was never embedded (no vec0 row for it).
        idNotEmbedded = await self._add(testDatabase, content="not-embedded", threadId=5)

        ok = await testDatabase.userMemories.deleteMemoryEmbedding(CHAT_ID, USER_ID, idNotEmbedded)
        assert ok is False

    ###
    # Memory-compaction-v1 Phase 1: soft-delete + getMemoriesByIds
    ###
    async def test_softDelete_rowSurvivesAndLiveReadsSkipIt(self, testDatabase: Database) -> None:
        """After ``deleteMemory`` the row survives with ``deleted_at`` set; live reads skip it.

        Covers: getPermanentMemories, getLatestMemories, searchMemories
        (filter-only), getMemory, and getDistinctTags all skip the
        soft-deleted row; the content row itself is NOT removed.
        """
        # Permanent memory tagged "keep", ephemeral tagged "bye".
        permId = await self._add(
            testDatabase,
            content="permanent to delete",
            tags=["solo"],
            permanent=True,
            threadId=None,
            memoryType=MemoryType.FACT,
        )
        ephemeralId = await self._add(
            testDatabase,
            content="ephemeral to delete",
            tags=["bye"],
            permanent=False,
            threadId=5,
            memoryType=MemoryType.FACT,
        )

        ok = await testDatabase.userMemories.deleteMemory(CHAT_ID, USER_ID, permId)
        assert ok is True
        ok = await testDatabase.userMemories.deleteMemory(CHAT_ID, USER_ID, ephemeralId)
        assert ok is True

        # Live reads skip both.
        assert await testDatabase.userMemories.getPermanentMemories(CHAT_ID, USER_ID, threadId=0) == []
        assert await testDatabase.userMemories.getLatestMemories(CHAT_ID, USER_ID, threadId=5) == []
        search = await testDatabase.userMemories.searchMemories(CHAT_ID, USER_ID, embeddingModel=None, limit=10)
        assert search == []
        assert await testDatabase.userMemories.getMemory(CHAT_ID, USER_ID, permId) is None
        assert await testDatabase.userMemories.getMemory(CHAT_ID, USER_ID, ephemeralId) is None
        # Tags of the soft-deleted rows are excluded from the wizard picker.
        assert await testDatabase.userMemories.getDistinctTags(CHAT_ID, USER_ID) == []

        # The content rows themselves survived (getMemoriesByIds has no
        # deleted_at filter) — this proves it was a soft, not hard, delete.
        survivors = await testDatabase.userMemories.getMemoriesByIds([permId, ephemeralId])
        survivorContents = {r["content"] for r in survivors}
        assert survivorContents == {"permanent to delete", "ephemeral to delete"}

        # deleted_at is set on the surviving rows (column is plumbing not
        # exposed via UserMemoryDict; read it via the raw provider).
        sqlProvider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=True)
        permRow = await sqlProvider.executeFetchOne(
            "SELECT deleted_at FROM user_memories WHERE memory_id = :mid",
            {"mid": permId},
        )
        assert permRow is not None and permRow["deleted_at"] is not None

    async def test_deleteMemory_idempotent_returnsFalseOnReDelete(self, testDatabase: Database) -> None:
        """A second ``deleteMemory`` on the same id returns False (already soft-deleted)."""
        memoryId = await self._add(testDatabase, content="bye", threadId=5)

        ok1 = await testDatabase.userMemories.deleteMemory(CHAT_ID, USER_ID, memoryId)
        assert ok1 is True
        # Re-delete the same id → False (already soft-deleted, no live row).
        ok2 = await testDatabase.userMemories.deleteMemory(CHAT_ID, USER_ID, memoryId)
        assert ok2 is False

    async def test_deleteMemory_neverRaises(self, testDatabase: Database) -> None:
        """``deleteMemory`` swallows DB errors and returns False (never raises).

        Injects a failure by patching the provider's execute to raise, then
        asserts the contract: no exception escapes, False is returned.
        """
        memoryId = await self._add(testDatabase, content="doomed", threadId=5)

        with patch.object(
            SQLite3Provider,
            "executeFetchOne",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            ok = await testDatabase.userMemories.deleteMemory(CHAT_ID, USER_ID, memoryId)
        assert ok is False

    async def test_softDelete_clearsVec0AndProvenance(self, testDatabase: Database) -> None:
        """After soft-delete the vec0 row is gone and provenance is NULL; regen does not resurface.

        A soft-deleted memory must never be a semantic-search hit and must
        never be re-embedded by the regen cron (``getMemoriesWithoutEmbeddings``
        skips it via the ``deleted_at IS NULL`` filter even though its
        ``model_id`` is NULL).
        """
        idA = await self._add(testDatabase, content="embedded then deleted", threadId=5)

        if self._vecAvailable(testDatabase):
            await testDatabase.userMemories.saveMemoryEmbedding(CHAT_ID, USER_ID, idA, [1.0, 0.0, 0.0], "modelA")
            # Sanity: semantic search finds it before delete.
            before = await testDatabase.userMemories.searchMemories(
                CHAT_ID, USER_ID, queryEmbedding=[1.0, 0.0, 0.0], embeddingModel="modelA", limit=5
            )
            assert any(r["memory_id"] == idA for r in before)
        else:
            sqlProvider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
            staleId = await testDatabase.embeddingModels.getOrCreateModelId("modelA", 3)
            await sqlProvider.execute(
                "UPDATE user_memories SET model_id = :mid "
                "WHERE chat_id = :c AND user_id = :u AND memory_id = :memoryId",
                {"c": CHAT_ID, "u": USER_ID, "memoryId": idA, "mid": staleId},
            )

        ok = await testDatabase.userMemories.deleteMemory(CHAT_ID, USER_ID, idA)
        assert ok is True

        # Provenance nulled on the surviving row.
        survivors = await testDatabase.userMemories.getMemoriesByIds([idA])
        assert len(survivors) == 1
        assert survivors[0]["model_id"] is None

        # The regen cron does NOT resurface the soft-deleted row for re-embedding
        # (its model_id is NULL, but deleted_at IS NOT NULL means the
        # deleted_at IS NULL filter excludes it).
        stale = await testDatabase.userMemories.getMemoriesWithoutEmbeddings(CHAT_ID, modelName="modelA", limit=10)
        assert idA not in {r["memory_id"] for r in stale}

        # With vec0: the row is gone → semantic search no longer hits it.
        if self._vecAvailable(testDatabase):
            after = await testDatabase.userMemories.searchMemories(
                CHAT_ID, USER_ID, queryEmbedding=[1.0, 0.0, 0.0], embeddingModel="modelA", limit=5
            )
            assert all(r["memory_id"] != idA for r in after)

    async def test_getMemoriesByIds_returnsSoftDeleted(self, testDatabase: Database) -> None:
        """``getMemoriesByIds`` returns a soft-deleted memory (content preserved)."""
        memoryId = await self._add(testDatabase, content="historical", threadId=5)

        await testDatabase.userMemories.deleteMemory(CHAT_ID, USER_ID, memoryId)

        result = await testDatabase.userMemories.getMemoriesByIds([memoryId])
        assert len(result) == 1
        assert result[0]["memory_id"] == memoryId
        assert result[0]["content"] == "historical"

    async def test_getMemoriesByIds_ignoresChatAndUserScope(self, testDatabase: Database) -> None:
        """``getMemoriesByIds`` returns memories from different (chat, user) scopes in one call.

        UUIDs are globally unique, so no chatId/userId scoping is needed.
        """
        idA = await self._add(testDatabase, chatId=1, userId=100, content="scope-a", threadId=5)
        idB = await self._add(testDatabase, chatId=2, userId=200, content="scope-b", threadId=9)

        result = await testDatabase.userMemories.getMemoriesByIds([idA, idB])
        contents = {r["content"] for r in result}
        assert contents == {"scope-a", "scope-b"}

    async def test_getMemoriesByIds_emptyListReturnsEmptyNoQuery(self, testDatabase: Database) -> None:
        """``getMemoriesByIds([])`` returns ``[]`` immediately (no SQL round-trip)."""
        # Patch at the class level (SQLite3Provider uses __slots__, so an
        # instance-level patch raises). If the empty-list path incorrectly
        # issued SQL, this would raise the AssertionError.
        with patch.object(
            SQLite3Provider,
            "executeFetchAll",
            new=AsyncMock(side_effect=AssertionError("expected no SQL round-trip for empty memoryIds")),
        ):
            result = await testDatabase.userMemories.getMemoriesByIds([])
        assert result == []

    async def test_getMemoriesByIds_missingIdsAbsentFromResult(self, testDatabase: Database) -> None:
        """An id not in the DB is simply absent from the result list."""
        idA = await self._add(testDatabase, content="present", threadId=5)
        missingId = "deadbeefdeadbeefdeadbeefdeadbeef"

        result = await testDatabase.userMemories.getMemoriesByIds([idA, missingId])
        assert len(result) == 1
        assert result[0]["memory_id"] == idA

    async def test_getMemoriesByIds_routesChatIdToProvider(self, testDatabase: Database) -> None:
        """``getMemoriesByIds`` passes ``chatId``/``dataSource`` through to ``getProvider``.

        Routing guard: the new ``chatId`` / ``dataSource`` params must reach
        ``self.manager.getProvider`` so the by-id query hits the correct data
        source on a multi-DB deployment. A simple spy assertion is sufficient —
        the default-source fallback is exercised by every other test here.
        """
        memoryId = await self._add(testDatabase, content="route-me", threadId=5)
        original = testDatabase.manager.getProvider

        # DatabaseManager uses __slots__ (getProvider is not a slot), so
        # instance-level patch.object fails with AttributeError. Patch the
        # CLASS instead; the AsyncMock wraps the bound method so the real
        # provider is still called.
        with patch.object(
            DatabaseManager,
            "getProvider",
            new=AsyncMock(wraps=original),
        ) as spy:
            await testDatabase.userMemories.getMemoriesByIds([memoryId], chatId=CHAT_ID, dataSource="custom-src")

        # The spy must have been called with the chatId and dataSource kwargs.
        assert spy.call_count >= 1
        lastCall = spy.call_args
        assert lastCall.kwargs.get("chatId") == CHAT_ID
        assert lastCall.kwargs.get("dataSource") == "custom-src"

    ###
    # Defensive hardening regression tests
    ###
    async def test_getMemoriesByIds_autoChunksLargeIdList(self, testDatabase: Database) -> None:
        """Regression: large ID lists (> MAX_SQL_VARIABLES) are auto-chunked, not rejected.

        SQLite's default SQLITE_MAX_VARIABLE_COUNT is 999; an unbounded
        ``IN (:id0, …)`` expansion with one placeholder per input ID would
        raise ``sqlite3.OperationalError: too many SQL variables``. The fix
        chunks the input into batches of ``MAX_SQL_VARIABLES`` and unions
        the per-chunk results. This test forces a tiny chunk size via
        patching (so multiple chunks execute without inserting 900+ rows)
        and verifies every requested row is returned across the chunks.
        """
        ids: list[str] = []
        for i in range(10):
            mid = await self._add(testDatabase, content=f"chunk-{i}", threadId=5)
            ids.append(mid)

        # Force a 3-element chunk size → 4 chunks (3 + 3 + 3 + 1).
        with patch("internal.database.repositories.user_memories.MAX_SQL_VARIABLES", 3):
            result = await testDatabase.userMemories.getMemoriesByIds(ids)

        assert len(result) == 10, f"expected all 10 across chunks, got {len(result)}"
        assert {r["memory_id"] for r in result} == set(ids)

    async def test_getMemoriesByIds_chunkingPreservesMissingIdSemantics(self, testDatabase: Database) -> None:
        """Chunked fetch still drops IDs not present in the DB (per-chunk absent → global absent)."""
        ids: list[str] = []
        for i in range(6):
            mid = await self._add(testDatabase, content=f"present-{i}", threadId=5)
            ids.append(mid)
        # A missing ID interleaved with present IDs.
        request = [ids[0], "deadbeefdeadbeefdeadbeefdeadbeef", ids[5]]

        with patch("internal.database.repositories.user_memories.MAX_SQL_VARIABLES", 2):
            result = await testDatabase.userMemories.getMemoriesByIds(request)

        assert {r["memory_id"] for r in result} == {ids[0], ids[5]}

    async def test_normalizeTags_stripsBackslash_roundTripsAndMatches(self, testDatabase: Database) -> None:
        """Regression: a tag containing a backslash round-trips and matches in search.

        Tags are stored as JSON (``json.dumps`` doubles every ``\\``) and
        the LIKE-escape helper ``_escapeTagForLike`` doubles ``\\`` again
        for the LIKE pattern. A literal backslash in a tag would therefore
        never match its own stored JSON pattern. ``_normalizeTags`` now
        strips backslashes (alongside quotes) so storage and query
        normalisation stay symmetric. Before the fix this test FAILED:
        the search with the backslash tag returned ``[]``.
        """
        # Write a memory with a backslash-containing tag.
        memId = await self._add(
            testDatabase,
            content="backslash-tagged",
            tags=["diet\\low-carb"],
            threadId=5,
        )

        # The stored tag has the backslash stripped.
        rows = await testDatabase.userMemories.searchMemories(CHAT_ID, USER_ID, embeddingModel=None, limit=10)
        assert len(rows) == 1
        assert rows[0]["memory_id"] == memId
        assert rows[0]["tags"] == ["dietlow-carb"], f"backslash must be stripped, got {rows[0]['tags']}"

        # Searching with the backslash tag matches (stripped on both sides).
        matches = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, tags=["diet\\low-carb"], embeddingModel=None, limit=10
        )
        assert len(matches) == 1, "backslash tag must match after stripping on both sides"
        assert matches[0]["memory_id"] == memId

        # Searching with the already-stripped tag also matches.
        matches2 = await testDatabase.userMemories.searchMemories(
            CHAT_ID, USER_ID, tags=["dietlow-carb"], embeddingModel=None, limit=10
        )
        assert len(matches2) == 1
        assert matches2[0]["memory_id"] == memId


class TestUserMemoriesRepository_ConstructionContract:
    """Wiring-contract checks for ``modelIdResolver`` injection (Decision D10).

    Mirrors the contract-test pattern from
    :class:`TestChatEmbeddingsRepository_ConstructionContract` in
    ``test_chat_embeddings.py``. These tests do not run database
    operations — they verify the ``_resolveModelId`` forwarding
    contract, including the ``dataSource`` kwarg introduced for
    multi-source routing.
    """

    @staticmethod
    async def test_resolverPassthroughHelper(testDatabase: Database) -> None:
        """``_resolveModelId`` is a thin pass-through to the injected callable.

        The private helper exists only so call sites within the repo
        read as ``await self._resolveModelId(model, dims)``; it must
        forward the exact args (including the default ``dataSource=None``)
        to the injected resolver and return its awaitable result.

        Args:
            testDatabase: Used only for its ``DatabaseManager``.
        """
        resolverMock = AsyncMock(return_value=777)
        repo = UserMemoriesRepository(testDatabase.manager, modelIdResolver=resolverMock)

        result = await repo._resolveModelId("alpha", 384)

        resolverMock.assert_awaited_once_with("alpha", 384, dataSource=None)
        assert result == 777

    @staticmethod
    async def test_resolveModelId_forwardsDataSource(testDatabase: Database) -> None:
        """``_resolveModelId`` forwards the ``dataSource`` kwarg to the injected resolver.

        Pins the multi-source routing contract: when a call site passes
        ``dataSource`` into ``_resolveModelId``, the injected resolver
        must receive it as a keyword argument so the underlying
        :meth:`EmbeddingModelsRepository.getOrCreateModelId` can route
        its provider acquisition.

        Args:
            testDatabase: Used only for its ``DatabaseManager``.
        """
        resolverMock = AsyncMock(return_value=42)
        repo = UserMemoriesRepository(testDatabase.manager, modelIdResolver=resolverMock)

        await repo._resolveModelId("routed-model", 512, dataSource="custom-src")

        resolverMock.assert_awaited_once_with("routed-model", 512, dataSource="custom-src")


# ---------------------------------------------------------------------------
# Module-level smoke test: __slots__ is correctly populated.
# ---------------------------------------------------------------------------


def test_userMemoriesRepository_slotsIncludesResolver() -> None:
    """The class ``__slots__`` tuple includes ``_modelIdResolver``.

    Catches the load-bearing edit documented in plan §8.6: the slot
    must be declared so the new instance attribute can be assigned in
    ``__init__``. Without it, construction raises ``AttributeError``.
    """
    assert "_modelIdResolver" in UserMemoriesRepository.__slots__
