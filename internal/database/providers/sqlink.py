"""SQLink database provider implementation.

Provides :class:`SQLinkProvider`, a concrete :class:`BaseSQLProvider` that
wraps the ``sqlink`` async client library to execute SQL queries against a
remote database server.
"""

from contextlib import asynccontextmanager
import logging
from collections.abc import AsyncGenerator, Sequence
from typing import Any, Dict, Optional

import sqlink

from .base import BaseSQLProvider, FetchType, ParametrizedQuery, QueryResult

logger = logging.getLogger(__name__)


class SQLinkProvider(BaseSQLProvider):
    """SQL provider backed by the ``sqlink`` async client library.

    Attributes:
        url: Base URL of the SQLink database server.
        user: Username used for authentication.
        password: Password used for authentication.
        database: Name of the database to connect to.
        timeout: Seconds to wait for a query response before raising an error.
    """

    __slots__ = ("_connection", "url", "user", "password", "database", "timeout")

    def __init__(
        self,
        *,
        url: str,
        user: str,
        password: str,
        database: str,
        timeout: int = 30,
    ) -> None:
        """Initialise the SQLink provider.

        Args:
            url: Base URL of the SQLink database server.
            user: Username for authentication.
            password: Password for authentication.
            database: Database name to connect to.
            timeout: Seconds to wait for a response; defaults to ``30``.
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

        self._connection: Optional[sqlink.AsyncConnection] = None

    async def connect(self) -> None:
        """Open the SQLink connection if not already open.

        Uses ``autoRefresh=True`` so the connection token is refreshed
        automatically when it expires.
        """
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
        """Close the SQLink connection if it is open."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.debug(f"Disconnected from SQLink database {self.url}/{self.database}")

    def _makeQueryResult(self, queryResult: sqlink.QueryResult, fetchType: FetchType) -> QueryResult:
        """Convert a ``sqlink.QueryResult`` into the provider's :obj:`QueryResult` type.

        Iterates over ``queryResult.rows`` and maps each row's values to a
        dict keyed by ``queryResult.columns``.

        Args:
            queryResult: Raw result returned by the sqlink client.
            fetchType: Controls how many rows to include in the return value.

        Returns:
            ``None`` when *fetchType* is :attr:`FetchType.NO_FETCH`, a single
            row dict when :attr:`FetchType.FETCH_ONE`, or a list of row dicts
            when :attr:`FetchType.FETCH_ALL`.
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
        """Open connection if needed, yield it, close if we opened it, dood!"""
        needDisconnect = self._connection is None
        await self.connect()
        assert self._connection is not None
        try:
            yield self._connection
        finally:
            if needDisconnect:
                await self.disconnect()

    async def _execute(self, query: ParametrizedQuery) -> QueryResult:
        """Execute a single parametrized query against the SQLink database.

        Opens the connection if necessary, executes the query, and closes
        the connection afterwards if it was not already open before the call.

        Args:
            query: The :class:`ParametrizedQuery` to run.

        Returns:
            Query result according to the query's fetch type.
        """
        async with self._autoConnection() as connection:
            ret = await connection.execute(query.query, query.params)
            return self._makeQueryResult(ret, query.fetchType)

    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """Execute multiple queries in a single batch request via ``executeBatch``.

        Opens the connection if necessary and closes it again afterwards when
        it was not open before the call.

        Args:
            queries: Sequence of :class:`ParametrizedQuery` objects to execute.

        Returns:
            A list of query results, one per input query, in the same order.
        """
        async with self._autoConnection() as connection:
            ret = await connection.executeBatch([(query.query, query.params) for query in queries])
            return [self._makeQueryResult(queryResult, query.fetchType) for queryResult, query in zip(ret, queries)]
