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
    """Mock rate limiter for testing."""

    def __init__(self):
        self.initialized = False
        self.destroyed = False
        self.applied_limits = []
        self.stats = {}

    async def initialize(self):
        self.initialized = True

    async def destroy(self):
        self.destroyed = True

    async def applyLimit(self, queue="default"):
        self.applied_limits.append(queue)

    def getStats(self, queue="default"):
        if queue not in self.stats:
            self.stats[queue] = {
                "requestsInWindow": 0,
                "maxRequests": 10,
                "windowSeconds": 60,
                "resetTime": 0,
                "utilizationPercent": 0.0,
            }
        return self.stats[queue]

    def listQueues(self):
        return list(self.stats.keys())


class TestRateLimiterManagerSingleton(unittest.TestCase):
    """Test suite for RateLimiterManager singleton pattern."""

    def testSingletonPattern(self):
        """Test that getInstance returns the same instance."""
        manager1 = RateLimiterManager.getInstance()
        manager2 = RateLimiterManager.getInstance()
        manager3 = RateLimiterManager()

        self.assertIs(manager1, manager2)
        self.assertIs(manager1, manager3)

    def testThreadSafety(self):
        """Test singleton pattern is thread-safe."""
        import threading

        instances = []

        def get_instance():
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

    def testInitializationOnlyOnce(self):
        """Test that initialization only happens once."""
        manager1 = RateLimiterManager.getInstance()
        manager2 = RateLimiterManager.getInstance()

        # Both should have the initialized flag
        self.assertTrue(hasattr(manager1, "initialized"))
        self.assertTrue(hasattr(manager2, "initialized"))
        self.assertTrue(manager1.initialized)
        self.assertTrue(manager2.initialized)


class TestRateLimiterManager(unittest.IsolatedAsyncioTestCase):
    """Test cases for RateLimiterManager functionality."""

    async def asyncSetUp(self):
        """Set up test fixtures."""
        # Get fresh manager instance
        self.manager = RateLimiterManager.getInstance()

        # Clean up any existing state
        await self.manager.destroy()

        # Create mock limiters
        self.mockLimiter1 = MockRateLimiter()
        self.mockLimiter2 = MockRateLimiter()
        self.realLimiter1 = SlidingWindowRateLimiter(QueueConfig(maxRequests=5, windowSeconds=10))
        self.realLimiter2 = SlidingWindowRateLimiter(QueueConfig(maxRequests=10, windowSeconds=60))

    async def asyncTearDown(self):
        """Clean up after tests."""
        await self.manager.destroy()

    async def testRegisterRateLimiter(self):
        """Test rate limiter registration."""
        # Register first limiter
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)

        self.assertIn("limiter1", self.manager.listRateLimiters())
        self.assertEqual(self.manager.getDefaultLimiter(), "limiter1")

        # Register second limiter
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        self.assertIn("limiter2", self.manager.listRateLimiters())
        # Default should still be the first one
        self.assertEqual(self.manager.getDefaultLimiter(), "limiter1")

    def testRegisterDuplicateLimiter(self):
        """Test error when registering duplicate limiter name."""
        self.manager.registerRateLimiter("duplicate", self.mockLimiter1)

        with self.assertRaises(ValueError) as context:
            self.manager.registerRateLimiter("duplicate", self.mockLimiter2)

        self.assertIn("already registered", str(context.exception))

    async def testSetAndGetDefaultLimiter(self):
        """Test setting and getting default limiter."""
        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Change default
        self.manager.setDefaultLimiter("limiter2")
        self.assertEqual(self.manager.getDefaultLimiter(), "limiter2")

        # Set to first limiter
        self.manager.setDefaultLimiter("limiter1")
        self.assertEqual(self.manager.getDefaultLimiter(), "limiter1")

    def testSetDefaultNonExistentLimiter(self):
        """Test error when setting non-existent limiter as default."""
        with self.assertRaises(ValueError) as context:
            self.manager.setDefaultLimiter("nonexistent")

        self.assertIn("not registered", str(context.exception))

    async def testBindQueue(self):
        """Test queue binding to specific limiters."""
        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Bind queues
        self.manager.bindQueue("queue1", "limiter1")
        self.manager.bindQueue("queue2", "limiter2")

        mappings = self.manager.getQueueMappings()
        self.assertEqual(mappings["queue1"], "limiter1")
        self.assertEqual(mappings["queue2"], "limiter2")

    def testBindQueueToNonExistentLimiter(self):
        """Test error when binding queue to non-existent limiter."""
        with self.assertRaises(ValueError) as context:
            self.manager.bindQueue("queue1", "nonexistent")

        self.assertIn("not registered", str(context.exception))

    async def testApplyLimitWithMapping(self):
        """Test applyLimit routes to correct limiter based on mapping."""
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

    async def testApplyLimitWithDefault(self):
        """Test applyLimit uses default limiter for unmapped queues."""
        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Don't bind queue, should use default (limiter1)
        await self.manager.applyLimit("unmapped_queue")

        # Should have been applied to default limiter
        self.assertIn("unmapped_queue", self.mockLimiter1.applied_limits)
        self.assertNotIn("unmapped_queue", self.mockLimiter2.applied_limits)

    async def testApplyLimitNoLimitersRegistered(self):
        """Test error when applying limit with no limiters registered."""
        with self.assertRaises(RuntimeError) as context:
            await self.manager.applyLimit("test_queue")

        self.assertIn("No rate limiters registered", str(context.exception))

    async def testApplyLimitNoDefaultLimiter(self):
        """Test error when no default limiter is set."""
        # Register limiter but clear default
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager._defaultLimiter = None

        with self.assertRaises(RuntimeError) as context:
            await self.manager.applyLimit("test_queue")

        self.assertIn("No default rate limiter set", str(context.exception))

    async def testGetStatsWithMapping(self):
        """Test getStats routes to correct limiter based on mapping."""
        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Bind queue
        self.manager.bindQueue("test_queue", "limiter1")

        # Get stats
        stats = self.manager.getStats("test_queue")

        # Should get stats from limiter1
        self.assertEqual(stats["maxRequests"], 10)  # Mock limiter default

    async def testGetStatsWithDefault(self):
        """Test getStats uses default limiter for unmapped queues."""
        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        # Get stats for unmapped queue
        stats = self.manager.getStats("unmapped_queue")

        # Should get stats from default limiter
        self.assertEqual(stats["maxRequests"], 10)  # Mock limiter default

    async def testGetStatsNoLimitersRegistered(self):
        """Test error when getting stats with no limiters registered."""
        with self.assertRaises(RuntimeError) as context:
            self.manager.getStats("test_queue")

        self.assertIn("No rate limiters registered", str(context.exception))

    async def testListRateLimiters(self):
        """Test listing registered rate limiters."""
        # Initially empty
        self.assertEqual(self.manager.listRateLimiters(), [])

        # Register limiters
        self.manager.registerRateLimiter("limiter1", self.mockLimiter1)
        self.manager.registerRateLimiter("limiter2", self.mockLimiter2)

        limiters = self.manager.listRateLimiters()
        self.assertEqual(len(limiters), 2)
        self.assertIn("limiter1", limiters)
        self.assertIn("limiter2", limiters)

    async def testGetQueueMappings(self):
        """Test getting queue-to-limiter mappings."""
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

    async def testGetDefaultLimiter(self):
        """Test getting default limiter name."""
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

    async def testDestroy(self):
        """Test manager destruction and cleanup."""
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

    async def testDestroyWithError(self):
        """Test destruction handles errors gracefully."""
        # Create limiter that raises error on destroy
        error_limiter = MockRateLimiter()
        error_limiter.destroy = AsyncMock(side_effect=Exception("Destroy error"))

        self.manager.registerRateLimiter("error_limiter", error_limiter)

        # Should not raise exception
        with patch("lib.rate_limiter.manager.logger") as mock_logger:
            await self.manager.destroy()

            # Should log error but continue cleanup
            mock_logger.error.assert_called()

    async def testRealLimitersIntegration(self):
        """Test manager with real SlidingWindowRateLimiter instances."""
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
        self.assertGreaterEqual(elapsed, 8.0)  # Should be delayed

        # Background jobs should still work immediately
        start_time = asyncio.get_event_loop().time()
        await self.manager.applyLimit("background_jobs")
        elapsed = asyncio.get_event_loop().time() - start_time
        self.assertLess(elapsed, 0.1)

    async def testMultipleQueuesSameLimiter(self):
        """Test multiple queues using the same limiter."""
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

    async def testRebindQueue(self):
        """Test rebinding queue to different limiter."""
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

    async def testDefaultQueue(self):
        """Test default queue behavior."""
        self.manager.registerRateLimiter("default_limiter", self.mockLimiter1)

        # Apply limit without specifying queue
        await self.manager.applyLimit()

        # Should use "default" queue
        self.assertIn("default", self.mockLimiter1.applied_limits)

    async def testGetStatsDefaultQueue(self):
        """Test getStats with default queue."""
        self.manager.registerRateLimiter("default_limiter", self.mockLimiter1)

        # Get stats without specifying queue
        stats = self.manager.getStats()

        # Should work and return mock stats
        self.assertEqual(stats["maxRequests"], 10)


class TestRateLimiterManagerEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Test suite for edge cases and error scenarios."""

    async def asyncSetUp(self):
        """Set up test fixtures."""
        # Get clean manager instance
        self.manager = RateLimiterManager.getInstance()
        await self.manager.destroy()

    async def asyncTearDown(self):
        """Clean up after tests."""
        await self.manager.destroy()

    async def testManagerWithDestroyedLimiter(self):
        """Test manager behavior when limiter is destroyed externally."""
        manager = RateLimiterManager.getInstance()
        await manager.destroy()  # Clean start

        limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=1, windowSeconds=1))
        await limiter.initialize()

        manager.registerRateLimiter("test", limiter)

        # Destroy limiter externally
        await limiter.destroy()

        # Manager should still work
        await limiter.initialize()  # Re-initialize
        await manager.applyLimit("test")

        await manager.destroy()

    async def testConcurrentOperations(self):
        """Test concurrent manager operations."""
        manager = RateLimiterManager.getInstance()
        await manager.destroy()  # Clean start

        limiter = MockRateLimiter()
        manager.registerRateLimiter("concurrent", limiter)

        async def make_requests(queue_name, count):
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

    def testManagerStateIsolation(self):
        """Test that manager instances maintain separate state."""
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
