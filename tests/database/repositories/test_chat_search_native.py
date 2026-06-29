"""Integration tests for native vector search in :class:`ChatSearchRepository`.

Covers the fast-path gate in :meth:`ChatSearchRepository._semanticSearch`
and the :meth:`_nativeVectorSearch` implementation that delegates to the
provider's :meth:`BaseSQLProvider.vectorSearch`.

The provider and downstream helpers are mocked so the tests focus purely
on the repository's dispatch logic: when to take the native path, when
to fall back to numpy, how post-filters compose, and how the
``maxMessages`` pre-filter is expressed. The end-to-end behaviour
(vec0 virtual table + sqlite-vec) is covered separately in
``tests/database/providers/``.

Patching is done at the class level (``patch.object(ChatSearchRepository, …)``)
because repository instances use ``__slots__`` and cannot host per-instance
attributes.
"""

# pyright: reportTypedDictNotRequiredAccess=false

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from internal.database.models import MessageCategory
from internal.database.repositories.chat_search import ChatSearchRepository
from internal.models import MessageId


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
        """:class:`ChatSearchRepository` wired to the mocked manager."""
        return ChatSearchRepository(manager=mockManager)

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
        """When ``isVectorSearchSupported()`` is True, the native path is taken."""
        mockProvider.vectorSearch.return_value = [
            {"rowKey": {"message_id": "msg_1", "date": "2024-01-01T00:00:00"}, "distance": 0.1},
        ]
        with patch.object(ChatSearchRepository, "_loadEmbeddingsFromDb") as mockLoad:
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
                mockLoad.assert_not_called()
                assert len(result) == 1
                assert result[0]["score"] == 0.9

    async def test_fallbackWhenNotAvailable(self, repo: ChatSearchRepository, mockProvider: AsyncMock) -> None:
        """When native search is unsupported, the numpy path is taken."""
        mockProvider.isVectorSearchSupported.return_value = False

        with patch.object(ChatSearchRepository, "_loadEmbeddingsFromDb") as mockLoad:
            mockLoad.return_value = ([[0.1] * 384], [MessageId("msg_1")])

            with patch.object(ChatSearchRepository, "_filterMessageIds") as mockFilter:
                mockFilter.return_value = [MessageId("msg_1")]
                with patch.object(ChatSearchRepository, "_fetchSearchResultRows") as mockFetch:
                    mockFetch.return_value = [{"message_id": "msg_1", "score": 1.0}]

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

                    mockLoad.assert_called_once()
                    mockProvider.vectorSearch.assert_not_called()
                    assert len(result) == 1

    async def test_nativeSearchEmptyVecResultsFallsBack(
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
        """When ``modelName`` is None, native search short-circuits to empty."""
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

    async def test_nativeSearchNearZeroNormReturnsEmpty(
        self, repo: ChatSearchRepository, mockProvider: AsyncMock
    ) -> None:
        """A near-zero-norm query vector short-circuits to empty results."""
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

    async def test_nativeSearchWithMaxMessages(self, repo: ChatSearchRepository, mockProvider: AsyncMock) -> None:
        """``maxMessages`` pre-filter computes ``minDate`` and ``minMessageId`` and adds the compound filter."""
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
            # Compound filter mirrors the numpy path's ORDER BY c.date DESC, me.message_id DESC
            # so messages sharing the cutoff timestamp don't leak into the native candidate pool.
            assert (
                "(date > :minDate OR (date = :minDate AND message_id >= :minMessageId))"
                in callArgs.kwargs["filterClause"]
            )
            assert callArgs.kwargs["filterParams"]["minDate"] == "2024-01-15T00:00:00"
            assert callArgs.kwargs["filterParams"]["minMessageId"] == "msg_cutoff"
            assert len(result) == 1

            # Regression: the cutoff must be computed over
            # ``message_embeddings`` joined to ``chat_messages`` (filtered by
            # ``modelName``), NOT over ``chat_messages`` alone. Otherwise,
            # during partial backfill or model change, the native candidate
            # pool would be trimmed differently from the numpy path.
            # applyPagination is mocked to return a placeholder, so we
            # inspect the *input* query string (first positional arg).
            applyPaginationCall = mockProvider.applyPagination.call_args
            cutoffSql: str = applyPaginationCall.args[0]
            assert "message_embeddings" in cutoffSql
            assert "JOIN chat_messages" in cutoffSql
            assert "me.model = :modelName" in cutoffSql
            # The cutoff query must select both columns used by the compound filter.
            assert "c.date" in cutoffSql
            assert "me.message_id" in cutoffSql
            # Verify the params passed to executeFetchOne carry modelName.
            fetchOneCall = mockProvider.executeFetchOne.call_args
            cutoffParams: dict = fetchOneCall.args[1]
            assert cutoffParams["modelName"] == "test-model"
            assert cutoffParams["chatId"] == 42
