"""Tests for the BaseSQLProvider vector search interface defaults."""

from collections.abc import Sequence
from typing import Any, Optional

import pytest

from internal.database.providers.base import (
    BaseSQLProvider,
    ParametrizedQuery,
    QueryResult,
    VectorDistanceMetric,
)


class _MinimalProvider(BaseSQLProvider):
    """Minimal concrete subclass for testing defaults.

    Implements all abstract methods of BaseSQLProvider with trivial
    stubs so we can test the concrete vector search defaults.
    """

    async def connect(self) -> None:
        """No-op connect stub.

        Returns:
            None.
        """
        pass

    async def disconnect(self) -> None:
        """No-op disconnect stub.

        Returns:
            None.
        """
        pass

    async def _execute(self, query: ParametrizedQuery) -> QueryResult:
        """No-op execute stub.

        Args:
            query: The parametrized query to execute (ignored).

        Returns:
            None, as no rows are fetched by this stub.
        """
        pass

    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """No-op batchExecute stub.

        Args:
            queries: Sequence of parametrized queries (ignored).

        Returns:
            An empty list of query results.
        """
        return []

    async def upsert(
        self,
        table: str,
        values: dict[str, Any],
        conflictColumns: list[str],
        updateExpressions: Optional[dict[str, Any]] = None,
    ) -> bool:
        """No-op upsert stub.

        Args:
            table: Table name (ignored).
            values: Column-to-value mapping (ignored).
            conflictColumns: Conflict target columns (ignored).
            updateExpressions: Optional update expressions (ignored).

        Returns:
            True, indicating a successful no-op upsert.
        """
        return True

    async def isReadOnly(self) -> bool:
        """Return False for the read-only flag.

        Returns:
            False, as this stub is not in read-only mode.
        """
        return False

    def applyPagination(self, query: str, limit: Optional[int], offset: int = 0) -> str:
        """No-op pagination stub that returns the query unchanged.

        Args:
            query: The base SQL query.
            limit: Maximum number of rows (ignored).
            offset: Number of rows to skip (ignored).

        Returns:
            The original query string, unmodified.
        """
        return query

    def getTextType(self, maxLength: Optional[int] = None) -> str:
        """Return a fixed TEXT type string.

        Args:
            maxLength: Optional maximum length (ignored).

        Returns:
            The literal string ``"TEXT"``.
        """
        return "TEXT"

    def getCaseInsensitiveComparison(self, column: str, param: str) -> str:
        """Return a LOWER-based case-insensitive comparison expression.

        Args:
            column: Column name to compare.
            param: Parameter name to compare against.

        Returns:
            A SQL expression comparing both sides via ``LOWER(...)``.
        """
        return f"LOWER({column}) = LOWER({param})"

    def getLikeComparison(self, column: str, param: str) -> str:
        """Return a LOWER-based case-insensitive LIKE comparison expression.

        Args:
            column: Column name to compare.
            param: Parameter name to compare against.

        Returns:
            A SQL expression performing ``LOWER(column) LIKE LOWER(param)``.
        """
        return f"LOWER({column}) LIKE LOWER({param})"


class TestVectorSearchInterface:
    """Test the BaseSQLProvider vector search defaults."""

    @pytest.fixture
    def provider(self) -> _MinimalProvider:
        """Minimal concrete provider for testing defaults."""
        return _MinimalProvider()

    async def test_isVectorSearchSupportedDefaultFalse(self, provider: _MinimalProvider) -> None:
        """Default isVectorSearchSupported returns False."""
        assert await provider.isVectorSearchSupported() is False

    async def test_vectorSearchDefaultRaises(self, provider: _MinimalProvider) -> None:
        """Default vectorSearch raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="vector search"):
            await provider.vectorSearch(
                table="test",
                vectorColumn="embedding",
                returnColumns=["id"],
                queryVector=b"test",
                k=10,
            )

    async def test_listTablesDefaultRaises(self, provider: _MinimalProvider) -> None:
        """Default listTables raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="table listing"):
            await provider.listTables()

    async def test_createVectorTableDefaultRaises(self, provider: _MinimalProvider) -> None:
        """Default createVectorTable raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="vector table"):
            await provider.createVectorTable("test", [])

    async def test_vectorSearchDefaultRaisesRegardlessOfMetric(self, provider: _MinimalProvider) -> None:
        """Default vectorSearch raises NotImplementedError regardless of metric."""
        with pytest.raises(NotImplementedError):
            await provider.vectorSearch(
                table="test",
                vectorColumn="embedding",
                returnColumns=["id"],
                queryVector=b"test",
                k=10,
                distanceMetric=VectorDistanceMetric.L2,
            )
