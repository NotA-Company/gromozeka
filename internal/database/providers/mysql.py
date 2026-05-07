"""MySQL database provider implementation, dood!

Provides :class:`MySQLProvider`, a concrete :class:`BaseSQLProvider` that
wraps the ``aiomysql`` library with a fully async interface, dood!
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
    """SQL provider backed by a MySQL database server, dood!

    Uses :mod:`aiomysql` for a fully non-blocking async interface, dood!

    Attributes:
        host: MySQL server hostname or IP address, dood!
        port: MySQL server port number, dood!
        user: Username for authentication, dood!
        password: Password for authentication, dood!
        database: Name of the database to connect to, dood!
        readOnly: When ``True``, the connection is opened in query-only mode, dood!
        timeout: Seconds to wait for a query response before raising an error, dood!
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
        """Initialise the MySQL provider, dood!

        Args:
            host: MySQL server hostname or IP address, dood!
            port: MySQL server port number; defaults to ``3306``, dood!
            user: Username for authentication, dood!
            password: Password for authentication, dood!
            database: Database name to connect to, dood!
            readOnly: Open connection in query-only mode when ``True``, dood!
            timeout: Seconds to wait for a response; defaults to ``30``, dood!
            keepConnection: If ``True``, connect on creation and keep connection open, dood!
                If ``False``, do not connect on creation, dood!
                If ``None`` (default), treat as ``False``, dood!
        """
        super().__init__()
        self.host: str = host
        """MySQL server hostname or IP address, dood!"""
        self.port: int = port
        """MySQL server port number, dood!"""
        self.user: str = user
        """Username used for authentication, dood!"""
        self.password: str = password
        """Password used for authentication, dood!"""
        self.database: str = database
        """Name of the database to connect to, dood!"""
        self.readOnly: bool = readOnly
        """When ``True``, the connection is opened in query-only mode, dood!"""
        self.timeout: int = timeout
        """Seconds to wait for a query response before raising an error, dood!"""
        self.keepConnection: bool = keepConnection if keepConnection is not None else False
        """If ``True``, the connection is kept open across operations, dood!"""

        self._pool: Optional[aiomysql.Pool] = None
        self._connectLock: asyncio.Lock = asyncio.Lock()
        """Lock to prevent race conditions during connection creation, dood!"""

    async def connect(self) -> None:
        """Open the MySQL connection pool if not already open, dood!

        Returns:
            None, dood!

        Raises:
            Exception: If the connection pool cannot be created, dood!
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
        """Close the MySQL connection pool if it is open, dood!

        Returns:
            None, dood!
        """
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            logger.debug(f"Disconnected from MySQL database at {self.host}:{self.port}/{self.database}")

    async def isReadOnly(self) -> bool:
        """Return if this provider is in read only mode or not, dood!

        Returns:
            ``True`` if the provider is in read-only mode, ``False`` otherwise, dood!
        """
        return self.readOnly

    @asynccontextmanager
    async def cursor(self) -> AsyncGenerator[aiomysql.Cursor, None]:
        """Async context manager that yields a database cursor within a transaction, dood!

        Automatically commits on success or rolls back on any exception, dood!

        Yields:
            An open :class:`aiomysql.Cursor` ready for query execution, dood!

        Raises:
            Exception: Re-raises any exception that occurs during execution
                after rolling back the transaction, dood!
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
        """Convert a cursor's pending rows into the appropriate result type, dood!

        Args:
            cursor: An executed :class:`aiomysql.Cursor`, dood!
            fetchType: Controls how many rows are retrieved, dood!

        Returns:
            All rows, one row, or ``None`` depending on *fetchType*, dood!

        Raises:
            ValueError: If *fetchType* is not a recognised :class:`FetchType` member, dood!
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
        """Execute a single parametrized query against the MySQL database, dood!

        Args:
            query: The :class:`ParametrizedQuery` to run, dood!

        Returns:
            Query result according to the query's fetch type, dood!
        """
        async with self.cursor() as cursor:
            await cursor.execute(query.query, utils.convertContainerElementsToSQLite(query.params))
            return await self._makeQueryResult(cursor, query.fetchType)

    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """Execute multiple queries in a single database transaction, dood!

        All queries share one cursor and one commit/rollback cycle, so either
        all succeed or all are rolled back together, dood!

        Args:
            queries: Sequence of :class:`ParametrizedQuery` objects to execute, dood!

        Returns:
            A list of query results, one per input query, in the same order, dood!
        """
        ret: list[QueryResult] = []
        async with self.cursor() as cursor:
            for query in queries:
                await cursor.execute(query.query, utils.convertContainerElementsToSQLite(query.params))
                ret.append(await self._makeQueryResult(cursor, query.fetchType))

        return ret

    def applyPagination(self, query: str, limit: Optional[int], offset: int = 0) -> str:
        """Apply MySQL-specific pagination to query, dood!

        Args:
            query: The base SQL query, dood!
            limit: The maximum number of rows to return, dood! If None, no pagination is applied, dood!
            offset: The number of rows to skip, dood! Defaults to 0, dood!

        Returns:
            The query with pagination clause appended, dood!
        """
        if limit is None:
            return query
        offsetStr = ""
        if offset:
            offsetStr = f" OFFSET {offset}"
        return f"{query} LIMIT {limit}{offsetStr}"

    def getTextType(self, maxLength: Optional[int] = None) -> str:
        """Get MySQL-specific TEXT type, dood!

        Args:
            maxLength: Optional maximum length for the text field, dood! Used to determine
                TEXT, MEDIUMTEXT, or LONGTEXT, dood!

        Returns:
            The appropriate TEXT type for MySQL, dood!
        """
        if maxLength is None or maxLength <= 65535:
            return "TEXT"
        elif maxLength <= 16777215:
            return "MEDIUMTEXT"
        else:
            return "LONGTEXT"

    def getCaseInsensitiveComparison(self, column: str, param: str) -> str:
        """Get MySQL-specific case-insensitive comparison, dood!

        Args:
            column: The column name to compare, dood!
            param: The parameter name to use in the comparison, dood!

        Returns:
            A SQL expression string for case-insensitive comparison, dood!
        """
        return f"{column} COLLATE utf8mb4_general_ci = :{param}"

    def getLikeComparison(self, column: str, param: str) -> str:
        """Get MySQL-specific case-insensitive LIKE comparison, dood!

        Args:
            column: The column name to compare, dood!
            param: The parameter name to use in the comparison, dood!

        Returns:
            A SQL expression string for case-insensitive LIKE comparison, dood!
        """
        return f"{column} LIKE :{param} COLLATE utf8mb4_general_ci"

    async def upsert(
        self,
        table: str,
        values: Dict[str, Any],
        conflictColumns: List[str],
        updateExpressions: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Execute MySQL-specific upsert operation, dood!

        Args:
            table: Table name, dood!
            values: Dictionary of column names and values to insert, dood!
            conflictColumns: List of columns that define the conflict target (must be UNIQUE/PRIMARY key), dood!
            updateExpressions: Optional dict of column -> expression for UPDATE clause, dood!
                If None, all non-conflict columns are updated with their values, dood!
                If empty dict {}, do nothing on conflict (INSERT IGNORE), dood!
                Supports complex expressions like "messages_count = messages_count + 1"
                or ExcludedValue() to set to excluded value, dood!

        Returns:
            True if successful, dood!
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
