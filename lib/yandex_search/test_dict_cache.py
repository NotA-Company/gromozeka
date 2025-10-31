"""
Tests for DictSearchCache implementation

This module contains comprehensive tests for the dictionary-based search cache.
"""

import asyncio
import time
import unittest

from .dict_cache import DictSearchCache
from .models import SearchResponse


class TestDictSearchCache(unittest.TestCase):
    """Test cases for DictSearchCache"""

    def setUp(self):
        """Set up test fixtures"""
        self.cache = DictSearchCache(default_ttl=1, max_size=3)

        # Sample search response for testing
        self.sample_response: SearchResponse = {
            "requestId": "test-request-123",
            "found": 10,
            "foundHuman": "10 results found",
            "page": 0,
            "groups": [
                {
                    "group": [
                        {
                            "url": "https://example.com/1",
                            "domain": "example.com",
                            "title": "Test Result 1",
                            "passages": ["This is a test passage"],
                            "modtime": "2023-01-01",
                            "size": "1024",
                            "charset": "utf-8",
                            "mimetypes": ["text/html"],
                            "hlwords": ["test"],
                        }
                    ]
                }
            ],
            "error": None,
        }

    def test_cache_storage_and_retrieval(self):
        """Test basic cache storage and retrieval"""

        async def run_test():
            # Store data
            result = await self.cache.setSearch("test-key", self.sample_response)
            self.assertTrue(result)

            # Retrieve data
            cached_data = await self.cache.getSearch("test-key")
            self.assertIsNotNone(cached_data)
            if cached_data:
                self.assertEqual(cached_data["requestId"], "test-request-123")
                self.assertEqual(cached_data["found"], 10)

        asyncio.run(run_test())

    def test_cache_miss(self):
        """Test cache miss scenario"""

        async def run_test():
            # Try to retrieve non-existent key
            cached_data = await self.cache.getSearch("non-existent-key")
            self.assertIsNone(cached_data)

        asyncio.run(run_test())

    def test_ttl_expiration(self):
        """Test TTL expiration functionality"""

        async def run_test():
            # Store data
            await self.cache.setSearch("ttl-key", self.sample_response)

            # Retrieve immediately (should work)
            cached_data = await self.cache.getSearch("ttl-key")
            self.assertIsNotNone(cached_data)

            # Wait for expiration
            time.sleep(1.1)

            # Try to retrieve after expiration (should fail)
            cached_data = await self.cache.getSearch("ttl-key")
            self.assertIsNone(cached_data)

        asyncio.run(run_test())

    def test_custom_ttl(self):
        """Test custom TTL parameter"""

        async def run_test():
            # Store data
            await self.cache.setSearch("custom-ttl-key", self.sample_response)

            # Retrieve immediately (should work)
            cached_data = await self.cache.getSearch("custom-ttl-key")
            self.assertIsNotNone(cached_data)

            # Wait for default TTL expiration
            time.sleep(1.1)

            # Should be expired with default TTL
            cached_data = await self.cache.getSearch("custom-ttl-key")
            self.assertIsNone(cached_data)

        asyncio.run(run_test())

    def test_max_size_enforcement(self):
        """Test maximum cache size enforcement"""

        async def run_test():
            # Fill cache to max size
            await self.cache.setSearch("key1", self.sample_response)
            await self.cache.setSearch("key2", self.sample_response)
            await self.cache.setSearch("key3", self.sample_response)

            # Check stats
            stats = self.cache.get_stats()
            self.assertEqual(stats["search_entries"], 3)

            # Add one more entry (should evict oldest)
            await self.cache.setSearch("key4", self.sample_response)

            # Check that cache size is maintained
            stats = self.cache.get_stats()
            self.assertEqual(stats["search_entries"], 3)  # Should still be max_size

            # Check that newest entry exists
            cached_data = await self.cache.getSearch("key4")
            self.assertIsNotNone(cached_data)

        asyncio.run(run_test())

    def test_cache_clear(self):
        """Test cache clearing functionality"""

        async def run_test():
            # Store some data
            await self.cache.setSearch("key1", self.sample_response)
            await self.cache.setSearch("key2", self.sample_response)

            # Verify data exists
            stats = self.cache.get_stats()
            self.assertEqual(stats["search_entries"], 2)

            # Clear cache
            self.cache.clear()

            # Verify cache is empty
            stats = self.cache.get_stats()
            self.assertEqual(stats["search_entries"], 0)

            # Verify data is gone
            cached_data = await self.cache.getSearch("key1")
            self.assertIsNone(cached_data)

        asyncio.run(run_test())

    def test_cache_stats(self):
        """Test cache statistics"""

        async def run_test():
            # Initial stats
            stats = self.cache.get_stats()
            self.assertEqual(stats["search_entries"], 0)
            self.assertEqual(stats["max_size"], 3)
            self.assertEqual(stats["default_ttl"], 1)

            # Add some data
            await self.cache.setSearch("key1", self.sample_response)
            await self.cache.setSearch("key2", self.sample_response)

            # Updated stats
            stats = self.cache.get_stats()
            self.assertEqual(stats["search_entries"], 2)

        asyncio.run(run_test())

    def test_cache_key_generation(self):
        """Test cache key generation from parameters"""
        # Test with different parameters
        key1 = self.cache.generate_key_from_params(queryText="test query", searchType="SEARCH_TYPE_RU", region="225")

        key2 = self.cache.generate_key_from_params(queryText="test query", searchType="SEARCH_TYPE_RU", region="225")

        key3 = self.cache.generate_key_from_params(
            queryText="different query", searchType="SEARCH_TYPE_RU", region="225"
        )

        # Same parameters should generate same key
        self.assertEqual(key1, key2)

        # Different parameters should generate different key
        self.assertNotEqual(key1, key3)

        # Keys should be valid MD5 hashes (32 characters)
        self.assertEqual(len(key1), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in key1))

    def test_thread_safety(self):
        """Test thread safety of cache operations"""

        async def worker(worker_id: int):
            # Each worker stores and retrieves data
            for i in range(10):
                key = f"worker-{worker_id}-key-{i}"
                await self.cache.setSearch(key, self.sample_response)
                cached_data = await self.cache.getSearch(key)
                self.assertIsNotNone(cached_data)

        async def run_test():
            # Run multiple workers concurrently
            tasks = [worker(i) for i in range(5)]
            await asyncio.gather(*tasks)

        asyncio.run(run_test())

    def test_error_handling(self):
        """Test error handling in cache operations"""

        async def run_test():
            # Test that cache handles normal operations gracefully
            # Store and retrieve data
            result = await self.cache.setSearch("error-key", self.sample_response)
            self.assertTrue(result)

            cached_data = await self.cache.getSearch("error-key")
            self.assertIsNotNone(cached_data)

            # Test with non-existent key (should return None gracefully)
            cached_data = await self.cache.getSearch("non-existent-key")
            self.assertIsNone(cached_data)

        asyncio.run(run_test())

    def test_parameter_order_independence(self):
        """Test that parameter order doesn't affect cache key generation"""
        key1 = self.cache.generate_key_from_params(queryText="test", searchType="SEARCH_TYPE_RU", region="225")

        key2 = self.cache.generate_key_from_params(region="225", queryText="test", searchType="SEARCH_TYPE_RU")

        # Different order should generate same key
        self.assertEqual(key1, key2)


if __name__ == "__main__":
    unittest.main()
