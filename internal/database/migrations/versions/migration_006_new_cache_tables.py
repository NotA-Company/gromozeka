"""
Add new cache tables for all cache types.

This migration creates cache tables for all defined cache types to support
persistent caching across different services.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration006NewCacheTables(BaseMigration):
    """Add new cache tables for all cache types."""

    version = 6
    description = "Add New Cache Tables"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create cache tables for all cache types.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        # Create all Cache Tables
        # Import CacheType here to avoid circular dependency
        from ...models import CacheType

        await sqlProvider.batchExecute([ParametrizedQuery(f"""
                CREATE TABLE IF NOT EXISTS cache_{cacheType} (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """) for cacheType in CacheType])

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback is not supported for this migration.

        This migration creates cache tables that should not be dropped
        as they may contain important cached data.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        pass


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module
    """
    return Migration006NewCacheTables
