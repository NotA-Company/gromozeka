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
from .base import BaseSQLProvider, ExcludedValue, FetchType, ParametrizedQuery, QueryResult

logger = logging.getLogger(__name__)


class SQLite3Provider(BaseSQLProvider):
    """SQL provider backed by a local SQLite3 database file.

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
    ) -> None:
        """Initialise the SQLite3 provider.

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
        """
        super().__init__()
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

    async def connect(self) -> None:
        """Open the aiosqlite connection if not already open.

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

            self._connection = connection
            logger.debug(
                f"Connected to SQLite3 database at {self.dbPath} with readOnly={self.readOnly} and useWal={self.useWal}"
            )

    async def disconnect(self) -> None:
        """Close the aiosqlite connection if it is open."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.debug(f"Disconnected from SQLite3 database at {self.dbPath}")

    async def isReadOnly(self) -> bool:
        """Return if this provider is in read only mode or not.

        Returns:
            ``True`` if the provider is in read-only mode, ``False`` otherwise.
        """

        return self.readOnly

    @asynccontextmanager
    async def cursor(self, *, keepConnection: Optional[bool] = None) -> AsyncGenerator[aiosqlite.Cursor, None]:
        """Async context manager that yields a database cursor within a transaction.

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
        """Convert a cursor's pending rows into the appropriate result type.

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
        """Execute a single parametrized query against the SQLite3 database.

        Args:
            query: The :class:`ParametrizedQuery` to run.

        Returns:
            Query result according to the query's fetch type.
        """
        async with self.cursor(keepConnection=self.keepConnection) as cursor:
            await cursor.execute(query.query, utils.convertContainerElementsToSQLite(query.params))
            return await self._makeQueryResult(cursor, query.fetchType)

    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """Execute multiple queries in a single database transaction.

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

    def applyPagination(self, query: str, limit: Optional[int], offset: Optional[int] = 0) -> str:
        """Apply SQLite-specific pagination to query.

        Args:
            query: The base SQL query.
            limit: The maximum number of rows to return. If None, no pagination is applied.
            offset: The number of rows to skip. Defaults to 0.

        Returns:
            The query with pagination clause appended.
        """
        if limit is None:
            return query
        return f"{query} LIMIT {limit} OFFSET {offset}"

    def getTextType(self, maxLength: Optional[int] = None) -> str:
        """Get SQLite-specific TEXT type.

        Args:
            maxLength: Optional maximum length for the text field (ignored in SQLite).

        Returns:
            The TEXT type for SQLite.
        """
        return "TEXT"

    def getCaseInsensitiveComparison(self, column: str, param: str) -> str:
        """Get SQLite-specific case-insensitive comparison.

        Args:
            column: The column name to compare.
            param: The parameter name to use in the comparison.

        Returns:
            A SQL expression string for case-insensitive comparison.
        """
        return f"LOWER({column}) = LOWER(:{param})"

    async def upsert(
        self,
        table: str,
        values: Dict[str, Any],
        conflictColumns: List[str],
        updateExpressions: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Execute SQLite-specific upsert operation.

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
