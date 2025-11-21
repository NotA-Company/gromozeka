"""
Generic database cache implementation for the Telegram bot, dood!

This module provides a database-backed cache implementation that uses the
DatabaseWrapper to store and retrieve cached data. It supports different
cache namespaces and configurable key/value conversion strategies, dood!
"""

import logging
from typing import Any, Dict, Optional

from lib.cache import CacheInterface, HashKeyGenerator, JsonValueConverter, K, KeyGenerator, V, ValueConverter

from .models import CacheType
from .wrapper import DatabaseWrapper

logger = logging.getLogger(__name__)


class GenericDatabaseCache(CacheInterface[K, V]):
    """
    Database-backed cache implementation, dood!

    This cache implementation stores data in the database using the DatabaseWrapper.
    It supports different cache namespaces for organizing data and uses configurable
    key generators and value converters for flexible data handling, dood!

    Type Parameters:
        K: The key type (any hashable type)
        V: The value type (any type)

    Attributes:
        db: DatabaseWrapper instance for database operations
        namespace: CacheType enum value for organizing cache data
        keyGenerator: KeyGenerator instance for converting keys to strings
        valueConverter: ValueConverter instance for serializing/deserializing values

    Example:
        >>> from internal.database.wrapper import DatabaseWrapper
        >>> from internal.database.models import CacheType
        >>> from lib.cache import StringKeyGenerator
        >>>
        >>> db = DatabaseWrapper("path/to/db.sqlite")
        >>> cache = GenericDatabaseCache[str, dict](
        ...     db=db,
        ...     namespace=CacheType.WEATHER,
        ...     keyGenerator=StringKeyGenerator()
        ... )
        >>> await cache.set("moscow", {"temp": 20, "humidity": 50})
        >>> weather = await cache.get("moscow")
    """

    def __init__(
        self,
        db: DatabaseWrapper,
        namespace: CacheType,
        keyGenerator: Optional[KeyGenerator[K]] = None,
        valueConverter: Optional[ValueConverter[V]] = None,
    ):
        """
        Initialize cache with database wrapper

        Args:
            db: DatabaseWrapper instance from internal.database.wrapper
            namespace: CacheType enum value for organizing cache data
            keyGenerator: Optional KeyGenerator instance for converting keys to strings.
                         If None, uses HashKeyGenerator by default.
            valueConverter: Optional ValueConverter instance for serializing/deserializing values.
                           If None, uses JsonValueConverter by default.
        """
        self.db = db
        self.namespace = namespace
        self.keyGenerator: KeyGenerator[K] = keyGenerator if keyGenerator is not None else HashKeyGenerator()
        self.valueConverter: ValueConverter[V] = (
            valueConverter if valueConverter is not None else JsonValueConverter[V]()
        )

    async def get(self, key: K, ttl: Optional[int] = None) -> Optional[V]:
        """Get cached data if exists and not expired"""
        try:
            _key = self.keyGenerator.generateKey(key)
            cacheEntry = self.db.getCacheEntry(_key, cacheType=self.namespace, ttl=ttl)
            if cacheEntry is not None:
                return self.valueConverter.decode(cacheEntry["data"])
            return None
        except Exception as e:
            logger.error(f"Failed to get cache entry {key}: {e}")
            return None

    async def set(self, key: K, value: V) -> bool:
        """Store data in cache"""
        try:
            _key = self.keyGenerator.generateKey(key)
            data = self.valueConverter.encode(value)
            return self.db.setCacheEntry(_key, data=data, cacheType=self.namespace)
        except Exception as e:
            logger.error(f"Failed to set cache entry {key}: {e}")
            return False

    async def clear(self) -> None:
        """Clear all cache entries in this namespace."""
        self.db.clearCache(self.namespace)

    def getStats(self) -> Dict[str, Any]:
        """
        Get cache statistics, dood!

        Returns basic statistics about the cache state including the namespace
        and enabled status. Additional statistics could be added in the future
        such as entry count, hit/miss ratios, and size information, dood!

        Returns:
            Dict[str, Any]: Dictionary containing cache statistics
        """
        return {
            "enabled": True,
            "namespace": self.namespace.value,
            "backend": "database",
            "keyGenerator": type(self.keyGenerator).__name__,
            "valueConverter": type(self.valueConverter).__name__,
        }
