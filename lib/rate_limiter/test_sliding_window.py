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
    """Test suite for QueueConfig dataclass validation.

    This test class validates the QueueConfig dataclass behavior, including:
    - Valid configuration creation
    - Validation of maxRequests parameter
    - Validation of windowSeconds parameter
    - Boundary value handling
    """

    def testValidConfig(self) -> None:
        """Test QueueConfig creation with valid parameters.

        Verifies that QueueConfig can be instantiated with valid maxRequests
        and windowSeconds values.
        """
        config = QueueConfig(maxRequests=10, windowSeconds=60)
        self.assertEqual(config.maxRequests, 10)
        self.assertEqual(config.windowSeconds, 60)

    def testInvalidMaxRequests(self) -> None:
        """Test QueueConfig validation rejects non-positive maxRequests.

        Verifies that QueueConfig raises ValueError when maxRequests is
        zero or negative.

        Raises:
            AssertionError: If validation does not raise ValueError for
                invalid maxRequests values.
        """
        with self.assertRaises(ValueError) as context:
            QueueConfig(maxRequests=0, windowSeconds=60)
        self.assertIn("maxRequests must be positive", str(context.exception))

        with self.assertRaises(ValueError) as context:
            QueueConfig(maxRequests=-5, windowSeconds=60)
        self.assertIn("maxRequests must be positive", str(context.exception))

    def testInvalidWindowSeconds(self) -> None:
        """Test QueueConfig validation rejects non-positive windowSeconds.

        Verifies that QueueConfig raises ValueError when windowSeconds is
        zero or negative.

        Raises:
            AssertionError: If validation does not raise ValueError for
                invalid windowSeconds values.
        """
        with self.assertRaises(ValueError) as context:
            QueueConfig(maxRequests=10, windowSeconds=0)
        self.assertIn("windowSeconds must be positive", str(context.exception))

        with self.assertRaises(ValueError) as context:
            QueueConfig(maxRequests=10, windowSeconds=-30)
        self.assertIn("windowSeconds must be positive", str(context.exception))

    def testValidBoundaryValues(self) -> None:
        """Test QueueConfig accepts minimum valid values.

        Verifies that QueueConfig can be instantiated with the minimum
        valid values (maxRequests=1, windowSeconds=1).
        """
        config = QueueConfig(maxRequests=1, windowSeconds=1)
        self.assertEqual(config.maxRequests, 1)
        self.assertEqual(config.windowSeconds, 1)


class TestSlidingWindowRateLimiter(unittest.IsolatedAsyncioTestCase):
    """Test cases for SlidingWindowRateLimiter functionality.

    This test class validates the SlidingWindowRateLimiter implementation,
    including:
    - Initialization and destruction
    - Rate limiting behavior
    - Sliding window mechanics
    - Multiple queue management
    - Concurrent access safety
    - Statistics tracking
    - Edge cases and boundary conditions
    """

    def setUp(self) -> None:
        """Set up test fixtures.

        Creates a QueueConfig with maxRequests=3 and windowSeconds=2,
        and instantiates a SlidingWindowRateLimiter for testing.
        """
        self.config = QueueConfig(maxRequests=3, windowSeconds=2)
        self.limiter = SlidingWindowRateLimiter(config=self.config)

    async def asyncSetUp(self) -> None:
        """Async set up for test fixtures.

        Initializes the rate limiter before each test.
        """
        await self.limiter.initialize()

    async def asyncTearDown(self) -> None:
        """Clean up after tests.

        Destroys the rate limiter and releases resources after each test.
        """
        await self.limiter.destroy()

    async def testInitialization(self) -> None:
        """Test limiter initialization.

        Verifies that the limiter can be initialized correctly and that
        double initialization triggers a warning.

        Raises:
            AssertionError: If initialization state is not correctly managed.
        """
        limiter = SlidingWindowRateLimiter(config=self.config)
        self.assertFalse(limiter._initialized)

        await limiter.initialize()
        self.assertTrue(limiter._initialized)

        # Test double initialization warning
        with patch("lib.rate_limiter.sliding_window.logger") as mock_logger:
            await limiter.initialize()
            mock_logger.warning.assert_called_with("SlidingWindowRateLimiter already initialized")

    async def testDestruction(self) -> None:
        """Test limiter cleanup.

        Verifies that the limiter properly cleans up internal state
        including request times and locks when destroyed.

        Raises:
            AssertionError: If cleanup does not properly reset internal state.
        """
        # Add some data first
        self.limiter._ensureQueue("test_queue")
        self.limiter._requestTimes["test_queue"] = [time.time()]
        self.limiter._locks["test_queue"] = asyncio.Lock()

        await self.limiter.destroy()

        self.assertFalse(self.limiter._initialized)
        self.assertEqual(len(self.limiter._requestTimes), 0)
        self.assertEqual(len(self.limiter._locks), 0)

    def testEnsureQueue(self) -> None:
        """Test automatic queue registration.

        Verifies that _ensureQueue creates a new queue with empty request
        times and a lock, and that calling it multiple times does not
        create duplicate locks.

        Raises:
            AssertionError: If queue registration does not work as expected.
        """
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

    async def testApplyLimitBasic(self) -> None:
        """Test basic rate limiting functionality.

        Verifies that requests up to the limit complete quickly without
        rate limiting delays, and that the queue is automatically registered.

        Raises:
            AssertionError: If basic rate limiting does not work correctly.
        """
        start_time = time.time()

        # Make requests up to the limit
        for i in range(3):
            await self.limiter.applyLimit("test_queue")

        # Should complete quickly (no rate limiting yet)
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 0.5)

        # Verify queue was auto-registered
        self.assertIn("test_queue", self.limiter.listQueues())

    async def testRateLimitingEnforcement(self) -> None:
        """Test that rate limiting actually delays requests.

        Verifies that requests exceeding the limit are delayed according
        to the sliding window algorithm.

        Raises:
            AssertionError: If rate limiting does not properly delay requests.
        """
        start_time = time.time()

        # Make requests exceeding the limit
        for i in range(4):  # 4 > maxRequests=3
            await self.limiter.applyLimit("rate_test")

        elapsed = time.time() - start_time

        # Should have taken at least some time due to rate limiting
        self.assertGreaterEqual(elapsed, 1.0)  # Allow some tolerance

    async def testSlidingWindowBehavior(self) -> None:
        """Test that old requests are removed from the sliding window.

        Verifies that requests older than the window duration are removed
        from the sliding window, allowing new requests to proceed without delay.

        Raises:
            AssertionError: If sliding window cleanup does not work correctly.
        """
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

    async def testMultipleQueues(self) -> None:
        """Test rate limiting with multiple independent queues.

        Verifies that different queues operate independently, with rate
        limits applied separately to each queue.

        Raises:
            AssertionError: If multiple queues do not operate independently.
        """
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

    async def testConcurrentAccess(self) -> None:
        """Test thread safety with concurrent access to same queue.

        Verifies that the limiter handles concurrent requests to the same
        queue safely without race conditions.

        Raises:
            AssertionError: If concurrent access causes errors or incorrect behavior.
        """

        async def make_requests(queue_name: str, count: int) -> None:
            """Helper to make multiple requests.

            Args:
                queue_name: Name of the queue to send requests to.
                count: Number of requests to make.
            """
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

    async def testGetStats(self) -> None:
        """Test statistics retrieval.

        Verifies that getStats returns accurate statistics including
        requestsInWindow, maxRequests, windowSeconds, resetTime, and
        utilizationPercent.

        Raises:
            AssertionError: If statistics are not calculated correctly.
        """
        # Make some requests
        for i in range(2):
            await self.limiter.applyLimit("stats_test")

        stats = self.limiter.getStats("stats_test")

        self.assertEqual(stats["requestsInWindow"], 2)
        self.assertEqual(stats["maxRequests"], 3)
        self.assertEqual(stats["windowSeconds"], 2)
        self.assertGreater(stats["resetTime"], time.time())
        self.assertAlmostEqual(stats["utilizationPercent"], 66.67, places=1)

    async def testGetStatsNonExistentQueue(self) -> None:
        """Test getStats raises error for non-existent queue.

        Verifies that getStats raises ValueError when called with a
        queue name that does not exist.

        Raises:
            AssertionError: If ValueError is not raised for non-existent queue.
        """
        with self.assertRaises(ValueError) as context:
            self.limiter.getStats("nonexistent_queue")
        self.assertIn("Queue 'nonexistent_queue' does not exist", str(context.exception))

    async def testGetStatsEmptyQueue(self) -> None:
        """Test getStats for queue with no recent requests.

        Verifies that getStats returns zero values for a queue that
        exists but has no requests in the current window.

        Raises:
            AssertionError: If empty queue statistics are not correct.
        """
        # Create queue but don't make requests
        self.limiter._ensureQueue("empty_test")

        stats = self.limiter.getStats("empty_test")

        self.assertEqual(stats["requestsInWindow"], 0)
        self.assertEqual(stats["utilizationPercent"], 0.0)

    async def testListQueues(self) -> None:
        """Test queue listing functionality.

        Verifies that listQueues returns a list of all registered queues
        without duplicates.

        Raises:
            AssertionError: If queue listing does not work correctly.
        """
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

    async def testZeroRequestsInWindow(self) -> None:
        """Test behavior with zero requests in time window.

        Verifies that statistics correctly report zero requests for a
        queue with no activity.

        Raises:
            AssertionError: If zero request statistics are not correct.
        """
        self.limiter._ensureQueue("zero_test")

        stats = self.limiter.getStats("zero_test")
        self.assertEqual(stats["requestsInWindow"], 0)
        self.assertEqual(stats["utilizationPercent"], 0.0)

    async def testBoundaryConditions(self) -> None:
        """Test boundary conditions and edge cases.

        Verifies that the limiter works correctly with minimum valid
        configuration values (maxRequests=1, windowSeconds=1).

        Raises:
            AssertionError: If boundary conditions are not handled correctly.
        """
        # Test with very small window
        small_config = QueueConfig(maxRequests=1, windowSeconds=1)
        small_limiter = SlidingWindowRateLimiter(config=small_config)
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

    async def testWaitTimeCalculation(self) -> None:
        """Test accurate wait time calculation.

        Verifies that the limiter calculates and applies the correct
        wait time when the rate limit is exceeded.

        Raises:
            AssertionError: If wait time calculation is not accurate.
        """
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

    async def testCleanupAfterWaiting(self) -> None:
        """Test that old requests are cleaned up after waiting.

        Verifies that old requests are removed from the sliding window
        after a rate-limited request completes.

        Raises:
            AssertionError: If cleanup does not work correctly after waiting.
        """
        # Fill up the limit
        for i in range(3):
            await self.limiter.applyLimit("cleanup_test")

        # Make rate-limited request (should trigger cleanup)
        await self.limiter.applyLimit("cleanup_test")

        # Check that only recent requests remain
        stats = self.limiter.getStats("cleanup_test")
        self.assertLessEqual(stats["requestsInWindow"], 3)

    async def testDefaultQueue(self) -> None:
        """Test default queue behavior.

        Verifies that applyLimit() uses the "default" queue when no
        queue name is specified.

        Raises:
            AssertionError: If default queue is not used correctly.
        """
        # Make request without specifying queue
        await self.limiter.applyLimit()

        # Should use "default" queue
        self.assertIn("default", self.limiter.listQueues())
        stats = self.limiter.getStats("default")
        self.assertEqual(stats["requestsInWindow"], 1)

    async def testLargeNumberOfRequests(self) -> None:
        """Test behavior with many requests over time.

        Verifies that the limiter correctly handles a large number of
        requests over an extended period while respecting rate limits.

        Raises:
            AssertionError: If large request volumes are not handled correctly.
        """
        # Make requests over a longer period
        for i in range(10):
            await self.limiter.applyLimit("large_test")
            if i % 3 == 2:  # Every 3rd request, wait a bit
                await asyncio.sleep(0.5)

        # Should complete without errors
        stats = self.limiter.getStats("large_test")
        self.assertLessEqual(stats["requestsInWindow"], 3)  # Should respect limit

    async def testConfigImmutability(self) -> None:
        """Test that config remains immutable after limiter creation.

        Verifies that the configuration values do not change during
        limiter operation.

        Raises:
            AssertionError: If configuration values are modified during operation.
        """
        original_max_requests = self.limiter._config.maxRequests
        original_window_seconds = self.limiter._config.windowSeconds

        # Config should not change during operation
        for i in range(5):
            await self.limiter.applyLimit("immutable_test")

        self.assertEqual(self.limiter._config.maxRequests, original_max_requests)
        self.assertEqual(self.limiter._config.windowSeconds, original_window_seconds)


class TestSlidingWindowRateLimiterErrorHandling(unittest.IsolatedAsyncioTestCase):
    """Test suite for error handling scenarios.

    This test class validates error handling and edge cases in the
    SlidingWindowRateLimiter, including:
    - Uninitialized limiter behavior
    - Destroyed limiter behavior
    - Re-initialization after destruction
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures.

        Creates a SlidingWindowRateLimiter with minimal configuration
        for error handling tests.
        """
        self.limiter = SlidingWindowRateLimiter(config=QueueConfig(maxRequests=1, windowSeconds=1))

    async def asyncTearDown(self) -> None:
        """Clean up after tests.

        Destroys the rate limiter if it was initialized, ensuring
        proper cleanup between tests.
        """
        if hasattr(self.limiter, "_initialized") and self.limiter._initialized:
            await self.limiter.destroy()

    async def testUninitializedLimiter(self) -> None:
        """Test behavior when using uninitialized limiter.

        Verifies that the limiter can still function correctly even
        when used without explicit initialization.

        Raises:
            AssertionError: If uninitialized limiter does not work correctly.
        """
        limiter = SlidingWindowRateLimiter(config=QueueConfig(maxRequests=1, windowSeconds=1))

        # Should still work (initialization is mostly for logging)
        await limiter.applyLimit("test")

        stats = limiter.getStats("test")
        self.assertEqual(stats["requestsInWindow"], 1)

    async def testDestroyedLimiter(self) -> None:
        """Test behavior after limiter destruction.

        Verifies that the limiter can be re-initialized and used after
        being destroyed.

        Raises:
            AssertionError: If re-initialization after destruction does not work.
        """
        limiter = SlidingWindowRateLimiter(config=QueueConfig(maxRequests=1, windowSeconds=1))
        await limiter.initialize()
        await limiter.destroy()

        # Should be able to use again after re-initialization
        await limiter.initialize()
        await limiter.applyLimit("test")

        stats = limiter.getStats("test")
        self.assertEqual(stats["requestsInWindow"], 1)


if __name__ == "__main__":
    unittest.main()
