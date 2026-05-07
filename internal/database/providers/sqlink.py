"""SQLink database provider implementation, dood!

Provides :class:`SQLinkProvider`, a concrete :class:`BaseSQLProvider` that
wraps the ``sqlink`` async client library to execute SQL queries against a
remote database server, dood!
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import sqlink

from . import utils
from .base import BaseSQLProvider, ExcludedValue, FetchType, ParametrizedQuery, QueryResult

logger = logging.getLogger(__name__)


class SQLinkProvider(BaseSQLProvider):
    """SQL provider backed by the ``sqlink`` async client library, dood!

    Wraps the SQLink async client to provide a concrete implementation of
    :class:`BaseSQLProvider` for remote database operations, dood!

    Attributes:
        url: Base URL of the SQLink database server.
        user: Username used for authentication.
        password: Password used for authentication.
        database: Name of the database to connect to.
        timeout: Seconds to wait for a query response before raising an error.
    """

    __slots__ = ("_connection", "url", "user", "password", "database", "timeout", "keepConnection", "_connectLock")

    def __init__(
        self,
        *,
        url: str,
        user: str,
        password: str,
        database: str,
        timeout: int = 30,
        keepConnection: Optional[bool] = None,
    ) -> None:
        """Initialise the SQLink provider, dood!

        Args:
            url: Base URL of the SQLink database server, dood.
            user: Username for authentication, dood.
            password: Password for authentication, dood.
            database: Database name to connect to, dood.
            timeout: Seconds to wait for a response; defaults to ``30``, dood.
            keepConnection: If ``True``, connect on creation and keep connection open, dood.
                If ``False``, do not connect on creation, dood.
                If ``None`` (default), treat as ``False``, dood.

        Returns:
            None.
        """
        super().__init__()
        self.url: str = url
        """Base URL of the SQLink database server."""
        self.user: str = user
        """Username used for authentication."""
        self.password: str = password
        """Password used for authentication."""
        self.database: str = database
        """Name of the database to connect to."""
        self.timeout: int = timeout
        """Seconds to wait for a query response before raising an error."""
        self.keepConnection: bool = keepConnection if keepConnection is not None else False
        """If ``True``, the connection is kept open across operations."""

        self._connection: Optional[sqlink.AsyncConnection] = None
        """Active SQLink connection, or ``None`` if not connected."""
        self._connectLock: asyncio.Lock = asyncio.Lock()
        """Lock to prevent race conditions during connection creation."""

    async def connect(self) -> None:
        """Open the SQLink connection if not already open, dood!

        Uses ``autoRefresh=True`` so the connection token is refreshed
        automatically when it expires, dood!

        Uses a lock to prevent race conditions when multiple coroutines
        try to connect simultaneously, dood!

        Returns:
            None.
        """
        # Fast path: if already connected, return immediately
        if self._connection is not None:
            return

        # Use lock to prevent race conditions during connection creation
        async with self._connectLock:
            # Double-check after acquiring lock
            if self._connection is not None:
                return

            self._connection = await sqlink.asyncConnect(
                self.url,
                username=self.user,
                password=self.password,
                database=self.database,
                timeout=self.timeout,
                autoRefresh=True,
            )

            logger.debug(f"Connected to SQLink database {self.url}/{self.database}")

    async def disconnect(self) -> None:
        """Close the SQLink connection if it is open, dood!

        Returns:
            None.
        """
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.debug(f"Disconnected from SQLink database {self.url}/{self.database}")

    async def isReadOnly(self) -> bool:
        """Check if the database is in read-only mode, dood!

        Returns:
            ``True`` if the database access mode is read-only, ``False`` otherwise, dood.
        """
        async with self._autoConnection() as connection:
            databases = await connection.databases()
            for db in databases:
                if db.name == self.database:
                    return db.access == "ro"

            logger.warning(f"Database {self.database} not found in SQLink databases: {databases}")
            return True

    def _makeQueryResult(self, queryResult: sqlink.QueryResult, fetchType: FetchType) -> QueryResult:
        """Convert a ``sqlink.QueryResult`` into the provider's :obj:`QueryResult` type, dood!

        Iterates over ``queryResult.rows`` and maps each row's values to a
        dict keyed by ``queryResult.columns``, dood!

        Args:
            queryResult: Raw result returned by the sqlink client, dood.
            fetchType: Controls how many rows to include in the return value, dood.

        Returns:
            ``None`` when *fetchType* is :attr:`FetchType.NO_FETCH`, a single
            row dict when :attr:`FetchType.FETCH_ONE`, or a list of row dicts
            when :attr:`FetchType.FETCH_ALL`, dood.
        """
        if fetchType == FetchType.NO_FETCH:
            return None

        ret: list[Dict[str, Any]] = []
        for row in queryResult.rows:
            rowRet: Dict[str, Any] = {}

            for idx, field in enumerate(queryResult.columns):
                rowRet[field] = row[idx]

            if fetchType == FetchType.FETCH_ONE:
                return rowRet

            ret.append(rowRet)

        if fetchType == FetchType.FETCH_ONE:
            # Actually only none can be returned here
            return ret[0] if ret else None

        return ret

    @asynccontextmanager
    async def _autoConnection(self) -> AsyncGenerator[sqlink.AsyncConnection, None]:
        """Context manager that provides a SQLink connection, dood!

        Opens a connection if one is not already active, yields it for use,
        and closes the connection after the context exits if it was opened
        by this context manager and ``keepConnection`` is ``False``, dood!

        Yields:
            An active ``sqlink.AsyncConnection`` instance, dood.
        """
        # Track whether we opened the connection ourselves
        # This prevents race conditions in concurrent operations
        wasConnected = self._connection is not None
        await self.connect()
        assert self._connection is not None
        try:
            yield self._connection
        finally:
            # Only disconnect if we opened the connection ourselves AND keepConnection is False
            if not wasConnected and not self.keepConnection:
                await self.disconnect()

    async def _execute(self, query: ParametrizedQuery) -> QueryResult:
        """Execute a single parametrized query against the SQLink database, dood!

        Opens the connection if necessary, executes the query, and closes
        the connection afterwards if it was not already open before the call, dood!

        Args:
            query: The :class:`ParametrizedQuery` to run, dood.

        Returns:
            Query result according to the query's fetch type, dood.
        """
        async with self._autoConnection() as connection:
            ret = await connection.execute(query.query, utils.convertContainerElementsToSQLite(query.params))
            return self._makeQueryResult(ret, query.fetchType)

    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """Execute multiple queries in a single batch request via ``executeBatch``, dood!

        Opens the connection if necessary and closes it again afterwards when
        it was not open before the call, dood!

        Args:
            queries: Sequence of :class:`ParametrizedQuery` objects to execute, dood.

        Returns:
            A list of query results, one per input query, in the same order, dood.
        """
        async with self._autoConnection() as connection:
            ret = await connection.executeBatch(
                [(query.query, utils.convertContainerElementsToSQLite(query.params)) for query in queries]
            )
            return [self._makeQueryResult(queryResult, query.fetchType) for queryResult, query in zip(ret, queries)]

    def applyPagination(self, query: str, limit: Optional[int], offset: int = 0) -> str:
        """Apply SQLite-specific pagination to query, dood!

        Args:
            query: The base SQL query, dood.
            limit: The maximum number of rows to return. If None, no pagination is applied, dood.
            offset: The number of rows to skip. Defaults to 0, dood.

        Returns:
            The query with pagination clause appended, dood.
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
            maxLength: Optional maximum length for the text field (ignored in SQLite), dood.

        Returns:
            The TEXT type for SQLite (maxLength is ignored), dood.
        """
        return "TEXT"

    def getCaseInsensitiveComparison(self, column: str, param: str) -> str:
        """Get SQLite-specific case-insensitive comparison, dood!

        Args:
            column: The column name to compare, dood.
            param: The parameter name to use in the comparison, dood.

        Returns:
            A SQL expression string for case-insensitive comparison using LOWER(), dood.
        """
        return f"LOWER({column}) = LOWER(:{param})"

    def getLikeComparison(self, column: str, param: str) -> str:
        """Get SQLite-specific case-insensitive LIKE comparison, dood!

        Args:
            column: The column name to compare, dood.
            param: The parameter name to use in the comparison, dood.

        Returns:
            A SQL expression string for case-insensitive LIKE comparison using LOWER(), dood.
        """
        return f"LOWER({column}) LIKE LOWER(:{param})"

    async def upsert(
        self,
        table: str,
        values: Dict[str, Any],
        conflictColumns: List[str],
        updateExpressions: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Execute SQLite-specific upsert operation via SQLink, dood!

        Args:
            table: Table name, dood.
            values: Dictionary of column names and values to insert, dood.
            conflictColumns: List of columns that define the conflict target, dood.
            updateExpressions: Optional dict of column -> expression for UPDATE clause, dood.
                If None, all non-conflict columns are updated with their values, dood.
                If empty dict {}, do nothing on conflict (ON CONFLICT DO NOTHING), dood.
                Supports complex expressions like "messages_count = messages_count + 1"
                or ExcludedValue() to set to excluded value, dood.

        Returns:
            True if successful, dood.
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
