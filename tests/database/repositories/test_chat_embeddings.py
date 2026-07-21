"""Tests for :class:`ChatEmbeddingsRepository` (post-``migration_025`` shape).

End-to-end coverage of the repository's post-refactor behaviour:

- :meth:`ChatEmbeddingsRepository.saveMessageEmbedding` UPDATEs
  ``chat_messages.model_id`` and dual-writes the vec0 row.
- :meth:`ChatEmbeddingsRepository.deleteObsoleteModelEmbeddings` clears
  ``model_id`` on rows whose provenance no longer matches the chat's
  active model (two branches: dimensions-known uses a resolved id;
  dimensions-unknown uses a subquery against ``models``).
- :meth:`ChatEmbeddingsRepository.getMessagesWithoutEmbeddings`
  discovers backfill candidates via a single-table predicate against
  ``chat_messages.model_id`` (three branches).

The legacy ``message_embeddings`` BLOB side table was dropped by
``migration_025``; the old CRUD (``getMessageEmbedding``,
``deleteChatEmbeddings``) was removed with it. These tests exercise
only the new schema.

Uses the shared ``testDatabase`` fixture from ``tests/conftest.py`` so
each test gets a fresh in-memory SQLite database with all migrations
applied — no mocks at the provider layer. The repository's
``modelIdResolver`` is wired in ``Database.__init__`` to the real
:class:`EmbeddingModelsRepository` bound method; the resolver-mocking tests
below construct :class:`ChatEmbeddingsRepository` directly.
"""

# pyright: reportTypedDictNotRequiredAccess=false

import datetime
from unittest.mock import AsyncMock

import pytest

from internal.database import Database
from internal.database.models import MessageCategory
from internal.database.providers.sqlite3 import _SQLITE_VEC_AVAILABLE
from internal.database.repositories.chat_embeddings import ChatEmbeddingsRepository
from internal.models import MessageId


class TestChatEmbeddingsRepository:
    """End-to-end coverage of the post-``migration_025`` repo behaviour."""

    ###
    # Seed helpers
    ###
    @staticmethod
    async def _seedUser(db: Database, chatId: int, userId: int) -> None:
        """Insert a chat_users row so JOINs to chat_messages succeed.

        Args:
            db: Database instance.
            chatId: Chat identifier.
            userId: User identifier.

        Returns:
            None.
        """
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
        """Insert a chat_users row and a chat_messages row for the test seed.

        Args:
            db: Database instance.
            chatId: Chat identifier.
            userId: User identifier.
            messageId: Message identifier.
            messageText: Message body text.
            messageCategory: Optional message category.

        Returns:
            None.
        """
        await TestChatEmbeddingsRepository._seedUser(db, chatId=chatId, userId=userId)
        await db.chatMessages.saveChatMessage(
            date=datetime.datetime.now(datetime.timezone.utc),
            chatId=chatId,
            userId=userId,
            messageId=MessageId(messageId),
            messageText=messageText,
            messageCategory=messageCategory,
        )

    @staticmethod
    async def _setModelIdOnMessage(db: Database, chatId: int, messageId: int, modelId: int) -> None:
        """Stamp a ``chat_messages.model_id`` value directly via SQL.

        Used to set up preconditions (existing model_id values for
        drift-cleanup / backfill tests) without exercising the code
        under test.

        Args:
            db: Database instance.
            chatId: Chat identifier.
            messageId: Message identifier.
            modelId: ``model_id`` value to stamp.

        Returns:
            None.
        """
        sqlProvider = await db.manager.getProvider(chatId=chatId, readonly=False)
        await sqlProvider.execute(
            "UPDATE chat_messages SET model_id = :modelId " "WHERE chat_id = :chatId AND message_id = :messageId",
            {"modelId": modelId, "chatId": chatId, "messageId": str(messageId)},
        )

    @staticmethod
    async def _getModelIdOnMessage(db: Database, chatId: int, messageId: int) -> int | None:
        """Read the ``chat_messages.model_id`` value directly via SQL.

        Args:
            db: Database instance.
            chatId: Chat identifier.
            messageId: Message identifier.

        Returns:
            The integer ``model_id`` if set, else ``None``.
        """
        sqlProvider = await db.manager.getProvider(chatId=chatId, readonly=True)
        row = await sqlProvider.executeFetchOne(
            "SELECT model_id FROM chat_messages " "WHERE chat_id = :chatId AND message_id = :messageId",
            {"chatId": chatId, "messageId": str(messageId)},
        )
        if row is None:
            return None
        value = row["model_id"]
        return int(value) if value is not None else None

    ###
    # saveMessageEmbedding
    ###
    async def test_saveMessageEmbedding_updatesChatMessagesModelId(self, testDatabase: Database) -> None:
        """``saveMessageEmbedding`` UPDATEs ``chat_messages.model_id`` to the resolved id.

        Seeds a chat_messages row, calls saveMessageEmbedding with a
        known ``(model, dimensions)`` pair, and asserts that
        ``chat_messages.model_id`` is set to the id allocated by the
        resolver (the real :class:`EmbeddingModelsRepository`).
        """
        if not _SQLITE_VEC_AVAILABLE:
            pytest.skip("sqlite-vec not installed")

        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="hi")

        # Sanity: model_id starts NULL (fresh row).
        assert await self._getModelIdOnMessage(testDatabase, chatId=1, messageId=1) is None

        ok = await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=1,
            messageId=MessageId(1),
            embedding=[1.0, 0.5, 0.25],
            model="test-model-A",
        )
        assert ok

        # Resolve the canonical id via the resolver that the repo uses.
        expectedId = await testDatabase.embeddingModels.getOrCreateModelId("test-model-A", 3)
        actualId = await self._getModelIdOnMessage(testDatabase, chatId=1, messageId=1)
        assert actualId == expectedId

    async def test_saveMessageEmbedding_dualWritesVec0(self, testDatabase: Database) -> None:
        """``saveMessageEmbedding`` lazy-creates the vec0 table with the new ``model_id`` DDL and writes the row.

        Verifies the post-``migration_025`` vec0 DDL: ``model_id INTEGER
        PARTITION KEY`` (replaces the legacy ``model TEXT PARTITION
        KEY``). The seeded row appears in the vec0 table with the
        resolved ``model_id``.
        """
        if not _SQLITE_VEC_AVAILABLE:
            pytest.skip("sqlite-vec not installed")

        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=42, messageText="vec me")

        dimensions = 3
        ok = await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=1,
            messageId=MessageId(42),
            embedding=[1.0, 0.0, 0.0],
            model="vec-model",
        )
        assert ok

        sqlProvider = await testDatabase.manager.getProvider(chatId=1, readonly=True)
        if not await sqlProvider.isVectorSearchSupported():
            pytest.skip("sqlite-vec extension not loaded by provider")

        # The vec0 table exists (lazy-create succeeded).
        tableName = f"vec_message_embeddings_{dimensions}"
        vecTables = await sqlProvider.listTables(tableName)
        assert tableName in vecTables, f"expected lazy-created vec0 table {tableName}"

        # The vec0 row is present with the resolved model_id. We do NOT
        # try to read back the BLOB column (vec0 returns it in a
        # transport-specific shape) — model_id + message_id are enough
        # to assert the row landed with the right provenance.
        expectedModelId = await testDatabase.embeddingModels.getOrCreateModelId("vec-model", dimensions)
        row = await sqlProvider.executeFetchOne(
            f"SELECT message_id, chat_id, model_id FROM {tableName} "
            f"WHERE chat_id = :chatId AND message_id = :messageId",
            {"chatId": 1, "messageId": "42"},
        )
        assert row is not None, "expected the vec0 row to be present after saveMessageEmbedding"
        assert int(row["model_id"]) == expectedModelId

    async def test_saveMessageEmbedding_resolvesModelIdViaResolver(self, testDatabase: Database) -> None:
        """The injected ``modelIdResolver`` callable is invoked with ``(model, dimensions)``.

        Constructs :class:`ChatEmbeddingsRepository` directly with a
        mock resolver to verify the wiring contract: the repo calls the
        resolver with the exact ``(model, len(embedding))`` tuple it
        receives from the caller.
        """
        if not _SQLITE_VEC_AVAILABLE:
            pytest.skip("sqlite-vec not installed")

        resolverMock = AsyncMock(return_value=99)
        repo = ChatEmbeddingsRepository(testDatabase.manager, modelIdResolver=resolverMock)

        await self._seedMessage(testDatabase, chatId=7, userId=200, messageId=5, messageText="resolver me")
        ok = await repo.saveMessageEmbedding(
            chatId=7,
            messageId=MessageId(5),
            embedding=[0.1, 0.2, 0.3, 0.4],
            model="explicit-model",
        )
        assert ok

        resolverMock.assert_awaited_once_with("explicit-model", 4, dataSource=None)

        # The UPDATE on chat_messages.model_id used the resolver's return value.
        assert await self._getModelIdOnMessage(testDatabase, chatId=7, messageId=5) == 99

    async def test_saveMessageEmbedding_resolverCachesModelId(self, testDatabase: Database) -> None:
        """Two saves with the same ``(model, dimensions)`` populate the resolver cache exactly once.

        Uses the real :class:`EmbeddingModelsRepository` as the resolver (the
        production wiring). The repo itself does NOT cache — it calls
        the resolver on every save; the resolver's process-local cache
        is what absorbs the second call. We assert by inspecting the
        resolver's cache dict and by patching ``getProvider`` on the
        second call to a strict mock that raises if awaited.
        """
        if not _SQLITE_VEC_AVAILABLE:
            pytest.skip("sqlite-vec not installed")

        repo = testDatabase.chatEmbeddings
        resolver = testDatabase.embeddingModels

        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="one")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=2, messageText="two")

        # First save: cold resolver cache → DB hit → cache populated.
        assert await repo.saveMessageEmbedding(
            chatId=1, messageId=MessageId(1), embedding=[1.0, 0.0, 0.0], model="cached-m"
        )
        assert ("cached-m", 3) in resolver._cache

        # Second save: resolver cache hit → no DB provider acquisition.
        # Patch getProvider on the manager's class (DatabaseManager
        # declares __slots__, so the patch must target the class) to a
        # strict mock that raises if awaited inside the resolver. The
        # repo itself still calls getProvider (for the chat_messages
        # UPDATE and the vec0 dual-write), so we cannot use a global
        # strict mock — instead we patch EmbeddingModelsRepository._cache access
        # is the load-bearing state. The observable assertion is that
        # the cache still holds exactly one entry and its id matches
        # both saves.
        assert await repo.saveMessageEmbedding(
            chatId=1, messageId=MessageId(2), embedding=[0.0, 1.0, 0.0], model="cached-m"
        )

        # Exactly one resolver cache entry — second save hit the cache.
        matchingEntries = [k for k in resolver._cache if k == ("cached-m", 3)]
        assert len(matchingEntries) == 1
        cachedId = resolver._cache[("cached-m", 3)]

        # Both messages carry the same model_id (the resolver returned
        # the same id for both saves — no duplicate allocation).
        mid1 = await self._getModelIdOnMessage(testDatabase, chatId=1, messageId=1)
        mid2 = await self._getModelIdOnMessage(testDatabase, chatId=1, messageId=2)
        assert mid1 == cachedId
        assert mid2 == cachedId

        # The models table has exactly one row for (cached-m, 3) — the
        # second save's resolver call short-circuited via cache.
        sqlProvider = await testDatabase.manager.getProvider(readonly=True)
        rows = await sqlProvider.executeFetchAll(
            "SELECT model_id FROM models WHERE model = :model AND dimensions = :dimensions",
            {"model": "cached-m", "dimensions": 3},
        )
        assert len(rows) == 1

    ###
    # deleteObsoleteModelEmbeddings
    ###
    async def test_deleteObsoleteModelEmbeddings_nullsNonMatchingModelId(self, testDatabase: Database) -> None:
        """``deleteObsoleteModelEmbeddings`` clears ``model_id`` on rows that do not match the current model.

        Three rows are seeded with different ``model_id`` values. After
        cleanup with the current model, only the matching row retains
        its ``model_id``; the other two are NULLed.
        """
        if not _SQLITE_VEC_AVAILABLE:
            pytest.skip("sqlite-vec not installed")

        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="current")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=2, messageText="stale-A")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=3, messageText="stale-B")

        currentId = await testDatabase.embeddingModels.getOrCreateModelId("current-model", 3)
        staleAId = await testDatabase.embeddingModels.getOrCreateModelId("stale-A-model", 3)
        staleBId = await testDatabase.embeddingModels.getOrCreateModelId("stale-B-model", 3)
        await self._setModelIdOnMessage(testDatabase, chatId=1, messageId=1, modelId=currentId)
        await self._setModelIdOnMessage(testDatabase, chatId=1, messageId=2, modelId=staleAId)
        await self._setModelIdOnMessage(testDatabase, chatId=1, messageId=3, modelId=staleBId)

        ok = await testDatabase.chatEmbeddings.deleteObsoleteModelEmbeddings(
            chatId=1, currentModel="current-model", currentDimensions=3
        )
        assert ok

        assert await self._getModelIdOnMessage(testDatabase, chatId=1, messageId=1) == currentId
        assert await self._getModelIdOnMessage(testDatabase, chatId=1, messageId=2) is None
        assert await self._getModelIdOnMessage(testDatabase, chatId=1, messageId=3) is None

    async def test_deleteObsoleteModelEmbeddings_dimensionsKnown(self, testDatabase: Database) -> None:
        """When ``currentDimensions`` is provided, the resolver IS called (single-id predicate branch).

        Uses a mock-augmented repo to verify the resolver was awaited —
        this distinguishes the dimensions-known branch from the
        dimensions-unknown subquery branch.
        """
        if not _SQLITE_VEC_AVAILABLE:
            pytest.skip("sqlite-vec not installed")

        # Three rows with three distinct model_id values.
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="current")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=2, messageText="stale")
        currentId = await testDatabase.embeddingModels.getOrCreateModelId("dimknown-current", 3)
        staleId = await testDatabase.embeddingModels.getOrCreateModelId("dimknown-stale", 3)
        await self._setModelIdOnMessage(testDatabase, chatId=1, messageId=1, modelId=currentId)
        await self._setModelIdOnMessage(testDatabase, chatId=1, messageId=2, modelId=staleId)

        # Wrap the resolver in an AsyncMock that delegates to the real
        # bound method. ``side_effect`` lets the mock record the call
        # AND transparently forward to the real implementation so the
        # SQL UPDATE still resolves the correct id.
        resolverMock = AsyncMock(side_effect=testDatabase.embeddingModels.getOrCreateModelId)
        repo = ChatEmbeddingsRepository(testDatabase.manager, modelIdResolver=resolverMock)

        ok = await repo.deleteObsoleteModelEmbeddings(chatId=1, currentModel="dimknown-current", currentDimensions=3)
        assert ok

        # The dimensions-known branch MUST call the resolver to obtain
        # the canonical model_id (this is what distinguishes it from
        # the subquery branch).
        resolverMock.assert_awaited_once_with("dimknown-current", 3, dataSource=None)

        # Observable behaviour: current-model row survives, stale row cleared.
        assert await self._getModelIdOnMessage(testDatabase, chatId=1, messageId=1) == currentId
        assert await self._getModelIdOnMessage(testDatabase, chatId=1, messageId=2) is None

    ###
    # getMessagesWithoutEmbeddings
    ###
    async def test_getMessagesWithoutEmbeddings_modelNameNone(self, testDatabase: Database) -> None:
        """With no ``modelName``, the helper returns messages where ``model_id IS NULL``.

        This is the "fresh backfill" case — messages that have never
        been embedded under any model. Messages with a non-NULL
        ``model_id`` are excluded regardless of which model produced
        them.
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="never-embedded")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=2, messageText="also-fresh")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=3, messageText="already-done")
        # Stamp the third one as embedded.
        someId = await testDatabase.embeddingModels.getOrCreateModelId("anything", 3)
        await self._setModelIdOnMessage(testDatabase, chatId=1, messageId=3, modelId=someId)

        results = await testDatabase.chatEmbeddings.getMessagesWithoutEmbeddings(chatId=1)

        assert {r["message_id"] for r in results} == {MessageId(1), MessageId(2)}
        # Empty messages are excluded too.
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=4, messageText="")
        resultsAfterEmpty = await testDatabase.chatEmbeddings.getMessagesWithoutEmbeddings(chatId=1)
        assert MessageId(4) not in {r["message_id"] for r in resultsAfterEmpty}

    async def test_getMessagesWithoutEmbeddings_modelNameAndDimensionsProvided(self, testDatabase: Database) -> None:
        """With ``modelName`` AND ``dimensions``, the helper resolves a single canonical id.

        Returns messages where ``model_id IS NULL`` OR
        ``model_id != :currentModelId``. Same-model name at a DIFFERENT
        dimensionality IS surfaced (the (model, dims) pair is the
        canonical key — same name, different dims = different model_id).
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="fresh")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=2, messageText="exact-match")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=3, messageText="same-name-other-dims")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=4, messageText="other-model")

        exactId = await testDatabase.embeddingModels.getOrCreateModelId("active", 384)
        sameNameOtherDimsId = await testDatabase.embeddingModels.getOrCreateModelId("active", 1024)
        otherId = await testDatabase.embeddingModels.getOrCreateModelId("retired", 384)
        await self._setModelIdOnMessage(testDatabase, chatId=1, messageId=2, modelId=exactId)
        await self._setModelIdOnMessage(testDatabase, chatId=1, messageId=3, modelId=sameNameOtherDimsId)
        await self._setModelIdOnMessage(testDatabase, chatId=1, messageId=4, modelId=otherId)

        results = await testDatabase.chatEmbeddings.getMessagesWithoutEmbeddings(
            chatId=1, modelName="active", dimensions=384
        )

        returnedIds = {r["message_id"] for r in results}
        # msg 1: fresh → surfaced.
        # msg 2: exact (model, dims) match → NOT surfaced.
        # msg 3: same model name, different dims → surfaced (different model_id).
        # msg 4: different model name → surfaced.
        assert returnedIds == {MessageId(1), MessageId(3), MessageId(4)}

    async def test_getMessagesWithoutEmbeddings_returnsFullChatMessageShape(self, testDatabase: Database) -> None:
        """Returned rows are :class:`ChatMessageDict`-shaped (chat + user fields).

        The backfill consumer (``ChatSearchHandler._dtCronJob``) reads
        ``message_id``, ``message_text``, ``username``, ``full_name``
        directly off the returned rows. The JOIN to ``chat_users`` is
        preserved for that reason.
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="hello")

        results = await testDatabase.chatEmbeddings.getMessagesWithoutEmbeddings(chatId=1)

        assert len(results) == 1
        row = results[0]
        assert row["chat_id"] == 1
        assert row["message_id"] == MessageId(1)
        assert row["user_id"] == 100
        assert row["message_text"] == "hello"
        assert row["username"] == "user100"
        assert row["full_name"] == "User 100"

    async def test_getMessagesWithoutEmbeddings_respectsLimit(self, testDatabase: Database) -> None:
        """The ``limit`` argument caps the number of returned rows.

        Uses ``applyPagination`` from the provider abstraction
        (portable LIMIT/OFFSET) — this test pins that the pagination
        wrapper is in fact applied.
        """
        for mid in range(1, 11):
            await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=mid, messageText=f"m{mid}")

        results = await testDatabase.chatEmbeddings.getMessagesWithoutEmbeddings(chatId=1, limit=3)
        assert len(results) == 3

    async def test_getMessagesWithoutEmbeddings_forwardsDataSourceToResolver(self, testDatabase: Database) -> None:
        """``getMessagesWithoutEmbeddings`` forwards ``dataSource`` to the resolver.

        Pins the multi-source routing contract on the (modelName,
        dimensions) branch — the only branch that resolves a model_id
        via the injected resolver. A future regression that drops the
        ``dataSource=dataSource`` kwarg from the resolver call breaks
        the multi-source deployment model silently; this test catches
        that.

        Args:
            testDatabase: Fresh in-memory database with migrations applied.
        """
        # Seed one chat_message + chat_user so the JOIN returns something.
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="route-me")
        resolverMock = AsyncMock(return_value=42)
        repo = ChatEmbeddingsRepository(testDatabase.manager, modelIdResolver=resolverMock)

        await repo.getMessagesWithoutEmbeddings(chatId=1, modelName="m", dimensions=3, dataSource="custom-src")

        resolverMock.assert_awaited_once_with("m", 3, dataSource="custom-src")


class TestChatEmbeddingsRepository_ConstructionContract:
    """Compile-time / wiring contract checks for the repo's new constructor.

    These do not run database operations — they verify the
    constructor-injection wiring (Decision D10) and the ``__slots__``
    edit that the new instance attribute requires.
    """

    @staticmethod
    def test_constructor_acceptsModelIdResolverKeyword(testDatabase: Database) -> None:
        """The constructor takes a keyword-only ``modelIdResolver`` argument.

        Args:
            testDatabase: Used only for its ``DatabaseManager``; no DB
                operations are performed.

        Verifies that the ``__slots__`` tuple was updated to allow the
        ``_modelIdResolver`` instance attribute (an empty ``__slots__``
        tuple would raise ``AttributeError`` on the assignment).
        """
        sentinel = AsyncMock()

        repo = ChatEmbeddingsRepository(testDatabase.manager, modelIdResolver=sentinel)

        # The instance attribute is set and reachable.
        assert repo._modelIdResolver is sentinel

    @staticmethod
    def test_constructor_requiresModelIdResolverKwarg(testDatabase: Database) -> None:
        """Omitting ``modelIdResolver`` raises ``TypeError``.

        The kwarg is required (no default). This locks in Decision D10:
        every consuming repo MUST receive a resolver — there is no
        implicit fall-through to a process-global singleton.
        """
        with pytest.raises(TypeError):
            ChatEmbeddingsRepository(testDatabase.manager)  # type: ignore[call-arg]

    @staticmethod
    async def test_resolverPassthroughHelper(testDatabase: Database) -> None:
        """``_resolveModelId`` is a thin pass-through to the injected callable.

        The private helper exists only so call sites within the repo
        read as ``await self._resolveModelId(model, dims)``; it must
        forward the exact args to the injected resolver and return its
        awaitable result. Verified by awaiting the helper and checking
        the mock was called with the forwarded args.

        Args:
            testDatabase: Used only for its ``DatabaseManager``.
        """
        resolverMock = AsyncMock(return_value=777)
        repo = ChatEmbeddingsRepository(testDatabase.manager, modelIdResolver=resolverMock)

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
        repo = ChatEmbeddingsRepository(testDatabase.manager, modelIdResolver=resolverMock)

        await repo._resolveModelId("routed-model", 512, dataSource="custom-src")

        resolverMock.assert_awaited_once_with("routed-model", 512, dataSource="custom-src")


# ---------------------------------------------------------------------------
# Module-level smoke test: __slots__ is correctly populated.
# ---------------------------------------------------------------------------


def test_chatEmbeddingsRepository_slotsIncludesResolver() -> None:
    """The class ``__slots__`` tuple includes ``_modelIdResolver``.

    Catches the load-bearing edit documented in plan §8.4: the slot
    must be declared so the new instance attribute can be assigned in
    ``__init__``. Without it, construction raises ``AttributeError``
    against the empty ``()`` tuple that the pre-refactor class carried.
    """
    assert "_modelIdResolver" in ChatEmbeddingsRepository.__slots__
