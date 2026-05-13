"""
Tests for RateLimiterManager implementation.

This module contains comprehensive unit tests for the RateLimiterManager
functionality, covering singleton pattern, rate limiter registration,
queue mapping, and error handling scenarios.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from .interface import RateLimiterInterface
from .manager import RateLimiterManager
from .sliding_window import QueueConfig, SlidingWindowRateLimiter


class MockRateLimiter(RateLimiterInterface):
    """Mock rate limiter for testing RateLimiterManager.

    This class provides a mock implementation of RateLimiterInterface
    for testing purposes. It tracks initialization, destruction, and
    limit application without actual rate limiting logic.

    Attributes:
        initialized: Flag indicating if the limiter has been initialized.
        destroyed: Flag indicating if the limiter has been destroyed.
        applied_limits: List of queue names where limits were applied.
        stats: Dictionary mapping queue names to their statistics.
    """

    def __init__(self) -> None:
        """Initialize the mock rate limiter."""
        self.initialized = False
        self.destroyed = False
        self.applied_limits = []
        self.stats = {}

    async def initialize(self) -> None:
        """Initialize the mock rate limiter.

        Sets the initialized flag to True.
        """
        self.initialized = True

    async def destroy(self) -> None:
        """Destroy the mock rate limiter.

        Sets the destroyed flag to True.
        """
        self.destroyed = True

    async def applyLimit(self, queue: str = "default") -> None:
        """Apply rate limit for a queue.

        Args:
            queue: The queue name to apply the limit for. Defaults to "default".
        """
        self.applied_limits.append(queue)

    def getStats(self, queue: str = "default") -> dict:
        """Get statistics for a queue.

        Args:
            queue: The queue name to get statistics for. Defaults to "default".

        Returns:
            Dictionary containing queue statistics including requestsInWindow,
            maxRequests, windowSeconds, resetTime, and utilizationPercent.
        """
        if queue not in self.stats:
            self.stats[queue] = {
                "requestsInWindow": 0,
                "maxRequests": 10,
                "windowSeconds": 60,
                "resetTime": 0,
                "utilizationPercent": 0.0,
            }
        return self.stats[queue]

    def listQueues(self) -> list:
        """List all queues with statistics.

        Returns:
            List of queue names that have statistics.
        """
        return list(self.stats.keys())


class TestRateLimiterManagerSingleton(unittest.TestCase):
    """Test suite for RateLimiterManager singleton pattern.

    This test class verifies that the RateLimiterManager implements the
    singleton pattern correctly, ensuring that only one instance exists
    throughout the application lifecycle and that the pattern is thread-safe.
    """

    def testSingletonPattern(self) -> None:
        """Test that getInstance returns the same instance.

        Verifies that calling getInstance multiple times returns the same
        object instance, and that direct instantiation also returns the
        same singleton instance.
        """
        manager1 = RateLimiterManager.getInstance()
        manager2 = RateLimiterManager.getInstance()
        manager3 = RateLimiterManager()

        self.assertIs(manager1, manager2)
        self.assertIs(manager1, manager3)

    def testThreadSafety(self) -> None:
        """Test singleton pattern is thread-safe.

        Verifies that multiple threads calling getInstance simultaneously
        all receive the same instance, ensuring thread-safe singleton
        initialization.
        """
        import threading

        instances = []

        def get_instance() -> None:
            instances.append(RateLimiterManager.getInstance())

        # Create multiple threads
        threads = [threading.Thread(target=get_instance) for _ in range(10)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All instances should be the same
        first_instance = instances[0]
        for instance in instances[1:]:
            self.assertIs(instance, first_instance)

    def testInitializationOnlyOnce(self) -> None:
        """Test that initialization only happens once.

        Verifies that the singleton instance is initialized only once,
        regardless of how many times getInstance is called.
        """
        manager1 = RateLimiterManager.getInstance()
        manager2 = RateLimiterManager.getInstance()

        # Both should have the initialized flag
        self.assertTrue(hasattr(manager1, "initialized"))
        self.assertTrue(hasattr(manager2, "initialized"))
        self.assertTrue(manager1.initialized)
        self.assertTrue(manager2.initialized)


class TestRateLimiterManager(unittest.IsolatedAsyncioTestCase):
    """Test cases for RateLimiterManager functionality.

    This test class comprehensively tests the RateLimiterManager's core
    functionality including rate limiter registration, queue mapping,
    default limiter management, statistics retrieval, and cleanup operations.
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures.

        Initializes a fresh RateLimiterManager instance, cleans up any
        existing state, and creates mock and real rate limiter instances
        for testing.
        """
        # Get fresh manager instance
        self.manager = RateLimiterManager.getInstance()

        # Clean up any existing state
        await self.manager.destroy()

        # Create mock limiters
        self.mockLimiter1 = MockRateLimiter()
        self.mockLimiter2 = MockRateLimiter()
        self.realLimiter1 = SlidingWindowRateLimiter(config=QueueConfig(maxRequests=5, windowSeconds=2))
        self.realLimiter2 = SlidingWindowRateLimiter(config=QueueConfig(maxRequests=10, windowSeconds=2))

    async def asyncTearDown(self) -> None:
        """Clean up after tests.

        Destroys the manager instance to ensure clean state between tests.
        """
        await self.manager.destroy()

    async def testRegisterRateLimiter(self) -> None:
        """Test rate limiter registration.

        Verifies that rate limiters can be registered with unique names,
        the first registered limiter becomes the default, and subsequent
        registrations do not change the default.
        """
        # Register first limiter
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)

        self.assertIn("limiter1", self.manager.listRateLimiters())
        self.assertEqual(self.manager.getDefaultLimiter(), "limiter1")

        # Register second limiter
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        self.assertIn("limiter2", self.manager.listRateLimiters())
        # Default should still be the first one
        self.assertEqual(self.manager.getDefaultLimiter(), "limiter1")

    def testRegisterDuplicateLimiter(self) -> None:
        """Test error when registering duplicate limiter name.

        Verifies that attempting to register a limiter with a name that
        is already in use raises a ValueError with an appropriate message.
        """
        self.manager.registerRateLimiter("duplicate", self.mockLimiter1)

        with self.assertRaises(ValueError) as context:
            self.manager.registerRateLimiter("duplicate", self.mockLimiter2)

        self.assertIn("already registered", str(context.exception))

    async def testSetAndGetDefaultLimiter(self) -> None:
        """Test setting and getting default limiter.

        Verifies that the default limiter can be changed to any registered
        limiter and that the change is reflected correctly.
        """
        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Change default
        self.manager.setDefaultLimiter("limiter2")
        self.assertEqual(self.manager.getDefaultLimiter(), "limiter2")

        # Set to first limiter
        self.manager.setDefaultLimiter("limiter1")
        self.assertEqual(self.manager.getDefaultLimiter(), "limiter1")

    def testSetDefaultNonExistentLimiter(self) -> None:
        """Test error when setting non-existent limiter as default.

        Verifies that attempting to set a non-registered limiter as the
        default raises a ValueError with an appropriate message.
        """
        with self.assertRaises(ValueError) as context:
            self.manager.setDefaultLimiter("nonexistent")

        self.assertIn("not registered", str(context.exception))

    async def testBindQueue(self) -> None:
        """Test queue binding to specific limiters.

        Verifies that queues can be bound to specific rate limiters and
        that the mappings are stored correctly.
        """
        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Bind queues
        self.manager.bindQueue("queue1", "limiter1")
        self.manager.bindQueue("queue2", "limiter2")

        mappings = self.manager.getQueueMappings()
        self.assertEqual(mappings["queue1"], "limiter1")
        self.assertEqual(mappings["queue2"], "limiter2")

    def testBindQueueToNonExistentLimiter(self) -> None:
        """Test error when binding queue to non-existent limiter.

        Verifies that attempting to bind a queue to a non-registered
        limiter raises a ValueError with an appropriate message.
        """
        with self.assertRaises(ValueError) as context:
            self.manager.bindQueue("queue1", "nonexistent")

        self.assertIn("not registered", str(context.exception))

    async def testApplyLimitWithMapping(self) -> None:
        """Test applyLimit routes to correct limiter based on mapping.

        Verifies that when a queue is bound to a specific limiter,
        applyLimit correctly routes the request to that limiter.
        """
        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Bind queue
        self.manager.bindQueue("test_queue", "limiter1")

        # Apply limit
        await self.manager.applyLimit("test_queue")

        # Should have been applied to limiter1
        self.assertIn("test_queue", self.mockLimiter1.applied_limits)
        self.assertNotIn("test_queue", self.mockLimiter2.applied_limits)

    async def testApplyLimitWithDefault(self) -> None:
        """Test applyLimit uses default limiter for unmapped queues.

        Verifies that when a queue is not bound to any limiter,
        applyLimit routes the request to the default limiter.
        """
        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Don't bind queue, should use default (limiter1)
        await self.manager.applyLimit("unmapped_queue")

        # Should have been applied to default limiter
        self.assertIn("unmapped_queue", self.mockLimiter1.applied_limits)
        self.assertNotIn("unmapped_queue", self.mockLimiter2.applied_limits)

    async def testApplyLimitNoLimitersRegistered(self) -> None:
        """Test error when applying limit with no limiters registered.

        Verifies that attempting to apply a limit when no rate limiters
        are registered raises a RuntimeError with an appropriate message.
        """
        with self.assertRaises(RuntimeError) as context:
            await self.manager.applyLimit("test_queue")

        self.assertIn("No rate limiters registered", str(context.exception))

    async def testApplyLimitNoDefaultLimiter(self) -> None:
        """Test error when no default limiter is set.

        Verifies that attempting to apply a limit when no default limiter
        is set raises a RuntimeError with an appropriate message.
        """
        # Register limiter but clear default
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager._defaultLimiter = None

        with self.assertRaises(RuntimeError) as context:
            await self.manager.applyLimit("test_queue")

        self.assertIn("No default rate limiter set", str(context.exception))

    async def testGetStatsWithMapping(self) -> None:
        """Test getStats routes to correct limiter based on mapping.

        Verifies that when a queue is bound to a specific limiter,
        getStats correctly retrieves statistics from that limiter.
        """
        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Bind queue
        self.manager.bindQueue("test_queue", "limiter1")

        # Get stats
        stats = self.manager.getStats("test_queue")

        # Should get stats from limiter1
        self.assertEqual(stats["maxRequests"], 10)  # Mock limiter default

    async def testGetStatsWithDefault(self) -> None:
        """Test getStats uses default limiter for unmapped queues.

        Verifies that when a queue is not bound to any limiter,
        getStats retrieves statistics from the default limiter.
        """
        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Get stats for unmapped queue
        stats = self.manager.getStats("unmapped_queue")

        # Should get stats from default limiter
        self.assertEqual(stats["maxRequests"], 10)  # Mock limiter default

    async def testGetStatsNoLimitersRegistered(self) -> None:
        """Test error when getting stats with no limiters registered.

        Verifies that attempting to get statistics when no rate limiters
        are registered raises a RuntimeError with an appropriate message.
        """
        with self.assertRaises(RuntimeError) as context:
            self.manager.getStats("test_queue")

        self.assertIn("No rate limiters registered", str(context.exception))

    async def testListRateLimiters(self) -> None:
        """Test listing registered rate limiters.

        Verifies that listRateLimiters returns the correct list of
        registered limiter names.
        """
        # Initially empty
        self.assertEqual(self.manager.listRateLimiters(), [])

        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        limiters = self.manager.listRateLimiters()
        self.assertEqual(len(limiters), 2)
        self.assertIn("limiter1", limiters)
        self.assertIn("limiter2", limiters)

    async def testGetQueueMappings(self) -> None:
        """Test getting queue-to-limiter mappings.

        Verifies that getQueueMappings returns the correct dictionary
        mapping queue names to their associated rate limiters.
        """
        # Initially empty
        self.assertEqual(self.manager.getQueueMappings(), {})

        # Register limiters and bind queues
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        self.manager.bindQueue("queue1", "limiter1")
        self.manager.bindQueue("queue2", "limiter2")

        mappings = self.manager.getQueueMappings()
        self.assertEqual(mappings["queue1"], "limiter1")
        self.assertEqual(mappings["queue2"], "limiter2")

    async def testGetDefaultLimiter(self) -> None:
        """Test getting default limiter name.

        Verifies that getDefaultLimiter returns the correct default
        limiter name, including None when no limiters are registered.
        """
        # Initially None
        self.assertIsNone(self.manager.getDefaultLimiter())

        # Register first limiter (should become default)
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.assertEqual(self.manager.getDefaultLimiter(), "limiter1")

        # Register second limiter (default shouldn't change)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)
        self.assertEqual(self.manager.getDefaultLimiter(), "limiter1")

        # Change default
        self.manager.setDefaultLimiter("limiter2")
        self.assertEqual(self.manager.getDefaultLimiter(), "limiter2")

    async def testDestroy(self) -> None:
        """Test manager destruction and cleanup.

        Verifies that destroy properly cleans up all registered limiters,
        clears queue mappings, resets the default limiter, and destroys
        all registered rate limiter instances.
        """
        # Register real limiters
        await self.realLimiter1.initialize()
        await self.realLimiter2.initialize()

        self.manager.registerRateLimiter("limiter1", self.realLimiter1)
        self.manager.registerRateLimiter("limiter2", self.realLimiter2)
        self.manager.bindQueue("queue1", "limiter1")

        # Verify state before destruction
        self.assertEqual(len(self.manager.listRateLimiters()), 2)
        self.assertEqual(len(self.manager.getQueueMappings()), 1)
        self.assertIsNotNone(self.manager.getDefaultLimiter())

        # Destroy
        await self.manager.destroy()

        # Verify cleanup
        self.assertEqual(len(self.manager.listRateLimiters()), 0)
        self.assertEqual(len(self.manager.getQueueMappings()), 0)
        self.assertIsNone(self.manager.getDefaultLimiter())
        # Verify limiters were destroyed (no explicit destroyed attribute,
        # but we can check they're no longer initialized)
        self.assertFalse(self.realLimiter1._initialized)
        self.assertFalse(self.realLimiter2._initialized)

    async def testDestroyWithError(self) -> None:
        """Test destruction handles errors gracefully.

        Verifies that if a rate limiter raises an error during destruction,
        the manager logs the error and continues cleaning up other limiters.
        """
        # Create limiter that raises error on destroy
        error_limiter = MockRateLimiter()
        error_limiter.destroy = AsyncMock(side_effect=Exception("Destroy error"))

        self.manager.registerRateLimiter("error_limiter", error_limiter)

        # Should not raise exception
        with patch("lib.rate_limiter.manager.logger") as mock_logger:
            await self.manager.destroy()

            # Should log error but continue cleanup
            mock_logger.error.assert_called()

    async def testRealLimitersIntegration(self) -> None:
        """Test manager with real SlidingWindowRateLimiter instances.

        Verifies that the manager works correctly with real rate limiter
        implementations, including actual rate limiting behavior and
        independent queue management.
        """
        # Initialize real limiters
        await self.realLimiter1.initialize()
        await self.realLimiter2.initialize()

        # Register with manager
        self.manager.registerRateLimiter("strict", self.realLimiter1)  # 5 req/10s
        self.manager.registerRateLimiter("lenient", self.realLimiter2)  # 10 req/60s

        # Bind queues
        self.manager.bindQueue("api_calls", "strict")
        self.manager.bindQueue("background_jobs", "lenient")

        # Test rate limiting through manager
        start_time = asyncio.get_event_loop().time()

        # Make requests that should be rate limited by strict limiter
        for i in range(6):  # Exceeds limit of 5
            await self.manager.applyLimit("api_calls")

        elapsed = asyncio.get_event_loop().time() - start_time
        self.assertGreaterEqual(elapsed, 2.0)  # Should be delayed

        # Background jobs should still work immediately
        start_time = asyncio.get_event_loop().time()
        await self.manager.applyLimit("background_jobs")
        elapsed = asyncio.get_event_loop().time() - start_time
        self.assertLess(elapsed, 0.1)

    async def testMultipleQueuesSameLimiter(self) -> None:
        """Test multiple queues using the same limiter.

        Verifies that multiple queues can be bound to the same rate limiter
        and that requests from all queues are processed by that limiter.
        """
        self.manager.registerRateLimiter("shared", self.mockLimiter1)

        # Bind multiple queues to same limiter
        self.manager.bindQueue("queue1", "shared")
        self.manager.bindQueue("queue2", "shared")

        # Apply limits to both queues
        await self.manager.applyLimit("queue1")
        await self.manager.applyLimit("queue2")

        # Both should go to the same limiter
        self.assertIn("queue1", self.mockLimiter1.applied_limits)
        self.assertIn("queue2", self.mockLimiter1.applied_limits)

    async def testRebindQueue(self) -> None:
        """Test rebinding queue to different limiter.

        Verifies that a queue can be rebound from one limiter to another
        and that subsequent requests use the new limiter.
        """
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Bind to first limiter
        self.manager.bindQueue("test_queue", "limiter1")
        await self.manager.applyLimit("test_queue")

        # Rebind to second limiter
        self.manager.bindQueue("test_queue", "limiter2")
        await self.manager.applyLimit("test_queue")

        # Should have used both limiters
        self.assertIn("test_queue", self.mockLimiter1.applied_limits)
        self.assertIn("test_queue", self.mockLimiter2.applied_limits)

    async def testDefaultQueue(self) -> None:
        """Test default queue behavior.

        Verifies that when no queue name is specified, the manager uses
        "default" as the queue name.
        """
        self.manager.registerRateLimiter("default_limiter", self.mockLimiter1)

        # Apply limit without specifying queue
        await self.manager.applyLimit()

        # Should use "default" queue
        self.assertIn("default", self.mockLimiter1.applied_limits)

    async def testGetStatsDefaultQueue(self) -> None:
        """Test getStats with default queue.

        Verifies that when no queue name is specified, getStats retrieves
        statistics for the "default" queue.
        """
        self.manager.registerRateLimiter("default_limiter", self.mockLimiter1)

        # Get stats without specifying queue
        stats = self.manager.getStats()

        # Should work and return mock stats
        self.assertEqual(stats["maxRequests"], 10)


class TestRateLimiterManagerEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Test suite for edge cases and error scenarios.

    This test class verifies that the RateLimiterManager handles edge cases
    and error scenarios correctly, including externally destroyed limiters,
    concurrent operations, and state isolation.
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures.

        Initializes a clean RateLimiterManager instance for each test
        to ensure isolated test environments.
        """
        # Get clean manager instance
        self.manager = RateLimiterManager.getInstance()
        await self.manager.destroy()

    async def asyncTearDown(self) -> None:
        """Clean up after tests.

        Destroys the manager instance to ensure clean state between tests.
        """
        await self.manager.destroy()

    async def testManagerWithDestroyedLimiter(self) -> None:
        """Test manager behavior when limiter is destroyed externally.

        Verifies that the manager continues to function correctly even
        when a registered rate limiter is destroyed and re-initialized
        externally.
        """
        manager = RateLimiterManager.getInstance()
        await manager.destroy()  # Clean start

        limiter = SlidingWindowRateLimiter(config=QueueConfig(maxRequests=1, windowSeconds=1))
        await limiter.initialize()

        manager.registerRateLimiter("test", limiter)

        # Destroy limiter externally
        await limiter.destroy()

        # Manager should still work
        await limiter.initialize()  # Re-initialize
        await manager.applyLimit("test")

        await manager.destroy()

    async def testConcurrentOperations(self) -> None:
        """Test concurrent manager operations.

        Verifies that the manager handles concurrent operations correctly,
        including multiple simultaneous applyLimit calls across different
        queues.
        """
        manager = RateLimiterManager.getInstance()
        await manager.destroy()  # Clean start

        limiter = MockRateLimiter()
        manager.registerRateLimiter("concurrent", limiter)

        async def make_requests(queue_name: str, count: int) -> None:
            for i in range(count):
                await manager.applyLimit(queue_name)

        # Run concurrent operations
        tasks = [
            make_requests("queue1", 5),
            make_requests("queue2", 5),
            make_requests("queue3", 5),
        ]

        await asyncio.gather(*tasks)

        # All requests should have been processed
        self.assertEqual(len(limiter.applied_limits), 15)

        await manager.destroy()

    def testManagerStateIsolation(self) -> None:
        """Test that manager instances maintain separate state.

        Verifies that the singleton pattern works correctly and that
        all references to the manager point to the same instance with
        shared state.
        """
        # This test verifies the singleton pattern works correctly
        manager1 = RateLimiterManager.getInstance()
        manager2 = RateLimiterManager.getInstance()

        # Both should be the same instance
        self.assertIs(manager1, manager2)

        # State should be shared
        limiter = MockRateLimiter()
        manager1.registerRateLimiter("test", limiter)

        self.assertIn("test", manager2.listRateLimiters())


if __name__ == "__main__":
    unittest.main()
