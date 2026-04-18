"""TODO: Description"""

import logging
from collections.abc import Sequence
from typing import Optional

import sqlink

from .base import BaseSQLProvider, FetchType, ParametrizedQuery, QueryResult

logger = logging.getLogger(__name__)


class SQLinkProvider(BaseSQLProvider):
    """TODO: Description"""

    __slots__ = ("_connection", "url", "user", "password", "database", "timeout")

    def __init__(
        self,
        *,
        url: str,
        user: str,
        password: str,
        database: str,
        timeout: int = 30,
    ):
        """TODO: Description"""

        super().__init__()
        """TODO: Description"""
        self.url = url
        """TODO: Description"""
        self.user = user
        """TODO: Description"""
        self.password = password
        """TODO: Description"""
        self.database = database
        """TODO: Description"""
        self.timeout = timeout

        self._connection: Optional[sqlink.AsyncConnection] = None
        pass

    async def connect(self):
        """TODO: Description"""
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

    async def disconnect(self):
        """TODO: Description"""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.debug(f"Disconnected from SQLink database {self.url}/{self.database}")

    def _makeQueryResult(self, queryResult: sqlink.QueryResult, fetchType: FetchType) -> QueryResult:
        """TODO: Description"""
        if fetchType == FetchType.NO_FETCH:
            return None

        ret: QueryResult = []
        for row in queryResult.rows:
            rowRet: QueryResult = {}

            for idx, field in enumerate(queryResult.columns):
                rowRet[field] = row[idx]

            if fetchType == FetchType.FETCH_ONE:
                return rowRet
            ret.append(rowRet)

        return ret

    async def _execute(self, query: ParametrizedQuery) -> QueryResult:
        """TODO: Description"""
        needDisconnect = self._connection is None
        await self.connect()
        assert self._connection is not None

        ret = await self._connection.execute(query.query, query.params)

        if needDisconnect:
            await self.disconnect()
        return self._makeQueryResult(ret, query.fetchType)

    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """TODO: Description"""
        needDisconnect = self._connection is None
        await self.connect()
        assert self._connection is not None
        ret = await self._connection.executeBatch([(query.query, query.params) for query in queries])

        if needDisconnect:
            await self.disconnect()

        return [self._makeQueryResult(queryResult, query.fetchType) for queryResult, query in zip(ret, queries)]
