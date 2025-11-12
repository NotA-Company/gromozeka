"""
Integration tests for rate limiter library.

This module contains comprehensive integration tests that verify the complete
workflow of the rate limiter library, including real-world usage scenarios,
multiple limiter coordination, and end-to-end functionality.
"""

import asyncio
import time
import unittest

from .manager import RateLimiterManager
from .sliding_window import QueueConfig, SlidingWindowRateLimiter


class TestRateLimiterIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests for complete rate limiter workflow."""

    async def asyncSetUp(self):
        """Set up test fixtures."""
        # Get clean manager instance
        self.manager = RateLimiterManager.getInstance()
        await self.manager.destroy()

    async def asyncTearDown(self):
        """Clean up after tests."""
        await self.manager.destroy()

    async def testCompleteWorkflow(self):
        """Test complete workflow: setup, bind queues, use them."""
        # Create different rate limiters for different purposes
        api_limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=5, windowSeconds=2))
        db_limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=10, windowSeconds=2))

        # Initialize limiters
        await api_limiter.initialize()
        await db_limiter.initialize()

        try:
            # Register with manager
            self.manager.registerRateLimiter("api", api_limiter)
            self.manager.registerRateLimiter("database", db_limiter)

            # Set default limiter
            self.manager.setDefaultLimiter("api")

            # Bind queues to specific limiters
            self.manager.bindQueue("yandex_search", "api")
            self.manager.bindQueue("openweather", "api")
            self.manager.bindQueue("postgres_queries", "database")
            self.manager.bindQueue("redis_queries", "database")

            # Verify setup
            self.assertEqual(set(self.manager.listRateLimiters()), {"api", "database"})
            self.assertEqual(self.manager.getDefaultLimiter(), "api")

            mappings = self.manager.getQueueMappings()
            self.assertEqual(mappings["yandex_search"], "api")
            self.assertEqual(mappings["postgres_queries"], "database")

            # Test rate limiting through manager
            start_time = time.time()

            # Make API calls (should be rate limited by api limiter)
            for i in range(6):  # Exceeds api limit of 5
                await self.manager.applyLimit("yandex_search")

            api_elapsed = time.time() - start_time
            self.assertGreaterEqual(api_elapsed, 1.5)  # Should be delayed

            # Database calls should still work immediately
            start_time = time.time()
            for i in range(3):
                await self.manager.applyLimit("postgres_queries")

            db_elapsed = time.time() - start_time
            self.assertLess(db_elapsed, 0.1)  # Should be immediate

            # Test unmapped queue uses default
            start_time = time.time()
            await self.manager.applyLimit("unknown_queue")
            default_elapsed = time.time() - start_time
            self.assertLess(default_elapsed, 0.1)  # Should be immediate

        finally:
            await api_limiter.destroy()
            await db_limiter.destroy()

    async def testDifferentRateLimitsForDifferentQueues(self):
        """Test different rate limits for different queues."""
        # Create limiters with different configurations
        strict_limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=2, windowSeconds=1))
        lenient_limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=10, windowSeconds=1))

        await strict_limiter.initialize()
        await lenient_limiter.initialize()

        try:
            self.manager.registerRateLimiter("strict", strict_limiter)
            self.manager.registerRateLimiter("lenient", lenient_limiter)

            self.manager.bindQueue("critical_api", "strict")
            self.manager.bindQueue("bulk_processing", "lenient")

            # Test strict limiter
            start_time = time.time()
            for i in range(3):  # Exceeds limit of 2
                await self.manager.applyLimit("critical_api")
            strict_elapsed = time.time() - start_time

            # Test lenient limiter
            start_time = time.time()
            for i in range(3):  # Within limit of 10
                await self.manager.applyLimit("bulk_processing")
            lenient_elapsed = time.time() - start_time

            # Strict should be delayed, lenient should be immediate
            self.assertGreater(strict_elapsed, lenient_elapsed)
            self.assertGreaterEqual(strict_elapsed, 0.8)
            self.assertLess(lenient_elapsed, 0.1)

        finally:
            await strict_limiter.destroy()
            await lenient_limiter.destroy()

    async def testConcurrentUsageAcrossMultipleQueues(self):
        """Test concurrent usage across multiple queues."""
        # Create multiple limiters
        limiter1 = SlidingWindowRateLimiter(QueueConfig(maxRequests=3, windowSeconds=2))
        limiter2 = SlidingWindowRateLimiter(QueueConfig(maxRequests=3, windowSeconds=2))
        limiter3 = SlidingWindowRateLimiter(QueueConfig(maxRequests=3, windowSeconds=2))

        await limiter1.initialize()
        await limiter2.initialize()
        await limiter3.initialize()

        try:
            self.manager.registerRateLimiter("service1", limiter1)
            self.manager.registerRateLimiter("service2", limiter2)
            self.manager.registerRateLimiter("service3", limiter3)

            self.manager.bindQueue("queue1", "service1")
            self.manager.bindQueue("queue2", "service2")
            self.manager.bindQueue("queue3", "service3")

            async def make_requests(queue_name, count):
                """Helper to make multiple requests."""
                for i in range(count):
                    await self.manager.applyLimit(queue_name)

            # Run concurrent requests across different queues
            tasks = [
                make_requests("queue1", 5),
                make_requests("queue2", 5),
                make_requests("queue3", 5),
            ]

            start_time = time.time()
            await asyncio.gather(*tasks)
            total_elapsed = time.time() - start_time

            # Should complete in reasonable time (parallel processing)
            self.assertLess(total_elapsed, 5.0)
            self.assertGreater(total_elapsed, 2.0)  # Some rate limiting expected

        finally:
            await limiter1.destroy()
            await limiter2.destroy()
            await limiter3.destroy()

    async def testStatisticsTrackingAcrossMultipleLimiters(self):
        """Test statistics tracking across multiple limiters."""
        limiter1 = SlidingWindowRateLimiter(QueueConfig(maxRequests=5, windowSeconds=10))
        limiter2 = SlidingWindowRateLimiter(QueueConfig(maxRequests=10, windowSeconds=10))

        await limiter1.initialize()
        await limiter2.initialize()

        try:
            self.manager.registerRateLimiter("service1", limiter1)
            self.manager.registerRateLimiter("service2", limiter2)

            self.manager.bindQueue("api_calls", "service1")
            self.manager.bindQueue("background_jobs", "service2")

            # Make requests to different queues
            for i in range(3):
                await self.manager.applyLimit("api_calls")

            for i in range(5):
                await self.manager.applyLimit("background_jobs")

            # Check statistics
            api_stats = self.manager.getStats("api_calls")
            bg_stats = self.manager.getStats("background_jobs")

            self.assertEqual(api_stats["requestsInWindow"], 3)
            self.assertEqual(api_stats["maxRequests"], 5)
            self.assertAlmostEqual(api_stats["utilizationPercent"], 60.0, places=1)

            self.assertEqual(bg_stats["requestsInWindow"], 5)
            self.assertEqual(bg_stats["maxRequests"], 10)
            self.assertAlmostEqual(bg_stats["utilizationPercent"], 50.0, places=1)

        finally:
            await limiter1.destroy()
            await limiter2.destroy()

    async def testCleanupAndReinitialization(self):
        """Test cleanup and reinitialization of the entire system."""
        # Create and setup limiters
        limiter1 = SlidingWindowRateLimiter(QueueConfig(maxRequests=3, windowSeconds=1))
        limiter2 = SlidingWindowRateLimiter(QueueConfig(maxRequests=3, windowSeconds=1))

        await limiter1.initialize()
        await limiter2.initialize()

        self.manager.registerRateLimiter("service1", limiter1)
        self.manager.registerRateLimiter("service2", limiter2)

        self.manager.bindQueue("queue1", "service1")
        self.manager.bindQueue("queue2", "service2")

        # Verify setup
        self.assertEqual(len(self.manager.listRateLimiters()), 2)
        self.assertEqual(len(self.manager.getQueueMappings()), 2)

        # Make some requests
        await self.manager.applyLimit("queue1")
        await self.manager.applyLimit("queue2")

        # Destroy everything
        await self.manager.destroy()

        # Verify cleanup
        self.assertEqual(len(self.manager.listRateLimiters()), 0)
        self.assertEqual(len(self.manager.getQueueMappings()), 0)
        self.assertIsNone(self.manager.getDefaultLimiter())

        # Reinitialize with new limiters
        new_limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=5, windowSeconds=2))
        await new_limiter.initialize()

        self.manager.registerRateLimiter("new_service", new_limiter)
        self.manager.bindQueue("new_queue", "new_service")

        # Should work with new setup
        await self.manager.applyLimit("new_queue")

        stats = self.manager.getStats("new_queue")
        self.assertEqual(stats["requestsInWindow"], 1)
        self.assertEqual(stats["maxRequests"], 5)

        await new_limiter.destroy()

    async def testRealWorldScenarioYandexSearchClient(self):
        """Test real-world scenario similar to YandexSearchClient usage."""
        # Simulate YandexSearchClient rate limiting setup
        search_limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=20, windowSeconds=60))
        cache_limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=100, windowSeconds=60))

        await search_limiter.initialize()
        await cache_limiter.initialize()

        try:
            self.manager.registerRateLimiter("yandex_search", search_limiter)
            self.manager.registerRateLimiter("cache_operations", cache_limiter)

            # Set search as default for unmapped operations
            self.manager.setDefaultLimiter("yandex_search")

            # Bind specific queues
            self.manager.bindQueue("search_requests", "yandex_search")
            self.manager.bindQueue("cache_get", "cache_operations")
            self.manager.bindQueue("cache_set", "cache_operations")

            # Simulate search operations
            start_time = time.time()

            # Make search requests (should be rate limited)
            for i in range(25):  # Exceeds search limit
                await self.manager.applyLimit("search_requests")

            search_elapsed = time.time() - start_time
            self.assertGreaterEqual(search_elapsed, 30.0)  # Should be significantly delayed

            # Cache operations should still be fast
            start_time = time.time()
            for i in range(50):  # Within cache limit
                await self.manager.applyLimit("cache_get")
                await self.manager.applyLimit("cache_set")

            cache_elapsed = time.time() - start_time
            self.assertLess(cache_elapsed, 1.0)  # Should be immediate

            # Default operations should use search limiter
            start_time = time.time()
            await self.manager.applyLimit("default_search")
            default_elapsed = time.time() - start_time
            self.assertLess(default_elapsed, 0.1)  # First request should be immediate

        finally:
            await search_limiter.destroy()
            await cache_limiter.destroy()

    async def testHighConcurrencyScenario(self):
        """Test high concurrency scenario with many queues and limiters."""
        # Create multiple limiters
        limiters = []
        for i in range(5):
            limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=5, windowSeconds=2))
            await limiter.initialize()
            limiters.append(limiter)
            self.manager.registerRateLimiter(f"service_{i}", limiter)

        try:
            # Create multiple queues per service
            queue_count = 0
            for i in range(5):
                for j in range(3):
                    queue_name = f"queue_{queue_count}"
                    self.manager.bindQueue(queue_name, f"service_{i}")
                    queue_count += 1

            async def burst_requests(queue_name, count):
                """Make burst of requests to a queue."""
                for _ in range(count):
                    await self.manager.applyLimit(queue_name)

            # Create high concurrency scenario
            tasks = []
            for i in range(queue_count):
                tasks.append(burst_requests(f"queue_{i}", 8))  # Exceeds limits

            start_time = time.time()
            await asyncio.gather(*tasks)
            total_elapsed = time.time() - start_time

            # Should complete but with rate limiting delays
            self.assertGreater(total_elapsed, 2.0)  # Should have some delays
            self.assertLess(total_elapsed, 10.0)  # But not too long

            # Verify all limiters were used
            for limiter in limiters:
                queues = limiter.listQueues()
                self.assertGreater(len(queues), 0)

        finally:
            for limiter in limiters:
                await limiter.destroy()

    async def testDynamicQueueAndLimiterManagement(self):
        """Test dynamic addition and removal of queues and limiters."""
        # Start with one limiter
        limiter1 = SlidingWindowRateLimiter(QueueConfig(maxRequests=3, windowSeconds=2))
        await limiter1.initialize()

        self.manager.registerRateLimiter("initial", limiter1)
        self.manager.bindQueue("initial_queue", "initial")

        # Use initial setup
        await self.manager.applyLimit("initial_queue")
        stats = self.manager.getStats("initial_queue")
        self.assertEqual(stats["requestsInWindow"], 1)

        # Add new limiter dynamically
        limiter2 = SlidingWindowRateLimiter(QueueConfig(maxRequests=5, windowSeconds=2))
        await limiter2.initialize()

        self.manager.registerRateLimiter("added", limiter2)
        self.manager.bindQueue("added_queue", "added")

        # Use new limiter
        await self.manager.applyLimit("added_queue")
        stats = self.manager.getStats("added_queue")
        self.assertEqual(stats["requestsInWindow"], 1)

        # Rebind queue to different limiter
        self.manager.bindQueue("initial_queue", "added")
        await self.manager.applyLimit("initial_queue")

        # Should now use added limiter
        added_stats = self.manager.getStats("initial_queue")
        self.assertEqual(added_stats["maxRequests"], 5)  # From added limiter

        await limiter1.destroy()
        await limiter2.destroy()

    async def testErrorRecoveryScenario(self):
        """Test error recovery and system resilience."""
        limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=3, windowSeconds=1))
        await limiter.initialize()

        self.manager.registerRateLimiter("resilient", limiter)
        self.manager.bindQueue("test_queue", "resilient")

        # Normal operation
        await self.manager.applyLimit("test_queue")
        stats = self.manager.getStats("test_queue")
        self.assertEqual(stats["requestsInWindow"], 1)

        # Simulate limiter destruction (external error)
        await limiter.destroy()

        # Re-initialize and continue
        await limiter.initialize()

        # Should continue working
        await self.manager.applyLimit("test_queue")
        stats = self.manager.getStats("test_queue")
        self.assertEqual(stats["requestsInWindow"], 1)  # Reset after destroy

        await limiter.destroy()

    async def testPerformanceWithManyOperations(self):
        """Test performance with many rate limiting operations."""
        limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=100, windowSeconds=5))
        await limiter.initialize()

        self.manager.registerRateLimiter("performance", limiter)
        self.manager.bindQueue("perf_queue", "performance")

        # Make many requests within limits
        start_time = time.time()

        for i in range(50):  # Within limit of 100
            await self.manager.applyLimit("perf_queue")

        elapsed = time.time() - start_time

        # Should complete quickly
        self.assertLess(elapsed, 1.0)

        # Verify statistics
        stats = self.manager.getStats("perf_queue")
        self.assertEqual(stats["requestsInWindow"], 50)
        self.assertAlmostEqual(stats["utilizationPercent"], 50.0, places=1)

        await limiter.destroy()


class TestRateLimiterRealWorldScenarios(unittest.IsolatedAsyncioTestCase):
    """Test suite for real-world usage scenarios."""

    async def asyncSetUp(self):
        """Set up test fixtures."""
        self.manager = RateLimiterManager.getInstance()
        await self.manager.destroy()

    async def asyncTearDown(self):
        """Clean up after tests."""
        await self.manager.destroy()

    async def testWebApiRateLimiting(self):
        """Test rate limiting for web API scenarios."""

        # Simulate different API endpoints with different limits
        public_api = SlidingWindowRateLimiter(QueueConfig(maxRequests=10, windowSeconds=60))
        premium_api = SlidingWindowRateLimiter(QueueConfig(maxRequests=100, windowSeconds=60))
        internal_api = SlidingWindowRateLimiter(QueueConfig(maxRequests=1000, windowSeconds=60))

        await public_api.initialize()
        await premium_api.initialize()
        await internal_api.initialize()

        try:
            self.manager.registerRateLimiter("public", public_api)
            self.manager.registerRateLimiter("premium", premium_api)
            self.manager.registerRateLimiter("internal", internal_api)

            self.manager.bindQueue("public_users", "public")
            self.manager.bindQueue("premium_users", "premium")
            self.manager.bindQueue("internal_services", "internal")

            # Test different rate limits
            start_time = time.time()

            # Public API should be rate limited quickly
            for i in range(12):  # Exceeds public limit
                await self.manager.applyLimit("public_users")
            public_elapsed = time.time() - start_time

            # Premium API should allow more requests
            start_time = time.time()
            for i in range(12):  # Within premium limit
                await self.manager.applyLimit("premium_users")
            premium_elapsed = time.time() - start_time

            # Internal API should be very fast
            start_time = time.time()
            for i in range(12):  # Within internal limit
                await self.manager.applyLimit("internal_services")
            internal_elapsed = time.time() - start_time

            # Verify different performance characteristics
            self.assertGreater(public_elapsed, premium_elapsed)
            # Internal and premium should both be fast (within limits), so we just check they're reasonable
            self.assertLess(premium_elapsed, 1.0)
            self.assertLess(internal_elapsed, 1.0)

        finally:
            await public_api.destroy()
            await premium_api.destroy()
            await internal_api.destroy()

    async def testDatabaseConnectionPooling(self):
        """Test rate limiting for database connection pooling."""

        # Simulate database connection limits
        read_connections = SlidingWindowRateLimiter(QueueConfig(maxRequests=50, windowSeconds=1))
        write_connections = SlidingWindowRateLimiter(QueueConfig(maxRequests=10, windowSeconds=1))

        await read_connections.initialize()
        await write_connections.initialize()

        try:
            self.manager.registerRateLimiter("read_db", read_connections)
            self.manager.registerRateLimiter("write_db", write_connections)

            self.manager.bindQueue("select_queries", "read_db")
            self.manager.bindQueue("insert_queries", "write_db")
            self.manager.bindQueue("update_queries", "write_db")

            # Test read vs write limits
            start_time = time.time()

            # Read operations should be fast
            for i in range(30):  # Within read limit
                await self.manager.applyLimit("select_queries")
            read_elapsed = time.time() - start_time

            # Write operations should be slower
            start_time = time.time()
            for i in range(15):  # Exceeds write limit
                await self.manager.applyLimit("insert_queries")
            write_elapsed = time.time() - start_time

            self.assertLess(read_elapsed, write_elapsed)
            self.assertGreaterEqual(write_elapsed, 1.0)  # Should be delayed

        finally:
            await read_connections.destroy()
            await write_connections.destroy()


if __name__ == "__main__":
    unittest.main()
