"""
Add cache_storage table for CacheService persistence.

This migration creates a cache_storage table to support persistent caching
with namespace-based key-value storage.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration004AddCacheStorageTable(BaseMigration):
    """Add cache_storage table for CacheService persistence."""

    version = 4
    description = "Add cache_storage table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create cache_storage table for CacheService persistence.

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
        """Drop cache_storage table and its index.

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
