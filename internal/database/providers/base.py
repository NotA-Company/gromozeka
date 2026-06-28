"""Base abstractions for SQL database providers.

Defines :class:`FetchType`, :class:`ParametrizedQuery`, type aliases
``QueryParams`` / ``QueryResult``, and the abstract :class:`BaseSQLProvider`
that all concrete providers must implement.
"""

import logging
import types
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from enum import Enum, StrEnum
from typing import Any, Dict, List, NotRequired, Optional, TypedDict

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

        Returns:
            None.
        """
        self.column = column
        """Optional column name for this excluded value."""

    def __repr__(self) -> str:
        """Return string representation of ExcludedValue.

        Returns:
            String representation in format ExcludedValue(column).
        """
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
    """Slots for query, params, and fetchType attributes."""

    def __init__(self, query: str, params: Optional[QueryParams] = None, fetchType: FetchType = FetchType.NO_FETCH):
        """Initialize a parametrized query.

        Args:
            query: Raw SQL query string.
            params: Parameters to bind; defaults to an empty list when ``None``.
            fetchType: Row-fetch strategy; defaults to :attr:`FetchType.FETCH_ALL`.

        Returns:
            None.
        """
        self.query: str = query
        """Raw SQL query string."""

        if params is None:
            params = []
        self.params: QueryParams = params
        """Positional or named parameters bound to the query."""
        self.fetchType: FetchType = fetchType
        """Controls how many rows are returned after execution."""


class VectorSearchResult(TypedDict):
    """A single row from a native vector similarity search.

    Attributes:
        rowKey: Mapping of column name to string value for each
            requested return column. For composite primary keys,
            all key columns are present (e.g. ``{"chat_id": "42",
            "message_id": "abc"}``). For single-column keys, the
            dict has one entry.
        distance: Raw distance/dissimilarity score from the database
            engine. Lower is more similar for cosine distance. Callers
            convert to similarity via ``1.0 - distance`` when the
            metric is cosine.
    """

    rowKey: dict[str, Any]
    """Column-name-to-value mapping for the requested return columns."""
    distance: float
    """Distance score (metric-dependent; lower = more similar for cosine)."""


class VectorDistanceMetric(StrEnum):
    """Distance metrics for native vector similarity search.

    Each provider maps these to its native syntax. If a provider does
    not support a particular metric, it raises ``ValueError``.
    """

    COSINE = "cosine"
    """Cosine distance (1.0 - cosine_similarity). Range [0, 2]."""
    L2 = "l2"
    """Euclidean (L2) distance."""


class VectorColumnType(StrEnum):
    """Column types for vector table creation.

    Providers map these to their native type names. The ``VECTOR`` type
    is special — it creates a vector/embedding column with dimension
    and distance metric parameters.
    """

    TEXT = "text"
    """Variable-length text."""
    INTEGER = "integer"
    """Integer."""
    FLOAT = "float"
    """Floating-point number."""
    BLOB = "blob"
    """Binary data."""
    VECTOR = "vector"
    """Vector/embedding column. Requires ``vectorDimension`` and
    optionally ``distanceMetric`` in the column definition."""


class VectorColumnDef(TypedDict):
    """Definition of a single column for :meth:`createVectorTable`.

    Attributes:
        name: Column name.
        columnType: Logical column type from :class:`VectorColumnType`.
        isPartitionKey: If ``True``, the column is a partition key
            (vec0 ``PARTITION KEY`` syntax). Used to prune search space.
            Default ``False``.
        vectorDimension: For ``VECTOR`` columns, the embedding
            dimension (e.g. 384, 1024). Required when ``columnType`` is
            ``VECTOR``.
        distanceMetric: For ``VECTOR`` columns, the distance metric.
            Default depends on provider.
    """

    name: str
    columnType: VectorColumnType
    isPartitionKey: NotRequired[bool]
    vectorDimension: NotRequired[int]
    distanceMetric: NotRequired[VectorDistanceMetric]


class BaseSQLProvider(ABC):
    """Abstract base class for SQL database providers.

    Concrete subclasses must implement :meth:`connect`, :meth:`disconnect`,
    :meth:`_execute`, and :meth:`batchExecute`. The class also supports
    the async context-manager protocol via :meth:`__aenter__` /
    :meth:`__aexit__`.
    """

    __slots__ = ()
    """Empty tuple for base class."""

    def __init__(self) -> None:
        """Initialize the provider base (no-op).

        Returns:
            None.
        """
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

        Returns:
            None.
        """
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the database connection.

        Raises:
            NotImplementedError: Must be overridden by subclasses.

        Returns:
            None.
        """
        raise NotImplementedError

    async def __aenter__(self) -> "BaseSQLProvider":
        """Enter the async context manager by calling :meth:`connect`.

        Returns:
            The provider instance itself.
        """
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[types.TracebackType],
    ) -> None:
        """Exit the async context manager by calling :meth:`disconnect`.

        Logs and re-raises any exception that occurred inside the ``async with``
        block.

        Args:
            exc_type: Exception type, or ``None`` if no exception occurred.
            exc: Exception instance, or ``None``.
            tb: Traceback object, or ``None``.

        Returns:
            None.
        """
        await self.disconnect()
        if exc_type is not None:
            assert exc is not None
            assert tb is not None
            logger.error(f"Exception in provider context: {exc_type}", exc_info=(exc_type, exc, tb))
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

        Raises:
            NotImplementedError: Must be overridden by subclasses.
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

        Raises:
            NotImplementedError: Must be overridden by subclasses.
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

        Raises:
            NotImplementedError: Must be overridden by subclasses.
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

        Raises:
            NotImplementedError: Must be overridden by subclasses.
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

        Raises:
            NotImplementedError: Must be overridden by subclasses.
        """
        raise NotImplementedError

    async def isVectorSearchSupported(self) -> bool:
        """Check if this provider supports native vector similarity search.

        Providers that load a vector extension (e.g. sqlite-vec, pgvector)
        override this to return ``True`` after confirming the extension is
        operational. The default returns ``False``.

        Returns:
            ``True`` if :meth:`vectorSearch` is available, ``False`` otherwise.
        """
        return False

    async def vectorSearch(
        self,
        *,
        table: str,
        vectorColumn: str,
        returnColumns: list[str],
        queryVector: bytes,
        k: int,
        filterClause: str = "",
        filterParams: Optional[dict[str, str | int | float | None]] = None,
        distanceMetric: VectorDistanceMetric = VectorDistanceMetric.COSINE,
    ) -> list[VectorSearchResult]:
        """Perform a native KNN vector similarity search.

        Executes a provider-specific nearest-neighbour query over the
        ``vectorColumn`` in ``table``, returning the ``k`` closest rows.

        The query vector must be pre-serialised to the provider's expected
        binary format (e.g. ``array.array("f", floats).tobytes()`` for
        sqlite-vec float32). This avoids an extra copy/conversion inside
        the provider.

        Args:
            table: Table (or virtual table) name containing the vectors.
            vectorColumn: Column holding the vector BLOB.
            returnColumns: List of column names whose values populate
                the :attr:`VectorSearchResult.rowKey` dict in results.
            queryVector: The query vector as raw bytes in the format
                expected by the provider.
            k: Maximum number of nearest neighbours to return.
            filterClause: Optional SQL WHERE fragment to pre-filter rows.
                Must use ``:named`` placeholders referencing keys in
                ``filterParams``. Example:
                ``"chat_id = :chatId AND model = :modelName"``.
                Empty string means no extra filter.
            filterParams: Named parameters for ``filterClause``. ``None``
                or empty dict when ``filterClause`` is empty.
            distanceMetric: Distance metric to use for the similarity
                comparison. Providers validate support at call time.

        Returns:
            List of :class:`VectorSearchResult` ordered by distance
            ascending (most similar first). May contain fewer than ``k``
            results if the table has fewer matching rows.

        Raises:
            NotImplementedError: When the provider does not support native
                vector search (default implementation).
            ValueError: When ``distanceMetric`` is not supported by this
                provider.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support native vector search")

    async def listTables(self, likePattern: str = "%") -> list[str]:
        """List table names matching a LIKE pattern.

        Each provider implements this with its native introspection query.
        Used by the vector search subsystem to discover vec0 tables for
        cleanup and to check whether a dimension-specific table exists.

        Args:
            likePattern: SQL LIKE pattern (e.g. ``"vec_message_embeddings_%"``).
                The default ``"%"`` matches all tables.

        Returns:
            List of matching table names.

        Raises:
            NotImplementedError: If the provider does not support table
                listing (default implementation).
        """
        raise NotImplementedError(f"{type(self).__name__} does not support table listing")

    async def createVectorTable(
        self,
        tableName: str,
        columns: list[VectorColumnDef],
    ) -> None:
        """Create a vector table/index for native similarity search.

        Each provider maps the column definitions to its native DDL.
        Providers without vector support raise ``NotImplementedError``.

        Args:
            tableName: Name for the new table (e.g. ``"vec_message_embeddings_384"``).
            columns: Ordered list of column definitions. At least one
                column must have ``columnType=VectorColumnType.VECTOR``.

        Raises:
            NotImplementedError: If the provider does not support vector
                tables (default implementation).
            ValueError: If no ``VECTOR`` column is present or required
                fields are missing.

        Returns:
            None.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support vector table creation")
