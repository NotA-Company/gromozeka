"""Database providers package.

Exports base abstractions and concrete SQL provider implementations,
along with a factory function for creating providers from configuration.
"""

from typing import TypedDict

from .base import BaseSQLProvider, FetchType, ParametrizedQuery, QueryResult
from .sqlink import SQLinkProvider
from .sqlite3 import SQLite3Provider


class SQLProviderConfig(TypedDict):
    """Configuration dictionary for a SQL provider.

    Attributes:
        provider: Provider name identifier (e.g. ``"sqlite3"`` or ``"sqlink"``).
        parameters: Keyword arguments forwarded to the provider constructor.
    """

    provider: str
    """Provider name identifier (e.g. ``"sqlite3"`` or ``"sqlink"``)."""
    parameters: dict
    """Keyword arguments forwarded to the provider constructor."""


def getSqlProvider(config: SQLProviderConfig) -> BaseSQLProvider:
    """Instantiate a SQL provider from a configuration dictionary.

    Args:
        config: A :class:`SQLProviderConfig` dict containing ``provider`` and
            ``parameters`` keys.

    Returns:
        A concrete :class:`BaseSQLProvider` instance matching the requested
        provider name.

    Raises:
        ValueError: If the ``provider`` value is not recognised.
    """
    provider = config.get("provider")
    parameters = config.get("parameters", {})

    if not provider:
        raise ValueError("SQLProviderConfig is missing the required 'provider' key, dood!")
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
