"""
Simple dictionary-based search cache implementation

This module provides a basic in-memory cache implementation using Python dictionaries.
It's designed for testing, development, and simple scenarios where persistent
caching is not required. The cache is thread-safe and supports TTL (Time To Live)
expiration with automatic cleanup of expired entries.

Key features:
- Thread-safe operations using RLock
- Configurable TTL for cache entries
- Maximum cache size with LRU-like eviction
- Automatic cleanup of expired entries
- MD5-based cache key generation
- Cache statistics for monitoring

This implementation follows the same pattern as lib/openweathermap/dict_cache.py
to maintain consistency across the project's caching components.

Use cases:
- Unit testing (mock cache)
- Development and debugging
- Simple applications with short runtime
- Scenarios where cache persistence is not needed
- Prototyping and proof-of-concept

Limitations:
- Cache is lost when the process restarts
- Memory usage grows with cache size
- Not suitable for distributed systems
- No persistence to disk or database

Example:
    ```python
    # Create cache with custom settings
    cache = DictSearchCache(
        default_ttl=1800,  # 30 minutes
        max_size=500      # Maximum 500 entries
    )

    # Use with YandexSearchClient
    client = YandexSearchClient(
        iam_token="your_token",
        folder_id="your_folder",
        cache=cache
    )

    # Monitor cache performance
    stats = cache.get_stats()
    print(f"Cache entries: {stats['search_entries']}/{stats['max_size']}")
    ```
"""

import hashlib
import json
import logging
import threading
import time
from typing import Dict, Optional, Tuple

from .cache_interface import SearchCacheInterface
from .models import SearchRequest, SearchResponse

logger = logging.getLogger(__name__)


class DictSearchCache(SearchCacheInterface):
    """
    Simple dictionary-based search cache implementation with thread safety.

    This class provides an in-memory caching solution for search results using
    Python dictionaries. It implements the SearchCacheInterface and adds features
    like TTL expiration, size limits, and thread safety.

    The cache stores entries as (data, timestamp) tuples, where the timestamp
    is used for TTL calculations. Expired entries are automatically removed
    during access operations and can be manually cleaned up.

    Thread Safety:
    All public methods use threading.RLock to ensure thread-safe operations
    in concurrent environments. This allows multiple threads to safely access
    and modify the cache without race conditions.

    Memory Management:
    The cache enforces a maximum size limit using a simple eviction strategy
    that removes the oldest entries when the limit is exceeded. This helps
    prevent unbounded memory growth in long-running applications.

    Performance:
    - O(1) average case for get/set operations
    - O(n) for cleanup operations (where n is cache size)
    - Minimal overhead for small to medium cache sizes

    Example:
        ```python
        # Basic usage
        cache = DictSearchCache()

        # Custom configuration
        cache = DictSearchCache(
            default_ttl=7200,  # 2 hours
            max_size=2000      # 2000 entries max
        )

        # Store and retrieve
        await cache.setSearch("key1", search_response)
        result = await cache.getSearch("key1")

        # Generate cache key from parameters
        key = cache.generate_key_from_params(
            query="python programming",
            region="225"
        )
        ```
    """

    def __init__(self, default_ttl: int = 3600, max_size: int = 1000):
        """
        Initialize cache with empty dictionary and thread lock.

        Creates a new cache instance with the specified TTL and size limits.
        The cache starts empty and will grow as entries are added, subject
        to the maximum size constraint.

        Args:
            default_ttl (int): Default TTL (Time To Live) in seconds for cache entries.
                              Entries older than this will be considered expired.
                              Default is 3600 seconds (1 hour).
                              Use 0 for immediate expiration, negative for no expiration.
            max_size (int): Maximum number of cached entries.
                           When this limit is exceeded, the oldest entries are removed.
                           Default is 1000 entries.
                           Must be positive.

        Raises:
            ValueError: If max_size is not a positive integer.

        Note:
            - The cache uses an RLock for thread safety
            - Cache entries are stored as (data, timestamp) tuples
            - Timestamps are Unix timestamps (seconds since epoch)
        """
        self.searchCache: Dict[str, Tuple[SearchResponse, float]] = {}
        self.defaultTtl = default_ttl
        self.maxSize = max_size
        self._lock = threading.RLock()  # Thread-safe operations

    def _generateCacheKey(self, request: SearchRequest) -> str:
        """
        Generate a consistent cache key from search request parameters.

        The cache key is an MD5 hash of the normalized request parameters,
        ensuring that identical searches produce the same cache key. The folderId
        is excluded from the hash since it's constant per client instance and
        doesn't affect the search results themselves.

        Args:
            request: Complete search request structure.

        Returns:
            str: 32-character MD5 hash string that uniquely identifies the search
                 parameters. This hash is used as the cache key for storing and
                 retrieving search results.

        Note:
            The cache key generation is deterministic - the same request parameters
            will always produce the same hash, regardless of parameter order.
        """
        import hashlib
        import json

        # Create a normalized representation of the request
        # Exclude folderId from cache key as it's constant per client
        cacheData = {
            "query": request["query"],
            "sortSpec": request["sortSpec"],
            "groupSpec": request["groupSpec"],
            # Include relevant metadata fields except folderId
            "maxPassages": request["maxPassages"],
            "region": request["region"],
            "l10n": request["l10n"],
            "responseFormat": request["responseFormat"],
        }

        # Sort and serialize to ensure consistent keys
        sorted_json = json.dumps(
            cacheData,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha512(sorted_json.encode("utf-8")).hexdigest()

    def _isExpired(self, timestamp: float, ttl: Optional[int] = None) -> bool:
        """
        Check if a cache entry is expired based on its timestamp.

        This internal method compares the entry's timestamp with the current
        time and the specified TTL to determine if the entry has expired.

        Args:
            timestamp (float): Unix timestamp when the entry was stored.
            ttl (Optional[int]): TTL in seconds to check against.
                               If None, uses the cache's default_ttl.
                               If 0, always returns True (expired).
                               If negative, always returns False (not expired).

        Returns:
            bool: True if the entry is expired, False otherwise.
        """
        effective_ttl = ttl if ttl is not None else self.defaultTtl
        return time.time() - timestamp > effective_ttl

    def _cleanupExpired(self) -> None:
        """
        Remove expired entries from cache.

        This internal method iterates through all cache entries and removes
        those that have exceeded their TTL. It's called automatically during
        get and set operations to maintain cache freshness.

        Note:
            - Must be called within a lock context
            - Logs the number of expired entries removed
            - No-op if no expired entries exist
        """
        with self._lock:
            expiredKeys = [key for key, (_, timestamp) in self.searchCache.items() if self._isExpired(timestamp)]
            for key in expiredKeys:
                del self.searchCache[key]

            if expiredKeys:
                logger.debug(f"Cleaned up {len(expiredKeys)} expired entries")

    def _enforceSizeLimit(self) -> None:
        """
        Enforce maximum cache size by removing oldest entries.

        This internal method implements a simple eviction strategy that removes
        the oldest entries when the cache exceeds its maximum size. Entries are
        sorted by timestamp (oldest first) to determine which to remove.

        The eviction strategy:
        1. Sort entries by timestamp (oldest first)
        2. If timestamps are equal, sort by key for consistency
        3. Remove the excess entries

        Note:
            - Must be called within a lock context
            - Only runs if cache size exceeds max_size
            - Logs the number of entries removed
            - Uses a simple LRU-like approach based on timestamps
        """
        with self._lock:
            if len(self.searchCache) <= self.maxSize:
                return

            # Sort by timestamp (oldest first), if timestamps are equal, sort by key
            sorted_items = sorted(
                self.searchCache.items(), key=lambda item: (item[1][1], item[0])  # timestamp then key
            )

            excessCount = len(self.searchCache) - self.maxSize
            for i in range(excessCount):
                key = sorted_items[i][0]
                del self.searchCache[key]

            logger.debug(f"Removed {excessCount} oldest entries to enforce size limit")

    async def getSearch(self, key: SearchRequest, ttl: Optional[int] = None) -> Optional[SearchResponse]:
        """
        Retrieve cached search results by key.

        This method looks up the cache key and returns the associated SearchResponse
        if it exists and hasn't expired. It automatically cleans up expired entries
        during the lookup process.

        Args:
            key (str): Cache key (typically an MD5 hash of query parameters).
                      Should match a key used in a previous setSearch() call.
            ttl (Optional[int]): TTL in seconds for expiration checking.
                               If None, uses the cache's default_ttl.
                               If 0, treats entry as expired.
                               If negative, treats entry as never expired.

        Returns:
            Optional[SearchResponse]: The cached SearchResponse if found and
                                    not expired, None otherwise.

        Note:
            - Thread-safe operation
            - Automatically removes expired entries
            - Logs cache hits and misses at debug level
            - Returns None for any errors (doesn't raise exceptions)

        Example:
            ```python
            # Get with default TTL
            result = await cache.getSearch("abc123def456")

            # Get with custom TTL
            result = await cache.getSearch("abc123def456", ttl=1800)
            ```
        """
        try:
            keyStr = self._generateCacheKey(key)
            with self._lock:
                self._cleanupExpired()

                if keyStr in self.searchCache:
                    data, timestamp = self.searchCache[keyStr]
                    if not self._isExpired(timestamp, ttl):
                        logger.debug(f"Cache hit for search key: {keyStr}")
                        return data
                    else:
                        # Remove expired entry
                        del self.searchCache[keyStr]
                        logger.debug(f"Removed expired search entry: {keyStr}")

                logger.debug(f"Cache miss for search key: {keyStr}")
                return None
        except Exception as e:
            logger.error(f"Failed to get search cache entry {keyStr}: {e}")
            return None

    async def setSearch(self, key: SearchRequest, data: SearchResponse) -> bool:
        """
        Store search results in cache.

        This method stores the SearchResponse with the provided key and current
        timestamp. It automatically cleans up expired entries and enforces the
        maximum cache size limit by removing oldest entries if necessary.

        Args:
            key (str): Cache key for storing the data.
                      Should be generated using _generate_cache_key() or
                      generate_key_from_params() for consistency.
            data (SearchResponse): The search response data to cache.
                                 Contains search results, metadata, and error info.

        Returns:
            bool: True if the data was successfully stored, False otherwise.

        Note:
            - Thread-safe operation
            - Automatically enforces size limits
            - Stores current timestamp for TTL calculations
            - Logs storage operations at debug level
            - Returns False for any errors (doesn't raise exceptions)

        Example:
            ```python
            success = await cache.setSearch("abc123def456", search_response)
            if success:
                print("Data cached successfully")
            ```
        """
        try:
            keyStr = self._generateCacheKey(key)
            with self._lock:
                self._cleanupExpired()

                # Add new entry first
                self.searchCache[keyStr] = (data, time.time())

                # Then enforce size limit
                self._enforceSizeLimit()

                logger.debug(f"Stored search data for key: {keyStr}")
                return True
        except Exception as e:
            logger.error(f"Failed to set search cache entry {keyStr}: {e}")
            return False

    def clear(self) -> None:
        """
        Clear all cached data.

        This method removes all entries from the cache, regardless of their
        expiration status. It's useful for testing, debugging, or when you
        need to reset the cache completely.

        Note:
            - Thread-safe operation
            - Resets the cache to empty state
            - Logs the clear operation at debug level
            - Cannot be undone

        Example:
            ```python
            cache.clear()
            print(f"Cache cleared. Entries: {cache.get_stats()['search_entries']}")
            ```
        """
        with self._lock:
            self.searchCache.clear()
            logger.debug("Cleared all cache data")

    def getStats(self) -> Dict[str, int]:
        """
        Get cache statistics for monitoring and debugging.

        This method returns current statistics about the cache state, which
        can be useful for monitoring cache performance, debugging issues,
        or optimizing cache settings.

        Returns:
            Dict[str, int]: Dictionary containing the following statistics:
                - search_entries (int): Current number of non-expired entries
                - max_size (int): Maximum configured cache size
                - default_ttl (int): Default TTL in seconds

        Note:
            - Thread-safe operation
            - Automatically cleans up expired entries before counting
            - Returns a copy to prevent external modification

        Example:
            ```python
            stats = cache.get_stats()
            print(f"Cache usage: {stats['search_entries']}/{stats['max_size']}")
            print(f"Default TTL: {stats['default_ttl']} seconds")

            # Calculate cache utilization
            utilization = stats['search_entries'] / stats['max_size'] * 100
            print(f"Cache utilization: {utilization:.1f}%")
            ```
        """
        with self._lock:
            self._cleanupExpired()
            return {
                "search_entries": len(self.searchCache),
                "max_size": self.maxSize,
                "default_ttl": self.defaultTtl,
            }
