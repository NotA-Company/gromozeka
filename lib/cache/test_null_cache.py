"""
Tests for NullCache implementation.

This module contains comprehensive tests for the NullCache class to ensure it
behaves as a proper no-op cache implementation. The tests verify that all cache
operations are no-ops and that the cache maintains no internal state.
"""

from typing import Any, Dict

import pytest

from .null_cache import NullCache


class TestNullCache:
    """Test cases for NullCache class.

    This test class verifies that NullCache behaves as a proper no-op cache
    implementation, ensuring that all operations return expected values without
    maintaining any internal state.
    """

    def setup_method(self) -> None:
        """Set up test fixtures before each test method.

        Creates a new NullCache instance with string keys and Any values for
        each test to ensure test isolation.
        """
        self.cache: NullCache[str, Any] = NullCache[str, Any]()

    @pytest.mark.asyncio
    async def test_get_always_returns_none(self) -> None:
        """Test that get() always returns None.

        Verifies that the get method returns None for all keys, including
        empty strings, numeric strings, and with various TTL parameters.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        # Test with various keys
        assert await self.cache.get("test_key") is None
        assert await self.cache.get("another_key") is None
        assert await self.cache.get("") is None
        assert await self.cache.get("123") is None

        # Test with TTL parameter
        assert await self.cache.get("test_key", ttl=60) is None
        assert await self.cache.get("test_key", ttl=0) is None
        assert await self.cache.get("test_key", ttl=None) is None

    @pytest.mark.asyncio
    async def test_set_always_returns_true(self) -> None:
        """Test that set() always returns True.

        Verifies that the set method returns True for all value types including
        strings, integers, dictionaries, lists, and None.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        # Test with various values
        assert await self.cache.set("key1", "value1") is True
        assert await self.cache.set("key2", 123) is True
        assert await self.cache.set("key3", {"nested": "dict"}) is True
        assert await self.cache.set("key4", [1, 2, 3]) is True
        assert await self.cache.set("key5", None) is True

    @pytest.mark.asyncio
    async def test_set_get_combination(self) -> None:
        """Test that set() followed by get() still returns None.

        Verifies that setting a value and immediately retrieving it returns None,
        confirming that no state is maintained.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        # Set a value
        result = await self.cache.set("test_key", "test_value")
        assert result is True

        # Try to get it back - should still be None
        retrieved = await self.cache.get("test_key")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_clear_does_nothing(self) -> None:
        """Test that clear() does nothing without errors.

        Verifies that the clear method can be called multiple times without
        raising exceptions, confirming it's a no-op operation.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        # Should not raise any exceptions
        await self.cache.clear()

        # Multiple calls should also be fine
        await self.cache.clear()
        await self.cache.clear()

    def test_get_stats_returns_disabled(self) -> None:
        """Test that getStats() returns cache disabled indicator.

        Verifies that getStats returns a dictionary with enabled: False,
        indicating the cache is disabled.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        stats = self.cache.getStats()

        # Should return dict with enabled: False
        assert isinstance(stats, dict)
        assert "enabled" in stats
        assert stats["enabled"] is False

        # Should be the only key
        assert len(stats) == 1

    def test_generic_type_support(self) -> None:
        """Test that NullCache works with different generic types.

        Verifies that NullCache can be instantiated with various type
        combinations including int/str, str/dict, and tuple/list.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        # Test with int keys and str values
        int_str_cache = NullCache[int, str]()
        assert isinstance(int_str_cache, NullCache)

        # Test with str keys and dict values
        str_dict_cache = NullCache[str, Dict[str, Any]]()
        assert isinstance(str_dict_cache, NullCache)

        # Test with complex types
        complex_cache = NullCache[tuple, list]()
        assert isinstance(complex_cache, NullCache)

    @pytest.mark.asyncio
    async def test_no_internal_state(self) -> None:
        """Test that NullCache maintains no internal state.

        Verifies that multiple NullCache instances behave identically and
        maintain no shared state, confirming the no-op behavior.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        # Create multiple instances
        cache1 = NullCache[str, Any]()
        cache2 = NullCache[str, Any]()

        # Both should behave identically
        assert await cache1.get("key") is None
        assert await cache2.get("key") is None

        assert await cache1.set("key", "value") is True
        assert await cache2.set("key", "value") is True

        # Both should still return None for get
        assert await cache1.get("key") is None
        assert await cache2.get("key") is None

        # Stats should be identical
        assert cache1.getStats() == cache2.getStats()

    @pytest.mark.asyncio
    async def test_edge_cases(self) -> None:
        """Test edge cases and unusual inputs.

        Verifies that NullCache handles None keys, complex objects as keys
        and values, and other edge cases without errors.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        # Test with None as key (if type allows)
        none_cache = NullCache[Any, Any]()
        assert await none_cache.get(None) is None
        assert await none_cache.set(None, "value") is True

        # Test with complex objects as keys and values
        complex_key = {"complex": "key", "nested": {"data": 123}}
        complex_value = {"value": {"nested": [1, 2, 3]}}

        complex_cache = NullCache[Dict[str, Any], Dict[str, Any]]()
        assert await complex_cache.get(complex_key) is None
        assert await complex_cache.set(complex_key, complex_value) is True
        assert await complex_cache.get(complex_key) is None

    def test_interface_compliance(self) -> None:
        """Test that NullCache properly implements CacheInterface.

        Verifies that NullCache is an instance of CacheInterface and has all
        required methods (get, set, clear, getStats) that are callable.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        from .interface import CacheInterface

        # Should be instance of CacheInterface
        assert isinstance(self.cache, CacheInterface)

        # Should have all required methods
        assert hasattr(self.cache, "get")
        assert hasattr(self.cache, "set")
        assert hasattr(self.cache, "clear")
        assert hasattr(self.cache, "getStats")

        # Methods should be callable
        assert callable(getattr(self.cache, "get"))
        assert callable(getattr(self.cache, "set"))
        assert callable(getattr(self.cache, "clear"))
        assert callable(getattr(self.cache, "getStats"))


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])
