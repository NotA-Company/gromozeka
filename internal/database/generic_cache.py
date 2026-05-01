"""
Generic database cache implementation.

Provides a database-backed cache implementation that uses the Database
to store and retrieve cached data. Supports different cache namespaces
and configurable key/value conversion strategies.
"""

import logging
from typing import Any, Dict, Optional

from lib.cache import CacheInterface, HashKeyGenerator, JsonValueConverter, K, KeyGenerator, V, ValueConverter

from .database import Database
from .models import CacheType

logger = logging.getLogger(__name__)


class GenericDatabaseCache(CacheInterface[K, V]):
    """
    Database-backed cache implementation.

    Stores data in the database using the Database. Supports different cache
    namespaces for organizing data and uses configurable key generators and
    value converters for flexible data handling.

    Type Parameters:
        K: The key type (any hashable type)
        V: The value type (any type)

    Attributes:
        db: Database instance for database operations
        dataSource: Optional data source identifier for multi-source configurations
        namespace: CacheType enum value for organizing cache data
        keyGenerator: KeyGenerator instance for converting keys to strings
        valueConverter: ValueConverter instance for serializing/deserializing values

    Example:
        >>> from internal.database import Database
        >>> from internal.database.models import CacheType
        >>> from lib.cache import StringKeyGenerator
        >>>
        >>> db = Database(...)
        >>> cache = GenericDatabaseCache[str, dict](
        ...     db=db,
        ...     namespace=CacheType.WEATHER,
        ...     keyGenerator=StringKeyGenerator()
        ... )
        >>> await cache.set("moscow", {"temp": 20, "humidity": 50})
        >>> weather = await cache.get("moscow")
    """

    __slots__ = ("db", "dataSource", "namespace", "keyGenerator", "valueConverter")

    def __init__(
        self,
        db: Database,
        namespace: CacheType,
        keyGenerator: Optional[KeyGenerator[K]] = None,
        valueConverter: Optional[ValueConverter[V]] = None,
        *,
        dataSource: Optional[str] = None,
    ):
        """
        Initialize cache with database wrapper.

        Args:
            db: Database instance from internal.database.database
            namespace: CacheType enum value for organizing cache data
            keyGenerator: Optional KeyGenerator instance for converting keys to strings.
                         If None, uses HashKeyGenerator by default.
            valueConverter: Optional ValueConverter instance for serializing/deserializing values.
                           If None, uses JsonValueConverter by default.
            dataSource: Optional data source identifier for multi-source configurations.
        """
        self.db = db
        self.dataSource = dataSource
        self.namespace = namespace
        self.keyGenerator: KeyGenerator[K] = keyGenerator if keyGenerator is not None else HashKeyGenerator()
        self.valueConverter: ValueConverter[V] = (
            valueConverter if valueConverter is not None else JsonValueConverter[V]()
        )

    async def get(self, key: K, ttl: Optional[int] = None) -> Optional[V]:
        """
        Get cached data if exists and not expired.

        Args:
            key: Cache key to retrieve
            ttl: Optional time-to-live in seconds. If provided, only returns entries
                 that are not older than this value.

        Returns:
            Optional[V]: Cached value if found and not expired, None otherwise.
        """
        try:
            _key = self.keyGenerator.generateKey(key)
            cacheEntry = await self.db.cache.getCacheEntry(
                _key, cacheType=self.namespace, ttl=ttl, dataSource=self.dataSource
            )
            if cacheEntry is not None:
                return self.valueConverter.decode(cacheEntry["data"])
            return None
        except Exception as e:
            logger.error(f"Failed to get cache entry {key}: {e}")
            return None

    async def set(self, key: K, value: V) -> bool:
        """
        Store data in cache.

        Args:
            key: Cache key to store
            value: Value to cache

        Returns:
            bool: True if successfully stored, False on error.
        """
        try:
            _key = self.keyGenerator.generateKey(key)
            data = self.valueConverter.encode(value)
            return await self.db.cache.setCacheEntry(
                _key, data=data, cacheType=self.namespace, dataSource=self.dataSource
            )
        except Exception as e:
            logger.error(f"Failed to set cache entry {key}: {e}")
            return False

    async def clear(self) -> None:
        """
        Clear all cache entries in this namespace.

        Returns:
            None
        """
        await self.db.cache.clearCache(self.namespace, dataSource=self.dataSource)

    def getStats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns basic statistics about the cache state including the namespace
        and enabled status. Additional statistics could be added in the future
        such as entry count, hit/miss ratios, and size information.

        Returns:
            Dict[str, Any]: Dictionary containing cache statistics with keys:
                - enabled: bool indicating if cache is enabled
                - namespace: str namespace identifier
                - backend: str backend type identifier
                - keyGenerator: str key generator class name
                - valueConverter: str value converter class name
        """
        return {
            "enabled": True,
            "namespace": self.namespace.value,
            "backend": "database",
            "keyGenerator": type(self.keyGenerator).__name__,
            "valueConverter": type(self.valueConverter).__name__,
        }
