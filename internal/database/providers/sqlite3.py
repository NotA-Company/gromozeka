"""SQLite3 database provider implementation.

Provides :class:`SQLite3Provider`, a concrete :class:`BaseSQLProvider` that
wraps the :mod:`aiosqlite` library with a fully async interface.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, cast

import aiosqlite

from . import utils
from .base import (
    BaseSQLProvider,
    ExcludedValue,
    FetchType,
    ParametrizedQuery,
    QueryResult,
    VectorColumnDef,
    VectorColumnType,
    VectorDistanceMetric,
    VectorSearchResult,
)

# Optional dependency for native vector search.
try:
    import sqlite_vec

    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    _SQLITE_VEC_AVAILABLE = False

logger = logging.getLogger(__name__)


async def _loadSqliteVecExtension(
    connection: aiosqlite.Connection,
    extensionPath: str,
) -> Optional[str]:
    """Load sqlite-vec into an aiosqlite connection.

    Uses aiosqlite's built-in extension-loading API. Enables extension
    loading, loads the sqlite-vec shared library, then disables extension
    loading immediately (security best-practice).

    Args:
        connection: Open aiosqlite connection.
        extensionPath: Filesystem path to the ``vec0`` shared library to
            load. 

    Returns:
        sqlite-vec version string on success, or ``None`` if loading
        fails for any reason (missing extension, permission denied, etc.).
    """
    # Deliberately narrow try/except — only catching extension-loading
    # failures. Other exceptions propagate. The outer try/except handles the
    # case where enable_load_extension(True) itself fails (e.g. on macOS Apple
    # Python). The inner try/finally guarantees extension loading is always
    # disabled, even when load_extension() or vec_version() raises.
    try:
        await connection.enable_load_extension(True)
        try:
            await connection.load_extension(extensionPath)
            async with connection.execute("SELECT vec_version()") as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                version: Optional[str] = row[0]
            return version
        finally:
            await connection.enable_load_extension(False)
    except Exception:
        return None


class SQLite3Provider(BaseSQLProvider):
    """SQL provider backed by a local SQLite3 database file, dood!

    Uses :mod:`aiosqlite` for a fully non-blocking async interface.

    Attributes:
        dbPath: Filesystem path to the SQLite3 database file.
        readOnly: When ``True``, the connection is opened in query-only mode.
        useWal: When ``True``, WAL journal mode is enabled on the connection.
        timeout: Seconds to wait for the database lock before raising an error.
    """

    __slots__ = (
        "dbPath",
        "readOnly",
        "useWal",
        "timeout",
        "enableForeignKeys",
        "keepConnection",
        "_connection",
        "_connectLock",
        "_vectorExtensionPath",
        "_vectorSearchAvailable",
    )

    def __init__(
        self,
        dbPath: str,
        *,
        readOnly: bool = False,
        useWal: bool = False,
        timeout: int = 30,
        enableForeignKeys: bool = True,
        keepConnection: Optional[bool] = None,
        vectorExtensionPath: Optional[str] = None,
    ) -> None:
        """Initialise the SQLite3 provider, dood!

        Args:
            dbPath: Filesystem path to the SQLite3 database file.
            readOnly: Open connection in query-only mode when ``True``.
            useWal: Enable WAL journal mode when ``True``.
            timeout: Seconds to wait for the database lock; defaults to ``30``.
            enableForeignKeys: Enable foreign key constraints when ``True``; defaults to ``True``.
            keepConnection: If ``True``, connect on creation and keep connection open.
                If ``False``, do not connect on creation.
                If ``None`` (default), treat as ``False`` except for in-memory
                databases (``dbPath == ":memory:"``) where it's treated as ``True``.
            vectorExtensionPath: Optional filesystem path to a prebuilt
                ``sqlite-vec`` shared library (``vec0.so``/``vec0.dylib``).
                Used as a fallback when the ``sqlite_vec`` pip package is not
                importable (e.g. Alpine Linux with no musl wheel), allowing the
                extension to be loaded from a source-built binary. When
                ``None`` and the pip package is available, the package's
                bundled ``loadable_path()`` is used.
        """
        super().__init__()
        self._vectorSearchAvailable: bool = False
        self.dbPath: str = dbPath
        """Filesystem path to the SQLite3 database file."""
        self.readOnly: bool = readOnly
        """When ``True``, the connection is opened in query-only mode."""
        self.useWal: bool = useWal
        """When ``True``, WAL journal mode is enabled on the connection."""
        self.timeout: int = timeout
        """Seconds to wait for the database lock before raising an error."""
        self.enableForeignKeys: bool = enableForeignKeys
        """When ``True``, foreign key constraints are enabled on the connection."""

        # Determine effective keepConnection value
        if keepConnection is None:
            # For in-memory databases, default to True to avoid losing data
            self.keepConnection: bool = dbPath == ":memory:"
        else:
            self.keepConnection: bool = keepConnection
        """If ``True``, the connection is kept open across operations."""

        self._connection: Optional[aiosqlite.Connection] = None
        self._connectLock: asyncio.Lock = asyncio.Lock()
        """Lock to prevent race conditions during connection creation."""
        self._vectorExtensionPath: Optional[str] = vectorExtensionPath
        """Filesystem path to a prebuilt sqlite-vec shared library, or ``None``."""

    async def connect(self) -> None:
        """Open the aiosqlite connection, dood!

        Applies ``PRAGMA query_only`` when :attr:`readOnly` is set, and
        ``PRAGMA journal_mode = WAL`` when :attr:`useWal` is set.

        Uses a lock to prevent race conditions when multiple coroutines
        try to connect simultaneously.
        """
        # Fast path: if already connected, return immediately
        if self._connection is not None:
            return

        # Use lock to prevent race conditions during connection creation
        async with self._connectLock:
            # Double-check after acquiring lock
            if self._connection is not None:
                return

            connection: aiosqlite.Connection = await aiosqlite.connect(
                self.dbPath,
                timeout=self.timeout,
            )

            connection.row_factory = aiosqlite.Row
            if self.readOnly:
                await connection.execute("PRAGMA query_only = ON")
            if self.useWal:
                await connection.execute("PRAGMA journal_mode = WAL")
            if self.enableForeignKeys:
                await connection.execute("PRAGMA foreign_keys = ON")

            # Attempt to load sqlite-vec for native vector search.
            # self._vectorSearchAvailable = False
        
            extensionSource: Optional[str] = None
            if _SQLITE_VEC_AVAILABLE:
                # Package installed — use its bundled .so (version-matched, reliable).
                extensionSource = sqlite_vec.loadable_path()
            elif self._vectorExtensionPath is not None:
                # No pip package, but a custom build path is configured (e.g. Alpine
                # Linux where the extension was built from source). See
                # ``vectorExtensionPath`` config key under
                # ``[database.providers.<name>.parameters]``.
                extensionSource = self._vectorExtensionPath

            if extensionSource is not None:
                version = await _loadSqliteVecExtension(connection, extensionSource)
                if version is not None:
                    self._vectorSearchAvailable = True
                    logger.info("sqlite-vec %s loaded from %s", version, extensionSource)
                else:
                    self._vectorSearchAvailable = False
                    logger.warning(
                        "sqlite-vec extension failed to load from %s; native vector search disabled",
                        extensionSource,
                    )
            else:
                self._vectorSearchAvailable = False


            self._connection = connection
            logger.debug(
                f"Connected to SQLite3 database at {self.dbPath} with readOnly={self.readOnly} and useWal={self.useWal}"
            )

    async def disconnect(self) -> None:
        """Close the aiosqlite connection, dood!"""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.debug(f"Disconnected from SQLite3 database at {self.dbPath}")

    async def isReadOnly(self) -> bool:
        """Return if this provider is in read only mode or not, dood!

        Returns:
            ``True`` if the provider is in read-only mode, ``False`` otherwise.
        """

        return self.readOnly

    @asynccontextmanager
    async def cursor(self, *, keepConnection: Optional[bool] = None) -> AsyncGenerator[aiosqlite.Cursor, None]:
        """Async context manager that yields a database cursor, dood!

        Automatically commits on success or rolls back on any exception.
        Opens the connection if it is not already open, and closes it again
        afterwards when it was not open before entering.

        Args:
            keepConnection: If True, keeps the connection open even if it was
                closed before entering this context manager. If None (default),
                uses the instance-level ``keepConnection`` setting.

        Yields:
            An open :class:`aiosqlite.Cursor` ready for query execution.

        Raises:
            Exception: Re-raises any exception that occurs during execution
                after rolling back the transaction.
        """
        # Use instance-level keepConnection if not explicitly provided
        effectiveKeepConnection = keepConnection if keepConnection is not None else self.keepConnection

        # Track whether we opened the connection ourselves
        # This prevents race conditions in concurrent operations
        wasConnected: bool = self._connection is not None

        # Connect if not already connected
        # If keepConnection is True, this will establish the connection on first use
        await self.connect()

        assert self._connection is not None

        cursor = await self._connection.cursor()
        try:
            yield cursor
            await self._connection.commit()
        except Exception as e:
            await self._connection.rollback()
            logger.error(f"Database operation failed: {e}")
            logger.exception(e)
            raise
        finally:
            # Close cursor before disconnecting to avoid "Connection closed" error
            await cursor.close()
            # Only disconnect if we opened the connection ourselves AND keepConnection is False
            if not wasConnected and not effectiveKeepConnection:
                await self.disconnect()

    async def _makeQueryResult(self, cursor: aiosqlite.Cursor, fetchType: FetchType) -> QueryResult:
        """Convert a cursor's pending rows into the appropriate result type, dood!

        Args:
            cursor: An executed :class:`aiosqlite.Cursor`.
            fetchType: Controls how many rows are retrieved.

        Returns:
            All rows, one row, or ``None`` depending on *fetchType*.

        Raises:
            ValueError: If *fetchType* is not a recognised :class:`FetchType` member.
        """
        match fetchType:
            case FetchType.FETCH_ALL:
                rows = await cursor.fetchall()
                # Convert Row objects to dicts
                return cast(QueryResult, [dict(row) for row in rows] if rows else [])
            case FetchType.FETCH_ONE:
                row = await cursor.fetchone()
                # Convert Row object to dict
                return cast(QueryResult, dict(row) if row else None)
            case FetchType.NO_FETCH:
                return None
        raise ValueError(f"Unknown fetch type: {fetchType}")

    async def _execute(self, query: ParametrizedQuery) -> QueryResult:
        """Execute a single parametrized query, dood!

        Args:
            query: The :class:`ParametrizedQuery` to run.

        Returns:
            Query result according to the query's fetch type.
        """
        async with self.cursor(keepConnection=self.keepConnection) as cursor:
            await cursor.execute(query.query, utils.convertContainerElementsToSQLite(query.params))
            return await self._makeQueryResult(cursor, query.fetchType)

    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """Execute multiple queries in a single database transaction, dood!

        All queries share one cursor and one commit/rollback cycle, so either
        all succeed or all are rolled back together.

        Args:
            queries: Sequence of :class:`ParametrizedQuery` objects to execute.

        Returns:
            A list of query results, one per input query, in the same order.
        """
        ret: list[QueryResult] = []
        async with self.cursor(keepConnection=self.keepConnection) as cursor:
            for query in queries:
                await cursor.execute(query.query, utils.convertContainerElementsToSQLite(query.params))
                ret.append(await self._makeQueryResult(cursor, query.fetchType))

        return ret

    def applyPagination(self, query: str, limit: Optional[int], offset: int = 0) -> str:
        """Apply SQLite-specific pagination to query, dood!

        Args:
            query: The base SQL query.
            limit: The maximum number of rows to return. If None, no pagination is applied.
            offset: The number of rows to skip. Defaults to 0.

        Returns:
            The query with pagination clause appended.
        """
        if limit is None:
            return query
        offsetStr = ""
        if offset:
            offsetStr = f" OFFSET {offset}"
        return f"{query} LIMIT {limit}{offsetStr}"

    def getTextType(self, maxLength: Optional[int] = None) -> str:
        """Get SQLite-specific TEXT type, dood!

        Args:
            maxLength: Optional maximum length for the text field (ignored in SQLite).

        Returns:
            The TEXT type for SQLite.
        """
        return "TEXT"

    def getCaseInsensitiveComparison(self, column: str, param: str) -> str:
        """Get SQLite-specific case-insensitive comparison, dood!

        Args:
            column: The column name to compare.
            param: The parameter name to use in the comparison.

        Returns:
            A SQL expression string for case-insensitive comparison.
        """
        return f"LOWER({column}) = LOWER(:{param})"

    def getLikeComparison(self, column: str, param: str) -> str:
        """Get SQLite-specific case-insensitive LIKE comparison, dood!

        Args:
            column: The column name to compare.
            param: The parameter name to use in the comparison.

        Returns:
            A SQL expression string for case-insensitive LIKE comparison.
        """
        return f"LOWER({column}) LIKE LOWER(:{param})"

    async def upsert(
        self,
        table: str,
        values: Dict[str, Any],
        conflictColumns: List[str],
        updateExpressions: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Execute SQLite-specific upsert operation, dood!

        Args:
            table: Table name.
            values: Dictionary of column names and values to insert.
            conflictColumns: List of columns that define the conflict target.
            updateExpressions: Optional dict of column -> expression for UPDATE clause.
                If None, all non-conflict columns are updated with their values.
                If empty dict {}, do nothing on conflict (ON CONFLICT DO NOTHING).
                Supports complex expressions like "messages_count = messages_count + 1"
                or ExcludedValue() to set to excluded value.

        Returns:
            True if successful.
        """
        if updateExpressions is None:
            updateExpressions = {col: ExcludedValue() for col in values.keys() if col not in conflictColumns}

        colsStr = ", ".join(values.keys())
        placeholders = ", ".join([f":{col}" for col in values.keys()])
        conflictStr = ", ".join(conflictColumns)

        # Handle empty updateExpressions - do nothing on conflict
        if not updateExpressions:
            query = f"""
                INSERT INTO {table} ({colsStr})
                VALUES ({placeholders})
                ON CONFLICT({conflictStr}) DO NOTHING
            """
        else:
            # Translate ExcludedValue to SQLite syntax
            translatedExpressions: Dict[str, str] = {}
            for col, expr in updateExpressions.items():
                if isinstance(expr, ExcludedValue):
                    columnName = expr.column if expr.column else col
                    translatedExpressions[col] = f"excluded.{columnName}"
                else:
                    translatedExpressions[col] = str(expr)

            updateStr = ", ".join([f"{col} = {expr}" for col, expr in translatedExpressions.items()])

            query = f"""
                INSERT INTO {table} ({colsStr})
                VALUES ({placeholders})
                ON CONFLICT({conflictStr}) DO UPDATE SET
                    {updateStr}
            """

        await self.execute(query, values)
        return True

    async def isVectorSearchSupported(self) -> bool:
        """Check if sqlite-vec extension is loaded and operational.

        Returns:
            ``True`` if ``sqlite-vec`` was successfully loaded during
            :meth:`connect`, ``False`` otherwise.
        """
        # We need to connect to try to load sqlite-vec lib
        if self._connection is None:
            await self.connect()
            if not self.keepConnection:
                await self.disconnect()

        return self._vectorSearchAvailable

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
        """Native KNN search using sqlite-vec vec0 virtual table.

        Constructs a MATCH query on the vec0 virtual table. The ``vec0``
        table has a fixed distance metric (set at creation time), so only
        that metric is supported.

        Args:
            table: vec0 virtual table name (e.g.
                ``"vec_message_embeddings_384"``).
            vectorColumn: Embedding column name (e.g. ``"embedding"``).
            returnColumns: Column names to return in ``rowKey``.
            queryVector: Query vector as float32 bytes.
            k: Number of nearest neighbours to return.
            filterClause: Optional SQL WHERE fragment with ``:named``
                params. Used for partition-key and metadata filters.
            filterParams: Named parameters for ``filterClause``.
            distanceMetric: Distance metric. Must match the metric
                declared in the vec0 table definition.

        Returns:
            List of :class:`VectorSearchResult` ordered by distance
            ascending (most similar first). May contain fewer than ``k``
            results if the table has fewer matching rows.

        Raises:
            ValueError: If ``distanceMetric`` is not supported by
                sqlite-vec's vec0 implementation (currently only cosine
                is supported).
            NotImplementedError: If vector search is not available
                (sqlite-vec not loaded).
        """
        # Auto-connect if needed — capability detection requires a live
        # connection because the sqlite-vec extension is loaded in connect().
        if not self._vectorSearchAvailable and _SQLITE_VEC_AVAILABLE:
            await self.connect()

        if not self._vectorSearchAvailable:
            raise NotImplementedError(f"{type(self).__name__} does not support native vector search")

        if distanceMetric != VectorDistanceMetric.COSINE:
            raise ValueError(
                f"SQLite3Provider vec0 table uses cosine distance. "
                f"Requested metric '{distanceMetric}' is not supported. "
                f"To use other metrics, create a vec0 table with the desired distance_metric."
            )

        returnCols = ", ".join(returnColumns)
        whereParts: list[str] = [f"{vectorColumn} MATCH :_queryVector", "AND k = :_k"]
        if filterClause:
            whereParts.append(f"AND {filterClause}")

        query = f"SELECT {returnCols}, distance " f"FROM {table} " f"WHERE {' '.join(whereParts)} " f"ORDER BY distance"

        params: dict[str, str | int | float | bytes | None] = dict(filterParams) if filterParams else {}
        params["_queryVector"] = queryVector
        params["_k"] = k

        rows = await self.executeFetchAll(query, params)
        results: list[VectorSearchResult] = []
        for row in rows:
            rowKey: dict[str, str] = {col: str(row[col]) for col in returnColumns}
            results.append(
                VectorSearchResult(
                    rowKey=rowKey,
                    distance=float(row["distance"]),
                )
            )
        return results

    async def listTables(self, likePattern: str = "%") -> list[str]:
        """List table names matching a LIKE pattern using SQLite's
        ``sqlite_master`` table.

        Args:
            likePattern: SQL LIKE pattern (e.g.
                ``"vec_message_embeddings_%"``). The default ``"%"``
                matches all tables.

        Returns:
            List of matching table names.
        """
        rows = await self.executeFetchAll(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE :pattern",
            {"pattern": likePattern},
        )
        return [row["name"] for row in rows]

    async def createVectorTable(
        self,
        tableName: str,
        columns: list[VectorColumnDef],
    ) -> None:
        """Create a vec0 virtual table.

        Maps :class:`VectorColumnDef` to vec0 DDL:

        - ``VECTOR`` → ``FLOAT[{dim}] distance_metric={metric}``
        - ``isPartitionKey`` → appends ``PARTITION KEY`` after the type
        - Other types → native type name (``TEXT``, ``INTEGER``, ``FLOAT``, ``BLOB``)

        Args:
            tableName: Name for the new vec0 virtual table
                (e.g. ``"vec_message_embeddings_384"``).
            columns: Ordered list of column definitions. At least one
                column must have ``columnType=VectorColumnType.VECTOR``.

        Returns:
            None.

        Raises:
            ValueError: If no ``VECTOR`` column is present.
        """
        if not any(col["columnType"] == VectorColumnType.VECTOR for col in columns):
            raise ValueError("At least one column with columnType=VECTOR is required")

        colDefs: list[str] = []
        for col in columns:
            parts: list[str] = [col["name"]]
            match col["columnType"]:
                case VectorColumnType.VECTOR:
                    dim = col.get("vectorDimension", 0)
                    if dim is None or dim <= 0:
                        raise ValueError(f"VECTOR column '{col['name']}' requires a positive vectorDimension")
                    metric = col.get("distanceMetric", VectorDistanceMetric.COSINE)
                    parts.append(f"FLOAT[{dim}] distance_metric={metric}")
                case VectorColumnType.TEXT:
                    parts.append("TEXT")
                case VectorColumnType.INTEGER:
                    parts.append("INTEGER")
                case VectorColumnType.BLOB:
                    parts.append("BLOB")
                case VectorColumnType.FLOAT:
                    parts.append("FLOAT")
            if col.get("isPartitionKey"):
                parts.append("PARTITION KEY")
            colDefs.append(" ".join(parts))

        query = (
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {tableName} USING vec0(\n"
            + ",\n".join(f"    {d}" for d in colDefs)
            + "\n)"
        )
        await self.execute(query)
