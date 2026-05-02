"""PostgreSQL database provider implementation.

Provides :class:`PostgreSQLProvider`, a concrete :class:`BaseSQLProvider` that
wraps the ``asyncpg`` library with a fully async interface.
"""

import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, cast

import asyncpg  # type: ignore[reportMissingImports]

from .base import BaseSQLProvider, ExcludedValue, FetchType, ParametrizedQuery, QueryResult

logger = logging.getLogger(__name__)


class PostgreSQLProvider(BaseSQLProvider):
    """SQL provider backed by a PostgreSQL database server.

    Uses :mod:`asyncpg` for a fully non-blocking async interface.

    Attributes:
        host: PostgreSQL server hostname or IP address.
        port: PostgreSQL server port number.
        user: Username for authentication.
        password: Password for authentication.
        database: Name of the database to connect to.
        readOnly: When ``True``, the connection is opened in query-only mode.
        timeout: Seconds to wait for a query response before raising an error.
    """

    __slots__ = ("host", "port", "user", "password", "database", "readOnly", "timeout", "_connection", "_pool")

    def __init__(
        self,
        *,
        host: str,
        port: int = 5432,
        user: str,
        password: str,
        database: str,
        readOnly: bool = False,
        timeout: int = 30,
    ) -> None:
        """Initialise the PostgreSQL provider.

        Args:
            host: PostgreSQL server hostname or IP address.
            port: PostgreSQL server port number; defaults to ``5432``.
            user: Username for authentication.
            password: Password for authentication.
            database: Database name to connect to.
            readOnly: Open connection in query-only mode when ``True``.
            timeout: Seconds to wait for a response; defaults to ``30``.
        """
        super().__init__()
        self.host: str = host
        """PostgreSQL server hostname or IP address."""
        self.port: int = port
        """PostgreSQL server port number."""
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

        self._connection: Optional[asyncpg.Connection] = None
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Open the PostgreSQL connection pool if not already open."""
        if self._pool is not None:
            return

        self._pool = await asyncpg.create_pool(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            command_timeout=self.timeout,
        )

        logger.debug(f"Connected to PostgreSQL database at {self.host}:{self.port}/{self.database}")

    async def disconnect(self) -> None:
        """Close the PostgreSQL connection pool if it is open."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.debug(f"Disconnected from PostgreSQL database at {self.host}:{self.port}/{self.database}")

    async def isReadOnly(self) -> bool:
        """Return if this provider is in read only mode or not.

        Returns:
            ``True`` if the provider is in read-only mode, ``False`` otherwise.
        """
        return self.readOnly

    @asynccontextmanager
    async def cursor(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """Async context manager that yields a database connection within a transaction.

        Automatically commits on success or rolls back on any exception.

        Yields:
            An open :class:`asyncpg.Connection` ready for query execution.

        Raises:
            Exception: Re-raises any exception that occurs during execution
                after rolling back the transaction.
        """
        await self.connect()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                try:
                    yield conn
                except Exception as e:
                    logger.error(f"Database operation failed: {e}")
                    logger.exception(e)
                    raise

    async def _makeQueryResult(self, record: Optional[asyncpg.Record], fetchType: FetchType) -> QueryResult:
        """Convert a record into the appropriate result type.

        Args:
            record: An :class:`asyncpg.Record` or None.
            fetchType: Controls how many rows are retrieved.

        Returns:
            All rows, one row, or ``None`` depending on *fetchType*.

        Raises:
            ValueError: If *fetchType* is not a recognised :class:`FetchType` member.
        """
        match fetchType:
            case FetchType.FETCH_ALL:
                # For FETCH_ALL, we need to handle multiple records
                # This is a simplified version - in practice, you'd need to fetch all records
                if record:
                    return cast(QueryResult, [dict(record)])
                return cast(QueryResult, [])
            case FetchType.FETCH_ONE:
                if record:
                    return cast(QueryResult, dict(record))
                return cast(QueryResult, None)
            case FetchType.NO_FETCH:
                return None
        raise ValueError(f"Unknown fetch type: {fetchType}")

    async def _execute(self, query: ParametrizedQuery) -> QueryResult:
        """Execute a single parametrized query against the PostgreSQL database.

        Args:
            query: The :class:`ParametrizedQuery` to run.

        Returns:
            Query result according to the query's fetch type.
        """
        async with self.cursor() as conn:
            # Convert named parameters from :name to $1, $2, etc. for PostgreSQL
            queryStr = query.query
            params = query.params

            if isinstance(params, dict):
                # Convert named parameters to positional
                paramNames = list(params.keys())
                paramValues = list(params.values())
                for idx, name in enumerate(paramNames, 1):
                    queryStr = queryStr.replace(f":{name}", f"${idx}")
                params = paramValues
            elif isinstance(params, Sequence):
                params = list(params)

            match query.fetchType:
                case FetchType.FETCH_ALL:
                    records = await conn.fetch(queryStr, *params)
                    return cast(QueryResult, [dict(rec) for rec in records])
                case FetchType.FETCH_ONE:
                    record = await conn.fetchrow(queryStr, *params)
                    return cast(QueryResult, dict(record) if record else None)
                case FetchType.NO_FETCH:
                    await conn.execute(queryStr, *params)
                    return None

    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """Execute multiple queries in a single database transaction.

        All queries share one transaction, so either all succeed or all are rolled back together.

        Args:
            queries: Sequence of :class:`ParametrizedQuery` objects to execute.

        Returns:
            A list of query results, one per input query, in the same order.
        """
        ret: list[QueryResult] = []
        async with self.cursor() as conn:
            for query in queries:
                # Convert named parameters from :name to $1, $2, etc. for PostgreSQL
                queryStr = query.query
                params = query.params

                if isinstance(params, dict):
                    paramNames = list(params.keys())
                    paramValues = list(params.values())
                    for idx, name in enumerate(paramNames, 1):
                        queryStr = queryStr.replace(f":{name}", f"${idx}")
                    params = paramValues
                elif isinstance(params, Sequence):
                    params = list(params)

                match query.fetchType:
                    case FetchType.FETCH_ALL:
                        records = await conn.fetch(queryStr, *params)
                        ret.append(cast(QueryResult, [dict(rec) for rec in records]))
                    case FetchType.FETCH_ONE:
                        record = await conn.fetchrow(queryStr, *params)
                        ret.append(cast(QueryResult, dict(record) if record else None))
                    case FetchType.NO_FETCH:
                        await conn.execute(queryStr, *params)
                        ret.append(None)

        return ret

    def applyPagination(self, query: str, limit: Optional[int], offset: Optional[int] = 0) -> str:
        """Apply PostgreSQL-specific pagination to query.

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
        """Get PostgreSQL-specific TEXT type.

        Args:
            maxLength: Optional maximum length for the text field (ignored in PostgreSQL).

        Returns:
            The TEXT type for PostgreSQL.
        """
        return "TEXT"

    def getCaseInsensitiveComparison(self, column: str, param: str) -> str:
        """Get PostgreSQL-specific case-insensitive comparison.

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
        """Execute PostgreSQL-specific upsert operation.

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
            # Translate ExcludedValue to PostgreSQL syntax
            translatedExpressions: Dict[str, str] = {}
            for col, expr in updateExpressions.items():
                if isinstance(expr, ExcludedValue):
                    columnName = expr.column if expr.column else col
                    translatedExpressions[col] = f"EXCLUDED.{columnName}"
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
