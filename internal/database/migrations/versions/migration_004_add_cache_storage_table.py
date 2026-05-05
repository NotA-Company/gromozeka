"""
Add cache_storage table for CacheService persistence.

This migration creates a cache_storage table to support persistent caching
with namespace-based key-value storage.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration004AddCacheStorageTable(BaseMigration):
    """Migration to add cache_storage table for CacheService persistence.

    This migration creates a cache_storage table to support persistent caching
    with namespace-based key-value storage. The table includes:
    - namespace: Cache namespace for organizing related cache entries
    - key: Cache key within the namespace
    - value: Cached value (stored as TEXT)
    - updated_at: Timestamp of last update

    A composite primary key on (namespace, key) ensures uniqueness within each
    namespace. An index on namespace is created for faster lookups by namespace.
    """

    version = 4
    description = "Add cache_storage table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create cache_storage table and supporting index for CacheService persistence.

        This method creates the cache_storage table with the following schema:
        - namespace (TEXT, NOT NULL): Cache namespace for organizing entries
        - key (TEXT, NOT NULL): Cache key within the namespace
        - value (TEXT, NOT NULL): Cached value
        - updated_at (TIMESTAMP, NOT NULL): Last update timestamp
        - PRIMARY KEY: Composite key on (namespace, key)

        Also creates an index on the namespace column for faster lookups.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS cache_storage (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (namespace, key)
            )
            """),
                # Create index for faster lookups by namespace
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS idx_cache_namespace
            ON cache_storage(namespace)
            """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop cache_storage table and its index to revert the migration.

        This method removes the cache_storage table and its associated index
        in reverse order of creation (index first, then table).

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_cache_namespace"),
                ParametrizedQuery("DROP TABLE IF EXISTS cache_storage"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module
    """
    return Migration004AddCacheStorageTable
