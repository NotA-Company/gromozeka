"""
Abstract cache interface for lib.cache, dood!

This module defines the generic CacheInterface that all cache implementations
must follow. It provides a consistent API for different cache backends
while maintaining type safety through Python generics, dood!
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, Optional

from .types import K, V


class CacheInterface(ABC, Generic[K, V]):
    """
    Generic cache interface for any key-value storage, dood!

    This abstract base class defines the contract that all cache implementations
    must follow. It provides a type-safe interface for basic cache operations
    including get, set, clear, and statistics retrieval, dood!

    Type Parameters:
        K: The key type (any hashable type)
        V: The value type (any type)

    Example:
        >>> from lib.cache import DictCache, StringKeyGenerator
        >>>
        >>> # Create a cache implementation
        >>> cache = DictCache[str, dict](
        ...     keyGenerator=StringKeyGenerator(),
        ...     defaultTtl=3600
        ... )
        >>>
        >>> # Use the interface methods
        >>> await cache.set("user:123", {"name": "Prinny", "level": 99})
        >>> userData = await cache.get("user:123")
        >>> stats = cache.getStats()
    """

    @abstractmethod
    async def get(self, key: K, ttl: Optional[int] = None) -> Optional[V]:
        """
        Get cached value by key, dood!

        Retrieves a value from the cache if it exists and hasn't expired.
        Returns None if the key is not found or the cached value has expired,
        dood!

        Args:
            key: The cache key to retrieve
            ttl: Optional TTL override for this operation in seconds.
                 If provided, overrides the default TTL for expiration check.
                 If None, uses the cache's default TTL behavior.

        Returns:
            Optional[V]: The cached value if found and not expired, None otherwise

        Example:
            >>> cache = DictCache[str, str](StringKeyGenerator())
            >>> await cache.set("greeting", "Hello, dood!")
            >>> result = await cache.get("greeting")
            >>> print(result)  # "Hello, dood!"
            >>>
            >>> # Get with custom TTL check
            >>> result = await cache.get("greeting", ttl=60)
        """
        pass

    @abstractmethod
    async def set(self, key: K, value: V) -> bool:
        """
        Store value in cache, dood!

        Stores a value in the cache with the current timestamp for TTL
        calculation. The value will be available until it expires based
        on the cache's default TTL or is manually removed, dood!

        Args:
            key: The cache key to store the value under
            value: The value to cache

        Returns:
            bool: True if the value was successfully stored, False otherwise

        Example:
            >>> cache = DictCache[str, dict](StringKeyGenerator())
            >>> success = await cache.set("user:123", {"name": "Prinny"})
            >>> print(success)  # True
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """
        Clear all cached data, dood!

        Removes all entries from the cache, resetting it to an empty state.
        This operation is synchronous and should complete immediately, dood!

        Example:
            >>> cache = DictCache[str, str](StringKeyGenerator())
            >>> await cache.set("key1", "value1")
            >>> await cache.set("key2", "value2")
            >>> cache.clear()  # All entries removed
            >>> stats = cache.getStats()
            >>> print(stats['entries'])  # 0
        """
        pass

    @abstractmethod
    def getStats(self) -> Dict[str, Any]:
        """
        Get cache statistics, dood!

        Returns implementation-specific statistics about the cache state
        and performance. The exact keys and values depend on the cache
        implementation, but common metrics include entry count, size limits,
        and configuration values, dood!

        Returns:
            Dict[str, Any]: Dictionary containing cache statistics

        Example:
            >>> cache = DictCache[str, str](StringKeyGenerator(), maxSize=100)
            >>> await cache.set("key", "value")
            >>> stats = cache.getStats()
            >>> print(f"Entries: {stats['entries']}")
            >>> print(f"Max size: {stats['maxSize']}")
            >>> print(f"Default TTL: {stats['defaultTtl']}s")
        """
        pass
