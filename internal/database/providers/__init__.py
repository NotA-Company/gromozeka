"""TODO: Add description"""

from typing import TypedDict

from .base import BaseSQLProvider, FetchType, ParametrizedQuery, QueryResult
from .sqlink import SQLinkProvider
from .sqlite3 import SQLite3Provider


class SQLProviderConfig(TypedDict):
    """TODO: Add description"""

    provider: str
    """TODO: Add description"""
    parameters: dict
    """TODO: Add description"""


def getSqlProvider(config: SQLProviderConfig) -> BaseSQLProvider:
    """TODO: Add description"""
    provider = config.get("provider")
    parameters = config.get("parameters", {})
    match provider:
        case "sqlite3":
            return SQLite3Provider(**parameters)
        case "sqlink":
            return SQLinkProvider(**parameters)
        case _:
            raise ValueError(f"Unknown provider: {provider}")


__all__ = [
    "BaseSQLProvider",
    "FetchType",
    "ParametrizedQuery",
    "QueryResult",
    "SQLite3Provider",
    "SQLinkProvider",
    "getSqlProvider",
    "SQLProviderConfig",
]
