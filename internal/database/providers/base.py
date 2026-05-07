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
        """Initialize excluded value marker, dood!

        Args:
            column: Optional column name. If None, uses the key from update_expressions dict, dood.

        Returns:
            None.
        """
        self.column = column
        """Optional column name for this excluded value, dood."""

    def __repr__(self) -> str:
        """Return string representation of ExcludedValue, dood!

        Returns:
            String representation in format ExcludedValue(column), dood.
        """
        return f"ExcludedValue({self.column})"


class FetchType(Enum):
    """Enumeration controlling how query results are fetched after execution, dood!

    Members, dood!
        NO_FETCH: Do not fetch any rows; returns ``None``, dood.
        FETCH_ONE: Fetch a single row; returns a single dict or ``None``, dood.
        FETCH_ALL: Fetch all rows; returns a list of dicts, dood.
    """

    NO_FETCH = 1
    """Do not fetch any rows; the query result is ``None``, dood."""
    FETCH_ONE = 2
    """Fetch a single row as a dict, or ``None`` if no rows were returned, dood."""
    FETCH_ALL = 3
    """Fetch all rows as a list of dicts, dood."""


type QueryParams = Dict[str, Any] | Sequence[Any] | Mapping[str, Any]
"""Type alias for query parameters: dict, sequence, or mapping, dood!"""
type QueryResultFetchOne = Dict[str, Any] | None
"""Type alias for query result when fetching a single row, dood!"""
type QueryResultFetchAll = Sequence[Dict[str, Any]]
"""Type alias for query result when fetching all rows, dood!"""
type QueryResult = QueryResultFetchOne | QueryResultFetchAll | None
"""Type alias for query result, which can be None, a single row, or all rows, dood!"""


class ParametrizedQuery:
    """A SQL query bundled with its parameters and fetch strategy, dood!

    Attributes, dood!
        query: Raw SQL query string, dood.
        params: Positional or named parameters to bind to the query, dood.
        fetchType: Controls how many rows are returned after execution, dood.
    """

    __slots__ = ("query", "params", "fetchType")
    """Slots for query, params, and fetchType attributes, dood."""

    def __init__(self, query: str, params: Optional[QueryParams] = None, fetchType: FetchType = FetchType.NO_FETCH):
        """Initialise a parametrized query, dood!

        Args:
            query: Raw SQL query string, dood.
            params: Parameters to bind; defaults to an empty list when ``None``, dood.
            fetchType: Row-fetch strategy; defaults to :attr:`FetchType.FETCH_ALL`, dood.

        Returns:
            None.
        """
        self.query: str = query
        """Raw SQL query string, dood."""

        if params is None:
            params = []
        self.params: QueryParams = params
        """Positional or named parameters bound to the query, dood."""
        self.fetchType: FetchType = fetchType
        """Controls how many rows are returned after execution, dood."""


class BaseSQLProvider(ABC):
    """Abstract base class for SQL database providers, dood!

    Concrete subclasses must implement :meth:`connect`, :meth:`disconnect`,
    :meth:`_execute`, and :meth:`batchExecute`, dood.  The class also supports
    the async context-manager protocol via :meth:`__aenter__` /
    :meth:`__aexit__`, dood!
    """

    __slots__ = ()
    """Empty tuple for base class, dood."""

    def __init__(self) -> None:
        """Initialise the provider base (no-op), dood!

        Returns:
            None.
        """
        pass

    def __repr__(self) -> str:
        """Return a human-readable representation of the provider instance, dood!

        Returns:
            A string in the form ``ClassName(attr1=val1, attr2=val2, …)``
            including all public (non-underscore-prefixed) slot attributes, dood.
        """
        params = []
        for attr in self.__slots__:
            if attr[0] == "_":
                continue
            params.append(f"{attr}={getattr(self, attr)}")

        return type(self).__name__ + "(" + ", ".join(params) + ")"

    @abstractmethod
    async def connect(self) -> None:
        """Open the database connection, dood!

        Raises:
            NotImplementedError: Must be overridden by subclasses, dood.

        Returns:
            None.
        """
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the database connection, dood!

        Raises:
            NotImplementedError: Must be overridden by subclasses, dood.

        Returns:
            None.
        """
        raise NotImplementedError

    async def __aenter__(self) -> "BaseSQLProvider":
        """Enter the async context manager by calling :meth:`connect`, dood!

        Returns:
            The provider instance itself, dood.
        """
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Exit the async context manager by calling :meth:`disconnect`, dood!

        Logs and re-raises any exception that occurred inside the ``async with``
        block, dood.

        Args:
            exc_type: Exception type, or ``None`` if no exception occurred, dood.
            exc: Exception instance, or ``None``, dood.
            tb: Traceback object, or ``None``, dood.

        Returns:
            None.
        """
        await self.disconnect()
        if exc_type is not None:
            logger.error(exc_type, exc, tb)
            raise

    @abstractmethod
    async def _execute(self, query: ParametrizedQuery) -> QueryResult:
        """Execute a single parametrized query (internal implementation), dood!

        Args:
            query: The :class:`ParametrizedQuery` to execute, dood.

        Returns:
            Query result according to the query's :attr:`~ParametrizedQuery.fetchType`, dood.

        Raises:
            NotImplementedError: Must be overridden by subclasses, dood.
        """
        raise NotImplementedError

    async def execute(
        self,
        query: str | ParametrizedQuery,
        params: Optional[QueryParams] = None,
        fetchType: FetchType = FetchType.NO_FETCH,
    ) -> QueryResult:
        """Execute a SQL query, wrapping a plain string in :class:`ParametrizedQuery` if needed, dood!

        Args:
            query: Either a raw SQL string or a pre-built :class:`ParametrizedQuery`, dood.
            params: Bind parameters; ignored when *query* is already a
                :class:`ParametrizedQuery`, dood.
            fetchType: Row-fetch strategy; ignored when *query* is already a
                :class:`ParametrizedQuery`, dood.

        Returns:
            Query result according to the effective fetch type, dood.
        """
        if not isinstance(query, ParametrizedQuery):
            query = ParametrizedQuery(query, params, fetchType)
        return await self._execute(query)

    async def executeFetchOne(
        self,
        query: str,
        params: Optional[QueryParams] = None,
    ) -> QueryResultFetchOne:
        """Execute a SQL query and return the first row, dood!

        Args:
            query: Raw SQL query string, dood.
            params: Parameters to bind to the query; defaults to None, dood.

        Returns:
            The first row as a dict, or None if no rows were returned, dood.
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
        """Execute a SQL query and return all rows, dood!

        Args:
            query: Raw SQL query string, dood.
            params: Parameters to bind to the query; defaults to None, dood.

        Returns:
            All rows as a list of dicts, or an empty list if no rows were returned, dood.
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
        """Execute multiple parametrized queries as a single batch, dood!

        Args:
            queries: Sequence of :class:`ParametrizedQuery` objects to run, dood.

        Returns:
            A sequence of query results, one per input query, dood.

        Raises:
            NotImplementedError: Must be overridden by subclasses, dood.
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
        """Execute provider-specific upsert operation, dood!

        Args:
            table: Table name, dood.
            values: Dictionary of column names and values to insert, dood.
            conflictColumns: List of columns that define the conflict target, dood.
            updateExpressions: Optional dict of column -> expression for UPDATE clause, dood.
                If None, all non-conflict columns are updated with their values, dood.
                Supports complex expressions like "messages_count = messages_count + 1"
                or ExcludedValue() to set to excluded value, dood.

        Returns:
            True if successful, dood.

        Raises:
            NotImplementedError: Must be overridden by subclasses, dood.
        """
        raise NotImplementedError

    @abstractmethod
    async def isReadOnly(self) -> bool:
        """Check if this provider is in read-only mode, dood!

        Returns:
            True if the provider is in read-only mode, False otherwise, dood.

        Raises:
            NotImplementedError: Must be overridden by subclasses, dood.
        """
        raise NotImplementedError

    @abstractmethod
    def applyPagination(self, query: str, limit: Optional[int], offset: int = 0) -> str:
        """Apply RDBMS-specific pagination to query, dood!

        Args:
            query: The base SQL query, dood.
            limit: The maximum number of rows to return. If None, no pagination is applied, dood.
            offset: The number of rows to skip. Defaults to 0, dood.

        Returns:
            The query with pagination clause appended, dood.

        Raises:
            NotImplementedError: Must be overridden by subclasses, dood.
        """
        raise NotImplementedError

    @abstractmethod
    def getTextType(self, maxLength: Optional[int] = None) -> str:
        """Get RDBMS-specific TEXT type, dood!

        Args:
            maxLength: Optional maximum length for the text field. Used for MySQL to determine
                TEXT, MEDIUMTEXT, or LONGTEXT, dood.

        Returns:
            The appropriate TEXT type for the provider, dood.

        Raises:
            NotImplementedError: Must be overridden by subclasses, dood.
        """
        raise NotImplementedError

    @abstractmethod
    def getCaseInsensitiveComparison(self, column: str, param: str) -> str:
        """Get RDBMS-specific case-insensitive comparison, dood!

        Args:
            column: The column name to compare, dood.
            param: The parameter name to use in the comparison, dood.

        Returns:
            A SQL expression string for case-insensitive comparison, dood.

        Raises:
            NotImplementedError: Must be overridden by subclasses, dood.
        """
        raise NotImplementedError

    @abstractmethod
    def getLikeComparison(self, column: str, param: str) -> str:
        """Get RDBMS-specific case-insensitive LIKE comparison, dood!

        Args:
            column: The column name to compare, dood.
            param: The parameter name to use in the comparison, dood.

        Returns:
            A SQL expression string for case-insensitive LIKE comparison, dood.

        Raises:
            NotImplementedError: Must be overridden by subclasses, dood.
        """
        raise NotImplementedError
