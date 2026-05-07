"""MySQL database provider implementation.

Provides :class:`MySQLProvider`, a concrete :class:`BaseSQLProvider` that
wraps the ``aiomysql`` library with a fully async interface.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, cast

import aiomysql  # type: ignore[reportMissingImports]

from . import utils
from .base import BaseSQLProvider, ExcludedValue, FetchType, ParametrizedQuery, QueryResult

logger = logging.getLogger(__name__)


class MySQLProvider(BaseSQLProvider):
    """SQL provider backed by a MySQL database server.

    Uses :mod:`aiomysql` for a fully non-blocking async interface.

    Attributes:
        host: MySQL server hostname or IP address.
        port: MySQL server port number.
        user: Username for authentication.
        password: Password for authentication.
        database: Name of the database to connect to.
        readOnly: When ``True``, the connection is opened in query-only mode.
        timeout: Seconds to wait for a query response before raising an error.
        keepConnection: If ``True``, the connection is kept open across operations.
        _pool: The aiomysql connection pool, or ``None`` if not connected.
        _connectLock: Lock to prevent race conditions during connection creation.
    """

    __slots__ = (
        "host",
        "port",
        "user",
        "password",
        "database",
        "readOnly",
        "timeout",
        "keepConnection",
        "_connectLock",
        "_pool",
    )

    def __init__(
        self,
        *,
        host: str,
        port: int = 3306,
        user: str,
        password: str,
        database: str,
        readOnly: bool = False,
        timeout: int = 30,
        keepConnection: Optional[bool] = None,
    ) -> None:
        """Initialise the MySQL provider.

        Args:
            host: MySQL server hostname or IP address.
            port: MySQL server port number; defaults to ``3306``.
            user: Username for authentication.
            password: Password for authentication.
            database: Database name to connect to.
            readOnly: Open connection in query-only mode when ``True``.
            timeout: Seconds to wait for a response; defaults to ``30``.
            keepConnection: If ``True``, connect on creation and keep connection open.
                If ``False``, do not connect on creation.
                If ``None`` (default), treat as ``False``.
        """
        super().__init__()
        self.host: str = host
        """MySQL server hostname or IP address."""
        self.port: int = port
        """MySQL server port number."""
        self.user: str = user
        """Username used for authentication."""
        self.password: str = password
        """Password used for authentication."""
        self.database: str = database
        """Name of the database to connect to."""
        self.readOnly: bool = readOnly
        """When ``True``, the connection is opened in query-only mode."""
        self.timeout: int = timeout
        """Seconds to wait for a query response before raising an error."""
        self.keepConnection: bool = keepConnection if keepConnection is not None else False
        """If ``True``, the connection is kept open across operations."""

        self._pool: Optional[aiomysql.Pool] = None
        """The aiomysql connection pool, or ``None`` if not connected."""
        self._connectLock: asyncio.Lock = asyncio.Lock()
        """Lock to prevent race conditions during connection creation."""

    async def connect(self) -> None:
        """Open the MySQL connection pool if not already open.

        Creates a connection pool to the MySQL database using the configured
        credentials. If a pool already exists, this method returns immediately.

        Returns:
            None.

        Raises:
            Exception: If the connection pool cannot be created.
        """
        if self._pool is not None:
            return

        async with self._connectLock:
            if self._pool is not None:
                return

            self._pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.database,
                autocommit=False,
                connect_timeout=self.timeout,
            )

            logger.debug(f"Connected to MySQL database at {self.host}:{self.port}/{self.database}")

    async def disconnect(self) -> None:
        """Close the MySQL connection pool if it is open.

        Closes all connections in the pool and waits for them to be properly
        shutdown. If no pool exists, this method returns immediately.

        Returns:
            None.
        """
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            logger.debug(f"Disconnected from MySQL database at {self.host}:{self.port}/{self.database}")

    async def isReadOnly(self) -> bool:
        """Return if this provider is in read only mode or not.

        Returns:
            ``True`` if the provider is in read-only mode, ``False`` otherwise.
        """
        return self.readOnly

    @asynccontextmanager
    async def cursor(self) -> AsyncGenerator[aiomysql.Cursor, None]:
        """Async context manager that yields a database cursor within a transaction.

        Acquires a connection from the pool, creates a cursor, and yields it
        for query execution. Automatically commits the transaction on success
        or rolls back on any exception.

        Yields:
            An open :class:`aiomysql.Cursor` ready for query execution.

        Raises:
            Exception: Re-raises any exception that occurs during execution
                after rolling back the transaction.
        """
        await self.connect()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    yield cursor
                    await conn.commit()
                except Exception as e:
                    await conn.rollback()
                    logger.error(f"Database operation failed: {e}")
                    logger.exception(e)
                    raise

    async def _makeQueryResult(self, cursor: aiomysql.Cursor, fetchType: FetchType) -> QueryResult:
        """Convert a cursor's pending rows into the appropriate result type.

        Fetches rows from the cursor based on the fetch type and converts
        them into dictionaries or a single dictionary as appropriate.

        Args:
            cursor: An executed :class:`aiomysql.Cursor` with pending results.
            fetchType: Controls how many rows are retrieved from the cursor.

        Returns:
            All rows as a list of dicts, a single dict, or ``None`` depending
            on *fetchType*. Returns ``None`` for :const:`FetchType.NO_FETCH`,
            a single dict for :const:`FetchType.FETCH_ONE`, or a list of
            dicts for :const:`FetchType.FETCH_ALL`.

        Raises:
            ValueError: If *fetchType* is not a recognised :class:`FetchType` member.
        """
        match fetchType:
            case FetchType.FETCH_ALL:
                rows = await cursor.fetchall()
                # Convert tuples to dicts using cursor.description
                if rows and cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    return cast(QueryResult, [dict(zip(columns, row)) for row in rows])
                return cast(QueryResult, [])
            case FetchType.FETCH_ONE:
                row = await cursor.fetchone()
                if row and cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    return cast(QueryResult, dict(zip(columns, row)))
                return cast(QueryResult, None)
            case FetchType.NO_FETCH:
                return None
        raise ValueError(f"Unknown fetch type: {fetchType}")

    async def _execute(self, query: ParametrizedQuery) -> QueryResult:
        """Execute a single parametrized query against the MySQL database.

        Args:
            query: The :class:`ParametrizedQuery` containing the SQL statement
                and parameters to execute.

        Returns:
            Query result according to the query's fetch type:
            - ``None`` for :const:`FetchType.NO_FETCH`
            - A dict for :const:`FetchType.FETCH_ONE`
            - A list of dicts for :const:`FetchType.FETCH_ALL`
        """
        async with self.cursor() as cursor:
            await cursor.execute(query.query, utils.convertContainerElementsToSQLite(query.params))
            return await self._makeQueryResult(cursor, query.fetchType)

    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """Execute multiple queries in a single database transaction.

        All queries are executed within a single cursor and share one commit/rollback
        cycle, meaning either all succeed or all are rolled back together.

        Args:
            queries: Sequence of :class:`ParametrizedQuery` objects to execute in order.

        Returns:
            A sequence of query results, one per input query, in the same order as
            the input. Each result follows the same pattern as :meth:`_execute`:
            - ``None`` for :const:`FetchType.NO_FETCH`
            - A dict for :const:`FetchType.FETCH_ONE`
            - A list of dicts for :const:`FetchType.FETCH_ALL`
        """
        ret: list[QueryResult] = []
        async with self.cursor() as cursor:
            for query in queries:
                await cursor.execute(query.query, utils.convertContainerElementsToSQLite(query.params))
                ret.append(await self._makeQueryResult(cursor, query.fetchType))

        return ret

    def applyPagination(self, query: str, limit: Optional[int], offset: int = 0) -> str:
        """Apply MySQL-specific pagination to a query.

        Appends MySQL's ``LIMIT`` and ``OFFSET`` clauses to a query string.

        Args:
            query: The base SQL query to paginate.
            limit: The maximum number of rows to return. If ``None``, no pagination
                is applied and the query is returned unchanged.
            offset: The number of rows to skip before returning results. Defaults
                to ``0`` (no offset).

        Returns:
            The original query with MySQL ``LIMIT`` and ``OFFSET`` clauses appended.
            If *limit* is ``None``, the query is returned unchanged.
        """
        if limit is None:
            return query
        offsetStr = ""
        if offset:
            offsetStr = f" OFFSET {offset}"
        return f"{query} LIMIT {limit}{offsetStr}"

    def getTextType(self, maxLength: Optional[int] = None) -> str:
        """Get MySQL-specific TEXT type for a given maximum length.

        Returns the appropriate MySQL TEXT type based on the required capacity.
        MySQL provides TEXT (64KB), MEDIUMTEXT (16MB), and LONGTEXT (4GB) variants.

        Args:
            maxLength: Optional maximum length in bytes needed for the text field.
                - ``None`` or ≤ 65535: returns ``TEXT`` (64KB)
                - ≤ 16777215: returns ``MEDIUMTEXT`` (16MB)
                - > 16777215: returns ``LONGTEXT`` (4GB)

        Returns:
            The appropriate MySQL TEXT type as a string (``TEXT``, ``MEDIUMTEXT``,
            or ``LONGTEXT``).
        """
        if maxLength is None or maxLength <= 65535:
            return "TEXT"
        elif maxLength <= 16777215:
            return "MEDIUMTEXT"
        else:
            return "LONGTEXT"

    def getCaseInsensitiveComparison(self, column: str, param: str) -> str:
        """Get MySQL-specific case-insensitive comparison expression.

        Generates a SQL expression that performs a case-insensitive equality
        comparison using MySQL's ``COLLATE`` with the ``utf8mb4_general_ci``
        collation.

        Args:
            column: The column name to compare against.
            param: The parameter name to use in the comparison (with ``:`` prefix).

        Returns:
            A SQL expression string for case-insensitive comparison, formatted as
            ``"{column} COLLATE utf8mb4_general_ci = :{param}"``.
        """
        return f"{column} COLLATE utf8mb4_general_ci = :{param}"

    def getLikeComparison(self, column: str, param: str) -> str:
        """Get MySQL-specific case-insensitive LIKE comparison expression.

        Generates a SQL expression that performs a case-insensitive pattern
        match using the ``LIKE`` operator with the ``utf8mb4_general_ci``
        collation.

        Args:
            column: The column name to compare against.
            param: The parameter name to use in the comparison (with ``:`` prefix).

        Returns:
            A SQL expression string for case-insensitive LIKE comparison, formatted
            as ``"{column} LIKE :{param} COLLATE utf8mb4_general_ci"``.
        """
        return f"{column} LIKE :{param} COLLATE utf8mb4_general_ci"

    async def upsert(
        self,
        table: str,
        values: Dict[str, Any],
        conflictColumns: List[str],
        updateExpressions: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Execute MySQL-specific upsert operation using ``INSERT ... ON DUPLICATE KEY UPDATE``.

        Performs an insert-or-update operation that either inserts a new row or,
        if a row with the same key exists, updates specified columns. This method
        adapts the generic upsert interface to MySQL's syntax.

        Args:
            table: The name of the table to perform the upsert on.
            values: Dictionary of column names and values to insert.
            conflictColumns: List of columns that define the conflict target.
                These must form a UNIQUE or PRIMARY key constraint in the table.
            updateExpressions: Optional dict mapping column names to expressions
                for the ``UPDATE`` clause on conflict:
                - If ``None`` (default): all non-conflict columns are updated with
                  their new values using ``VALUES(column)`` syntax.
                - If empty dict ``{}``: equivalent to ``INSERT IGNORE`` - does
                  nothing on conflict (insert only, no update).
                - If populated: each ``column -> expression`` pair defines how to
                  update that column. Supports:
                  - Literal values
                  - Complex expressions like ``"messages_count = messages_count + 1"``
                  - :class:`ExcludedValue` to reference the value that would have
                    been inserted (translates to ``VALUES(column)`` in MySQL)

        Returns:
            ``True`` if the operation completes successfully. MySQL does not
            report whether a row was inserted or updated, so a boolean success
            indicator is always returned.

        Raises:
            DatabaseError: If the SQL execution fails due to invalid table name,
            missing columns, type mismatches, or constraint violations.
        """
        if updateExpressions is None:
            updateExpressions = {col: ExcludedValue() for col in values.keys() if col not in conflictColumns}

        colsStr = ", ".join(values.keys())
        placeholders = ", ".join([f":{col}" for col in values.keys()])

        # Handle empty updateExpressions - do nothing on conflict
        if not updateExpressions:
            query = f"""
                INSERT IGNORE INTO {table} ({colsStr})
                VALUES ({placeholders})
            """
        else:
            # Translate ExcludedValue to MySQL syntax
            translatedExpressions: Dict[str, str] = {}
            for col, expr in updateExpressions.items():
                if isinstance(expr, ExcludedValue):
                    columnName = expr.column if expr.column else col
                    translatedExpressions[col] = f"VALUES({columnName})"
                else:
                    translatedExpressions[col] = str(expr)

            updateStr = ", ".join([f"{col} = {expr}" for col, expr in translatedExpressions.items()])

            query = f"""
                INSERT INTO {table} ({colsStr})
                VALUES ({placeholders})
                ON DUPLICATE KEY UPDATE
                    {updateStr}
            """

        await self.execute(query, values)
        return True
