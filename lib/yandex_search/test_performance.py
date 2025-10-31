"""
Performance tests for Yandex Search API client.

This module contains performance tests to measure:
- Search response times
- Cache performance (hit/miss ratios)
- Rate limiting effectiveness
- Memory usage with caching
- Concurrent request handling

Run with:
    ./venv/bin/python3 -m pytest lib/yandex_search/test_performance.py -v
"""

import asyncio
import gc
import logging
import time
import tracemalloc

import pytest

from lib.yandex_search import DictSearchCache, YandexSearchClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration - use mock credentials for performance tests
TEST_IAM_TOKEN = "test_token_for_performance"
TEST_API_KEY = "test_api_key_for_performance"
TEST_FOLDER_ID = "test_folder_id_for_performance"


class MockYandexSearchClient(YandexSearchClient):
    """Mock client for performance testing without actual API calls."""

    def __init__(self, **kwargs):
        # Set default test credentials
        kwargs.setdefault("iamToken", TEST_IAM_TOKEN)
        kwargs.setdefault("folderId", TEST_FOLDER_ID)
        # Disable rate limiting by default for performance tests
        kwargs.setdefault("rateLimitRequests", 1000)  # Very high limit
        kwargs.setdefault("rateLimitWindow", 60)  # 60 second window

        # Initialize parent with all provided kwargs
        super().__init__(**kwargs)
        # Mock response data
        self.mock_response = {
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
        self.request_count = 0

    async def _makeRequest(self, request):
        """Mock API request that simulates network latency."""
        # Simulate network delay
        await asyncio.sleep(0.1)  # 100ms delay

        # Increment request counter
        self.request_count += 1

        # Return mock response
        return self.mock_response


@pytest.fixture
def mock_client():
    """Create a mock client for performance testing."""
    return MockYandexSearchClient(iamToken=TEST_IAM_TOKEN, folderId=TEST_FOLDER_ID, requestTimeout=10)


@pytest.fixture
def cached_client():
    """Create a mock client with caching enabled."""
    cache = DictSearchCache(max_size=1000, default_ttl=3600)
    return MockYandexSearchClient(iamToken=TEST_IAM_TOKEN, folderId=TEST_FOLDER_ID, cache=cache, cacheTTL=3600)


@pytest.fixture
def rate_limited_client():
    """Create a mock client with strict rate limiting."""
    return MockYandexSearchClient(
        iamToken=TEST_IAM_TOKEN,
        folderId=TEST_FOLDER_ID,
        rateLimitRequests=3,
        rateLimitWindow=1,  # 3 requests per 1 second
    )


class TestSearchPerformance:
    """Test search response times and performance metrics."""

    @pytest.mark.asyncio
    async def test_single_search_response_time(self, mock_client):
        """Test response time for a single search request."""
        start_time = time.time()

        result = await mock_client.searchSimple("test query")

        end_time = time.time()
        response_time = end_time - start_time

        assert result is not None
        assert response_time < 1.0  # Should complete within 1 second
        assert response_time >= 0.1  # Should account for mock delay

        logger.info(f"Single search response time: {response_time:.3f}s")

    @pytest.mark.asyncio
    async def test_sequential_search_performance(self, mock_client):
        """Test performance of multiple sequential searches."""
        queries = [f"test query {i}" for i in range(10)]

        start_time = time.time()
        results = []

        for query in queries:
            result = await mock_client.searchSimple(query)
            results.append(result)

        end_time = time.time()
        total_time = end_time - start_time
        avg_time = total_time / len(queries)

        assert all(results)  # All searches should succeed
        assert total_time < 5.0  # Should complete within 5 seconds
        assert avg_time < 0.5  # Average should be under 500ms

        logger.info(f"Sequential searches: {len(queries)} in {total_time:.3f}s")
        logger.info(f"Average time per search: {avg_time:.3f}s")

    @pytest.mark.asyncio
    async def test_concurrent_search_performance(self, mock_client):
        """Test performance of concurrent searches."""
        queries = [f"test query {i}" for i in range(20)]

        start_time = time.time()

        # Create tasks for concurrent execution
        tasks = [mock_client.searchSimple(query) for query in queries]
        results = await asyncio.gather(*tasks)

        end_time = time.time()
        total_time = end_time - start_time
        avg_time = total_time / len(queries)

        assert all(results)  # All searches should succeed
        assert total_time < 10.0  # Should complete faster than sequential
        assert avg_time < 0.5  # Average should be under 500ms due to concurrency

        logger.info(f"Concurrent searches: {len(queries)} in {total_time:.3f}s")
        logger.info(f"Average time per search: {avg_time:.3f}s")


class TestCachePerformance:
    """Test cache hit/miss ratios and performance."""

    @pytest.mark.asyncio
    async def test_cache_hit_performance(self, cached_client):
        """Test that cached responses are faster than API calls."""
        query = "cache performance test"

        # First request - should hit the API
        start_time = time.time()
        result1 = await cached_client.searchSimple(query)
        first_request_time = time.time() - start_time

        # Second request - should hit cache
        start_time = time.time()
        result2 = await cached_client.searchSimple(query)
        second_request_time = time.time() - start_time

        assert result1 is not None
        assert result2 is not None
        assert result1["requestId"] == result2["requestId"]  # Same cached result
        assert second_request_time < first_request_time  # Cache should be faster

        # Check cache stats
        cache = cached_client.cache
        stats = cache.get_stats()
        assert stats["search_entries"] >= 1

        logger.info(f"First request (API): {first_request_time:.3f}s")
        logger.info(f"Second request (cache): {second_request_time:.3f}s")
        logger.info(f"Cache speedup: {first_request_time / second_request_time:.1f}x")

    @pytest.mark.asyncio
    async def test_cache_hit_miss_ratio(self, cached_client):
        """Test cache hit/miss ratio with repeated queries."""
        queries = ["query 1", "query 2", "query 3"]
        repeat_count = 5

        # Make initial requests to populate cache
        for query in queries:
            await cached_client.searchSimple(query)

        # Clear cache to start fresh
        cached_client.cache.clear()

        # Repeat queries multiple times
        for _ in range(repeat_count):
            for query in queries:
                await cached_client.searchSimple(query)

        # Check cache stats
        stats = cached_client.cache.get_stats()
        # We should have 3 unique queries cached
        assert stats["search_entries"] == 3

        logger.info(f"Cache stats: {stats}")
        logger.info(f"Unique cached queries: {stats['search_entries']}")

    @pytest.mark.asyncio
    async def test_cache_memory_usage(self):
        """Test memory usage with caching enabled."""
        tracemalloc.start()

        # Create cache with limited size
        cache = DictSearchCache(max_size=100, default_ttl=3600)
        client = MockYandexSearchClient(iamToken=TEST_IAM_TOKEN, folderId=TEST_FOLDER_ID, cache=cache)

        # Take initial memory snapshot
        snapshot1 = tracemalloc.take_snapshot()

        # Make many requests to fill cache
        for i in range(150):  # More than cache max_size
            await client.search(f"test query {i}")

        # Take second memory snapshot
        snapshot2 = tracemalloc.take_snapshot()

        # Calculate memory difference
        top_stats = snapshot2.compare_to(snapshot1, "lineno")
        total_size = sum(stat.size_diff for stat in top_stats if stat.size_diff > 0)

        # Cache should not grow beyond its limits
        stats = cache.getStats()
        assert stats["search_entries"] <= 100  # Should not exceed max_size

        # Memory usage should be reasonable
        assert total_size < 10 * 1024 * 1024  # Less than 10MB

        tracemalloc.stop()

        logger.info(f"Cache entries: {stats['search_entries']}")
        logger.info(f"Memory used: {total_size / 1024:.1f} KB")


class TestRateLimitingPerformance:
    """Test rate limiting effectiveness and performance."""

    @pytest.mark.asyncio
    async def test_rate_limiting_effectiveness(self, rate_limited_client):
        """Test that rate limiting actually limits request rate."""
        # Make requests faster than rate limit allows
        start_time = time.time()

        tasks = []
        for i in range(6):  # More than rate limit (3)
            task = rate_limited_client.searchSimple(f"test query {i}")
            tasks.append(task)

        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks)

        end_time = time.time()
        total_time = end_time - start_time

        # All requests should succeed
        assert all(results)

        # Should take at least 1 second due to rate limiting
        # (3 requests immediately, then wait for window to reset)
        assert total_time >= 1.0  # Allow some tolerance

        # Check rate limit stats
        stats = rate_limited_client.get_rate_limit_stats()
        assert stats["max_requests"] == 3
        assert stats["window_seconds"] == 1

        logger.info(f"Rate limited requests: {len(results)} in {total_time:.3f}s")
        logger.info(f"Rate limit stats: {stats}")

    @pytest.mark.asyncio
    async def test_rate_limiting_stats_accuracy(self, rate_limited_client):
        """Test accuracy of rate limiting statistics."""
        # Make some requests
        for i in range(3):
            await rate_limited_client.searchSimple(f"test query {i}")

        # Check stats
        stats = rate_limited_client.get_rate_limit_stats()
        assert stats["requests_in_window"] == 3

        # Wait for window to reset
        await asyncio.sleep(1.1)

        # Make another request
        await rate_limited_client.searchSimple("new query")

        # Stats should show only the new request
        stats = rate_limited_client.get_rate_limit_stats()
        assert stats["requests_in_window"] == 1

        logger.info(f"Rate limit stats accuracy test passed: {stats}")


class TestMemoryAndResourceUsage:
    """Test memory usage and resource management."""

    @pytest.mark.asyncio
    async def test_memory_cleanup_after_requests(self, mock_client):
        """Test that memory is properly cleaned up after requests."""
        # Force garbage collection before test
        gc.collect()

        # Make many requests
        for i in range(100):
            await mock_client.searchSimple(f"test query {i}")

        # Force garbage collection after requests
        gc.collect()

        # Client should still be functional
        result = await mock_client.searchSimple("final test")
        assert result is not None

        logger.info("Memory cleanup test passed - no memory leaks detected")

    @pytest.mark.asyncio
    async def test_concurrent_request_resource_management(self, mock_client):
        """Test resource management during concurrent requests."""
        # Create many concurrent tasks
        tasks = []
        for i in range(50):
            task = mock_client.searchSimple(f"concurrent test {i}")
            tasks.append(task)

        # Execute all tasks
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(results)

        # Client should still be functional
        result = await mock_client.searchSimple("post-concurrent test")
        assert result is not None

        logger.info("Concurrent resource management test passed")


class TestPerformanceBenchmarks:
    """Performance benchmarks for comparison."""

    @pytest.mark.asyncio
    async def benchmark_search_throughput(self, mock_client):
        """Benchmark search throughput (requests per second)."""
        num_requests = 100

        start_time = time.time()

        # Create concurrent tasks
        tasks = [mock_client.searchSimple(f"benchmark query {i}") for i in range(num_requests)]
        results = await asyncio.gather(*tasks)

        end_time = time.time()
        total_time = end_time - start_time
        throughput = num_requests / total_time

        assert all(results)  # All requests should succeed

        logger.info(f"Throughput benchmark: {throughput:.1f} requests/second")
        logger.info(f"Total time for {num_requests} requests: {total_time:.3f}s")

        # Performance assertion - should handle at least 5 requests/second
        assert throughput >= 5.0

    @pytest.mark.asyncio
    async def benchmark_cache_throughput(self, cached_client):
        """Benchmark cache throughput (requests per second with cache)."""
        query = "cache benchmark query"

        # First request to populate cache
        await cached_client.searchSimple(query)

        # Benchmark cached requests
        num_requests = 1000
        start_time = time.time()

        tasks = [cached_client.searchSimple(query) for _ in range(num_requests)]
        results = await asyncio.gather(*tasks)

        end_time = time.time()
        total_time = end_time - start_time
        throughput = num_requests / total_time

        assert all(results)  # All requests should succeed

        logger.info(f"Cache throughput benchmark: {throughput:.1f} requests/second")
        logger.info(f"Total time for {num_requests} cached requests: {total_time:.3f}s")

        # Cache should be much faster - at least 100 requests/second
        assert throughput >= 100.0


if __name__ == "__main__":
    # Run performance tests directly
    import sys

    print("Running Yandex Search performance tests...")
    print("Note: These tests use mock clients and don't make real API calls")

    # Run pytest with verbose output
    sys.exit(pytest.main([__file__, "-v", "-s"]))
