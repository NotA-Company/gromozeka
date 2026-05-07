"""Base abstractions for SQL database providers.

Defines :class:`FetchType`, :class:`ParametrizedQuery`, type aliases
``QueryParams`` / ``QueryResult``, and the abstract :class:`BaseSQLProvider`
that all concrete providers must implement.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExcludedValue:
    """Special marker to indicate a column should be set to the excluded value.

    This allows provider-specific translation:
    - SQLite/PostgreSQL: excluded.column
    - MySQL: VALUES(column)

    Usage:
        update_expressions = {
            "value": ExcludedValue(),  # Will be translated to excluded.value or VALUES(value)
            "count": "count + 1"  # Custom expression
        }
    """

    def __init__(self, column: Optional[str] = None):
        """Initialize excluded value marker.

        Args:
            column: Optional column name. If None, uses the key from update_expressions dict.
        """
        self.column = column

    def __repr__(self) -> str:
        """Return string representation of ExcludedValue."""
        return f"ExcludedValue({self.column})"


class FetchType(Enum):
    """Enumeration controlling how query results are fetched after execution.

    Members:
        NO_FETCH: Do not fetch any rows; returns ``None``.
        FETCH_ONE: Fetch a single row; returns a single dict or ``None``.
        FETCH_ALL: Fetch all rows; returns a list of dicts.
    """

    NO_FETCH = 1
    """Do not fetch any rows; the query result is ``None``."""
    FETCH_ONE = 2
    """Fetch a single row as a dict, or ``None`` if no rows were returned."""
    FETCH_ALL = 3
    """Fetch all rows as a list of dicts."""


type QueryParams = Dict[str, Any] | Sequence[Any] | Mapping[str, Any]
"""Type alias for query parameters: dict, sequence, or mapping."""
type QueryResultFetchOne = Dict[str, Any] | None
"""Type alias for query result when fetching a single row."""
type QueryResultFetchAll = Sequence[Dict[str, Any]]
"""Type alias for query result when fetching all rows."""
type QueryResult = QueryResultFetchOne | QueryResultFetchAll | None
"""Type alias for query result, which can be None, a single row, or all rows."""


class ParametrizedQuery:
    """A SQL query bundled with its parameters and fetch strategy.

    Attributes:
        query: Raw SQL query string.
        params: Positional or named parameters to bind to the query.
        fetchType: Controls how many rows are returned after execution.
    """

    __slots__ = ("query", "params", "fetchType")

    def __init__(self, query: str, params: Optional[QueryParams] = None, fetchType: FetchType = FetchType.NO_FETCH):
        """Initialise a parametrized query.

        Args:
            query: Raw SQL query string.
            params: Parameters to bind; defaults to an empty list when ``None``.
            fetchType: Row-fetch strategy; defaults to :attr:`FetchType.FETCH_ALL`.
        """
        self.query: str = query
        """Raw SQL query string."""

        if params is None:
            params = []
        self.params: QueryParams = params
        """Positional or named parameters bound to the query."""
        self.fetchType: FetchType = fetchType
        """Controls how many rows are returned after execution."""


class BaseSQLProvider(ABC):
    """Abstract base class for SQL database providers.

    Concrete subclasses must implement :meth:`connect`, :meth:`disconnect`,
    :meth:`_execute`, and :meth:`batchExecute`.  The class also supports
    the async context-manager protocol via :meth:`__aenter__` /
    :meth:`__aexit__`.
    """

    __slots__ = ()

    def __init__(self) -> None:
        """Initialise the provider base (no-op)."""
        pass

    def __repr__(self) -> str:
        """Return a human-readable representation of the provider instance.

        Returns:
            A string in the form ``ClassName(attr1=val1, attr2=val2, …)``
            including all public (non-underscore-prefixed) slot attributes.
        """
        params = []
        for attr in self.__slots__:
            if attr[0] == "_":
                continue
            params.append(f"{attr}={getattr(self, attr)}")

        return type(self).__name__ + "(" + ", ".join(params) + ")"

    @abstractmethod
    async def connect(self) -> None:
        """Open the database connection.

        Raises:
            NotImplementedError: Must be overridden by subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the database connection.

        Raises:
            NotImplementedError: Must be overridden by subclasses.
        """
        raise NotImplementedError

    async def __aenter__(self) -> "BaseSQLProvider":
        """Enter the async context manager by calling :meth:`connect`.

        Returns:
            The provider instance itself.
        """
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Exit the async context manager by calling :meth:`disconnect`.

        Logs and re-raises any exception that occurred inside the ``async with``
        block.

        Args:
            exc_type: Exception type, or ``None`` if no exception occurred.
            exc: Exception instance, or ``None``.
            tb: Traceback object, or ``None``.
        """
        await self.disconnect()
        if exc_type is not None:
            logger.error(exc_type, exc, tb)
            raise

    @abstractmethod
    async def _execute(self, query: ParametrizedQuery) -> QueryResult:
        """Execute a single parametrized query (internal implementation).

        Args:
            query: The :class:`ParametrizedQuery` to execute.

        Returns:
            Query result according to the query's :attr:`~ParametrizedQuery.fetchType`.

        Raises:
            NotImplementedError: Must be overridden by subclasses.
        """
        raise NotImplementedError

    async def execute(
        self,
        query: str | ParametrizedQuery,
        params: Optional[QueryParams] = None,
        fetchType: FetchType = FetchType.NO_FETCH,
    ) -> QueryResult:
        """Execute a SQL query, wrapping a plain string in :class:`ParametrizedQuery` if needed.

        Args:
            query: Either a raw SQL string or a pre-built :class:`ParametrizedQuery`.
            params: Bind parameters; ignored when *query* is already a
                :class:`ParametrizedQuery`.
            fetchType: Row-fetch strategy; ignored when *query* is already a
                :class:`ParametrizedQuery`.

        Returns:
            Query result according to the effective fetch type.
        """
        if not isinstance(query, ParametrizedQuery):
            query = ParametrizedQuery(query, params, fetchType)
        return await self._execute(query)

    async def executeFetchOne(
        self,
        query: str,
        params: Optional[QueryParams] = None,
    ) -> QueryResultFetchOne:
        """Execute a SQL query and return the first row.

        Args:
            query: Raw SQL query string.
            params: Parameters to bind to the query; defaults to None.

        Returns:
            The first row as a dict, or None if no rows were returned.
        """
        ret = await self._execute(ParametrizedQuery(query, params, FetchType.FETCH_ONE))
        if not ret:
            return None
        if isinstance(ret, Sequence):
            logger.warning(f"Query returned more than one row: {ret}")
            ret = ret[0]

        if not isinstance(ret, Mapping):
            logger.error(f"Query returned non-mapping: {ret}")
            return None

        return ret

    async def executeFetchAll(
        self,
        query: str,
        params: Optional[QueryParams] = None,
    ) -> QueryResultFetchAll:
        """Execute a SQL query and return all rows.

        Args:
            query: Raw SQL query string.
            params: Parameters to bind to the query; defaults to None.

        Returns:
            All rows as a list of dicts, or an empty list if no rows were returned.
        """
        ret = await self._execute(ParametrizedQuery(query, params, FetchType.FETCH_ALL))
        if not ret:
            return []

        if not isinstance(ret, Sequence):
            logger.error(f"Query returned non-sequence: {ret}")
            return []

        return ret

    @abstractmethod
    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """Execute multiple parametrized queries as a single batch.

        Args:
            queries: Sequence of :class:`ParametrizedQuery` objects to run.

        Returns:
            A sequence of query results, one per input query.

        Raises:
            NotImplementedError: Must be overridden by subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    async def upsert(
        self,
        table: str,
        values: Dict[str, Any],
        conflictColumns: List[str],
        updateExpressions: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Execute provider-specific upsert operation.

        Args:
            table: Table name.
            values: Dictionary of column names and values to insert.
            conflictColumns: List of columns that define the conflict target.
            updateExpressions: Optional dict of column -> expression for UPDATE clause.
                If None, all non-conflict columns are updated with their values.
                Supports complex expressions like "messages_count = messages_count + 1"
                or ExcludedValue() to set to excluded value.

        Returns:
            True if successful.

        Raises:
            NotImplementedError: Must be overridden by subclasses.
        """
        raise NotImplementedError

    @abstractmethod
    async def isReadOnly(self) -> bool:
        """Check if this provider is in read-only mode.

        Returns:
            True if the provider is in read-only mode, False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def applyPagination(self, query: str, limit: Optional[int], offset: int = 0) -> str:
        """Apply RDBMS-specific pagination to query.

        Args:
            query: The base SQL query.
            limit: The maximum number of rows to return. If None, no pagination is applied.
            offset: The number of rows to skip. Defaults to 0.

        Returns:
            The query with pagination clause appended.
        """
        raise NotImplementedError

    @abstractmethod
    def getTextType(self, maxLength: Optional[int] = None) -> str:
        """Get RDBMS-specific TEXT type.

        Args:
            maxLength: Optional maximum length for the text field. Used for MySQL to determine
                TEXT, MEDIUMTEXT, or LONGTEXT.

        Returns:
            The appropriate TEXT type for the provider.
        """
        raise NotImplementedError

    @abstractmethod
    def getCaseInsensitiveComparison(self, column: str, param: str) -> str:
        """Get RDBMS-specific case-insensitive comparison.

        Args:
            column: The column name to compare.
            param: The parameter name to use in the comparison.

        Returns:
            A SQL expression string for case-insensitive comparison.
        """
        raise NotImplementedError

    @abstractmethod
    def getLikeComparison(self, column: str, param: str) -> str:
        """Get RDBMS-specific case-insensitive LIKE comparison.

        Args:
            column: The column name to compare.
            param: The parameter name to use in the comparison.

        Returns:
            A SQL expression string for case-insensitive LIKE comparison.
        """
        raise NotImplementedError
