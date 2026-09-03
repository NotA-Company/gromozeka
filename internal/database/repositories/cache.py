"""Cache repository for managing cache storage entries.

This module provides the CacheRepository class which handles all cache storage
database operations including storing, retrieving, and clearing cache entries
from the cache_storage table. This repository provides the persistence backing
for CacheService.

All methods support multi-source database routing, allowing operations to be
directed to specific data sources or automatically routed based on configuration.

Typical usage:
    repository = CacheRepository(databaseManager)
    await repository.setCacheStorage("weather", "Moscow", "sunny")
    entries = await repository.getCacheStorage()
"""

import logging
from typing import List, Optional

from lib.db import utils as dbUtils
from lib.db.manager import DatabaseManager
from lib.db.providers.base import ExcludedValue

from ..models import CacheStorageDict
from .base import BaseRepository

logger = logging.getLogger(__name__)


class CacheRepository(BaseRepository):
    """Repository for managing cache storage entries in the database.

    Provides methods to interact with the cache_storage table for simple
    namespace/key/value storage. All methods support multi-source database
    routing. This repository provides the persistence backing for CacheService.

    Attributes:
        manager: Database manager instance for provider access (inherited from BaseRepository)

    The repository handles cache storage with namespace/key/value structure:
    - Namespace: Grouping key for related cache entries
    - Key: Identifier within a namespace
    - Value: String data to store

    All write operations require a writable data source and will fail if
    routed to a readonly source.
    """

    __slots__ = ()

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the cache repository.

        Args:
            manager: Database manager instance for provider access

        Raises:
            TypeError: If manager is not a DatabaseManager instance
        """
        super().__init__(manager)

    ###
    # Cache manipulation functions
    ###

    async def getCacheStorage(self, *, dataSource: Optional[str] = None) -> List[CacheStorageDict]:
        """Get all cache storage entries.

        Retrieves all entries from the cache_storage table, ordered by update time
        in descending order (most recently updated first).

        Args:
            dataSource: Optional data source identifier for multi-source database routing.
                       If None, uses the default readonly source.

        Returns:
            List of cache storage dictionaries containing namespace, key, value,
            and updated_at fields. Returns empty list on error.

        Raises:
            Exception: Logs error and returns empty list if database operation fails
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll("""
                SELECT namespace, key, value, updated_at
                FROM cache_storage
                ORDER BY updated_at DESC
                """)
            return [dbUtils.sqlToTypedDict(row, CacheStorageDict) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get cache storage: {e}")
            return []

    async def setCacheStorage(self, namespace: str, key: str, value: str, *, dataSource: Optional[str] = None) -> bool:
        """Store cache entry in cache_storage table.

        Creates or updates a cache entry in the cache_storage table. Uses upsert
        semantics - if the entry exists, it will be updated; otherwise, a new entry
        is created.

        Args:
            namespace: Cache namespace for grouping related entries
            key: Cache key within the namespace
            value: Cache value to store
            dataSource: Optional data source name for explicit routing. If None,
                       writes to the default writable source.

        Returns:
            True if successful, False otherwise

        Raises:
            Exception: Logs error and returns False if database operation fails

        Note:
            Writes to default source unless dataSource specified. Cannot write to readonly sources.
            The updated_at timestamp is automatically set to the current time.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=False)
            await sqlProvider.upsert(
                table="cache_storage",
                values={
                    "namespace": namespace,
                    "key": key,
                    "value": value,
                    "updated_at": dbUtils.getCurrentTimestamp(),
                },
                conflictColumns=["namespace", "key"],
                updateExpressions={
                    "value": ExcludedValue(),
                    "updated_at": ExcludedValue(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set cache storage: {e}")
            return False

    async def unsetCacheStorage(self, namespace: str, key: str) -> bool:
        """Delete cache entry from cache_storage table.

        Removes a specific cache entry identified by namespace and key from the
        cache_storage table.

        Args:
            namespace: Cache namespace of the entry to delete
            key: Cache key of the entry to delete

        Returns:
            True if successful, False otherwise

        Raises:
            Exception: Logs error and returns False if database operation fails

        Note:
            Writes to default source. Cannot write to readonly sources.
            If the entry doesn't exist, the operation still succeeds.
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=False)
            await sqlProvider.execute(
                """
                DELETE FROM cache_storage
                WHERE
                    namespace = :namespace AND
                    key = :key
                """,
                {
                    "namespace": namespace,
                    "key": key,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to unset cache storage: {e}")
            return False
