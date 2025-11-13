"""
Integration tests for lib.cache library, dood!

This module contains comprehensive integration tests that verify the complete
workflow of the cache library, including real-world usage scenarios,
multiple cache implementations, and end-to-end functionality.
"""

import asyncio
import time
import unittest
from dataclasses import dataclass
from typing import Any, Dict, List

from . import DictCache, HashKeyGenerator, JsonKeyGenerator, NullCache, StringKeyGenerator
from .interface import CacheInterface


class TestCachePublicAPI(unittest.IsolatedAsyncioTestCase):
    """Test public API imports and exports, dood!"""

    def test_all_exports_available(self):
        """Test that all exports from __init__.py are importable, dood!"""
        # Test that we can import all the main components
        from lib.cache import (
            CacheInterface,
            DictCache,
            HashKeyGenerator,
            JsonKeyGenerator,
            KeyGenerator,
            NullCache,
            StringKeyGenerator,
        )

        # Verify they are the correct types
        assert CacheInterface is not None
        assert DictCache is not None
        assert NullCache is not None
        assert StringKeyGenerator is not None
        assert HashKeyGenerator is not None
        assert JsonKeyGenerator is not None
        assert KeyGenerator is not None

    def test_import_from_module(self):
        """Test that imports work as expected, dood!"""
        # Test the import pattern from the docstring
        from lib.cache import DictCache, StringKeyGenerator

        # Should be able to create instances
        cache = DictCache[str, dict](keyGenerator=StringKeyGenerator())
        assert cache is not None
        assert isinstance(cache, CacheInterface)

    def test_type_annotations_available(self):
        """Test that type annotations are available, dood!"""
        from lib.cache import K, KeyGenerator, V

        # Type variables should be available
        assert K is not None
        assert V is not None
        assert KeyGenerator is not None


class TestCacheEndToEndUsage(unittest.IsolatedAsyncioTestCase):
    """Test end-to-end usage scenarios, dood!"""

    async def test_string_keys_with_dict_cache(self):
        """Test string keys with DictCache, dood!"""
        cache = DictCache[str, dict](keyGenerator=StringKeyGenerator(), defaultTtl=3600, maxSize=1000)

        # Store and retrieve user data
        user_data = {"name": "Prinny", "level": 99, "class": "Demon"}
        success = await cache.set("user:123", user_data)
        assert success is True

        # Retrieve the data
        retrieved_data = await cache.get("user:123")
        assert retrieved_data is not None
        assert retrieved_data == user_data
        assert retrieved_data["name"] == "Prinny"

        # Test cache stats
        stats = cache.getStats()
        assert stats["entries"] == 1
        assert stats["maxSize"] == 1000
        assert stats["defaultTtl"] == 3600

    async def test_complex_object_keys_with_hash_key_generator(self):
        """Test complex object keys with HashKeyGenerator, dood!"""
        cache = DictCache[Dict[str, Any], List[Dict[str, Any]]](
            keyGenerator=HashKeyGenerator(), defaultTtl=1800, maxSize=500
        )

        # Complex search query as key
        search_query = {
            "query": "prinny squad",
            "filters": {"type": "demon", "level": "high"},
            "page": 1,
            "sort": "relevance",
        }

        # Search results as value
        search_results = [
            {"id": 1, "name": "Prinny Squad", "power": 9000},
            {"id": 2, "name": "Elite Prinny", "power": 8500},
        ]

        # Store and retrieve
        success = await cache.set(search_query, search_results)
        assert success is True

        retrieved_results = await cache.get(search_query)
        assert retrieved_results is not None
        assert retrieved_results == search_results
        assert len(retrieved_results) == 2

    async def test_json_serializable_objects_with_json_key_generator(self):
        """Test JSON-serializable objects with JsonKeyGenerator, dood!"""
        cache = DictCache[Dict[str, Any], str](keyGenerator=JsonKeyGenerator(), defaultTtl=3600)

        # Test that equivalent keys produce same cache entry
        key1 = {"a": 1, "b": 2, "c": [1, 2, 3]}
        key2 = {"c": [1, 2, 3], "b": 2, "a": 1}  # Same content, different order

        # Store with first key
        await cache.set(key1, "test_value")

        # Retrieve with equivalent key
        value = await cache.get(key2)
        assert value == "test_value"

        # Verify it's the same cache entry
        stats = cache.getStats()
        assert stats["entries"] == 1

    async def test_switching_between_cache_implementations(self):
        """Test switching between DictCache and NullCache, dood!"""
        # Start with DictCache
        real_cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        # Store some data
        await real_cache.set("test_key", "test_value")
        value = await real_cache.get("test_key")
        assert value == "test_value"

        # Switch to NullCache for testing
        null_cache = NullCache[str, str]()

        # Same operations should work but not cache
        success = await null_cache.set("test_key", "test_value")
        assert success is True  # Pretends to succeed

        value = await null_cache.get("test_key")
        assert value is None  # Always returns None

        # Verify interface compatibility
        assert isinstance(real_cache, CacheInterface)
        assert isinstance(null_cache, CacheInterface)


class TestCacheRealWorldPatterns(unittest.IsolatedAsyncioTestCase):
    """Test real-world usage patterns, dood!"""

    async def test_caching_api_responses(self):
        """Test caching API responses (dict values), dood!"""
        cache = DictCache[str, Dict[str, Any]](
            keyGenerator=StringKeyGenerator(), defaultTtl=300, maxSize=100  # 5 minutes
        )

        # Simulate API response
        api_response = {
            "status": "success",
            "data": {
                "users": [{"id": 1, "name": "Prinny", "active": True}, {"id": 2, "name": "Etna", "active": True}],
                "total": 2,
                "page": 1,
            },
            "timestamp": time.time(),
        }

        # Cache the API response
        endpoint = "GET:/api/users?page=1"
        success = await cache.set(endpoint, api_response)
        assert success is True

        # Retrieve cached response
        cached_response = await cache.get(endpoint)
        assert cached_response is not None
        assert cached_response == api_response
        assert cached_response["data"]["users"][0]["name"] == "Prinny"

    async def test_caching_computed_results_with_ttl(self):
        """Test caching computed results with TTL, dood!"""
        cache = DictCache[str, int](
            keyGenerator=StringKeyGenerator(), defaultTtl=2, maxSize=50  # 2 seconds for testing
        )

        # Simulate expensive computation
        def expensive_computation(x: int) -> int:
            # Simulate work
            time.sleep(0.1)
            return x * x * x  # cube

        # Cache computation result
        input_value = 42
        cache_key = f"cube:{input_value}"

        # First computation (not cached)
        start_time = time.time()
        result1 = expensive_computation(input_value)
        await cache.set(cache_key, result1)
        first_time = time.time() - start_time

        # Second retrieval (cached)
        start_time = time.time()
        cached_result = await cache.get(cache_key)
        second_time = time.time() - start_time

        assert cached_result == result1
        assert second_time < first_time / 2  # Should be much faster

        # Wait for expiration
        await asyncio.sleep(2.1)

        # Should be expired now
        expired_result = await cache.get(cache_key)
        assert expired_result is None

    async def test_using_cache_with_dataclasses_as_keys(self):
        """Test using cache with dataclasses as keys, dood!"""

        @dataclass
        class SearchQuery:
            query: str
            filters: Dict[str, Any]
            page: int
            limit: int

        cache = DictCache[SearchQuery, List[Dict[str, Any]]](keyGenerator=HashKeyGenerator(), defaultTtl=600)

        # Create search query
        query = SearchQuery(
            query="prinny characters", filters={"game": "disgaea", "role": "playable"}, page=1, limit=10
        )

        # Search results
        results = [
            {"name": "Prinny", "game": "Disgaea", "role": "Protagonist"},
            {"name": "Etna", "game": "Disgaea", "role": "Vassal"},
            {"name": "Flonne", "game": "Disgaea", "role": "Angel"},
        ]

        # Cache and retrieve
        await cache.set(query, results)
        cached_results = await cache.get(query)
        assert cached_results is not None
        assert cached_results == results
        assert len(cached_results) == 3

    async def test_thread_safe_concurrent_access_patterns(self):
        """Test thread-safe concurrent access patterns, dood!"""
        cache = DictCache[str, int](keyGenerator=StringKeyGenerator(), defaultTtl=3600, maxSize=1000)

        async def worker(worker_id: int):
            """Worker that performs cache operations, dood!"""
            for i in range(20):
                key = f"worker_{worker_id}_item_{i}"
                value = worker_id * 1000 + i

                # Set value
                success = await cache.set(key, value)
                assert success is True

                # Get value
                retrieved = await cache.get(key)
                assert retrieved == value

                # Small delay to simulate real work
                await asyncio.sleep(0.001)

        # Run multiple workers concurrently
        workers = [worker(i) for i in range(5)]
        await asyncio.gather(*workers)

        # Verify all data is cached correctly
        stats = cache.getStats()
        assert stats["entries"] == 100  # 5 workers * 20 items each

        # Spot check some values
        for worker_id in range(5):
            for i in range(0, 20, 5):  # Check every 5th item
                key = f"worker_{worker_id}_item_{i}"
                expected_value = worker_id * 1000 + i
                retrieved = await cache.get(key)
                assert retrieved == expected_value


class TestCacheReplacementScenarios(unittest.IsolatedAsyncioTestCase):
    """Test cache replacement scenarios, dood!"""

    async def test_start_with_dict_cache_switch_to_null_cache(self):
        """Test starting with DictCache, switching to NullCache for testing, dood!"""
        # Production cache
        prod_cache = DictCache[str, Dict[str, Any]](keyGenerator=StringKeyGenerator(), defaultTtl=3600, maxSize=1000)

        # Store some production data
        user_data = {"id": 123, "name": "Prinny", "level": 99}
        await prod_cache.set("user:123", user_data)

        # Verify it works
        retrieved = await prod_cache.get("user:123")
        assert retrieved == user_data

        # Switch to null cache for testing
        test_cache = NullCache[str, Dict[str, Any]]()

        # Same interface, different behavior
        success = await test_cache.set("user:123", user_data)
        assert success is True  # Pretends to succeed

        retrieved = await test_cache.get("user:123")
        assert retrieved is None  # Always returns None

        # Verify both implement the same interface
        assert isinstance(prod_cache, CacheInterface)
        assert isinstance(test_cache, CacheInterface)

    async def test_same_interface_works_with_both_implementations(self):
        """Test that same interface works with both implementations, dood!"""

        def create_cache(use_real_cache: bool) -> CacheInterface[str, str]:
            """Factory function to create cache based on flag, dood!"""
            if use_real_cache:
                return DictCache[str, str](keyGenerator=StringKeyGenerator(), defaultTtl=3600)
            else:
                return NullCache[str, str]()

        # Test with real cache
        real_cache = create_cache(True)
        await real_cache.set("test", "value")
        assert await real_cache.get("test") == "value"

        # Test with null cache (same code, different behavior)
        null_cache = create_cache(False)
        await null_cache.set("test", "value")
        assert await null_cache.get("test") is None

        # Both should support stats
        real_stats = real_cache.getStats()
        null_stats = null_cache.getStats()
        assert isinstance(real_stats, dict)
        assert isinstance(null_stats, dict)
        assert null_stats.get("enabled") is False

    async def test_cache_behavior_transparency(self):
        """Test that cache behavior is transparent to calling code, dood!"""

        async def process_data_with_cache(data_id: str, cache: CacheInterface[str, Dict[str, Any]]) -> Dict[str, Any]:
            """Process data using cache, dood!"""
            # Try to get from cache first
            cached_data = await cache.get(f"data:{data_id}")
            if cached_data:
                return cached_data

            # Simulate data processing
            processed_data = {
                "id": data_id,
                "processed": True,
                "timestamp": time.time(),
                "result": f"processed_{data_id}",
            }

            # Cache the result
            await cache.set(f"data:{data_id}", processed_data)
            return processed_data

        # Test with real cache
        real_cache = DictCache[str, Dict[str, Any]](StringKeyGenerator())

        result1 = await process_data_with_cache("123", real_cache)
        result2 = await process_data_with_cache("123", real_cache)  # Should be cached

        assert result1 == result2
        assert result1["processed"] is True

        # Test with null cache
        null_cache = NullCache[str, Dict[str, Any]]()

        result3 = await process_data_with_cache("456", null_cache)
        result4 = await process_data_with_cache("456", null_cache)  # Should not be cached

        # Same logical result, but processed twice (different timestamps)
        assert result3["id"] == result4["id"] == "456"
        assert result3["processed"] == result4["processed"] is True
        assert result3["result"] == result4["result"] == "processed_456"
        # Timestamps should be different because processed twice
        assert result3["timestamp"] != result4["timestamp"]


class TestCachePerformanceCharacteristics(unittest.IsolatedAsyncioTestCase):
    """Test performance characteristics, dood!"""

    async def test_ttl_expiration_works_correctly(self):
        """Test that TTL expiration works correctly, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator(), defaultTtl=1)  # 1 second

        # Store value
        await cache.set("test_key", "test_value")

        # Should be available immediately
        value = await cache.get("test_key")
        assert value == "test_value"

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be expired
        value = await cache.get("test_key")
        assert value is None

        # Stats should reflect expiration
        stats = cache.getStats()
        assert stats["entries"] == 0

    async def test_size_limits_trigger_eviction(self):
        """Test that size limits trigger eviction, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator(), maxSize=3)  # Very small cache

        # Fill cache to capacity
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")

        # All should be present
        assert await cache.get("key1") == "value1"
        assert await cache.get("key2") == "value2"
        assert await cache.get("key3") == "value3"

        stats = cache.getStats()
        assert stats["entries"] == 3

        # Add one more (should evict oldest)
        await cache.set("key4", "value4")

        # Oldest should be evicted
        assert await cache.get("key1") is None
        assert await cache.get("key2") == "value2"
        assert await cache.get("key3") == "value3"
        assert await cache.get("key4") == "value4"

        stats = cache.getStats()
        assert stats["entries"] == 3  # Still at max capacity

    async def test_thread_safe_operations_dont_deadlock(self):
        """Test that thread-safe operations don't deadlock, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        async def intensive_worker(worker_id: int):
            """Worker that does intensive cache operations, dood!"""
            for i in range(50):
                key = f"worker_{worker_id}_key_{i}"
                value = f"worker_{worker_id}_value_{i}"

                # Mix of operations
                await cache.set(key, value)
                await cache.get(key)

                # Occasionally clear and check stats
                if i % 10 == 0:
                    stats = cache.getStats()
                    assert isinstance(stats, dict)

                # Small delay
                await asyncio.sleep(0.001)

        # Run multiple intensive workers
        workers = [intensive_worker(i) for i in range(3)]

        # Should complete without deadlock
        start_time = time.time()
        await asyncio.gather(*workers)
        elapsed = time.time() - start_time

        # Should complete in reasonable time
        assert elapsed < 10.0

        # Cache should still be functional
        await cache.set("final_test", "final_value")
        assert await cache.get("final_test") == "final_value"

    async def test_performance_with_different_key_generators(self):
        """Test performance with different key generators, dood!"""
        # Test with StringKeyGenerator
        string_cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        start_time = time.time()
        for i in range(100):
            await string_cache.set(f"key_{i}", f"value_{i}")
            await string_cache.get(f"key_{i}")
        string_elapsed = time.time() - start_time

        assert string_elapsed < 5.0, f"StringKeyGenerator was too slow: {string_elapsed}s"
        stats = string_cache.getStats()
        assert stats["entries"] == 100

        # Test with HashKeyGenerator
        hash_cache = DictCache[Dict[str, Any], str](keyGenerator=HashKeyGenerator())

        start_time = time.time()
        for i in range(100):
            test_key = {"query": "test", "index": i}
            await hash_cache.set(test_key, f"value_{i}")
            await hash_cache.get(test_key)
        hash_elapsed = time.time() - start_time

        assert hash_elapsed < 5.0, f"HashKeyGenerator was too slow: {hash_elapsed}s"
        stats = hash_cache.getStats()
        assert stats["entries"] == 100

        # Test with JsonKeyGenerator
        json_cache = DictCache[Dict[str, Any], str](keyGenerator=JsonKeyGenerator())

        start_time = time.time()
        for i in range(100):
            test_key = {"query": "test", "index": i}
            await json_cache.set(test_key, f"value_{i}")
            await json_cache.get(test_key)
        json_elapsed = time.time() - start_time

        assert json_elapsed < 5.0, f"JsonKeyGenerator was too slow: {json_elapsed}s"
        stats = json_cache.getStats()
        assert stats["entries"] == 100


class TestCacheEdgeCasesAndErrorConditions(unittest.IsolatedAsyncioTestCase):
    """Test edge cases and error conditions, dood!"""

    async def test_cache_with_none_values(self):
        """Test cache with None values, dood!"""
        cache = DictCache[str, Any](keyGenerator=StringKeyGenerator())

        # Store None value
        success = await cache.set("none_key", None)
        assert success is True

        # Retrieve None value
        value = await cache.get("none_key")
        assert value is None

        # But key should exist (different from missing key)
        stats = cache.getStats()
        assert stats["entries"] == 1

        # Missing key should also return None
        missing_value = await cache.get("missing_key")
        assert missing_value is None

    async def test_cache_with_large_objects(self):
        """Test cache with large objects, dood!"""
        cache = DictCache[str, List[int]](keyGenerator=StringKeyGenerator(), maxSize=10)

        # Large list
        large_data = list(range(10000))

        # Store and retrieve large data
        success = await cache.set("large_key", large_data)
        assert success is True

        retrieved = await cache.get("large_key")
        assert retrieved is not None
        assert retrieved == large_data
        assert len(retrieved) == 10000

    async def test_cache_with_special_characters_in_keys(self):
        """Test cache with special characters in keys, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        special_keys = [
            "key with spaces",
            "key-with-dashes",
            "key_with_underscores",
            "key.with.dots",
            "key/with/slashes",
            "key\\with\\backslashes",
            "key:with:colons",
            "key;with;semicolons",
            "key@with@ats",
            "key#with#hashes",
            "key$with$dollars",
            "key%with%percents",
            "key^with^carets",
            "key&with&ampersands",
            "key*with*asterisks",
            "key(with)parentheses",
            "key[with]brackets",
            "key{with}braces",
            "key|with|pipes",
            "key+with+plus",
            "key=with=equals",
            "key?with?questions",
            "key<with>angles",
            'key"with"quotes',
            "key'with'apostrophes",
        ]

        for key in special_keys:
            value = f"value_for_{key}"
            await cache.set(key, value)
            retrieved = await cache.get(key)
            assert retrieved == value

    async def test_cache_rapid_operations(self):
        """Test cache with rapid operations, dood!"""
        cache = DictCache[str, int](keyGenerator=StringKeyGenerator())

        # Rapid set/get operations
        for i in range(1000):
            await cache.set(f"rapid_key_{i}", i)
            value = await cache.get(f"rapid_key_{i}")
            assert value == i

        # Verify all entries are there
        stats = cache.getStats()
        assert stats["entries"] == 1000

    async def test_cache_mixed_ttl_operations(self):
        """Test cache with mixed TTL operations, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator(), defaultTtl=10)  # 10 seconds default

        # Set some values
        await cache.set("normal_key", "normal_value")
        await cache.set("short_key", "short_value")
        await cache.set("long_key", "long_value")

        # Test with different TTL overrides
        # Normal TTL should work
        value = await cache.get("normal_key")
        assert value == "normal_value"

        # Short TTL should expire immediately
        value = await cache.get("short_key", ttl=0)
        assert value is None

        # Long TTL should work even with short default
        value = await cache.get("long_key", ttl=-1)  # No expiration
        assert value == "long_value"


if __name__ == "__main__":
    unittest.main()
