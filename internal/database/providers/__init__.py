"""Database providers package.

This package provides the database provider abstraction layer for the Gromozeka
database system. It defines the base interfaces and concrete implementations for
different SQL database backends, enabling a unified API for database operations
across multiple database technologies.

The providers package is part of Stage 2: Database Layer and serves as the
foundation for all database interactions in the system. It abstracts away the
differences between various SQL database implementations (SQLite3, SQLink, etc.)
and provides a consistent interface for executing queries, managing transactions,
and handling database connections.

Key Components:
    - BaseSQLProvider: Abstract base class defining the provider interface
    - SQLite3Provider: Concrete implementation using Python's sqlite3 module
    - SQLinkProvider: Concrete implementation using the SQLink library
    - getSqlProvider: Factory function for instantiating providers from config
    - SQLProviderConfig: TypedDict for provider configuration

The provider architecture supports:
    - Parameterized queries to prevent SQL injection
    - Multiple fetch types (one, many, all, cursor)
    - Transaction management
    - Connection pooling and lifecycle management
    - Type-safe query results

Usage Example:
    >>> from internal.database.providers import getSqlProvider, SQLProviderConfig
    >>> config: SQLProviderConfig = {
    ...     "provider": "sqlite3",
    ...     "parameters": {"database": ":memory:"}
    ... }
    >>> provider = getSqlProvider(config)
    >>> result = provider.execute("SELECT * FROM users WHERE id = ?", (1,))
"""

from typing import TypedDict

from .base import (
    BaseSQLProvider,
    ExcludedValue,
    FetchType,
    ParametrizedQuery,
    QueryResult,
    QueryResultFetchAll,
    QueryResultFetchOne,
)
from .sqlink import SQLinkProvider
from .sqlite3 import SQLite3Provider


class SQLProviderConfig(TypedDict):
    """Configuration dictionary for a SQL provider.

    This TypedDict defines the structure for configuring SQL database providers.
    It is used by the :func:`getSqlProvider` factory function to instantiate
    the appropriate provider implementation with the correct parameters.

    The configuration supports multiple provider types, each with their own
    specific parameter requirements. Common parameters include database path,
    connection settings, and provider-specific options.

    Attributes:
        provider: Provider name identifier. Must be one of the supported
            provider names: ``"sqlite3"`` or ``"sqlink"``. The provider name
            determines which concrete implementation will be instantiated.
        parameters: Keyword arguments forwarded to the provider constructor.
            The contents vary by provider type. For SQLite3, this typically
            includes ``database`` (path to database file). For SQLink, this
            includes connection-specific parameters.

    Example:
        >>> config: SQLProviderConfig = {
        ...     "provider": "sqlite3",
        ...     "parameters": {"database": "/path/to/database.db"}
        ... }
    """

    provider: str
    """Provider name identifier (e.g. ``"sqlite3"`` or ``"sqlink"``)."""
    parameters: dict
    """Keyword arguments forwarded to the provider constructor."""


def getSqlProvider(config: SQLProviderConfig) -> BaseSQLProvider:
    """Instantiate a SQL provider from a configuration dictionary.

    This factory function creates and returns a concrete SQL provider instance
    based on the configuration provided. It abstracts the provider instantiation
    logic, allowing the application to work with different database backends
    through a unified interface.

    The function validates the configuration and instantiates the appropriate
    provider class (SQLite3Provider or SQLinkProvider) with the specified
    parameters. This enables runtime selection of database backends without
    modifying application code.

    Args:
        config: A :class:`SQLProviderConfig` dictionary containing the provider
            configuration. Must include a ``provider`` key with a valid provider
            name and an optional ``parameters`` key with provider-specific
            configuration options.

    Returns:
        A concrete :class:`BaseSQLProvider` instance matching the requested
        provider name. The returned instance is ready to use for database
        operations.

    Raises:
        ValueError: If the ``provider`` key is missing from the configuration
            or if the provider name is not recognized. Recognized provider names
            are ``"sqlite3"`` and ``"sqlink"``.

    Example:
        >>> config: SQLProviderConfig = {
        ...     "provider": "sqlite3",
        ...     "parameters": {"database": ":memory:"}
        ... }
        >>> provider = getSqlProvider(config)
        >>> result = provider.execute("SELECT 1")
    """
    provider = config.get("provider")
    parameters = config.get("parameters", {})

    if not provider:
        raise ValueError("SQLProviderConfig is missing the required 'provider' key")
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
    "ExcludedValue",
    "QueryResultFetchAll",
    "QueryResultFetchOne",
]
