"""Abstract cache interface for Yandex Search data caching.

This module defines the abstract interface that all search cache implementations
must follow. The interface provides a standardized contract for caching search
results, enabling different storage backends (in-memory, database, Redis, etc.)
to be used interchangeably with the YandexSearchClient.

The caching strategy is designed to optimize API usage by:
- Reducing redundant API calls through result storage
- Improving response times for frequently repeated queries
- Providing configurable TTL (Time To Live) for cache entries
- Supporting cache bypassing when fresh results are required

This interface follows the established pattern used in the OpenWeatherMap
cache interface to maintain consistency across the project's caching implementations.

Example:
    Creating a custom cache implementation::

        class MyCustomCache(SearchCacheInterface):
            async def getSearch(self, key: SearchRequest, ttl: Optional[int] = None) -> Optional[SearchResponse]:
                # Implementation for retrieving cached search results
                pass

            async def setSearch(self, key: SearchRequest, data: SearchResponse) -> bool:
                # Implementation for storing search results
                pass

    Using the custom cache with YandexSearchClient::

        cache = MyCustomCache()
        client = YandexSearchClient(
            apiKey="your_api_key",
            folderId="your_folder_id",
            cache=cache
        )
"""

from abc import ABC, abstractmethod
from typing import Optional

from .models import SearchRequest, SearchResponse


class SearchCacheInterface(ABC):
    """Abstract interface for search data caching.

    This interface defines the standardized contract that all search cache
    implementations must follow. It provides async methods for storing and
    retrieving SearchResponse objects with configurable TTL (Time To Live)
    expiration support.

    Supported storage backends include:
        - In-memory dictionaries (DictSearchCache)
        - Database tables with persistence
        - Redis or other key-value stores
        - File-based storage systems

    The interface is designed to be fully async-compatible to integrate
    seamlessly with the async YandexSearchClient without blocking operations.

    Cache Key Strategy:
        Cache keys are SearchRequest objects that contain all query parameters.
        The same search parameters should always generate the same cache key
        to ensure consistent cache hits across requests.

    Thread Safety Requirements:
        Implementations must be thread-safe when used in concurrent environments.
        Use appropriate locking mechanisms to prevent race conditions during
        cache operations.

    Example:
        Redis-based cache implementation::

            class RedisSearchCache(SearchCacheInterface):
                def __init__(self, redisClient):
                    self.redis = redisClient

                async def getSearch(self, key: SearchRequest, ttl: Optional[int] = None) -> Optional[SearchResponse]:
                    data = await self.redis.get(str(key))
                    if data:
                        return json.loads(data)
                    return None

                async def setSearch(self, key: SearchRequest, data: SearchResponse) -> bool:
                    await self.redis.setex(str(key), 3600, json.dumps(data))
                    return True
    """

    @abstractmethod
    async def getSearch(self, key: SearchRequest, ttl: Optional[int] = None) -> Optional[SearchResponse]:
        """Retrieve cached search results by cache key.

        This method should return the cached SearchResponse if it exists and
        hasn't expired based on the provided TTL parameters. The method must
        handle cache misses gracefully and return None for any errors.

        Args:
            key (SearchRequest): Cache key containing search query parameters.
                The key uniquely identifies a specific search request.
            ttl (Optional[int]): Custom TTL in seconds for expiration checking.
                If None, use the cache implementation's default TTL.
                If 0, treat as always expired (force cache miss).
                If negative, treat as never expired (ignore expiration).

        Returns:
            Optional[SearchResponse]: The cached SearchResponse if found and
                valid, None otherwise (cache miss or expired entry).

        Raises:
            This method should not raise exceptions for expected cache operations.
            All errors should be handled internally and result in None return.

        Note:
            - Expired entries should be removed from cache when possible
            - Implementations must be thread-safe for concurrent access
            - Cache key validation should be performed before lookup
            - Performance should be optimized for frequent access patterns

        Example:
            Basic cache retrieval::

                result = await cache.getSearch(searchRequest)

            Custom TTL override for specific requirements::

                result = await cache.getSearch(searchRequest, ttl=1800)  # 30 minutes
        """
        pass

    @abstractmethod
    async def setSearch(self, key: SearchRequest, data: SearchResponse) -> bool:
        """Store search results in cache with the specified key.

        This method should store the SearchResponse data with the provided key,
        including necessary metadata for TTL calculations. The implementation
        should handle storage errors gracefully and manage cache size limits.

        Args:
            key (SearchRequest): Cache key for storing the search data.
                Must match exactly the key used for subsequent retrieval.
            data (SearchResponse): The search response data to cache.
                Contains search results, metadata, error information, and timestamps.

        Returns:
            bool: True if the data was successfully stored, False otherwise.

        Raises:
            This method should not raise exceptions for expected cache operations.
            All storage errors should be handled internally and result in False return.

        Note:
            - Implementations must store creation timestamps for TTL calculations
            - Consider implementing cache size limits and eviction policies
            - Thread safety is essential for concurrent write operations
            - Data serialization should preserve all SearchResponse fields
            - Cache key validation should be performed before storage

        Example:
            Storing search results with error handling::

                success = await cache.setSearch(searchRequest, searchResponse)
                if not success:
                    logger.warning("Failed to cache search result for key: %s", searchRequest)
        """
        pass
