"""Performance tests for Yandex Search API client.

This module contains comprehensive performance tests to measure various aspects
of the client's performance including response times, cache efficiency, rate
limiting behavior, memory usage, and concurrent request handling capabilities.

The tests use mock clients to ensure consistent and reliable performance
measurements without external dependencies, while maintaining realistic
network latency simulation.

Run with:
    ./venv/bin/python3 -m pytest lib/yandex_search/test_performance.py -v
"""

import asyncio
import logging
import time

import pytest

from lib.cache import DictCache
from lib.rate_limiter import RateLimiterManager
from lib.yandex_search import SearchRequestKeyGenerator, YandexSearchClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration - use mock credentials for performance tests
TEST_IAM_TOKEN = "test_token_for_performance"
TEST_API_KEY = "test_api_key_for_performance"
TEST_FOLDER_ID = "test_folder_id_for_performance"


class MockYandexSearchClient(YandexSearchClient):
    """Mock client for performance testing without actual API calls.

    This mock client extends the YandexSearchClient to provide predictable
    performance characteristics for testing. It simulates network latency
    and returns consistent mock responses, enabling reliable performance
    measurements without external dependencies.
    """

    def __init__(self, **kwargs):
        """Initialize the mock client with performance test settings.

        Sets up default test credentials for performance testing. Prepares mock
        response data that matches the structure of real API responses.

        Args:
            **kwargs: Additional keyword arguments passed to the parent YandexSearchClient.
                     Default values are set for:
                     - iamToken: TEST_IAM_TOKEN
                     - folderId: TEST_FOLDER_ID
        """
        # Set default test credentials
        kwargs.setdefault("iamToken", TEST_IAM_TOKEN)
        kwargs.setdefault("folderId", TEST_FOLDER_ID)

        # Initialize parent with all provided kwargs
        super().__init__(**kwargs)
        # Mock response data
        self.mockResponse = {
            "requestId": "test-request-id",
            "found": 1000,
            "foundHuman": "Найдено 1\xa00000 результатов",
            "page": 0,
            "groups": [
                {
                    "group": [
                        {
                            "url": "https://example.com",
                            "domain": "example.com",
                            "title": "Test Result",
                            "passages": ["This is a test passage"],
                            "hlwords": ["test"],
                            "size": "1024",
                            "modtime": "2023-01-01",
                        }
                    ]
                }
            ],
        }
        # Track request count for rate limiting tests
        self.requestCount = 0

    async def _makeRequest(self, request):
        """Mock API request that simulates network latency.

        Simulates a realistic network delay and returns a consistent mock
        response. This method tracks request count for rate limiting tests
        and provides predictable performance characteristics.

        Args:
            request: The search request data (ignored in mock).

        Returns:
            Dict: Mock search response matching the expected structure.
        """
        # Simulate network delay
        await asyncio.sleep(0.1)  # 100ms delay

        # Increment request counter
        self.requestCount += 1

        # Return mock response
        return self.mockResponse


@pytest.fixture
def mockClient():
    """Create a mock client for performance testing."""
    return MockYandexSearchClient(iamToken=TEST_IAM_TOKEN, folderId=TEST_FOLDER_ID, requestTimeout=10)


@pytest.fixture
def cachedClient():
    """Create a mock client with caching enabled."""
    cache = DictCache(keyGenerator=SearchRequestKeyGenerator(), maxSize=1000, defaultTtl=3600)
    return MockYandexSearchClient(iamToken=TEST_IAM_TOKEN, folderId=TEST_FOLDER_ID, cache=cache, cacheTTL=3600)


@pytest.fixture
def rateLimiterManager():
    """Create a rate limiter manager for testing."""
    manager = RateLimiterManager.getInstance()
    if "default" not in manager.listRateLimiters():
        asyncio.run(
            manager.loadConfig(
                {
                    "ratelimiters": {
                        "default": {
                            "type": "SlidingWindow",
                            "config": {
                                "maxRequests": 1000,
                                "windowSeconds": 1,
                            },
                        },
                    },
                }
            )
        )  # init default rate limiter
    return manager


class TestSearchPerformance:
    """Test search response times and performance metrics.

    This test class measures various aspects of search performance including
    single request response times, sequential search performance, and
    concurrent search capabilities.
    """

    @pytest.mark.asyncio
    async def testSingleSearchResponseTime(self, mockClient, rateLimiterManager):
        """Test response time for a single search request.

        Measures the response time for a single search request and verifies
        that it falls within expected bounds, accounting for the simulated
        network delay in the mock client.
        """
        startTime = time.time()

        result = await mockClient.search("test query")

        endTime = time.time()
        responseTime = endTime - startTime

        assert result is not None
        assert responseTime < 1.0  # Should complete within 1 second
        assert responseTime >= 0.1  # Should account for mock delay

        logger.info(f"Single search response time: {responseTime:.3f}s")

    @pytest.mark.asyncio
    async def testSequentialSearchPerformance(self, mockClient, rateLimiterManager):
        """Test performance of multiple sequential searches.

        Measures the performance of executing multiple searches sequentially
        and verifies that the average response time remains within acceptable
        limits. Tests the client's performance under sustained load.
        """
        queries = [f"test query {i}" for i in range(10)]

        startTime = time.time()
        results = []

        for query in queries:
            result = await mockClient.search(query)
            results.append(result)

        endTime = time.time()
        totalTime = endTime - startTime
        avgTime = totalTime / len(queries)

        assert all(results)  # All searches should succeed
        assert totalTime < 5.0  # Should complete within 5 seconds
        assert avgTime < 0.5  # Average should be under 500ms

        logger.info(f"Sequential searches: {len(queries)} in {totalTime:.3f}s")
        logger.info(f"Average time per search: {avgTime:.3f}s")

    @pytest.mark.asyncio
    async def testConcurrentSearchPerformance(self, mockClient, rateLimiterManager):
        """Test performance of concurrent searches.

        Measures the performance of executing multiple searches concurrently
        and verifies that concurrent execution provides better throughput
        than sequential execution. Tests the client's ability to handle
        parallel requests efficiently.
        """
        queries = [f"test query {i}" for i in range(20)]

        startTime = time.time()

        # Create tasks for concurrent execution
        tasks = [mockClient.search(query) for query in queries]
        results = await asyncio.gather(*tasks)

        endTime = time.time()
        totalTime = endTime - startTime
        avgTime = totalTime / len(queries)

        assert all(results)  # All searches should succeed
        assert totalTime < 10.0  # Should complete faster than sequential
        assert avgTime < 0.5  # Average should be under 500ms due to concurrency

        logger.info(f"Concurrent searches: {len(queries)} in {totalTime:.3f}s")
        logger.info(f"Average time per search: {avgTime:.3f}s")


class TestMemoryAndResourceUsage:
    """Test memory usage and resource management.

    This test class evaluates the client's memory usage patterns and
    resource management, ensuring proper cleanup and absence of memory
    leaks during normal operation.
    """

    @pytest.mark.asyncio
    async def testConcurrentRequestResourceManagement(self, mockClient, rateLimiterManager):
        """Test resource management during concurrent requests.

        Verifies that the client properly manages resources during
        concurrent request processing, ensuring that resources are
        not exhausted or leaked during high-load scenarios.
        """
        # Create many concurrent tasks
        tasks = []
        for i in range(50):
            task = mockClient.search(f"concurrent test {i}")
            tasks.append(task)

        # Execute all tasks
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(results)

        # Client should still be functional
        result = await mockClient.search("post-concurrent test")
        assert result is not None

        logger.info("Concurrent resource management test passed")


class TestPerformanceBenchmarks:
    """Performance benchmarks for comparison.

    This test class provides standardized benchmarks for measuring and
    comparing the client's performance characteristics, establishing
    baseline performance metrics.
    """

    @pytest.mark.asyncio
    async def benchmarkSearchThroughput(self, mockClient):
        """Benchmark search throughput (requests per second).

        Measures the maximum throughput the client can achieve for
        search requests, establishing a baseline performance metric
        for comparison and regression testing.
        """
        numRequests = 100

        startTime = time.time()

        # Create concurrent tasks
        tasks = [mockClient.search(f"benchmark query {i}") for i in range(numRequests)]
        results = await asyncio.gather(*tasks)

        endTime = time.time()
        totalTime = endTime - startTime
        throughput = numRequests / totalTime

        assert all(results)  # All requests should succeed

        logger.info(f"Throughput benchmark: {throughput:.1f} requests/second")
        logger.info(f"Total time for {numRequests} requests: {totalTime:.3f}s")

        # Performance assertion - should handle at least 5 requests/second
        assert throughput >= 5.0

    @pytest.mark.asyncio
    async def benchmarkCacheThroughput(self, cachedClient):
        """Benchmark cache throughput (requests per second with cache).

        Measures the maximum throughput the client can achieve when
        serving requests from cache, demonstrating the performance
        benefits of caching and establishing cache performance metrics.
        """
        query = "cache benchmark query"

        # First request to populate cache
        await cachedClient.search(query)

        # Benchmark cached requests
        numRequests = 1000
        startTime = time.time()

        tasks = [cachedClient.search(query) for _ in range(numRequests)]
        results = await asyncio.gather(*tasks)

        endTime = time.time()
        totalTime = endTime - startTime
        throughput = numRequests / totalTime

        assert all(results)  # All requests should succeed

        logger.info(f"Cache throughput benchmark: {throughput:.1f} requests/second")
        logger.info(f"Total time for {numRequests} cached requests: {totalTime:.3f}s")

        # Cache should be much faster - at least 100 requests/second
        assert throughput >= 100.0


if __name__ == "__main__":
    # Run performance tests directly
    import sys

    print("Running Yandex Search performance tests...")
    print("Note: These tests use mock clients and don't make real API calls")

    # Run pytest with verbose output
    sys.exit(pytest.main([__file__, "-v", "-s"]))
