"""Database provider abstraction and manager for Gromozeka.

Provides a generic, bot-free SQL provider abstraction layer and database
manager routing for multi-database configurations. The package is independent
of any bot-specific code and can be used by any application requiring
cross-RDBMS SQL portability.

Key components:
    - BaseSQLProvider: Abstract base class for SQL database providers
    - SQLite3Provider, SQLinkProvider: Concrete implementations
    - DatabaseManager: Multi-source provider routing and lifecycle management
    - getSqlProvider: Factory function for instantiating providers from config

The package abstracts differences between SQL database implementations,
providing a consistent interface for queries, transactions, and connection
management across SQLite3, SQLink, and future providers.

Example:
    >>> from lib.db import DatabaseManager, DatabaseManagerConfig
    >>> config: DatabaseManagerConfig = {
    ...     "default": "sqlite3",
    ...     "chatMapping": {},
    ...     "providers": {
    ...         "sqlite3": {"provider": "sqlite3", "parameters": {"database": ":memory:"}}
    ...     }
    ... }
    >>> manager = DatabaseManager(config)
    >>> provider = await manager.getProvider()
    >>> result = provider.execute("SELECT 1")
"""

from .manager import DatabaseManager, DatabaseManagerConfig, SQLProviderInitializationHook
from .providers import (
    BaseSQLProvider,
    ExcludedValue,
    FetchType,
    ParametrizedQuery,
    QueryResult,
    QueryResultFetchAll,
    QueryResultFetchOne,
    SQLinkProvider,
    SQLite3Provider,
    SQLProviderConfig,
    VectorColumnDef,
    VectorColumnType,
    VectorDistanceMetric,
    VectorSearchResult,
    getSqlProvider,
)
from .utils import FORCE_SQL_TIMEZONE, sqlToCustomType, sqlToTypedDict

__all__ = [
    "BaseSQLProvider",
    "DatabaseManager",
    "DatabaseManagerConfig",
    "ExcludedValue",
    "FetchType",
    "FORCE_SQL_TIMEZONE",
    "ParametrizedQuery",
    "QueryResult",
    "QueryResultFetchAll",
    "QueryResultFetchOne",
    "SQLinkProvider",
    "SQLProviderConfig",
    "SQLProviderInitializationHook",
    "SQLite3Provider",
    "VectorColumnDef",
    "VectorColumnType",
    "VectorDistanceMetric",
    "VectorSearchResult",
    "getSqlProvider",
    "sqlToCustomType",
    "sqlToTypedDict",
]
