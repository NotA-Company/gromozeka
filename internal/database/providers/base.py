"""Base abstractions for SQL database providers.

Defines :class:`FetchType`, :class:`ParametrizedQuery`, type aliases
``QueryParams`` / ``QueryResult``, and the abstract :class:`BaseSQLProvider`
that all concrete providers must implement.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


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


type QueryParams = Dict[str, Any] | Sequence[Any]
type QueryResult = Dict[str, Any] | Sequence[Dict[str, Any]] | None


class ParametrizedQuery:
    """A SQL query bundled with its parameters and fetch strategy.

    Attributes:
        query: Raw SQL query string.
        params: Positional or named parameters to bind to the query.
        fetchType: Controls how many rows are returned after execution.
    """

    __slots__ = ("query", "params", "fetchType")

    def __init__(self, query: str, params: Optional[QueryParams] = None, fetchType: FetchType = FetchType.FETCH_ALL):
        """Initialise a parametrized query.

        Args:
            query: Raw SQL query string.
            params: Parameters to bind; defaults to an empty list when ``None``.
            fetchType: Row-fetch strategy; defaults to :attr:`FetchType.FETCH_ALL`.
        """
        self.query: str = query

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
        fetchType: FetchType = FetchType.FETCH_ALL,
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
