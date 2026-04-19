"""
Initial schema migration - creates all base tables, dood!

This migration extracts all table creation from the original _initDatabase() method.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration006NewCacheTables(BaseMigration):
    """Initial database schema migration, dood!"""

    version = 6
    description = "Add New Cache Tables"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create all initial tables, dood!

        Args:
            sqlProvider: SQL provider for executing queries
        """
        # Create all Cache Tables
        # Import CacheType here to avoid circular dependency
        from ...models import CacheType

        await sqlProvider.batchExecute([ParametrizedQuery(f"""
                CREATE TABLE IF NOT EXISTS cache_{cacheType} (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """) for cacheType in CacheType])

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Do not want to

        Args:
            sqlProvider: SQL provider for executing queries
        """
        pass


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration006NewCacheTables
