"""TODO: Description"""

import logging
from collections.abc import Sequence
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class FetchType(Enum):
    """TODO: Description"""

    """TODO: Description"""
    NO_FETCH = 1
    """TODO: Description"""
    FETCH_ONE = 2
    """TODO: Description"""
    FETCH_ALL = 3


type QueryParams = Dict[str, Any] | Sequence[Any]
type QueryResult = Dict[str, Any] | Sequence[Dict[str, Any]] | None


class ParametrizedQuery:
    """TODO: Description"""

    __slots__ = ("query", "params", "fetchType")

    def __init__(self, query: str, params: Optional[QueryParams] = None, fetchType: FetchType = FetchType.FETCH_ALL):
        """TODO: Description"""
        self.query = query

        if params is None:
            params = []
        """TODO: Description"""
        self.params: QueryParams = params
        """TODO: Description"""
        self.fetchType = fetchType


class BaseSQLProvider:
    """TODO: Description"""

    __slots__ = ()

    def __init__(self):
        pass

    def __repr__(self) -> str:
        params = []
        for attr in self.__slots__:
            if attr[0] == "_":
                continue
            params.append(f"{attr}={getattr(self, attr)}")

        return type(self).__name__ + "(" + ", ".join(params) + ")"

    async def connect(self):
        """TODO: Description"""
        raise NotImplementedError

    async def disconnect(self):
        """TODO: Description"""
        raise NotImplementedError

    async def __aenter__(self):
        """TODO: Description"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """TODO: Description"""
        await self.disconnect()
        if exc_type is not None:
            logger.error(exc_type, exc, tb)
            raise exc_type(exc) from exc

    async def _execute(self, query: ParametrizedQuery) -> QueryResult:
        """TODO: Description"""
        raise NotImplementedError

    async def execute(
        self,
        query: str | ParametrizedQuery,
        params: Optional[QueryParams] = None,
        fetchType: FetchType = FetchType.FETCH_ALL,
    ) -> QueryResult:
        """TODO: Description"""
        if not isinstance(query, ParametrizedQuery):
            query = ParametrizedQuery(query, params, fetchType)
        return await self._execute(query)

    async def batchExecute(self, queries: Sequence[ParametrizedQuery]) -> Sequence[QueryResult]:
        """TODO: Description"""
        raise NotImplementedError
