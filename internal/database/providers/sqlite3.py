"""SQLite3 database provider implementation.

Provides :class:`SQLite3Provider`, a concrete :class:`BaseSQLProvider` that
wraps the standard-library :mod:`sqlite3` module with an async-compatible
interface.
"""

import logging
import sqlite3
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Optional

from .base import BaseSQLProvider, FetchType, ParametrizedQuery, QueryResult

logger = logging.getLogger(__name__)


class SQLite3Provider(BaseSQLProvider):
    """SQL provider backed by a local SQLite3 database file.

    Attributes:
        dbPath: Filesystem path to the SQLite3 database file.
        readOnly: When ``True``, the connection is opened in query-only mode.
        useWal: When ``True``, WAL journal mode is enabled on the connection.
        timeout: Seconds to wait for the database lock before raising an error.
    """

    __slots__ = ("dbPath", "readOnly", "useWal", "timeout", "_connection")

    def __init__(self, dbPath: str, *, readOnly: bool = False, useWal: bool = False, timeout: int = 30) -> None:
        """Initialise the SQLite3 provider.

        Args:
            dbPath: Filesystem path to the SQLite3 database file.
            readOnly: Open connection in query-only mode when ``True``.
            useWal: Enable WAL journal mode when ``True``.
            timeout: Seconds to wait for the database lock; defaults to ``30``.
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

        self._connection: Optional[sqlite3.Connection] = None

    async def connect(self) -> None:
        """Open the SQLite3 connection if not already open.

        Applies ``PRAGMA query_only`` when :attr:`readOnly` is set, and
        ``PRAGMA journal_mode = WAL`` when :attr:`useWal` is set.
        """
        if self._connection is not None:
            return

        connection = sqlite3.connect(
            self.dbPath,
            timeout=self.timeout,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )

        connection.row_factory = sqlite3.Row
        if self.readOnly:
            connection.execute("PRAGMA query_only = ON")
        if self.useWal:
            connection.execute("PRAGMA journal_mode = WAL")

        self._connection = connection
        logger.debug(
            f"Connected to SQLite3 database at {self.dbPath} with readOnly={self.readOnly} and useWal={self.useWal}"
        )

    async def disconnect(self) -> None:
        """Close the SQLite3 connection if it is open."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            logger.debug(f"Disconnected from SQLite3 database at {self.dbPath}")

    @asynccontextmanager
    async def cursor(self) -> AsyncGenerator[sqlite3.Cursor, None]:
        """Async context manager that yields a database cursor within a transaction.

        Automatically commits on success or rolls back on any exception.
        Opens the connection if it is not already open, and closes it again
        afterwards when it was not open before entering.

        Yields:
            An open :class:`sqlite3.Cursor` ready for query execution.

        Raises:
            Exception: Re-raises any exception that occurs during execution
                after rolling back the transaction.
        """
        needDisconnect = self._connection is None
        await self.connect()

        assert self._connection is not None

        cursor = self._connection.cursor()
        try:
            yield cursor
            self._connection.commit()
        except Exception as e:
            self._connection.rollback()
            logger.error(f"Database operation failed: {e}")
            logger.exception(e)
            raise
        finally:
            cursor.close()
            if needDisconnect:
                await self.disconnect()

    def _makeQueryResult(self, cursor: sqlite3.Cursor, fetchType: FetchType) -> QueryResult:
        """Convert a cursor's pending rows into the appropriate result type.

        Args:
            cursor: An executed :class:`sqlite3.Cursor`.
            fetchType: Controls how many rows are retrieved.

        Returns:
            All rows, one row, or ``None`` depending on *fetchType*.

        Raises:
            ValueError: If *fetchType* is not a recognised :class:`FetchType` member.
        """
        match fetchType:
            case FetchType.FETCH_ALL:
                return cursor.fetchall()
            case FetchType.FETCH_ONE:
                return cursor.fetchone()
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
        async with self.cursor() as cursor:
            cursor.execute(query.query, query.params)
            return self._makeQueryResult(cursor, query.fetchType)

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
        async with self.cursor() as cursor:
            for query in queries:
                cursor.execute(query.query, query.params)
                ret.append(self._makeQueryResult(cursor, query.fetchType))

        return ret
