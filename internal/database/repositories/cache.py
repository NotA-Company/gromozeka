"""Cache repository for managing cache storage and cache entries.

This module provides the CacheRepository class which handles all cache-related
database operations including storing, retrieving, and clearing cache entries
from both the cache_storage and cache tables.

The repository supports two cache tables:
- cache_storage: General-purpose cache storage with namespace/key/value structure
- cache: Typed cache entries with TTL (time-to-live) support and automatic expiration

All methods support multi-source database routing, allowing operations to be
directed to specific data sources or automatically routed based on configuration.

Typical usage:
    repository = CacheRepository(databaseManager)
    await repository.setCacheStorage("weather", "Moscow", "sunny")
    entries = await repository.getCacheStorage()
"""

import datetime
import logging
from typing import List, Optional

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import CacheDict, CacheStorageDict, CacheType
from ..providers.base import ExcludedValue
from .base import BaseRepository

logger = logging.getLogger(__name__)


class CacheRepository(BaseRepository):
    """Repository for managing cache storage and cache entries in the database.

    Provides methods to interact with both the cache_storage table (for
    general cache storage) and the cache table (for typed cache entries with
    TTL support). All methods support multi-source database routing.

    Attributes:
        manager: Database manager instance for provider access (inherited from BaseRepository)

    The repository handles two types of cache:
    1. Cache Storage: Simple namespace/key/value storage without expiration
    2. Cache: Typed entries with TTL support and automatic expiration checking

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

    async def getCacheEntry(
        self,
        key: str,
        cacheType: CacheType,
        ttl: Optional[int] = None,
        *,
        dataSource: Optional[str] = None,
    ) -> Optional[CacheDict]:
        """Get cache entry by key and type.

        Retrieves a cache entry from the cache table, optionally filtering by TTL.
        Only returns entries that are not expired based on the TTL parameter.

        Args:
            key: Cache key to retrieve
            cacheType: Type of cache (namespace)
            ttl: Time-to-live in seconds. If provided, only returns entries
                 updated within this time window. If None or 0, returns all entries.
            dataSource: Optional data source name. If None in multi-source mode,
                       returns first match from any source.

        Returns:
            CacheDict containing key, data, created_at, and updated_at if found,
            None if not found or expired.

        Raises:
            Exception: Logs error and returns None if database operation fails

        Note:
            TTL of 0 or negative means entry must be from the future (impossible),
            so returns None immediately without querying the database.
        """
        # TTL of 0 or negative means entry must be from the future (impossible), so return None
        if ttl is not None and ttl <= 0:
            return None

        minimalUpdatedAt = (
            dbUtils.getCurrentTimestamp() - datetime.timedelta(seconds=ttl) if ttl is not None and ttl > 0 else None
        )

        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
            row = await sqlProvider.executeFetchOne(
                """
                SELECT key, data, created_at, updated_at
                FROM cache
                WHERE namespace = :namespace AND
                        key = :cacheKey AND
                        (:minimalUpdatedAt IS NULL OR updated_at >= :minimalUpdatedAt)
            """,
                {
                    "namespace": cacheType,
                    "cacheKey": key,
                    "minimalUpdatedAt": minimalUpdatedAt,
                },
            )

            return dbUtils.sqlToTypedDict(row, CacheDict) if row else None
        except Exception as e:
            logger.error(f"Failed to get cache entry: {e}")
            return None

    async def setCacheEntry(
        self, key: str, data: str, cacheType: CacheType, *, dataSource: Optional[str] = None
    ) -> bool:
        """Store cache entry.

        Creates or updates a cache entry in the cache table. Uses upsert semantics
        - if the entry exists, it will be updated; otherwise, a new entry is created.

        Args:
            key: Cache key to store
            data: Cache data to store
            cacheType: Type of cache (namespace)
            dataSource: Optional data source name for explicit routing. If None,
                       writes to the default writable source.

        Returns:
            True if successful, False otherwise

        Raises:
            Exception: Logs error and returns False if database operation fails

        Note:
            Writes to default source unless dataSource specified. Cannot write to readonly sources.
            Both created_at and updated_at timestamps are automatically set to the current time.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=False)
            now = dbUtils.getCurrentTimestamp()
            await sqlProvider.upsert(
                table="cache",
                values={
                    "namespace": cacheType,
                    "key": key,
                    "data": data,
                    "created_at": now,
                    "updated_at": now,
                },
                conflictColumns=["namespace", "key"],
                updateExpressions={
                    "data": ExcludedValue(),
                    "updated_at": ExcludedValue(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set cache entry: {e}")
            return False

    async def clearCache(self, cacheType: CacheType, *, dataSource: Optional[str] = None) -> None:
        """Clear all entries from a specific cache.

        Removes all cache entries of the specified type from the cache table.

        Args:
            cacheType: The type of cache to clear (e.g., WEATHER, GEOCODING, YANDEX_SEARCH)
            dataSource: Optional data source name for explicit routing. If None,
                       writes to the default writable source.

        Raises:
            Exception: Logs error if the cache clearing operation fails

        Note:
            Writes to default source unless dataSource specified. Cannot write to readonly sources.
            This operation cannot be undone.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=False)
            await sqlProvider.execute(
                """
                DELETE FROM cache
                WHERE
                    namespace = :cacheType
                """,
                {"cacheType": cacheType},
            )
        except Exception as e:
            logger.error(f"Failed to clear cache {cacheType}: {e}")

    async def clearOldCacheEntries(
        self,
        ttl: Optional[int],
        cacheType: Optional[CacheType] = None,
        *,
        dataSource: Optional[str] = None,
    ) -> bool:
        """Clear cache entries older than the specified age.

        Removes cache entries that were updated more than the specified number
        of seconds ago. Useful for cache cleanup and maintenance.

        Args:
            ttl: Remove entries older than this many seconds. If None or 0, removes all entries.
            cacheType: Optional cache type to filter by. If None, clears old entries from all caches.
            dataSource: Optional data source name for explicit routing. If None,
                       writes to the default writable source.

        Returns:
            True if successful, False otherwise

        Raises:
            Exception: Logs error and returns False if database operation fails

        Note:
            Writes to default source unless dataSource specified. Cannot write to readonly sources.
            The cutoff time is calculated as: current_time - ttl seconds.
        """
        # Calculate the cutoff timestamp
        if ttl is None:
            ttl = 0
        cutoffTime = dbUtils.getCurrentTimestamp() - datetime.timedelta(seconds=ttl)

        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=False)
            # Clear old entries of specific cache type
            await sqlProvider.execute(
                """
                DELETE FROM cache
                WHERE
                    (:cacheType IS NULL OR namespace = :cacheType) AND
                    updated_at < :cutoffTime
                """,
                {
                    "cacheType": cacheType,
                    "cutoffTime": cutoffTime,
                },
            )

            logger.info(f"Cleared old cache entries (older than {ttl}s, type={cacheType}).")
            return True
        except Exception as e:
            logger.error(f"Failed to clear old cache entries: {e}")
            return False
