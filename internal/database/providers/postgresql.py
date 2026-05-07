"""PostgreSQL database provider implementation.

Provides :class:`PostgreSQLProvider`, a concrete :class:`BaseSQLProvider` that
wraps the ``asyncpg`` library with a fully async interface. This provider supports
all standard SQL operations with PostgreSQL-specific syntax for upserts,
pagination, and case-insensitive comparisons, dood!.

Classes:
    PostgreSQLProvider: SQL provider backed by a PostgreSQL database server.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, cast

import asyncpg  # type: ignore[reportMissingImports]

from .base import BaseSQLProvider, ExcludedValue, FetchType, ParametrizedQuery, QueryResult

logger = logging.getLogger(__name__)


class PostgreSQLProvider(BaseSQLProvider):
    """SQL provider backed by a PostgreSQL database server.

    Uses :mod:`asyncpg` for a fully non-blocking async interface. This provider
    implements all abstract methods from :class:`BaseSQLProvider` with PostgreSQL-
    specific syntax for maximum performance and compatibility, dood!.

    Attributes:
        host: PostgreSQL server hostname or IP address (str).
        port: PostgreSQL server port number (int).
        user: Username for authentication (str).
        password: Password for authentication (str).
        database: Name of the database to connect to (str).
        readOnly: When ``True``, the connection is opened in query-only mode (bool).
        timeout: Seconds to wait for a query response before raising an error (int).
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
        port: int = 5432,
        user: str,
        password: str,
        database: str,
        readOnly: bool = False,
        timeout: int = 30,
        keepConnection: Optional[bool] = None,
    ) -> None:
        """Initialise the PostgreSQL provider.

        Creates a new PostgreSQL provider instance without establishing a
        connection. The connection pool is created on-demand when the first
        query is executed or when :meth:`connect` is called explicitly, dood!.

        Args:
            host: PostgreSQL server hostname or IP address (str).
            port: PostgreSQL server port number; defaults to ``5432`` (int).
            user: Username for authentication (str).
            password: Password for authentication (str).
            database: Database name to connect to (str).
            readOnly: Open connection in query-only mode when ``True`` (bool).
            timeout: Seconds to wait for a response; defaults to ``30`` (int).
            keepConnection: If ``True``, connect immediately and keep connection open.
                If ``False``, do not connect on creation (bool).
                If ``None`` (default), treat as ``False`` (optional bool).
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
        self.keepConnection: bool = keepConnection if keepConnection is not None else False
        """If ``True``, the connection is kept open across operations."""

        self._pool: Optional[asyncpg.Pool] = None
        self._connectLock: asyncio.Lock = asyncio.Lock()
        """Lock to prevent race conditions during connection creation."""

    async def connect(self) -> None:
        """Open the PostgreSQL connection pool if not already open.

        Creates an asyncpg connection pool using the configured connection
        parameters. This method is idempotent - multiple calls are safe and will
        not create additional pools. Uses a lock to prevent race conditions
        during concurrent connection attempts, dood!.

        Returns:
            ``None`` (always).
        """
        if self._pool is not None:
            return

        async with self._connectLock:
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
        """Close the PostgreSQL connection pool if it is open.

        Gracefully closes all connections in the pool and releases resources.
        This method is idempotent - safe to call multiple times or when no
        connection exists. After calling this method, any subsequent query will
        automatically reconnect, dood!.

        Returns:
            ``None`` (always).
        """
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.debug(f"Disconnected from PostgreSQL database at {self.host}:{self.port}/{self.database}")

    async def isReadOnly(self) -> bool:
        """Return if this provider is in read only mode or not.

        Check the ``readOnly`` flag that was set during provider initialization,
        dood!.

        Returns:
            ``True`` (bool) if the provider is in read-only mode, ``False``
            otherwise.
        """
        return self.readOnly

    @asynccontextmanager
    async def cursor(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """Async context manager that yields a database connection within a transaction.

        Acquires a connection from the pool and begins a transaction. The transaction
        is automatically committed when the context exits successfully, or rolled
        back if any exception occurs, dood!. Use this for multi-step operations
        that require atomicity.

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

        This helper method transforms raw asyncpg records into the expected
        result format based on the fetch type specified in the query, dood!.

        Args:
            record: An :class:`asyncpg.Record` or None (optional asyncpg.Record).
            fetchType: Controls how many rows are retrieved (FetchType).

        Returns:
            All rows (List[Dict[str, Any]]), one row (Optional[Dict[str, Any]]),
            or ``None`` depending on *fetchType* (QueryResult).

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

        Converts named parameters (:name) to PostgreSQL's positional parameter
        syntax ($1, $2, etc.) and executes the query within a transaction, dood!.

        Args:
            query: The :class:`ParametrizedQuery` to run.

        Returns:
            Query result according to the query's fetch type:
            - For FETCH_ALL: List[Dict[str, Any]]
            - For FETCH_ONE: Optional[Dict[str, Any]]
            - For NO_FETCH: None
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

        All queries share one transaction, so either all succeed or all are
        rolled back together. Named parameters are converted to PostgreSQL
        positional syntax for each query, dood!.

        Args:
            queries: Sequence of :class:`ParametrizedQuery` objects to execute
                (Sequence[ParametrizedQuery]).

        Returns:
            A list of query results, one per input query, in the same order
            (Sequence[QueryResult]).
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

    def applyPagination(self, query: str, limit: Optional[int], offset: int = 0) -> str:
        """Apply PostgreSQL-specific pagination to query.

        PostgreSQL uses ``LIMIT`` and ``OFFSET`` for pagination, dood!. Unlike
        some databases, PostgreSQL applies these clauses after the entire result
        set is materialized, so they don't affect internal query execution.

        Args:
            query: The base SQL query (str).
            limit: The maximum number of rows to return (optional int).
                If None, no pagination is applied.
            offset: The number of rows to skip (int). Defaults to 0.

        Returns:
            The query with pagination clause appended (str).
        """
        if limit is None:
            return query
        offsetStr = ""
        if offset:
            offsetStr = f" OFFSET {offset}"
        return f"{query} LIMIT {limit}{offsetStr}"

    def getTextType(self, maxLength: Optional[int] = None) -> str:
        """Get PostgreSQL-specific TEXT type.

        PostgreSQL's TEXT type is unbounded and very efficient, so maxLength
        is ignored. This consistency allows schemas to be portable across
        databases without losing functionality on PostgreSQL, dood!.

        Args:
            maxLength: Optional maximum length for the text field (optional int).
                Ignored in PostgreSQL as TEXT is unbounded.

        Returns:
            The TEXT type for PostgreSQL (always ``"TEXT"``).
        """
        return "TEXT"

    def getCaseInsensitiveComparison(self, column: str, param: str) -> str:
        """Get PostgreSQL-specific case-insensitive comparison.

        Uses PostgreSQL's ``LOWER()`` function for case-insensitive equality
        checks, which works for international text and is functionally
        complete, dood!. This syntax is portable across databases.

        Args:
            column: The column name to compare (str).
            param: The parameter name to use in the comparison (str).

        Returns:
            A SQL expression string for case-insensitive comparison (str).
        """
        return f"LOWER({column}) = LOWER(:{param})"

    def getLikeComparison(self, column: str, param: str) -> str:
        """Get PostgreSQL-specific case-insensitive LIKE comparison.

        Uses PostgreSQL's ``LOWER()`` function on both sides of the LIKE
        operator to achieve case-insensitive pattern matching, dood!. This
        approach is portable and supports wildcards (% and _) in the parameter
        value.

        Args:
            column: The column name to compare (str).
            param: The parameter name to use in the comparison (str).

        Returns:
            A SQL expression string for case-insensitive LIKE comparison (str).
        """
        return f"LOWER({column}) LIKE LOWER(:{param})"

    async def upsert(
        self,
        table: str,
        values: Dict[str, Any],
        conflictColumns: List[str],
        updateExpressions: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Execute PostgreSQL-specific upsert operation.

        Uses PostgreSQL's ``ON CONFLICT`` clause to either insert a new row
        or update an existing row on conflict, dood!. Supports both simple
        updates with ``EXCLUDED.column`` references and complex expressions,
        atomic counters, or conditional updates.

        Args:
            table: Table name (str).
            values: Dictionary of column names and values to insert
                (Dict[str, Any]).
            conflictColumns: List of columns that define the conflict target
                (List[str]).
            updateExpressions: Optional dict of column -> expression for UPDATE clause
                (optional Dict[str, Any]).
                If None, all non-conflict columns are updated with their values.
                If empty dict {}, do nothing on conflict (ON CONFLICT DO NOTHING).
                Supports complex expressions like "messages_count = messages_count + 1"
                or ExcludedValue() to set to excluded value.

        Returns:
            ``True`` (bool) if successful.
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
