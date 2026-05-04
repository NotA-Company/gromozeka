"""Database migration for adding Yandex Search cache tables.

This migration creates cache tables for storing Yandex Search API results
to improve performance by caching search responses locally. The migration
creates tables for all cache types defined in the CacheType enum, including
YANDEX_SEARCH, WEATHER, GEOCODING, URL_CONTENT, and others.

Each cache table follows a consistent schema with:
- key: Primary key for cache lookup
- data: JSON-serialized cached data
- created_at: Timestamp when the cache entry was created
- updated_at: Timestamp when the cache entry was last updated
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration005YandexSearchCache(BaseMigration):
    """Migration to add Yandex Search cache tables.

    This migration creates cache tables for all cache types defined in the
    CacheType enum. Each table stores cached data with a consistent schema
    to support efficient caching of API responses and computed results.

    Attributes:
        version: Migration version number (5).
        description: Human-readable description of the migration.
    """

    version = 5
    description = "Add Yandex Search Cache"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create cache tables for all cache types.

        Creates a separate cache table for each value in the CacheType enum.
        Each table has a consistent schema with key, data, created_at, and
        updated_at columns. The tables are created with IF NOT EXISTS to
        allow for idempotent migration execution.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        # Create all Cache Tables
        # Import CacheType here to avoid circular dependency
        from ...models import CacheType

        cacheQueries: list[ParametrizedQuery] = [ParametrizedQuery(f"""
                CREATE TABLE IF NOT EXISTS cache_{cacheType} (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """) for cacheType in CacheType]
        await sqlProvider.batchExecute(cacheQueries)

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop the Yandex Search cache table.

        Removes the cache table for YANDEX_SEARCH cache type. Note that this
        only drops the YANDEX_SEARCH table, not all cache tables created by
        the up() method, as other cache types may have been added by later
        migrations.

        Args:
            sqlProvider: SQL provider for executing database queries.

        Returns:
            None
        """
        # Drop cache tables
        from ...models import CacheType

        dropQueries: list[ParametrizedQuery] = [
            ParametrizedQuery(f"DROP TABLE IF EXISTS cache_{cacheType}") for cacheType in [CacheType.YANDEX_SEARCH]
        ]
        await sqlProvider.batchExecute(dropQueries)


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    This function is used by the migration system to dynamically load and
    instantiate the migration class.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration005YandexSearchCache
