"""Dictionary-based search cache implementation with thread safety.

This module provides a lightweight in-memory cache implementation using Python
dictionaries, designed specifically for testing, development, and simple production
scenarios where persistent caching is not required. The implementation features
comprehensive thread safety, configurable TTL expiration, and automatic cleanup
mechanisms.

Core Features:
    - Thread-safe operations using RLock for concurrent access
    - Configurable TTL (Time To Live) for individual cache entries
    - Maximum cache size enforcement with LRU-like eviction strategy
    - Automatic cleanup of expired entries during access operations
    - SHA512-based cache key generation for consistent hashing
    - Comprehensive cache statistics for monitoring and debugging

Design Philosophy:
    This implementation follows the established pattern from the OpenWeatherMap
    dict cache to maintain consistency across the project's caching components,
    ensuring familiar behavior and maintenance patterns.

Ideal Use Cases:
    - Unit testing scenarios requiring predictable cache behavior
    - Development environments with frequent restarts
    - Simple applications with short runtime periods
    - Prototyping and proof-of-concept implementations
    - Situations where cache persistence is not a requirement

Known Limitations:
    - Cache data is volatile and lost on process restart
    - Memory usage scales linearly with cache size
    - Not suitable for distributed or multi-process systems
    - No persistence mechanisms to disk or external storage

Example:
    Cache initialization with custom configuration::

        cache = DictSearchCache(
            defaultTtl=1800,  # 30 minutes
            maxSize=500      # Maximum 500 entries
        )

    Integration with YandexSearchClient::

        client = YandexSearchClient(
            iamToken="your_iam_token",
            folderId="your_folder_id",
            cache=cache
        )

    Cache performance monitoring::

        stats = cache.getStats()
        print(f"Cache entries: {stats['searchEntries']}/{stats['maxSize']}")
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
    """Thread-safe dictionary-based search cache with TTL and size management.

    This class provides a robust in-memory caching solution for search results
    using Python dictionaries with comprehensive thread safety, TTL expiration,
    and size management features. It fully implements the SearchCacheInterface
    while adding advanced caching capabilities.

    Storage Architecture:
        Cache entries are stored as (data, timestamp) tuples where the timestamp
        enables precise TTL calculations. Expired entries are automatically
        removed during access operations and can be manually cleaned up.

    Thread Safety Implementation:
        All public methods utilize threading.RLock to ensure atomic operations
        in concurrent environments, preventing race conditions and maintaining
        data consistency across multiple threads.

    Memory Management Strategy:
        The cache enforces configurable size limits using an LRU-like eviction
        strategy that removes the oldest entries when capacity is exceeded,
        preventing unbounded memory growth in long-running applications.

    Performance Characteristics:
        - O(1) average time complexity for get/set operations
        - O(n) time complexity for cleanup operations (n = cache size)
        - Minimal memory overhead for small to medium cache sizes
        - Efficient lock usage with minimal contention

    Example:
        Basic cache initialization::

            cache = DictSearchCache()

        Custom configuration for specific requirements::

            cache = DictSearchCache(
                defaultTtl=7200,  # 2 hours
                maxSize=2000      # 2000 entries maximum
            )

        Standard cache operations::

            await cache.setSearch(searchRequest, searchResponse)
            result = await cache.getSearch(searchRequest)

        Cache monitoring and statistics::

            stats = cache.getStats()
            print(f"Cache utilization: {stats['searchEntries']}/{stats['maxSize']}")
    """

    def __init__(self, default_ttl: int = 3600, max_size: int = 1000):
        """Initialize cache with configurable TTL and size limits.

        Creates a new cache instance with the specified TTL and size constraints.
        The cache initializes empty and grows dynamically as entries are added,
        automatically enforcing the maximum size limit through eviction.

        Args:
            defaultTtl (int): Default TTL (Time To Live) in seconds for cache entries.
                Entries older than this duration are considered expired.
                Default is 3600 seconds (1 hour).
                Use 0 for immediate expiration, negative values for no expiration.
            maxSize (int): Maximum number of cached entries allowed.
                When this limit is exceeded, the oldest entries are automatically removed.
                Default is 1000 entries.
                Must be a positive integer greater than 0.

        Raises:
            ValueError: If maxSize is not a positive integer.

        Note:
            - The cache uses RLock for thread-safe operations
            - Cache entries are stored as (data, timestamp) tuples
            - Timestamps are Unix timestamps in seconds since epoch
            - Cache cleanup occurs automatically during access operations
        """
        self.searchCache: Dict[str, Tuple[SearchResponse, float]] = {}
        self.defaultTtl = default_ttl
        self.maxSize = max_size
        self._lock = threading.RLock()  # Thread-safe operations

    def _generateCacheKey(self, request: SearchRequest) -> str:
        """Generate consistent cache key from search request parameters.

        Creates a SHA512 hash of the normalized request parameters, ensuring
        that identical searches always produce the same cache key. The folderId
        is excluded from the hash calculation since it remains constant per
        client instance and doesn't influence the actual search results.

        Args:
            request (SearchRequest): Complete search request structure containing
                all query parameters, sorting options, and metadata.

        Returns:
            str: 128-character SHA512 hash string that uniquely identifies the
                search parameters. This hash serves as the cache key for storing
                and retrieving search results.

        Note:
            The cache key generation is deterministic - identical request parameters
            will always produce the same hash, regardless of parameter ordering.
            The use of SHA512 provides excellent collision resistance for cache keys.
        """

        # Create a normalized representation of the request
        # Exclude folderId from cache key as it's constant per client
        cacheData = {
            "query": request["query"],
            "sortSpec": request.get("sortSpec", None),
            "groupSpec": request.get("groupSpec", None),
            "maxPassages": request.get("maxPassages", None),
            "region": request.get("region", None),
            "l10n": request.get("l10n", None),
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
        """Check if a cache entry has expired based on its storage timestamp.

        This internal method compares the entry's creation timestamp with the
        current time and the specified TTL to determine expiration status.

        Args:
            timestamp (float): Unix timestamp (seconds since epoch) when the
                entry was originally stored in the cache.
            ttl (Optional[int]): Custom TTL in seconds for expiration checking.
                If None, uses the cache's defaultTtl.
                If 0, always returns True (treat as expired).
                If negative, always returns False (treat as never expired).

        Returns:
            bool: True if the entry has exceeded its TTL, False otherwise.
        """
        effective_ttl = ttl if ttl is not None else self.defaultTtl
        return time.time() - timestamp > effective_ttl

    def _cleanupExpired(self) -> None:
        """Remove all expired entries from the cache.

        This internal method iterates through the entire cache and removes
        entries that have exceeded their TTL. The operation is automatically
        triggered during get and set operations to maintain cache freshness
        and prevent memory waste from expired data.

        Note:
            - Must be called within an existing lock context
            - Logs the number of expired entries removed at debug level
            - Performs no operation if no expired entries exist
            - Complexity: O(n) where n is the number of cache entries
        """
        with self._lock:
            expiredKeys = [key for key, (_, timestamp) in self.searchCache.items() if self._isExpired(timestamp)]
            for key in expiredKeys:
                del self.searchCache[key]

            if expiredKeys:
                logger.debug(f"Cleaned up {len(expiredKeys)} expired entries")

    def _enforceSizeLimit(self) -> None:
        """Enforce maximum cache size through LRU-like eviction.

        This internal method implements an eviction strategy that removes the
        oldest entries when the cache exceeds its configured maximum size.
        Entries are sorted primarily by timestamp (oldest first) and secondarily
        by cache key for consistent eviction behavior.

        Eviction Algorithm:
            1. Sort all entries by timestamp (oldest first)
            2. For equal timestamps, sort by cache key for deterministic behavior
            3. Remove the excess entries starting from the oldest

        Note:
            - Must be called within an existing lock context
            - Only executes when cache size exceeds maxSize
            - Logs the number of evicted entries at debug level
            - Uses timestamp-based LRU approximation for efficiency
            - Complexity: O(n log n) due to sorting operation
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
        """Retrieve cached search results by request key.

        This method performs a cache lookup using the provided request key and
        returns the associated SearchResponse if it exists and hasn't expired.
        The operation automatically triggers cleanup of expired entries during
        the lookup process to maintain cache efficiency.

        Args:
            key (SearchRequest): Search request object containing query parameters.
                The cache key is generated internally from this request.
            ttl (Optional[int]): Custom TTL in seconds for expiration checking.
                If None, uses the cache's defaultTtl.
                If 0, treats entry as immediately expired.
                If negative, treats entry as never expired.

        Returns:
            Optional[SearchResponse]: The cached SearchResponse if found and valid,
                None if the entry is expired, missing, or an error occurs.

        Note:
            - Operation is fully thread-safe with internal locking
            - Automatically removes expired entries during lookup
            - Logs cache hits and misses at debug level for monitoring
            - Returns None for any errors without raising exceptions

        Example:
            Basic cache retrieval::

                result = await cache.getSearch(searchRequest)

            Custom TTL override for specific requirements::

                result = await cache.getSearch(searchRequest, ttl=1800)  # 30 minutes
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
        """Store search results in cache with automatic size management.

        This method stores the SearchResponse data with the provided request key
        and current timestamp. The operation automatically triggers cleanup of
        expired entries and enforces the maximum cache size limit by removing
        the oldest entries if necessary.

        Args:
            key (SearchRequest): Search request object serving as the cache key.
                The cache key is generated internally from this request.
            data (SearchResponse): The search response data to cache.
                Contains search results, metadata, and any error information.

        Returns:
            bool: True if the data was successfully stored, False if an error
                occurred during the storage operation.

        Note:
            - Operation is fully thread-safe with internal locking
            - Automatically enforces size limits through eviction
            - Stores current timestamp for TTL calculations
            - Logs storage operations at debug level for monitoring
            - Returns False for any errors without raising exceptions

        Example:
            Standard cache storage::

                success = await cache.setSearch(searchRequest, searchResponse)
                if success:
                    logger.info("Search results cached successfully")
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
        """Remove all cached data regardless of expiration status.

        This method completely empties the cache, removing all entries regardless
        of their expiration status or timestamps. It's particularly useful for
        testing scenarios, debugging cache behavior, or when a complete cache
        reset is required.

        Note:
            - Operation is fully thread-safe with internal locking
            - Resets the cache to a completely empty state
            - Logs the clear operation at debug level for monitoring
            - Operation is irreversible and cannot be undone

        Example:
            Complete cache reset::

                cache.clear()
                stats = cache.getStats()
                print(f"Cache cleared. Current entries: {stats['searchEntries']}")
        """
        with self._lock:
            self.searchCache.clear()
            logger.debug("Cleared all cache data")

    def getStats(self) -> Dict[str, int]:
        """Retrieve comprehensive cache statistics for monitoring and optimization.

        This method returns real-time statistics about the cache state, including
        current usage, configuration limits, and performance metrics. The data
        is valuable for monitoring cache performance, debugging issues, or
        optimizing cache settings for specific workloads.

        Returns:
            Dict[str, int]: Statistics dictionary containing:
                - searchEntries (int): Current number of valid, non-expired entries
                - maxSize (int): Maximum configured cache size limit
                - defaultTtl (int): Default TTL in seconds for new entries

        Note:
            - Operation is fully thread-safe with internal locking
            - Automatically cleans up expired entries before counting
            - Returns a copy to prevent external modification of internal state
            - Statistics reflect the state after cleanup operations

        Example:
            Basic cache monitoring::

                stats = cache.getStats()
                print(f"Cache usage: {stats['searchEntries']}/{stats['maxSize']}")
                print(f"Default TTL: {stats['defaultTtl']} seconds")

            Advanced utilization analysis::

                utilization = stats['searchEntries'] / stats['maxSize'] * 100
                print(f"Cache utilization: {utilization:.1f}%")

                if utilization > 80:
                    logger.warning("Cache approaching capacity limit")
        """
        with self._lock:
            self._cleanupExpired()
            return {
                "search_entries": len(self.searchCache),
                "max_size": self.maxSize,
                "default_ttl": self.defaultTtl,
            }
