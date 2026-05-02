"""
Add Yandex Search cache tables.

This migration creates cache tables for Yandex Search results to improve
performance by storing search results locally.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration005YandexSearchCache(BaseMigration):
    """Add Yandex Search cache tables."""

    version = 5
    description = "Add Yandex Search Cache"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create Yandex Search cache tables.

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
        """Drop Yandex Search cache tables.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        # Drop cache tables
        from ...models import CacheType

        await sqlProvider.batchExecute(
            [ParametrizedQuery(f"DROP TABLE IF EXISTS cache_{cacheType}") for cacheType in [CacheType.YANDEX_SEARCH]]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module
    """
    return Migration005YandexSearchCache
