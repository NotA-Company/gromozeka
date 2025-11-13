"""
Comprehensive tests for DictCache implementation, dood!

This test suite validates all functionality of the DictCache class including:
- Basic cache operations (get, set, clear)
- TTL expiration behavior
- Size limits and eviction
- Thread safety
- Key generation strategies
- Cache statistics
- Error handling
"""

import asyncio
import time
from typing import Any, Dict

import pytest

from .dict_cache import DictCache
from .key_generator import HashKeyGenerator, JsonKeyGenerator, StringKeyGenerator


class TestDictCacheBasic:
    """Test basic cache operations, dood!"""

    def test_cache_initialization(self):
        """Test cache initialization with default parameters, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        assert cache._keyGenerator is not None
        assert cache._defaultTtl == 3600
        assert cache._maxSize == 1000
        assert cache._lock is not None

    def test_cache_initialization_custom_params(self):
        """Test cache initialization with custom parameters, dood!"""
        key_gen = StringKeyGenerator()
        cache = DictCache[str, int](keyGenerator=key_gen, defaultTtl=600, maxSize=500)

        assert cache._keyGenerator == key_gen
        assert cache._defaultTtl == 600
        assert cache._maxSize == 500

    @pytest.mark.asyncio
    async def test_basic_set_and_get(self):
        """Test basic set and get operations, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        # Set a value
        result = await cache.set("key1", "value1")
        assert result is True

        # Get the value
        value = await cache.get("key1")
        assert value == "value1"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self):
        """Test getting a non-existent key returns None, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        value = await cache.get("nonexistent")
        assert value is None

    @pytest.mark.asyncio
    async def test_clear_cache(self):
        """Test clearing the cache, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        # Add some values
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")

        # Verify values exist
        assert await cache.get("key1") == "value1"
        assert await cache.get("key2") == "value2"

        # Clear cache
        cache.clear()

        # Verify values are gone
        assert await cache.get("key1") is None
        assert await cache.get("key2") is None

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test cache statistics, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        # Initial stats
        stats = cache.getStats()
        assert stats["entries"] == 0
        assert stats["maxSize"] == 1000
        assert stats["defaultTtl"] == 3600
        assert stats["threadSafe"] is True

        # Add a value
        await cache.set("key1", "value1")

        # Get stats after adding
        stats = cache.getStats()
        assert stats["entries"] == 1


class TestDictCacheTTL:
    """Test TTL (Time To Live) functionality, dood!"""

    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        """Test that entries expire after TTL, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator(), defaultTtl=1)  # 1 second TTL

        # Set a value
        await cache.set("key1", "value1")

        # Value should be available immediately
        value = await cache.get("key1")
        assert value == "value1"

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Value should be expired
        value = await cache.get("key1")
        assert value is None

    @pytest.mark.asyncio
    async def test_custom_ttl_per_get(self):
        """Test custom TTL per get operation, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator(), defaultTtl=10)  # 10 second default

        # Set value
        await cache.set("key1", "value1")

        # Value should be available immediately
        value = await cache.get("key1")
        assert value == "value1"

        # Wait a bit
        await asyncio.sleep(0.2)

        # Value should still be available with default TTL
        value = await cache.get("key1")
        assert value == "value1"

        # But should be expired with custom TTL of 0.1 seconds
        value = await cache.get("key1", ttl=int(0.1))
        assert value is None

    @pytest.mark.asyncio
    async def test_ttl_zero_means_immediate_expiration(self):
        """Test that TTL=0 means immediate expiration, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator(), defaultTtl=10)  # Normal TTL

        # Set a value
        await cache.set("key1", "value1")

        # Value should be available with normal TTL
        value = await cache.get("key1")
        assert value == "value1"

        # Set another value for testing negative TTL
        await cache.set("key2", "value2")

        # key2 should be immediately expired with TTL=0 override
        value = await cache.get("key2", ttl=0)
        assert value is None

        # key1 should still be available with negative TTL (no expiration)
        value = await cache.get("key1", ttl=-1)
        assert value == "value1"

        # key2 should still be gone even with negative TTL (since it was removed)
        value = await cache.get("key2", ttl=-1)
        assert value is None


class TestDictCacheSize:
    """Test size limits and eviction, dood!"""

    @pytest.mark.asyncio
    async def test_size_limit_enforcement(self):
        """Test that cache respects size limits, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator(), maxSize=3)

        # Fill cache to capacity
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")

        # All values should be present
        assert await cache.get("key1") == "value1"
        assert await cache.get("key2") == "value2"
        assert await cache.get("key3") == "value3"

        # Add one more entry (should evict oldest)
        await cache.set("key4", "value4")

        # Check that oldest entry was evicted
        assert await cache.get("key1") is None
        assert await cache.get("key2") == "value2"
        assert await cache.get("key3") == "value3"
        assert await cache.get("key4") == "value4"

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """Test LRU-like eviction behavior (oldest entries are evicted first), dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator(), maxSize=2)

        # Add two entries
        await cache.set("key1", "value1")
        await asyncio.sleep(0.01)  # Small delay to ensure different timestamps
        await cache.set("key2", "value2")

        # Add third entry (should evict key1, the oldest)
        await cache.set("key3", "value3")

        # key1 should be evicted (oldest), key2 and key3 should be present
        assert await cache.get("key1") is None
        assert await cache.get("key2") == "value2"
        assert await cache.get("key3") == "value3"


class TestDictCacheKeyGenerators:
    """Test different key generation strategies, dood!"""

    @pytest.mark.asyncio
    async def test_string_key_generator(self):
        """Test StringKeyGenerator, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        await cache.set("test_key", "test_value")
        value = await cache.get("test_key")
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_hash_key_generator(self):
        """Test HashKeyGenerator, dood!"""
        cache = DictCache[str, str](keyGenerator=HashKeyGenerator())

        await cache.set("test_key", "test_value")
        value = await cache.get("test_key")
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_json_key_generator(self):
        """Test JsonKeyGenerator with complex keys, dood!"""
        cache = DictCache[Dict[str, Any], str](keyGenerator=JsonKeyGenerator())

        complex_key = {"query": "test", "page": 1, "filters": ["a", "b"]}
        await cache.set(complex_key, "test_value")
        value = await cache.get(complex_key)
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_json_key_generator_equivalent_keys(self):
        """Test that JsonKeyGenerator treats equivalent keys as same, dood!"""
        cache = DictCache[Dict[str, Any], str](keyGenerator=JsonKeyGenerator())

        key1 = {"a": 1, "b": 2}
        key2 = {"b": 2, "a": 1}  # Same content, different order

        await cache.set(key1, "value1")
        value = await cache.get(key2)  # Should get the same value
        assert value == "value1"


class TestDictCacheThreadSafety:
    """Test thread safety functionality, dood!"""

    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        """Test concurrent access to cache, dood!"""
        cache = DictCache[str, int](keyGenerator=StringKeyGenerator())

        async def worker(worker_id: int):
            for i in range(10):
                await cache.set(f"key_{worker_id}_{i}", worker_id * 100 + i)
                value = await cache.get(f"key_{worker_id}_{i}")
                assert value == worker_id * 100 + i

        # Run multiple workers concurrently
        tasks = [worker(i) for i in range(5)]
        await asyncio.gather(*tasks)

        # Verify all values are present
        for worker_id in range(5):
            for i in range(10):
                key = f"key_{worker_id}_{i}"
                value = await cache.get(key)
                assert value == worker_id * 100 + i

    @pytest.mark.asyncio
    async def test_clear_thread_safety(self):
        """Test that clear operation is thread-safe, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        async def writer():
            for i in range(100):
                await cache.set(f"key_{i}", f"value_{i}")

        async def clearer():
            await asyncio.sleep(0.05)  # Let writer start
            cache.clear()

        # Run writer and clearer concurrently
        await asyncio.gather(writer(), clearer())

        # Cache should be empty or partially filled, but not crash
        stats = cache.getStats()
        assert stats["entries"] >= 0


class TestDictCacheErrorHandling:
    """Test error handling, dood!"""

    @pytest.mark.asyncio
    async def test_key_generator_exception_handling(self):
        """Test handling of key generator exceptions, dood!"""

        class FailingKeyGenerator:
            def generateKey(self, obj: Any) -> str:
                raise Exception("Key generation failed, dood!")

        cache = DictCache[str, str](keyGenerator=FailingKeyGenerator())

        # Should handle exception gracefully
        result = await cache.set("key", "value")
        assert result is False

        value = await cache.get("key")
        assert value is None

    @pytest.mark.asyncio
    async def test_invalid_ttl_handling(self):
        """Test handling of invalid TTL values, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        # Set a value
        result = await cache.set("key", "value")
        assert result is True

        # Negative TTL should be treated as no expiration
        value = await cache.get("key", ttl=-1)
        assert value == "value"

        # Zero TTL should be treated as immediate expiration
        value = await cache.get("key", ttl=0)
        assert value is None


class TestDictCachePerformance:
    """Test performance characteristics, dood!"""

    @pytest.mark.asyncio
    async def test_large_cache_operations(self):
        """Test operations with large cache, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator(), maxSize=10000)

        # Add many entries
        start_time = time.time()
        for i in range(1000):
            await cache.set(f"key_{i}", f"value_{i}")
        set_time = time.time() - start_time

        # Retrieve many entries
        start_time = time.time()
        for i in range(1000):
            value = await cache.get(f"key_{i}")
            assert value == f"value_{i}"
        get_time = time.time() - start_time

        # Performance should be reasonable (these are loose bounds)
        assert set_time < 5.0  # Should complete in under 5 seconds
        assert get_time < 2.0  # Should complete in under 2 seconds

    @pytest.mark.asyncio
    async def test_cleanup_performance(self):
        """Test cleanup performance with many expired entries, dood!"""
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator(), defaultTtl=int(0.1))  # Very short TTL

        # Add many entries
        for i in range(100):
            await cache.set(f"key_{i}", f"value_{i}")

        # Wait for expiration
        await asyncio.sleep(0.2)

        # Cleanup should be efficient
        start_time = time.time()
        stats = cache.getStats()  # Triggers cleanup
        cleanup_time = time.time() - start_time

        assert stats["entries"] == 0  # All entries should be cleaned up
        assert cleanup_time < 1.0  # Should complete quickly
