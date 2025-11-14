"""
Null cache implementation for lib.cache, dood!

This module provides a no-op cache implementation that implements the
CacheInterface but doesn't actually cache anything. Useful for testing
scenarios where caching is not needed or should be disabled, dood!
"""

from typing import Any, Dict, Optional

from .interface import CacheInterface
from .types import K, V


class NullCache(CacheInterface[K, V]):
    """No-op cache that never stores anything, dood!

    Useful for:
    - Testing without cache side effects
    - Disabling cache in production
    - Benchmarking cache impact
    """

    async def get(self, key: K, ttl: Optional[int] = None) -> Optional[V]:
        """
        Always return None (cache miss), dood!

        This method never returns cached data since NullCache doesn't
        store anything. It's useful for testing code that expects
        cache behavior without actual caching side effects, dood!

        Args:
            key: The cache key to retrieve (ignored)
            ttl: Optional TTL override in seconds (ignored)

        Returns:
            Optional[V]: Always None (never found in cache)
        """
        return None

    async def set(self, key: K, value: V) -> bool:
        """
        Do nothing (don't cache), but pretend to succeed, dood!

        This method doesn't actually store anything but returns True
        to maintain compatibility with code that expects cache operations
        to succeed. Useful for testing cache-dependent code without
        actual caching behavior, dood!

        Args:
            key: The cache key to store under (ignored)
            value: The value to cache (ignored)

        Returns:
            bool: Always True (pretends to succeed)
        """
        return True

    async def clear(self) -> None:
        """
        Do nothing (no-op operation), dood!

        Since NullCache doesn't store anything, there's nothing to clear.
        This method exists for interface compatibility but has no effect, dood!
        """
        pass

    def getStats(self) -> Dict[str, Any]:
        """
        Return cache statistics indicating cache is disabled, dood!

        Returns minimal statistics showing that caching is disabled.
        This helps monitoring and debugging by clearly indicating
        that the cache is a null implementation, dood!

        Returns:
            Dict[str, Any]: Dictionary with cache disabled indicator
        """
        return {"enabled": False}
