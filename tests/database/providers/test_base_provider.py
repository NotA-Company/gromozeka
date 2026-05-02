"""
Tests for base provider functionality and helper methods.

This module tests the BaseSQLProvider abstract class and its helper methods:
- ExcludedValue class
"""

from typing import Optional

from internal.database.providers.base import (
    BaseSQLProvider,
    ExcludedValue,
    FetchType,
    ParametrizedQuery,
)


class MockProvider(BaseSQLProvider):
    """Mock provider for testing base functionality."""

    def __init__(self, providerType: str = "sqlite"):
        self._providerType = providerType
        self._connected = False

    async def connect(self) -> None:
        """Mock connect."""
        self._connected = True

    async def disconnect(self) -> None:
        """Mock disconnect."""
        self._connected = False

    async def _execute(self, query: ParametrizedQuery):
        """Mock execute."""
        return None

    async def batchExecute(self, queries):
        """Mock batch execute."""
        return []

    async def upsert(self, table, values, conflictColumns, updateExpressions=None):
        """Mock upsert."""
        return True

    async def isReadOnly(self) -> bool:
        """Mock isReadOnly."""
        return False

    def getProviderType(self) -> str:
        """Return provider type."""
        return self._providerType

    def applyPagination(self, query: str, limit: Optional[int], offset: int = 0) -> str:
        """Mock applyPagination."""
        if limit is None:
            return query
        return f"{query} LIMIT {limit} OFFSET {offset}"

    def getTextType(self, maxLength: Optional[int] = None) -> str:
        """Mock getTextType."""
        return "TEXT"

    def getCaseInsensitiveComparison(self, column: str, param: str) -> str:
        """Mock getCaseInsensitiveComparison."""
        return f"LOWER({column}) = LOWER(:{param})"


class TestExcludedValue:
    """Tests for ExcludedValue class."""

    def test_excluded_value_without_column(self):
        """Test ExcludedValue without column name."""
        excluded = ExcludedValue()
        assert excluded.column is None
        assert repr(excluded) == "ExcludedValue(None)"

    def test_excluded_value_with_column(self):
        """Test ExcludedValue with column name."""
        excluded = ExcludedValue("value")
        assert excluded.column == "value"
        assert repr(excluded) == "ExcludedValue(value)"


class TestParametrizedQuery:
    """Tests for ParametrizedQuery class."""

    def test_parametrized_query_with_defaults(self):
        """Test ParametrizedQuery with default parameters."""
        query = ParametrizedQuery("SELECT * FROM test")
        assert query.query == "SELECT * FROM test"
        assert query.params == []
        assert query.fetchType == FetchType.NO_FETCH

    def test_parametrized_query_with_params(self):
        """Test ParametrizedQuery with parameters."""
        query = ParametrizedQuery("SELECT * FROM test WHERE id = :id", {"id": 1})
        assert query.query == "SELECT * FROM test WHERE id = :id"
        assert query.params == {"id": 1}
        assert query.fetchType == FetchType.NO_FETCH

    def test_parametrized_query_with_fetch_type(self):
        """Test ParametrizedQuery with fetch type."""
        query = ParametrizedQuery("SELECT * FROM test", fetchType=FetchType.FETCH_ALL)
        assert query.query == "SELECT * FROM test"
        assert query.params == []
        assert query.fetchType == FetchType.FETCH_ALL

    def test_parametrized_query_with_all_params(self):
        """Test ParametrizedQuery with all parameters."""
        query = ParametrizedQuery("SELECT * FROM test WHERE id = :id", {"id": 1}, FetchType.FETCH_ONE)
        assert query.query == "SELECT * FROM test WHERE id = :id"
        assert query.params == {"id": 1}
        assert query.fetchType == FetchType.FETCH_ONE

    def test_parametrized_query_params_none_becomes_empty_list(self):
        """Test that None params becomes empty list."""
        query = ParametrizedQuery("SELECT * FROM test", None)
        assert query.params == []
