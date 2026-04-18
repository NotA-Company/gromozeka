"""TODO: Description"""

import logging
import sqlite3
from collections.abc import Sequence
from contextlib import asynccontextmanager

from .base import BaseSQLProvider, FetchType, ParametrizedQuery, QueryResult

logger = logging.getLogger(__name__)


class SQLite3Provider(BaseSQLProvider):
    """TODO: Description"""

    __slots__ = ("dbPath", "readOnly", "useWal", "timeout", "_connection")

    def __init__(self, dbPath: str, *, readOnly: bool = False, useWal: bool = False, timeout: int = 30):
        """TODO: Description"""
        super().__init__()
        """TODO: Description"""
        self.dbPath = dbPath
        """TODO: Description"""
        self.readOnly = readOnly
        """TODO: Description"""
        self.useWal = useWal
        """TODO: Description"""
        self.timeout = timeout

        self._connection = None
        pass

    async def connect(self):
        """TODO: Description"""
        if self._connection is not None:
            return

        connection = sqlite3.connect(
            self.dbPath,  # Should we add ?ro=true or something like that?
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

    async def disconnect(self):
        """TODO: Description"""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            logger.debug(f"Disconnected from SQLite3 database at {self.dbPath}")

    @asynccontextmanager
    async def cursor(self):  # TODO: Add return type typehint
        """TODO: Description"""
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
        """TODO: Description"""
        match fetchType:
            case FetchType.FETCH_ALL:
                return cursor.fetchall()
            case FetchType.FETCH_ONE:
                return cursor.fetchone()
            case FetchType.NO_FETCH:
                return None
        raise ValueError(f"Unknown fetch type: {fetchType}")

    async def _execute(self, query: ParametrizedQuery) -> QueryResult:
        """TODO: Description"""
        async with self.cursor() as cursor:
            cursor.execute(query.query, query.params)
            return self._makeQueryResult(cursor, query.fetchType)

    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """TODO: Description"""
        ret: Sequence[QueryResult] = []
        async with self.cursor() as cursor:
            for query in queries:
                cursor.execute(query.query, query.params)
                ret.append(self._makeQueryResult(cursor, query.fetchType))

        return ret
