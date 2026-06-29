"""
Test suite for lib/utils/ttl_dict.py
"""

import time
import unittest

from lib.utils.ttl_dict import TTLDict


class TestTTLDictBasic(unittest.TestCase):
    """Test basic TTLDict functionality"""

    def test_init_empty(self) -> None:
        """Test creating an empty TTLDict"""
        d = TTLDict[str, int]()
        self.assertEqual(len(d), 0)
        self.assertIsNone(d.defaultTTL)
        self.assertEqual(d.gcTimeout, 60)

    def test_init_with_dict(self) -> None:
        """Test creating TTLDict with initial dict"""
        d = TTLDict[str, int]({"a": 1, "b": 2})
        self.assertEqual(len(d), 2)
        self.assertEqual(d["a"], 1)
        self.assertEqual(d["b"], 2)

    def test_init_with_kwargs(self) -> None:
        """Test creating TTLDict with keyword arguments"""
        d = TTLDict[str, int](a=1, b=2)
        self.assertEqual(len(d), 2)
        self.assertEqual(d["a"], 1)
        self.assertEqual(d["b"], 2)

    def test_init_with_default_ttl_kwarg(self) -> None:
        """Regression: ``TTLDict(defaultTtl=...)`` must set ``defaultTTL``.

        Previously the kwarg was silently swallowed by the underlying
        ``dict.__init__`` and stored as a string key (``{"defaultTtl": 300}``),
        leaving ``defaultTTL`` as ``None`` so entries never expired. The
        ``ChatMessagesRepository`` embedding cache relied on this kwarg, so
        the cache-TTL config from TOML had no effect at runtime.
        """
        d = TTLDict[str, int](defaultTtl=300)
        self.assertEqual(d.defaultTTL, 300)
        # The buggy behaviour would have left a stray key in the dict.
        self.assertNotIn("defaultTtl", d)

    def test_init_with_default_ttl_none(self) -> None:
        """``TTLDict(defaultTtl=None)`` is equivalent to omitting the kwarg."""
        d = TTLDict[str, int](defaultTtl=None)
        self.assertIsNone(d.defaultTTL)
        self.assertEqual(len(d), 0)


class TestTTLDictGetSetDel(unittest.TestCase):
    """Test TTLDict get, set, and del operations"""

    def test_setitem_getitem(self) -> None:
        """Test setting and getting items"""
        d = TTLDict[str, int]()
        d["a"] = 1
        self.assertEqual(d["a"], 1)

    def test_setitem_with_default_ttl(self) -> None:
        """Test setting items with default TTL"""
        d = TTLDict[str, int]()
        d.setDefaultTTL(60)
        d["a"] = 1
        self.assertEqual(d["a"], 1)
        # Entry should still be accessible immediately
        self.assertIn("a", d)

    def test_setitem_override(self) -> None:
        """Test overriding existing items"""
        d = TTLDict[str, int]()
        d["a"] = 1
        d["a"] = 2
        self.assertEqual(d["a"], 2)
        self.assertEqual(len(d), 1)

    def test_delitem(self) -> None:
        """Test deleting items"""
        d = TTLDict[str, int]()
        d["a"] = 1
        del d["a"]
        self.assertNotIn("a", d)
        self.assertEqual(len(d), 0)

    def test_delitem_nonexistent(self) -> None:
        """Test deleting non-existent item raises KeyError"""
        d = TTLDict[str, int]()
        with self.assertRaises(KeyError):
            del d["nonexistent"]

    def test_getitem_nonexistent(self) -> None:
        """Test getting non-existent item raises KeyError"""
        d = TTLDict[str, int]()
        with self.assertRaises(KeyError):
            value = d["nonexistent"]  # noqa: F841


class TestTTLDictContains(unittest.TestCase):
    """Test TTLDict contains operation"""

    def test_contains_exists(self) -> None:
        """Test contains returns True for existing key"""
        d = TTLDict[str, int]()
        d["a"] = 1
        self.assertIn("a", d)
        self.assertTrue("a" in d)

    def test_contains_not_exists(self) -> None:
        """Test contains returns False for non-existent key"""
        d = TTLDict[str, int]()
        d["a"] = 1
        self.assertNotIn("b", d)
        self.assertFalse("b" in d)


class TestTTLDictLen(unittest.TestCase):
    """Test TTLDict length operation"""

    def test_len_empty(self) -> None:
        """Test length of empty dict"""
        d = TTLDict[str, int]()
        self.assertEqual(len(d), 0)

    def test_len_single(self) -> None:
        """Test length of dict with one item"""
        d = TTLDict[str, int]()
        d["a"] = 1
        self.assertEqual(len(d), 1)

    def test_len_multiple(self) -> None:
        """Test length of dict with multiple items"""
        d = TTLDict[str, int]()
        d["a"] = 1
        d["b"] = 2
        d["c"] = 3
        self.assertEqual(len(d), 3)


class TestTTLDictIteration(unittest.TestCase):
    """Test TTLDict iteration operations"""

    def test_iter_keys(self) -> None:
        """Test iterating over keys"""
        d = TTLDict[str, int]()
        d["a"] = 1
        d["b"] = 2
        d["c"] = 3
        keys = list(d)
        self.assertIn("a", keys)
        self.assertIn("b", keys)
        self.assertIn("c", keys)

    def test_keys_method(self) -> None:
        """Test keys() method"""
        d = TTLDict[str, int]()
        d["a"] = 1
        d["b"] = 2
        keys = d.keys()
        self.assertIn("a", keys)
        self.assertIn("b", keys)

    def test_values_method(self) -> None:
        """Test values() method"""
        d = TTLDict[str, int]()
        d["a"] = 1
        d["b"] = 2
        values = d.values()
        self.assertIn(1, values)
        self.assertIn(2, values)

    def test_items_method(self) -> None:
        """Test items() method"""
        d = TTLDict[str, int]()
        d["a"] = 1
        d["b"] = 2
        items = d.items()
        self.assertIn(("a", 1), items)
        self.assertIn(("b", 2), items)


class TestTTLDictGet(unittest.TestCase):
    """Test TTLDict get method"""

    def test_get_exists(self) -> None:
        """Test get returns value for existing key"""
        d = TTLDict[str, int]()
        d["a"] = 1
        self.assertEqual(d.get("a"), 1)

    def test_get_not_exists_no_default(self) -> None:
        """Test get returns None for non-existent key without default"""
        d = TTLDict[str, int]()
        self.assertIsNone(d.get("nonexistent"))

    def test_get_not_exists_with_default(self) -> None:
        """Test get returns default for non-existent key with default"""
        d = TTLDict[str, int]()
        self.assertEqual(d.get("nonexistent", 42), 42)


class TestTTLDictPop(unittest.TestCase):
    """Test TTLDict pop method"""

    def test_pop_exists(self) -> None:
        """Test pop removes and returns value"""
        d = TTLDict[str, int]()
        d["a"] = 1
        self.assertEqual(d.pop("a"), 1)
        self.assertNotIn("a", d)

    def test_pop_not_exists_no_default(self) -> None:
        """Test pop returns None for non-existent key without default"""
        d = TTLDict[str, int]()
        self.assertIsNone(d.pop("nonexistent"))

    def test_pop_not_exists_with_default(self) -> None:
        """Test pop returns default for non-existent key with default"""
        d = TTLDict[str, int]()
        self.assertEqual(d.pop("nonexistent", 42), 42)


class TestTTLDictPopitem(unittest.TestCase):
    """Test TTLDict popitem method"""

    def test_popitem(self) -> None:
        """Test popitem removes and returns (key, value) tuple"""
        d = TTLDict[str, int]()
        d["a"] = 1
        d["b"] = 2
        key, value = d.popitem()
        self.assertIn(key, ["a", "b"])
        self.assertIn(value, [1, 2])
        self.assertEqual(len(d), 1)

    def test_popitem_empty(self) -> None:
        """Test popitem raises KeyError on empty dict"""
        d = TTLDict[str, int]()
        with self.assertRaises(KeyError):
            d.popitem()


class TestTTLDictClear(unittest.TestCase):
    """Test TTLDict clear method"""

    def test_clear(self) -> None:
        """Test clear removes all items"""
        d = TTLDict[str, int]()
        d["a"] = 1
        d["b"] = 2
        d.clear()
        self.assertEqual(len(d), 0)
        self.assertNotIn("a", d)
        self.assertNotIn("b", d)


class TestTTLDictUpdate(unittest.TestCase):
    """Test TTLDict update method"""

    def test_update_with_dict(self) -> None:
        """Test update with dictionary"""
        d = TTLDict[str, int]()
        d.setDefaultTTL(60)
        d.update({"a": 1, "b": 2})
        self.assertEqual(d["a"], 1)
        self.assertEqual(d["b"], 2)

    def test_update_with_kwargs(self) -> None:
        """Test update with keyword arguments"""
        d = TTLDict[str, int]()
        d.setDefaultTTL(60)
        d.update(a=1, b=2)
        self.assertEqual(d["a"], 1)
        self.assertEqual(d["b"], 2)

    def test_update_override(self) -> None:
        """Test update overrides existing keys"""
        d = TTLDict[str, int]()
        d["a"] = 1
        d.update({"a": 2})
        self.assertEqual(d["a"], 2)


class TestTTLDictSetdefault(unittest.TestCase):
    """Test TTLDict setdefault method"""

    def test_setdefault_exists(self) -> None:
        """Test setdefault returns existing value"""
        d = TTLDict[str, int]()
        d["a"] = 1
        self.assertEqual(d.setdefault("a", 42), 1)
        self.assertEqual(d["a"], 1)

    def test_setdefault_not_exists(self) -> None:
        """Test setdefault sets and returns default value"""
        d = TTLDict[str, int]()
        self.assertEqual(d.setdefault("a", 42), 42)
        self.assertEqual(d["a"], 42)

    def test_setdefault_none_default(self) -> None:
        """Test setdefault with None default"""
        d = TTLDict[str, int]()
        self.assertIsNone(d.setdefault("a"))
        self.assertIsNone(d["a"])


class TestTTLDictTTLMethods(unittest.TestCase):
    """Test TTLDict TTL-specific methods"""

    def test_set_default_ttl(self) -> None:
        """Test setDefaultTTL method"""
        d = TTLDict[str, int]()
        d.setDefaultTTL(60)
        self.assertEqual(d.defaultTTL, 60)

    def test_set_default_ttl_none(self) -> None:
        """Test setDefaultTTL with None"""
        d = TTLDict[str, int]()
        d.setDefaultTTL(None)
        self.assertIsNone(d.defaultTTL)

    def test_set_gc_timeout(self) -> None:
        """Test setGCTimeout method"""
        d = TTLDict[str, int]()
        d.setGCTimeout(30)
        self.assertEqual(d.gcTimeout, 30)

    def test_set_method_with_ttl(self) -> None:
        """Test set method with custom TTL"""
        d = TTLDict[str, int]()
        d.set("a", 1, ttl=10)
        self.assertEqual(d["a"], 1)

    def test_set_method_with_none_ttl(self) -> None:
        """Test set method with None TTL"""
        d = TTLDict[str, int]()
        d.setDefaultTTL(60)
        d.set("a", 1, ttl=None)
        self.assertEqual(d["a"], 1)


class TestTTLDictExpiration(unittest.TestCase):
    """Test TTLDict expiration functionality"""

    def test_gc_force_true(self) -> None:
        """Test gc with force=True always runs"""
        d = TTLDict[str, int]()
        d.setDefaultTTL(60)
        d["a"] = 1
        removed = d.gc(force=True)
        # Should return 0 (no expired entries)
        self.assertEqual(removed, 0)

    def test_gc_force_false_respects_timeout(self) -> None:
        """Test gc with force=False respects gcTimeout"""
        d = TTLDict[str, int]()
        d.setGCTimeout(60)
        d["a"] = 1
        # First GC should run (lastGC = 0)
        removed1 = d.gc(force=False)
        self.assertEqual(removed1, 0)
        # Immediate second GC should not run
        removed2 = d.gc(force=False)
        self.assertEqual(removed2, 0)

    def test_gc_removes_expired_entries(self) -> None:
        """Test gc removes expired entries"""
        d = TTLDict[str, int]()
        d.setDefaultTTL(1)
        d["a"] = 1
        d["b"] = 2
        time.sleep(2)
        removed = d.gc(force=True)
        self.assertEqual(removed, 2)
        self.assertEqual(len(d), 0)
        self.assertNotIn("a", d)
        self.assertNotIn("b", d)

    def test_expired_entries_accessible_until_gc(self) -> None:
        """Test expired entries are accessible until GC runs"""
        d = TTLDict[str, int]()
        d.set("a", 1, ttl=1)
        d.set("b", 2, ttl=1)
        # Immediately, entries should be accessible
        self.assertEqual(d["a"], 1)
        self.assertEqual(d["b"], 2)
        # Wait for expiration
        time.sleep(2)
        # Entries should still be accessible before GC
        self.assertEqual(d["a"], 1)
        self.assertEqual(d["b"], 2)
        # Run GC
        d.gc(force=True)
        # Now they should be gone
        self.assertNotIn("a", d)
        self.assertNotIn("b", d)

    def test_none_ttl_never_expires(self) -> None:
        """Test entries with ttl=None never expire"""
        d = TTLDict[str, int]()
        d["a"] = 1  # No default TTL set
        time.sleep(2)
        d.gc(force=True)
        self.assertIn("a", d)
        self.assertEqual(d["a"], 1)

    def test_default_ttl_none_with_custom_ttl(self) -> None:
        """Test default TTL=None with custom TTL works"""
        d = TTLDict[str, int]()
        d.setDefaultTTL(None)
        d["a"] = 1  # No expiration
        d.set("b", 2, ttl=1)  # Custom TTL
        time.sleep(2)
        d.gc(force=True)
        self.assertIn("a", d)
        self.assertNotIn("b", d)

    def test_set_ttl_none_clears_previous_expiration(self) -> None:
        """Test that rewriting a key with ttl=None clears the old expiration.

        Regression test: previously, set(key, value, ttl=None) left the old
        expiration timestamp in _expirations, causing the entry to expire at
        the original deadline despite the caller's intent to make it non-expiring.
        """
        d = TTLDict[str, int]()
        # Set a key with a short TTL
        d.set("key", 1, ttl=1)
        # Overwrite the same key with ttl=None — should clear the old expiration
        d.set("key", 2, ttl=None)
        # Sleep past the original 1-second deadline
        time.sleep(2)
        # Force GC — the entry must still exist because ttl=None cleared the expiration
        d.gc(force=True)
        self.assertIn("key", d)
        self.assertEqual(d["key"], 2)

    def test_set_default_ttl_none_clears_previous_expiration(self) -> None:
        """Test that rewriting a key with defaultTTL=None clears the old expiration.

        When defaultTTL is None and set() is called without an explicit ttl,
        actualTTL resolves to None, which should also clear any previous expiration.
        """
        d = TTLDict[str, int]()
        # Set a key with a short TTL
        d.set("key", 1, ttl=1)
        # Overwrite using defaultTTL=None (no explicit ttl argument)
        d.setDefaultTTL(None)
        d.set("key", 2)
        # Sleep past the original 1-second deadline
        time.sleep(2)
        d.gc(force=True)
        self.assertIn("key", d)
        self.assertEqual(d["key"], 2)

    def test_mixed_ttl_values(self) -> None:
        """Test mixing different TTL values"""
        d = TTLDict[str, int]()
        d.setDefaultTTL(2)
        d["a"] = 1  # Default 2s
        d.set("b", 2, ttl=1)  # Custom 1s
        d.set("c", 3, ttl=None)  # Never expires
        time.sleep(1.5)
        d.gc(force=True)
        # b should be expired, a and c should remain
        self.assertIn("a", d)
        self.assertNotIn("b", d)
        self.assertIn("c", d)
        time.sleep(1)
        d.gc(force=True)
        # a should now be expired too
        self.assertNotIn("a", d)
        self.assertIn("c", d)

    def test_update_preserves_expiration_state(self) -> None:
        """Test that expired entries are not resurrected by update"""
        d = TTLDict[str, int]()
        d.set("a", 1, ttl=1)
        time.sleep(2)
        d.gc(force=True)
        self.assertNotIn("a", d)
        d.update({"a": 2})
        self.assertEqual(d["a"], 2)

    def test_gc_called_after_set(self) -> None:
        """Test that gc is called after every set operation"""
        d = TTLDict[str, int]()
        d.setGCTimeout(0)  # No timeout, always run
        d.setDefaultTTL(1)
        d["a"] = 1
        time.sleep(2)
        # Set operation should trigger GC
        d["b"] = 2
        # a should be removed by now
        self.assertNotIn("a", d)


class TestTTLDictThreadSafety(unittest.TestCase):
    """Test TTLDict thread safety"""

    def test_concurrent_sets(self) -> None:
        """Test concurrent set operations"""
        import threading

        d = TTLDict[int, int]()
        results = []

        def worker(threadId: int) -> None:
            for i in range(100):
                d[threadId * 100 + i] = i
            results.append(threadId)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should complete
        self.assertEqual(len(results), 5)
        # Should have 500 items
        self.assertEqual(len(d), 500)

    def test_concurrent_gc(self) -> None:
        """Test concurrent GC operations"""
        import threading

        d = TTLDict[int, int]()
        d.setDefaultTTL(1)
        errors = []

        def add_worker() -> None:
            try:
                for i in range(100):
                    d[i] = i
            except Exception as e:
                errors.append(e)

        def gc_worker() -> None:
            try:
                for _ in range(50):
                    d.gc(force=True)
            except Exception as e:
                errors.append(e)

        add_thread = threading.Thread(target=add_worker)
        gc_thread = threading.Thread(target=gc_worker)

        add_thread.start()
        gc_thread.start()
        add_thread.join()
        gc_thread.join()

        # No errors should have occurred
        self.assertEqual(len(errors), 0)


class TestTTLDictEdgeCases(unittest.TestCase):
    """Test TTLDict edge cases"""

    def test_zero_ttl(self) -> None:
        """Test TTL of 0 seconds works"""
        d = TTLDict[str, int]()
        d.set("a", 1, ttl=0)
        # Should be accessible immediately
        self.assertEqual(d["a"], 1)
        # Run GC
        d.gc(force=True)
        # Should be expired
        self.assertNotIn("a", d)

    def test_large_ttl(self) -> None:
        """Test very large TTL values"""
        d = TTLDict[str, int]()
        large_ttl = 365 * 24 * 60 * 60  # 1 year
        d.set("a", 1, ttl=large_ttl)
        d.gc(force=True)
        self.assertIn("a", d)

    def test_update_empty_dict(self) -> None:
        """Test update with empty dict does nothing"""
        d = TTLDict[str, int]()
        d.update({})
        self.assertEqual(len(d), 0)

    def test_setdefault_with_existing_expired(self) -> None:
        """Test setdefault with expired key"""
        d = TTLDict[str, int]()
        d.set("a", 1, ttl=1)
        time.sleep(2)
        d.gc(force=True)
        # Key should be gone
        self.assertNotIn("a", d)
        # setdefault should work
        result = d.setdefault("a", 42)
        self.assertEqual(result, 42)
        self.assertEqual(d["a"], 42)

    def test_pop_expired_key(self) -> None:
        """Test pop on expired key"""
        d = TTLDict[str, int]()
        d.set("a", 1, ttl=1)
        time.sleep(2)
        d.gc(force=True)
        # Key should be gone
        self.assertNotIn("a", d)
        # pop should return default
        self.assertEqual(d.pop("a", 42), 42)

    def test_iter_after_gc(self) -> None:
        """Test iteration works correctly after GC"""
        d = TTLDict[str, int]()
        d.setDefaultTTL(1)
        d["a"] = 1
        d["b"] = 2
        d.set("c", 3, ttl=None)
        time.sleep(2)
        d.gc(force=True)
        # Only c should remain
        items = list(d.items())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0], ("c", 3))


if __name__ == "__main__":
    unittest.main()
