"""Migration 006: Add new cache tables for all cache types.

This migration creates cache tables for all defined cache types to support
persistent caching across different services. Each cache type gets its own
table with a standardized schema for storing cached data with timestamps.

The tables created follow the naming convention: cache_{cache_type}
where {cache_type} is the name of each CacheType enum value.

Schema for each cache table:
    - key: TEXT PRIMARY KEY - unique identifier for the cached item
    - data: TEXT NOT NULL - serialized cached data
    - created_at: TIMESTAMP NOT NULL - when the cache entry was created
    - updated_at: TIMESTAMP NOT NULL - when the cache entry was last updated
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration006NewCacheTables(BaseMigration):
    """Migration to add new cache tables for all cache types.

    This migration creates separate cache tables for each defined cache type
    in the CacheType enum. Each table follows a standardized schema with
    key, data, created_at, and updated_at columns.

    Attributes:
        version: The migration version number (6).
        description: Human-readable description of the migration.
    """

    version: int = 6
    description: str = "Add New Cache Tables"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create cache tables for all cache types.

        Creates a separate table for each cache type defined in the CacheType enum.
        Each table is named cache_{cache_type} and contains columns for key, data,
        created_at, and updated_at timestamps. The tables are created with
        IF NOT EXISTS to allow for idempotent execution.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        # Create all Cache Tables
        # Import CacheType here to avoid circular dependency
        from ...models import CacheType

        cacheTables: list[ParametrizedQuery] = [ParametrizedQuery(f"""
                CREATE TABLE IF NOT EXISTS cache_{cacheType} (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """) for cacheType in CacheType]
        await sqlProvider.batchExecute(cacheTables)

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback is not supported for this migration.

        This migration creates cache tables that should not be dropped
        as they may contain important cached data. Dropping these tables
        would result in loss of cached data and potential performance
        degradation. The method does nothing to preserve existing data.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        pass


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    This function is used by the migration system to discover and load
    the migration class defined in this module.

    Returns:
        Type[BaseMigration]: The Migration006NewCacheTables class.
    """
    return Migration006NewCacheTables
