"""
Tests for SlidingWindowRateLimiter implementation.

This module contains comprehensive unit tests for the SlidingWindowRateLimiter
functionality, covering configuration validation, initialization, rate limiting
behavior, statistics tracking, and edge cases.
"""

import asyncio
import time
import unittest
from unittest.mock import patch

from .sliding_window import QueueConfig, SlidingWindowRateLimiter


class TestQueueConfig(unittest.TestCase):
    """Test suite for QueueConfig dataclass validation."""

    def testValidConfig(self):
        """Test QueueConfig creation with valid parameters."""
        config = QueueConfig(maxRequests=10, windowSeconds=60)
        self.assertEqual(config.maxRequests, 10)
        self.assertEqual(config.windowSeconds, 60)

    def testInvalidMaxRequests(self):
        """Test QueueConfig validation rejects non-positive maxRequests."""
        with self.assertRaises(ValueError) as context:
            QueueConfig(maxRequests=0, windowSeconds=60)
        self.assertIn("maxRequests must be positive", str(context.exception))

        with self.assertRaises(ValueError) as context:
            QueueConfig(maxRequests=-5, windowSeconds=60)
        self.assertIn("maxRequests must be positive", str(context.exception))

    def testInvalidWindowSeconds(self):
        """Test QueueConfig validation rejects non-positive windowSeconds."""
        with self.assertRaises(ValueError) as context:
            QueueConfig(maxRequests=10, windowSeconds=0)
        self.assertIn("windowSeconds must be positive", str(context.exception))

        with self.assertRaises(ValueError) as context:
            QueueConfig(maxRequests=10, windowSeconds=-30)
        self.assertIn("windowSeconds must be positive", str(context.exception))

    def testValidBoundaryValues(self):
        """Test QueueConfig accepts minimum valid values."""
        config = QueueConfig(maxRequests=1, windowSeconds=1)
        self.assertEqual(config.maxRequests, 1)
        self.assertEqual(config.windowSeconds, 1)


class TestSlidingWindowRateLimiter(unittest.IsolatedAsyncioTestCase):
    """Test cases for SlidingWindowRateLimiter functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = QueueConfig(maxRequests=3, windowSeconds=2)
        self.limiter = SlidingWindowRateLimiter(self.config)

    async def asyncSetUp(self):
        """Async set up for test fixtures."""
        await self.limiter.initialize()

    async def asyncTearDown(self):
        """Clean up after tests."""
        await self.limiter.destroy()

    async def testInitialization(self):
        """Test limiter initialization."""
        limiter = SlidingWindowRateLimiter(self.config)
        self.assertFalse(limiter._initialized)

        await limiter.initialize()
        self.assertTrue(limiter._initialized)

        # Test double initialization warning
        with patch("lib.rate_limiter.sliding_window.logger") as mock_logger:
            await limiter.initialize()
            mock_logger.warning.assert_called_with("SlidingWindowRateLimiter already initialized")

    async def testDestruction(self):
        """Test limiter cleanup."""
        # Add some data first
        self.limiter._ensureQueue("test_queue")
        self.limiter._requestTimes["test_queue"] = [time.time()]
        self.limiter._locks["test_queue"] = asyncio.Lock()

        await self.limiter.destroy()

        self.assertFalse(self.limiter._initialized)
        self.assertEqual(len(self.limiter._requestTimes), 0)
        self.assertEqual(len(self.limiter._locks), 0)

    def testEnsureQueue(self):
        """Test automatic queue registration."""
        # Queue should not exist initially
        self.assertNotIn("new_queue", self.limiter._requestTimes)
        self.assertNotIn("new_queue", self.limiter._locks)

        # Ensure queue creates it
        self.limiter._ensureQueue("new_queue")

        self.assertIn("new_queue", self.limiter._requestTimes)
        self.assertIn("new_queue", self.limiter._locks)
        self.assertEqual(self.limiter._requestTimes["new_queue"], [])
        self.assertIsInstance(self.limiter._locks["new_queue"], asyncio.Lock)

        # Calling again should not create duplicates
        original_lock = self.limiter._locks["new_queue"]
        self.limiter._ensureQueue("new_queue")
        self.assertIs(self.limiter._locks["new_queue"], original_lock)

    async def testApplyLimitBasic(self):
        """Test basic rate limiting functionality."""
        start_time = time.time()

        # Make requests up to the limit
        for i in range(3):
            await self.limiter.applyLimit("test_queue")

        # Should complete quickly (no rate limiting yet)
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 0.5)

        # Verify queue was auto-registered
        self.assertIn("test_queue", self.limiter.listQueues())

    async def testRateLimitingEnforcement(self):
        """Test that rate limiting actually delays requests."""
        start_time = time.time()

        # Make requests exceeding the limit
        for i in range(4):  # 4 > maxRequests=3
            await self.limiter.applyLimit("rate_test")

        elapsed = time.time() - start_time

        # Should have taken at least some time due to rate limiting
        self.assertGreaterEqual(elapsed, 1.0)  # Allow some tolerance

    async def testSlidingWindowBehavior(self):
        """Test that old requests are removed from the sliding window."""
        # Make requests up to the limit
        for i in range(3):
            await self.limiter.applyLimit("sliding_test")

        # Wait for window to slide (requests to expire)
        await asyncio.sleep(2.1)  # windowSeconds=2

        # Should be able to make requests again without delay
        start_time = time.time()
        await self.limiter.applyLimit("sliding_test")
        elapsed = time.time() - start_time

        self.assertLess(elapsed, 0.1)  # Should be immediate

    async def testMultipleQueues(self):
        """Test rate limiting with multiple independent queues."""
        start_time = time.time()

        # Fill up first queue
        for i in range(3):
            await self.limiter.applyLimit("queue1")

        # Second queue should still work immediately
        await self.limiter.applyLimit("queue2")

        elapsed = time.time() - start_time
        self.assertLess(elapsed, 0.5)  # Should be fast

        # But queue1 should now be rate limited
        start_time = time.time()
        await self.limiter.applyLimit("queue1")
        elapsed = time.time() - start_time
        self.assertGreaterEqual(elapsed, 1.0)

    async def testConcurrentAccess(self):
        """Test thread safety with concurrent access to same queue."""

        async def make_requests(queue_name, count):
            """Helper to make multiple requests."""
            for i in range(count):
                await self.limiter.applyLimit(queue_name)

        # Run concurrent tasks on the same queue
        tasks = [
            make_requests("concurrent_test", 2),
            make_requests("concurrent_test", 2),
        ]

        start_time = time.time()
        await asyncio.gather(*tasks)
        elapsed = time.time() - start_time

        # Should complete without errors and respect rate limits
        self.assertGreaterEqual(elapsed, 1.0)  # Some delay expected

    async def testGetStats(self):
        """Test statistics retrieval."""
        # Make some requests
        for i in range(2):
            await self.limiter.applyLimit("stats_test")

        stats = self.limiter.getStats("stats_test")

        self.assertEqual(stats["requestsInWindow"], 2)
        self.assertEqual(stats["maxRequests"], 3)
        self.assertEqual(stats["windowSeconds"], 2)
        self.assertGreater(stats["resetTime"], time.time())
        self.assertAlmostEqual(stats["utilizationPercent"], 66.67, places=1)

    async def testGetStatsNonExistentQueue(self):
        """Test getStats raises error for non-existent queue."""
        with self.assertRaises(ValueError) as context:
            self.limiter.getStats("nonexistent_queue")
        self.assertIn("Queue 'nonexistent_queue' does not exist", str(context.exception))

    async def testGetStatsEmptyQueue(self):
        """Test getStats for queue with no recent requests."""
        # Create queue but don't make requests
        self.limiter._ensureQueue("empty_test")

        stats = self.limiter.getStats("empty_test")

        self.assertEqual(stats["requestsInWindow"], 0)
        self.assertEqual(stats["utilizationPercent"], 0.0)

    async def testListQueues(self):
        """Test queue listing functionality."""
        # Initially should be empty
        self.assertEqual(self.limiter.listQueues(), [])

        # Make requests to different queues
        await self.limiter.applyLimit("queue1")
        await self.limiter.applyLimit("queue2")
        await self.limiter.applyLimit("queue1")  # Duplicate

        queues = self.limiter.listQueues()
        self.assertEqual(len(queues), 2)
        self.assertIn("queue1", queues)
        self.assertIn("queue2", queues)

    async def testZeroRequestsInWindow(self):
        """Test behavior with zero requests in time window."""
        self.limiter._ensureQueue("zero_test")

        stats = self.limiter.getStats("zero_test")
        self.assertEqual(stats["requestsInWindow"], 0)
        self.assertEqual(stats["utilizationPercent"], 0.0)

    async def testBoundaryConditions(self):
        """Test boundary conditions and edge cases."""
        # Test with very small window
        small_config = QueueConfig(maxRequests=1, windowSeconds=1)
        small_limiter = SlidingWindowRateLimiter(small_config)
        await small_limiter.initialize()

        try:
            # Make request
            await small_limiter.applyLimit("boundary_test")

            # Second request should be delayed
            start_time = time.time()
            await small_limiter.applyLimit("boundary_test")
            elapsed = time.time() - start_time
            self.assertGreaterEqual(elapsed, 0.8)  # Allow some tolerance
        finally:
            await small_limiter.destroy()

    async def testWaitTimeCalculation(self):
        """Test accurate wait time calculation."""
        # Fill up the limit
        for i in range(3):
            await self.limiter.applyLimit("wait_test")

        # Record time before rate-limited request
        start_time = time.time()
        await self.limiter.applyLimit("wait_test")
        elapsed = time.time() - start_time

        # Should wait approximately the remaining time in window
        self.assertGreaterEqual(elapsed, 1.5)  # Should be close to window duration
        self.assertLess(elapsed, 2.5)  # But not too long

    async def testCleanupAfterWaiting(self):
        """Test that old requests are cleaned up after waiting."""
        # Fill up the limit
        for i in range(3):
            await self.limiter.applyLimit("cleanup_test")

        # Make rate-limited request (should trigger cleanup)
        await self.limiter.applyLimit("cleanup_test")

        # Check that only recent requests remain
        stats = self.limiter.getStats("cleanup_test")
        self.assertLessEqual(stats["requestsInWindow"], 3)

    async def testDefaultQueue(self):
        """Test default queue behavior."""
        # Make request without specifying queue
        await self.limiter.applyLimit()

        # Should use "default" queue
        self.assertIn("default", self.limiter.listQueues())
        stats = self.limiter.getStats("default")
        self.assertEqual(stats["requestsInWindow"], 1)

    async def testLargeNumberOfRequests(self):
        """Test behavior with many requests over time."""
        # Make requests over a longer period
        for i in range(10):
            await self.limiter.applyLimit("large_test")
            if i % 3 == 2:  # Every 3rd request, wait a bit
                await asyncio.sleep(0.5)

        # Should complete without errors
        stats = self.limiter.getStats("large_test")
        self.assertLessEqual(stats["requestsInWindow"], 3)  # Should respect limit

    async def testConfigImmutability(self):
        """Test that config remains immutable after limiter creation."""
        original_max_requests = self.limiter._config.maxRequests
        original_window_seconds = self.limiter._config.windowSeconds

        # Config should not change during operation
        for i in range(5):
            await self.limiter.applyLimit("immutable_test")

        self.assertEqual(self.limiter._config.maxRequests, original_max_requests)
        self.assertEqual(self.limiter._config.windowSeconds, original_window_seconds)


class TestSlidingWindowRateLimiterErrorHandling(unittest.IsolatedAsyncioTestCase):
    """Test suite for error handling scenarios."""

    async def asyncSetUp(self):
        """Set up test fixtures."""
        self.limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=1, windowSeconds=1))

    async def asyncTearDown(self):
        """Clean up after tests."""
        if hasattr(self.limiter, "_initialized") and self.limiter._initialized:
            await self.limiter.destroy()

    async def testUninitializedLimiter(self):
        """Test behavior when using uninitialized limiter."""
        limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=1, windowSeconds=1))

        # Should still work (initialization is mostly for logging)
        await limiter.applyLimit("test")

        stats = limiter.getStats("test")
        self.assertEqual(stats["requestsInWindow"], 1)

    async def testDestroyedLimiter(self):
        """Test behavior after limiter destruction."""
        limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=1, windowSeconds=1))
        await limiter.initialize()
        await limiter.destroy()

        # Should be able to use again after re-initialization
        await limiter.initialize()
        await limiter.applyLimit("test")

        stats = limiter.getStats("test")
        self.assertEqual(stats["requestsInWindow"], 1)


if __name__ == "__main__":
    unittest.main()
