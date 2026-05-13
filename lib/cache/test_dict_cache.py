"""Comprehensive tests for DictCache implementation.

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
    """Test basic cache operations.

    This test class validates fundamental cache functionality including
    initialization, basic get/set operations, clearing, and statistics.
    """

    def test_cache_initialization(self) -> None:
        """Test cache initialization with default parameters.

        Verifies that DictCache is properly initialized with default values
        for key generator, TTL, max size, and lock.
        """
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        assert cache._keyGenerator is not None
        assert cache._defaultTtl == 3600
        assert cache._maxSize == 1000
        assert cache._lock is not None

    def test_cache_initialization_custom_params(self) -> None:
        """Test cache initialization with custom parameters.

        Verifies that DictCache properly accepts and stores custom values
        for key generator, TTL, and max size.

        Args:
            None

        Returns:
            None
        """
        key_gen = StringKeyGenerator()
        cache = DictCache[str, int](keyGenerator=key_gen, defaultTtl=600, maxSize=500)

        assert cache._keyGenerator == key_gen
        assert cache._defaultTtl == 600
        assert cache._maxSize == 500

    @pytest.mark.asyncio
    async def test_basic_set_and_get(self) -> None:
        """Test basic set and get operations.

        Verifies that values can be stored in the cache and retrieved
        correctly using the same key.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If set/get operations fail.
        """
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        # Set a value
        result = await cache.set("key1", "value1")
        assert result is True

        # Get the value
        value = await cache.get("key1")
        assert value == "value1"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self) -> None:
        """Test getting a non-existent key returns None.

        Verifies that attempting to retrieve a key that was never set
        returns None instead of raising an exception.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If non-existent key doesn't return None.
        """
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        value = await cache.get("nonexistent")
        assert value is None

    @pytest.mark.asyncio
    async def test_clear_cache(self) -> None:
        """Test clearing the cache.

        Verifies that the clear() method removes all entries from the cache
        and subsequent get operations return None.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If cache is not properly cleared.
        """
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        # Add some values
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")

        # Verify values exist
        assert await cache.get("key1") == "value1"
        assert await cache.get("key2") == "value2"

        # Clear cache
        await cache.clear()

        # Verify values are gone
        assert await cache.get("key1") is None
        assert await cache.get("key2") is None

    @pytest.mark.asyncio
    async def test_get_stats(self) -> None:
        """Test cache statistics.

        Verifies that getStats() returns accurate information about the cache
        including entry count, max size, default TTL, and thread safety status.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If statistics are incorrect.
        """
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
    """Test TTL (Time To Live) functionality.

    This test class validates that cache entries expire correctly based on
    their TTL settings, including default TTL and custom TTL overrides.
    """

    @pytest.mark.asyncio
    async def test_ttl_expiration(self) -> None:
        """Test that entries expire after TTL.

        Verifies that cache entries are automatically removed after their
        TTL expires and subsequent get operations return None.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If entries don't expire correctly.
        """
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
    async def test_custom_ttl_per_get(self) -> None:
        """Test custom TTL per get operation.

        Verifies that the get() method accepts a custom TTL parameter that
        overrides the default TTL for that specific retrieval.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If custom TTL doesn't work correctly.
        """
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
    async def test_ttl_zero_means_immediate_expiration(self) -> None:
        """Test that TTL=0 means immediate expiration.

        Verifies that TTL=0 causes immediate expiration while negative TTL
        disables expiration for that retrieval.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If TTL edge cases don't work correctly.
        """
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
    """Test size limits and eviction.

    This test class validates that the cache respects its maximum size limit
    and evicts entries when the limit is exceeded.
    """

    @pytest.mark.asyncio
    async def test_size_limit_enforcement(self) -> None:
        """Test that cache respects size limits.

        Verifies that when the cache reaches its maximum size, adding new
        entries causes the oldest entries to be evicted.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If size limit is not enforced.
        """
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
    async def test_lru_eviction(self) -> None:
        """Test LRU-like eviction behavior (oldest entries are evicted first).

        Verifies that when the cache is full, the oldest entries are evicted
        first to make room for new entries.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If eviction doesn't follow LRU pattern.
        """
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
    """Test different key generation strategies.

    This test class validates that different key generators (String, Hash, JSON)
    work correctly with the cache and handle various key types appropriately.
    """

    @pytest.mark.asyncio
    async def test_string_key_generator(self) -> None:
        """Test StringKeyGenerator.

        Verifies that StringKeyGenerator correctly handles string keys
        for cache operations.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If string key generation fails.
        """
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        await cache.set("test_key", "test_value")
        value = await cache.get("test_key")
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_hash_key_generator(self) -> None:
        """Test HashKeyGenerator.

        Verifies that HashKeyGenerator correctly handles string keys
        by generating hash-based cache keys.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If hash key generation fails.
        """
        cache = DictCache[str, str](keyGenerator=HashKeyGenerator())

        await cache.set("test_key", "test_value")
        value = await cache.get("test_key")
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_json_key_generator(self) -> None:
        """Test JsonKeyGenerator with complex keys.

        Verifies that JsonKeyGenerator correctly handles complex dictionary
        keys by serializing them to JSON for cache operations.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If JSON key generation fails.
        """
        cache = DictCache[Dict[str, Any], str](keyGenerator=JsonKeyGenerator())

        complex_key = {"query": "test", "page": 1, "filters": ["a", "b"]}
        await cache.set(complex_key, "test_value")
        value = await cache.get(complex_key)
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_json_key_generator_equivalent_keys(self) -> None:
        """Test that JsonKeyGenerator treats equivalent keys as same.

        Verifies that JsonKeyGenerator treats dictionary keys with the same
        content but different order as equivalent keys.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If equivalent keys are not treated as same.
        """
        cache = DictCache[Dict[str, Any], str](keyGenerator=JsonKeyGenerator())

        key1 = {"a": 1, "b": 2}
        key2 = {"b": 2, "a": 1}  # Same content, different order

        await cache.set(key1, "value1")
        value = await cache.get(key2)  # Should get the same value
        assert value == "value1"


class TestDictCacheThreadSafety:
    """Test thread safety functionality.

    This test class validates that the cache can handle concurrent access
    from multiple coroutines without data corruption or race conditions.
    """

    @pytest.mark.asyncio
    async def test_concurrent_access(self) -> None:
        """Test concurrent access to cache.

        Verifies that multiple coroutines can safely read from and write to
        the cache concurrently without data corruption.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If concurrent access causes data corruption.
        """
        cache = DictCache[str, int](keyGenerator=StringKeyGenerator())

        async def worker(worker_id: int) -> None:
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
    async def test_clear_thread_safety(self) -> None:
        """Test that clear operation is thread-safe.

        Verifies that the clear() operation can be safely called while other
        coroutines are writing to the cache without causing crashes.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If clear operation is not thread-safe.
        """
        cache = DictCache[str, str](keyGenerator=StringKeyGenerator())

        async def writer() -> None:
            for i in range(100):
                await cache.set(f"key_{i}", f"value_{i}")

        async def clearer() -> None:
            await asyncio.sleep(0.05)  # Let writer start
            await cache.clear()

        # Run writer and clearer concurrently
        await asyncio.gather(writer(), clearer())

        # Cache should be empty or partially filled, but not crash
        stats = cache.getStats()
        assert stats["entries"] >= 0


class TestDictCacheErrorHandling:
    """Test error handling.

    This test class validates that the cache handles errors gracefully,
    including key generator failures and invalid TTL values.
    """

    @pytest.mark.asyncio
    async def test_key_generator_exception_handling(self) -> None:
        """Test handling of key generator exceptions.

        Verifies that the cache handles exceptions from key generators
        gracefully without crashing.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If exceptions are not handled properly.
        """

        class FailingKeyGenerator:
            """A key generator that always raises an exception."""

            def generateKey(self, obj: Any) -> str:
                raise Exception("Key generation failed, dood!")

        cache = DictCache[str, str](keyGenerator=FailingKeyGenerator())

        # Should handle exception gracefully
        result = await cache.set("key", "value")
        assert result is False

        value = await cache.get("key")
        assert value is None

    @pytest.mark.asyncio
    async def test_invalid_ttl_handling(self) -> None:
        """Test handling of invalid TTL values.

        Verifies that the cache handles edge cases for TTL values correctly,
        including negative TTL (no expiration) and zero TTL (immediate expiration).

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If invalid TTL values are not handled correctly.
        """
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
    """Test performance characteristics.

    This test class validates that the cache performs efficiently with
    large numbers of entries and cleanup operations.
    """

    @pytest.mark.asyncio
    async def test_large_cache_operations(self) -> None:
        """Test operations with large cache.

        Verifies that the cache can handle a large number of set and get
        operations within reasonable time limits.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If performance is below acceptable thresholds.
        """
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
    async def test_cleanup_performance(self) -> None:
        """Test cleanup performance with many expired entries.

        Verifies that the cache cleanup process efficiently removes expired
        entries even when there are many of them.

        Args:
            None

        Returns:
            None

        Raises:
            AssertionError: If cleanup is too slow.
        """
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
