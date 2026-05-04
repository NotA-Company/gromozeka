"""Migration 012: Unify cache tables into a single unified table.

This migration consolidates multiple cache tables (cache_{type}) into a single
unified cache table with a namespace column to distinguish between different
cache types. This simplifies the database schema and makes cache management
more efficient.

The migration performs the following changes:
- Creates a new unified `cache` table with namespace support
- Adds indexes for efficient querying by namespace/key and TTL cleanup
- Drops the old separate cache_{type} tables

The unified cache table structure:
- namespace: TEXT NOT NULL - identifies the cache type (e.g., 'llm', 'geocode')
- key: TEXT NOT NULL - the cache key within the namespace
- data: TEXT NOT NULL - the cached data (serialized)
- created_at: TIMESTAMP NOT NULL - when the cache entry was created
- updated_at: TIMESTAMP NOT NULL - when the cache entry was last updated
- PRIMARY KEY: (namespace, key) - ensures uniqueness per namespace/key pair
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration012UnifyCacheTables(BaseMigration):
    """Migration to unify all cache tables into a single unified_cache table.

    This migration replaces the 6 separate cache_{type} tables with a single
    unified cache table that uses a namespace column to distinguish cache types.
    This simplifies the database schema and improves cache management efficiency.

    Attributes:
        version: The migration version number (12).
        description: A brief description of what this migration does.
    """

    version = 12
    description = "Unify cache tables into single unified_cache table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration: create unified cache table and drop old tables.

        This method creates a new unified cache table with namespace support,
        adds appropriate indexes for efficient querying, and drops the old
        separate cache_{type} tables.

        Args:
            sqlProvider: The SQL provider instance for executing database queries.

        Returns:
            None
        """
        from ...models import CacheType

        await sqlProvider.batchExecute(
            [
                # Create generic cache table with namespace support
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS cache (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (namespace, key)
            )
            """),
                # Add index on namespace column for efficient filtering
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS idx_cache_namespace_key
            ON cache (namespace, key)
            """),
                # Add index on updated_at column for TTL cleanup
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS idx_cache_updated_at
            ON cache (updated_at)
            """),
                # Drop old cache tables
                *[ParametrizedQuery(f"DROP TABLE IF EXISTS cache_{cacheType}") for cacheType in CacheType],
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration: recreate separate cache tables and drop unified table.

        This method recreates the old separate cache_{type} tables and drops
        the unified cache table, reverting the database to its previous state.

        Args:
            sqlProvider: The SQL provider instance for executing database queries.

        Returns:
            None
        """
        from ...models import CacheType

        await sqlProvider.batchExecute(
            [
                # Recreate old cache tables
                *[ParametrizedQuery(f"""
                CREATE TABLE IF NOT EXISTS cache_{cacheType} (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """) for cacheType in CacheType],
                # Drop unified cache table
                ParametrizedQuery("DROP TABLE IF EXISTS cache"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    This function is used by the migration system to discover and load
    the migration class defined in this module.

    Returns:
        Type[BaseMigration]: The migration class (Migration012UnifyCacheTables).
    """
    return Migration012UnifyCacheTables
