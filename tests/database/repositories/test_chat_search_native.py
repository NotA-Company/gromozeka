"""Integration tests for native vector search in :class:`ChatSearchRepository`.

Covers the vec0 dispatch gate in :meth:`ChatSearchRepository._semanticSearch`
and the :meth:`_nativeVectorSearch` implementation that delegates to the
provider's :meth:`BaseSQLProvider.vectorSearch`.

Post-``migration_025`` contract (Decision D8 — numpy fully retired):
vec0 is the sole vector store on the message side. When the provider
does not support native vector search, when vec0 raises, or when it
returns no matches, the semantic path returns ``[]`` — there is NO
in-process fallback anymore. These tests pin that contract plus the
internal model-resolution wiring (Decision D10): the repo converts
``modelName`` to ``model_id`` via the injected resolver before issuing
the vec0 lookup.

The provider and downstream helpers are mocked so the tests focus
purely on the repository's dispatch logic. The end-to-end behaviour
(vec0 virtual table + sqlite-vec) is covered separately in
``tests/database/repositories/test_chat_search.py``.

Patching is done at the class level (``patch.object(ChatSearchRepository, …)``)
because repository instances use ``__slots__`` and cannot host per-instance
attributes.

The repo's ``modelIdResolver`` kwarg is injected via the ``repo``
fixture below (an :class:`AsyncMock`); the assertion on
``resolverMock.assert_awaited_once_with(modelName, dimension, dataSource=...)``
is the load-bearing wiring check (Decision D10 + Decision D6 extended).
"""

# pyright: reportTypedDictNotRequiredAccess=false

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from internal.database.models import MessageCategory
from internal.database.repositories.chat_search import ChatSearchRepository
from internal.models import MessageId


def _makeRepo(manager: MagicMock) -> ChatSearchRepository:
    """Build a :class:`ChatSearchRepository` with a stub resolver.

    Args:
        manager: Mocked :class:`DatabaseManager` (the repo only uses
            ``await manager.getProvider(...)``).

    Returns:
        A repository wired with an :class:`AsyncMock` resolver that
        returns ``42`` for any ``(model, dimensions)`` pair. Tests that
        need to assert on resolver invocation can reach the mock back
        via ``repo._modelIdResolver``.
    """
    return ChatSearchRepository(manager=manager, modelIdResolver=AsyncMock(return_value=42))


class TestChatSearchNativeVectorSearch:
    """Test the ``_nativeVectorSearch`` path in :class:`ChatSearchRepository`."""

    @pytest.fixture
    def mockManager(self) -> MagicMock:
        """DatabaseManager mock with an async ``getProvider`` accessor."""
        manager = MagicMock()
        manager.getProvider = AsyncMock()
        return manager

    @pytest.fixture
    def repo(self, mockManager: MagicMock) -> ChatSearchRepository:
        """:class:`ChatSearchRepository` wired to the mocked manager + a stub resolver."""
        return _makeRepo(mockManager)

    @pytest.fixture
    def mockProvider(self, mockManager: MagicMock) -> AsyncMock:
        """Mock provider that advertises native vector search support.

        ``isVectorSearchSupported`` is an ``async def`` method on the real
        provider, so it is set up as an :class:`AsyncMock` — using a
        :class:`MagicMock` would cause a ``TypeError`` when the repository
        calls ``await sqlProvider.isVectorSearchSupported()``.
        """
        provider = AsyncMock()
        provider.isVectorSearchSupported = AsyncMock(return_value=True)
        provider.applyPagination = MagicMock(return_value="paginated_query")
        mockManager.getProvider.return_value = provider
        return provider

    async def test_nativePathUsedWhenAvailable(self, repo: ChatSearchRepository, mockProvider: AsyncMock) -> None:
        """When ``isVectorSearchSupported()`` is True, the native path is taken.

        Verifies the vec0 lookup is issued AND that the resolver was
        called with ``(modelName, dimension)`` (Decision D10 + Decision
        D6 extended — internal model_id resolution).
        """
        mockProvider.vectorSearch.return_value = [
            {"rowKey": {"message_id": "msg_1", "date": "2024-01-01T00:00:00"}, "distance": 0.1},
        ]
        with patch.object(ChatSearchRepository, "_fetchSearchResultRows") as mockFetch:
            mockFetch.return_value = [{"message_id": "msg_1", "score": 0.9}]

            result = await repo._nativeVectorSearch(
                sqlProvider=mockProvider,
                chatId=42,
                queryEmbedding=[0.1] * 384,
                limit=10,
                topK=100,
                userFilter=None,
                categoryFilter=None,
                maxAgeDays=None,
                rootMessageId=None,
                modelName="test-model",
                maxMessages=None,
                dimension=384,
            )

            mockProvider.vectorSearch.assert_called_once()
            assert len(result) == 1
            assert result[0]["score"] == 0.9

        # Resolver was awaited with (modelName, dimension) — the
        # load-bearing wiring contract per Decisions D6+D10. The
        # ``dataSource=None`` kwarg is forwarded because this test does
        # not pass ``dataSource`` through ``_nativeVectorSearch``.
        repo._modelIdResolver.assert_awaited_once_with("test-model", 384, dataSource=None)

    async def test_nativeVectorSearch_forwardsDataSourceToResolver(
        self, repo: ChatSearchRepository, mockProvider: AsyncMock
    ) -> None:
        """``_nativeVectorSearch`` forwards ``dataSource`` to the resolver.

        Pins the multi-source routing contract: when a caller passes
        ``dataSource`` into ``_nativeVectorSearch``, the injected
        resolver must receive it as a keyword argument so the
        underlying ``getOrCreateModelId`` can route its provider
        acquisition. A future regression that drops
        ``dataSource=dataSource`` from the resolver call breaks the
        multi-source deployment model silently; this test catches that.

        Args:
            repo: Repository wired with the stub resolver via ``_makeRepo``.
            mockProvider: Mock provider advertising vector-search support.
        """
        # Empty vec0 results — keeps the test focused on the resolver
        # call (which happens before the vec0 lookup) without needing
        # to mock the post-filter / fetch helpers.
        mockProvider.vectorSearch.return_value = []

        await repo._nativeVectorSearch(
            sqlProvider=mockProvider,
            chatId=42,
            queryEmbedding=[0.1] * 384,
            limit=10,
            topK=100,
            userFilter=None,
            categoryFilter=None,
            maxAgeDays=None,
            rootMessageId=None,
            modelName="test-model",
            maxMessages=None,
            dimension=384,
            dataSource="custom-src",
        )

        repo._modelIdResolver.assert_awaited_once_with("test-model", 384, dataSource="custom-src")

    async def test_semanticSearchReturnsEmptyWhenVec0Unsupported(
        self, repo: ChatSearchRepository, mockProvider: AsyncMock
    ) -> None:
        """``_semanticSearch`` returns ``[]`` when vec0 is unsupported (no fallback).

        Post-``migration_025`` contract: there is no numpy fallback. When
        the provider does not support native vector search, semantic
        search returns ``[]`` immediately. The vec0 path is NOT taken
        and neither is any other ranking path.
        """
        mockProvider.isVectorSearchSupported.return_value = False

        with patch.object(ChatSearchRepository, "_nativeVectorSearch") as mockNative:
            result = await repo._semanticSearch(
                chatId=42,
                queryEmbedding=[0.1] * 384,
                limit=10,
                topK=100,
                userFilter=None,
                categoryFilter=None,
                maxAgeDays=None,
                rootMessageId=None,
                modelName="test-model",
                maxMessages=None,
                dataSource=None,
            )

            # Native search is NEVER called when vec0 is unsupported —
            # the dispatcher short-circuits before reaching it.
            mockNative.assert_not_called()
            mockProvider.vectorSearch.assert_not_called()
            assert result == []

    async def test_semanticSearchReturnsEmptyWhenNativeRaises(
        self, repo: ChatSearchRepository, mockProvider: AsyncMock
    ) -> None:
        """``_semanticSearch`` returns ``[]`` when ``_nativeVectorSearch`` raises.

        The exception is logged but swallowed; the dispatcher returns
        ``[]`` rather than propagating or attempting any fallback.
        """
        with patch.object(
            ChatSearchRepository, "_nativeVectorSearch", new=AsyncMock(side_effect=RuntimeError("vec0 boom"))
        ):
            result = await repo._semanticSearch(
                chatId=42,
                queryEmbedding=[0.1] * 384,
                limit=10,
                topK=100,
                userFilter=None,
                categoryFilter=None,
                maxAgeDays=None,
                rootMessageId=None,
                modelName="test-model",
                maxMessages=None,
                dataSource=None,
            )

        assert result == []

    async def test_semanticSearchReturnsEmptyWhenNativeReturnsEmpty(
        self, repo: ChatSearchRepository, mockProvider: AsyncMock
    ) -> None:
        """``_semanticSearch`` returns ``[]`` when ``_nativeVectorSearch`` yields no matches.

        Mirrors the vec0-empty case (table exists, no rows match the
        partition-key filter, or table has not yet been created for
        this dimension). There is no fallback — ``[]`` is the result.
        """
        with patch.object(ChatSearchRepository, "_nativeVectorSearch", new=AsyncMock(return_value=[])):
            result = await repo._semanticSearch(
                chatId=42,
                queryEmbedding=[0.1] * 384,
                limit=10,
                topK=100,
                userFilter=None,
                categoryFilter=None,
                maxAgeDays=None,
                rootMessageId=None,
                modelName="test-model",
                maxMessages=None,
                dataSource=None,
            )

        assert result == []

    async def test_nativeSearchEmptyVecResultsReturnsEmpty(
        self, repo: ChatSearchRepository, mockProvider: AsyncMock
    ) -> None:
        """When vec0 returns empty results, native search returns an empty list."""
        mockProvider.vectorSearch.return_value = []

        result = await repo._nativeVectorSearch(
            sqlProvider=mockProvider,
            chatId=42,
            queryEmbedding=[0.1] * 384,
            limit=10,
            topK=100,
            userFilter=None,
            categoryFilter=None,
            maxAgeDays=None,
            rootMessageId=None,
            modelName="test-model",
            maxMessages=None,
            dimension=384,
        )

        assert result == []

    async def test_nativeSearchModelNameNoneReturnsEmpty(
        self, repo: ChatSearchRepository, mockProvider: AsyncMock
    ) -> None:
        """When ``modelName`` is None, native search short-circuits to empty.

        Also verifies the resolver is NOT called (no resolution
        possible without a model name) and vec0 is NOT queried.
        """
        result = await repo._nativeVectorSearch(
            sqlProvider=mockProvider,
            chatId=42,
            queryEmbedding=[0.1] * 384,
            limit=10,
            topK=100,
            userFilter=None,
            categoryFilter=None,
            maxAgeDays=None,
            rootMessageId=None,
            modelName=None,
            maxMessages=None,
            dimension=384,
        )

        assert result == []
        mockProvider.vectorSearch.assert_not_called()
        repo._modelIdResolver.assert_not_awaited()

    async def test_nativeSearchNearZeroNormReturnsEmpty(
        self, repo: ChatSearchRepository, mockProvider: AsyncMock
    ) -> None:
        """A near-zero-norm query vector short-circuits to empty results.

        This also implicitly pins that the query-norm is now computed
        via ``math.sqrt(sum(x*x for x in queryEmbedding))`` rather than
        ``numpy.linalg.norm`` (Decision D8): if the refactor accidentally
        left an ``np.linalg.norm`` reference in place, importing the repo
        module would have failed at collection time (numpy import was
        dropped from the file).
        """
        result = await repo._nativeVectorSearch(
            sqlProvider=mockProvider,
            chatId=42,
            queryEmbedding=[0.0] * 384,
            limit=10,
            topK=100,
            userFilter=None,
            categoryFilter=None,
            maxAgeDays=None,
            rootMessageId=None,
            modelName="test-model",
            maxMessages=None,
            dimension=384,
        )

        assert result == []
        mockProvider.vectorSearch.assert_not_called()

    async def test_nativeSearchWithPostFilters(self, repo: ChatSearchRepository, mockProvider: AsyncMock) -> None:
        """Post-filters (user, category) are applied after the vector search."""
        mockProvider.vectorSearch.return_value = [
            {"rowKey": {"message_id": "msg_1", "date": "2024-01-02T00:00:00"}, "distance": 0.1},
            {"rowKey": {"message_id": "msg_2", "date": "2024-01-01T00:00:00"}, "distance": 0.2},
        ]

        # Simulate the post-filter removing msg_1, keeping msg_2.
        async def mockFilter(**_kwargs: object) -> list[MessageId]:
            return [MessageId("msg_2")]

        with patch.object(ChatSearchRepository, "_filterMessageIds", side_effect=mockFilter):
            with patch.object(ChatSearchRepository, "_fetchSearchResultRows") as mockFetch:
                mockFetch.return_value = [{"message_id": "msg_2", "score": 0.8}]

                result = await repo._nativeVectorSearch(
                    sqlProvider=mockProvider,
                    chatId=42,
                    queryEmbedding=[0.1] * 384,
                    limit=10,
                    topK=100,
                    userFilter=123,
                    categoryFilter=[MessageCategory.USER],
                    maxAgeDays=None,
                    rootMessageId=None,
                    modelName="test-model",
                    maxMessages=None,
                    dimension=384,
                )

                assert len(result) == 1
                assert result[0]["message_id"] == "msg_2"

    async def test_nativeSearchVecFilterUsesModelId(self, repo: ChatSearchRepository, mockProvider: AsyncMock) -> None:
        """The vec0 partition-key filter uses ``model_id`` (NOT ``model``).

        Post-``migration_025`` the vec0 table partition key changed from
        ``model TEXT`` to ``model_id INTEGER``. The repo resolves
        ``modelName`` to a ``model_id`` via the injected resolver and
        threads it into the filter. This test pins that wiring by
        inspecting the ``filterClause`` + ``filterParams`` that reach
        ``sqlProvider.vectorSearch``.

        The stub resolver returns ``42`` for every call, so the
        expected ``filterParams["modelId"] == 42`` and the
        ``filterClause`` contains ``model_id = :modelId`` (and does NOT
        contain ``model = :modelName``).
        """
        mockProvider.vectorSearch.return_value = []

        await repo._nativeVectorSearch(
            sqlProvider=mockProvider,
            chatId=42,
            queryEmbedding=[0.1] * 384,
            limit=10,
            topK=100,
            userFilter=None,
            categoryFilter=None,
            maxAgeDays=None,
            rootMessageId=None,
            modelName="test-model",
            maxMessages=None,
            dimension=384,
        )

        callArgs = mockProvider.vectorSearch.call_args
        filterClause: str = callArgs.kwargs["filterClause"]
        filterParams: dict = callArgs.kwargs["filterParams"]

        assert "model_id = :modelId" in filterClause
        assert "model = :modelName" not in filterClause
        assert filterParams["modelId"] == 42
        assert "modelName" not in filterParams
        assert filterParams["chatId"] == 42

    async def test_nativeSearchWithMaxMessages(self, repo: ChatSearchRepository, mockProvider: AsyncMock) -> None:
        """``maxMessages`` pre-filter pushes a compound date filter into vec0.

        Post-``migration_025`` the cutoff is sourced from a single-table
        query against ``chat_messages`` (filtered by ``model_id``) — the
        legacy ``JOIN message_embeddings ... WHERE me.model = :modelName``
        was dropped along with the ``message_embeddings`` table.

        This test pins:
          - the cutoff SQL is issued against ``chat_messages`` only,
          - the cutoff SQL carries ``model_id = :modelId`` (resolved),
          - the cutoff SQL does NOT reference ``message_embeddings`` or
            ``me.model = :modelName``,
          - the compound ``date >= :minDate`` filter reaches vec0.
        """
        mockProvider.executeFetchOne.return_value = {
            "date": "2024-01-15T00:00:00",
            "message_id": "msg_cutoff",
        }
        mockProvider.vectorSearch.return_value = [
            {"rowKey": {"message_id": "msg_1", "date": "2024-01-20T00:00:00"}, "distance": 0.1},
        ]
        with patch.object(ChatSearchRepository, "_fetchSearchResultRows") as mockFetch:
            mockFetch.return_value = [{"message_id": "msg_1", "score": 0.9}]

            result = await repo._nativeVectorSearch(
                sqlProvider=mockProvider,
                chatId=42,
                queryEmbedding=[0.1] * 384,
                limit=10,
                topK=100,
                userFilter=None,
                categoryFilter=None,
                maxAgeDays=None,
                rootMessageId=None,
                modelName="test-model",
                maxMessages=50,
                dimension=384,
            )

            callArgs = mockProvider.vectorSearch.call_args
            # Compound filter mirrors the ORDER BY date DESC, message_id DESC
            # semantics so messages sharing the cutoff timestamp do not leak.
            assert (
                "(date > :minDate OR (date = :minDate AND message_id >= :minMessageId))"
                in callArgs.kwargs["filterClause"]
            )
            assert callArgs.kwargs["filterParams"]["minDate"] == "2024-01-15T00:00:00"
            assert callArgs.kwargs["filterParams"]["minMessageId"] == "msg_cutoff"
            # The resolved modelId is threaded into BOTH the cutoff query
            # params (via executeFetchOne) AND the vec0 filter params.
            assert callArgs.kwargs["filterParams"]["modelId"] == 42
            assert len(result) == 1

            # The cutoff query must be a single-table query against
            # ``chat_messages`` filtered by ``model_id`` — NOT the
            # legacy JOIN to ``message_embeddings``.
            applyPaginationCall = mockProvider.applyPagination.call_args
            cutoffSql: str = applyPaginationCall.args[0]
            assert "FROM chat_messages" in cutoffSql
            assert "message_embeddings" not in cutoffSql
            assert "JOIN" not in cutoffSql
            assert "model_id = :modelId" in cutoffSql
            assert "ORDER BY date DESC, message_id DESC" in cutoffSql

            # The cutoff query params carry the resolved modelId (not modelName).
            fetchOneCall = mockProvider.executeFetchOne.call_args
            cutoffParams: dict = fetchOneCall.args[1]
            assert cutoffParams["modelId"] == 42
            assert cutoffParams["chatId"] == 42
            assert "modelName" not in cutoffParams


class TestChatSearchRepository_ConstructionContract:
    """Compile-time / wiring contract checks for the repo's new constructor.

    Mirrors the contract-test pattern from
    :class:`TestChatEmbeddingsRepository_ConstructionContract` in
    ``test_chat_embeddings.py`` — verifies the constructor-injection
    wiring (Decision D10) and the ``__slots__`` edit.
    """

    @staticmethod
    def test_constructor_acceptsModelIdResolverKeyword() -> None:
        """The constructor takes a keyword-only ``modelIdResolver`` argument.

        Verifies that the ``__slots__`` tuple was updated to allow the
        ``_modelIdResolver`` instance attribute (an empty ``__slots__``
        tuple would raise ``AttributeError`` on the assignment).
        """
        manager = MagicMock()
        sentinel = AsyncMock()

        repo = ChatSearchRepository(manager=manager, modelIdResolver=sentinel)

        # The instance attribute is set and reachable.
        assert repo._modelIdResolver is sentinel

    @staticmethod
    def test_constructor_requiresModelIdResolverKwarg() -> None:
        """Omitting ``modelIdResolver`` raises ``TypeError``.

        The kwarg is required (no default). This locks in Decision D10:
        every consuming repo MUST receive a resolver — there is no
        implicit fall-through to a process-global singleton.
        """
        manager = MagicMock()
        with pytest.raises(TypeError):
            ChatSearchRepository(manager=manager)  # type: ignore[call-arg]

    @staticmethod
    async def test_resolverPassthroughHelper() -> None:
        """``_resolveModelId`` is a thin pass-through to the injected callable.

        The private helper exists only so call sites within the repo
        read as ``await self._resolveModelId(model, dims)``; it must
        forward the exact args to the injected resolver and return its
        awaitable result.
        """
        manager = MagicMock()
        resolverMock = AsyncMock(return_value=777)
        repo = ChatSearchRepository(manager=manager, modelIdResolver=resolverMock)

        result = await repo._resolveModelId("alpha", 384)

        resolverMock.assert_awaited_once_with("alpha", 384, dataSource=None)
        assert result == 777

    @staticmethod
    async def test_resolveModelId_forwardsDataSource() -> None:
        """``_resolveModelId`` forwards the ``dataSource`` kwarg to the injected resolver.

        Pins the multi-source routing contract: when a call site passes
        ``dataSource`` into ``_resolveModelId``, the injected resolver
        must receive it as a keyword argument so the underlying
        :meth:`EmbeddingModelsRepository.getOrCreateModelId` can route
        its provider acquisition.
        """
        manager = MagicMock()
        resolverMock = AsyncMock(return_value=42)
        repo = ChatSearchRepository(manager=manager, modelIdResolver=resolverMock)

        await repo._resolveModelId("routed-model", 512, dataSource="custom-src")

        resolverMock.assert_awaited_once_with("routed-model", 512, dataSource="custom-src")


# ---------------------------------------------------------------------------
# Module-level smoke test: __slots__ is correctly populated.
# ---------------------------------------------------------------------------


def test_chatSearchRepository_slotsIncludesResolver() -> None:
    """The class ``__slots__`` tuple includes ``_modelIdResolver``.

    Catches the load-bearing edit documented in plan §8.5: the slot
    must be declared so the new instance attribute can be assigned in
    ``__init__``. Without it, construction raises ``AttributeError``
    against the empty ``()`` tuple that the pre-refactor class carried.
    """
    assert "_modelIdResolver" in ChatSearchRepository.__slots__
