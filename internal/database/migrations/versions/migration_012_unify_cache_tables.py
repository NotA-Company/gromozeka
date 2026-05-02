"""
Unify cache tables migration - consolidates all cache tables into one.

This migration replaces the 6 separate cache_{type} tables with a single
unified_cache table that uses a namespace column to distinguish cache types.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration012UnifyCacheTables(BaseMigration):
    """Unify all cache tables into a single unified_cache table."""

    version = 12
    description = "Unify cache tables into single unified_cache table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create unified_cache table and drop old cache tables.

        Args:
            sqlProvider: SQL provider for executing queries

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
        """Revert to separate cache tables.

        Args:
            sqlProvider: SQL provider for executing queries

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

    Returns:
        Type[BaseMigration]: The migration class for this module
    """
    return Migration012UnifyCacheTables
