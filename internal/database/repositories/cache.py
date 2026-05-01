"""TODO: write docstring"""

import datetime
import logging
from typing import List, Optional

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import CacheDict, CacheStorageDict, CacheType
from .base import BaseRepository

logger = logging.getLogger(__name__)


class CacheRepository(BaseRepository):
    """TODO: write docstring"""

    __slots__ = ()

    def __init__(self, manager: DatabaseManager):
        super().__init__(manager)

    ###
    # Cache manipulation functions
    ###

    async def getCacheStorage(self, *, dataSource: Optional[str] = None) -> List[CacheStorageDict]:
        """Get all cache storage entries

        Args:
            dataSource: Optional data source identifier for multi-source database routing

        Returns:
            List of cache storage dictionaries"""
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

    async def setCacheStorage(self, namespace: str, key: str, value: str) -> bool:
        """
        Store cache entry in cache_storage table.

        Args:
            namespace: Cache namespace
            key: Cache key
            value: Cache value

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO cache_storage
                    (namespace, key, value, updated_at)
                VALUES
                    (:namespace, :key, :value, CURRENT_TIMESTAMP)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    value = :value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                {
                    "namespace": namespace,
                    "key": key,
                    "value": value,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set cache storage: {e}")
            return False

    async def unsetCacheStorage(self, namespace: str, key: str) -> bool:
        """
        Delete cache entry from cache_storage table.

        Args:
            namespace: Cache namespace
            key: Cache key

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
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
        """
        Get cache entry by key and type.

        Args:
            key: Cache key
            cacheType: Type of cache
            ttl: Time-to-live in seconds (optional)
            dataSource: Optional data source name. If None in multi-source mode,
                       returns first match from any source.

        Returns:
            CacheDict or None if not found
        """
        # TTL of 0 or negative means entry must be from the future (impossible), so return None
        if ttl is not None and ttl <= 0:
            return None

        # Use datetime.now(datetime.UTC) and remove timezone info to match SQLite's CURRENT_TIMESTAMP
        # which returns offset-naive datetime
        minimalUpdatedAt = (
            datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(seconds=ttl)
            if ttl is not None and ttl > 0
            else None
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
        """
        Store cache entry.

        Args:
            key: Cache key
            data: Cache data
            cacheType: Type of cache

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO cache
                    (namespace, key, data, created_at, updated_at)
                VALUES
                    (:namespace, :key, :data, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    data = :data,
                    updated_at = CURRENT_TIMESTAMP
            """,
                {
                    "namespace": cacheType,
                    "key": key,
                    "data": data,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set cache entry: {e}")
            return False

    async def clearCache(self, cacheType: CacheType, *, dataSource: Optional[str] = None) -> None:
        """
        Clear all entries from a specific cache.

        Args:
            cacheType: The type of cache to clear (WEATHER, GEOCODING, or YANDEX_SEARCH)

        Raises:
            Logs an error message if the cache clearing operation fails

        Note:
            Writes to default source. Cannot write to readonly sources.
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
        """
        Clear cache entries older than the specified age, dood!

        Args:
            olderThanSeconds: Remove entries older than this many seconds
            cacheType: Optional cache type to filter by. If None, clears old entries from all caches.
            dataSource: Optional data source name for explicit routing

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source unless dataSource specified. Cannot write to readonly sources.
        """
        # Calculate the cutoff timestamp
        if ttl is None:
            ttl = 0
        cutoffTime = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=ttl)

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
