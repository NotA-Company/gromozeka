"""
TTL (Time-To-Live) dictionary implementation.

This module provides a dict-like class that supports automatic expiration of entries
based on a configurable time-to-live. The TTLDict class is a drop-in replacement
for the built-in dict with additional features for managing entry lifetimes.

Example:
    >>> from lib.utils.ttl_dict import TTLDict
    >>> d = TTLDict()
    >>> d.setDefaultTTL(60)  # Set default TTL to 60 seconds
    >>> d["key1"] = "value1"  # Uses default TTL
    >>> d.set("key2", "value2", ttl=120)  # Custom TTL of 120 seconds
    >>> d.gc()  # Remove expired entries
"""

import time
from threading import RLock
from typing import Any, Dict, Optional, Self, Tuple, TypeVar

K = TypeVar("K")
V = TypeVar("V")


# Sentinel value to distinguish between "not provided" and "explicitly None"
class _TTLDictSentinel:
    __slots__ = ()


_UNSPECIFIED = _TTLDictSentinel()


class TTLDict(Dict[K, V]):
    """Dictionary with time-to-live (TTL) support for automatic entry expiration.

    This class extends the built-in dict to support TTL-based expiration of entries.
    Each entry can have its own TTL, or a default TTL can be configured. Expired
    entries are removed explicitly when gc() is called or automatically after
    set operations if the GC timeout has passed.

    Type Parameters:
        K: The type of keys in the dictionary
        V: The type of values in the dictionary

    Attributes:
        defaultTTL: Default time-to-live for new entries in seconds
        gcTimeout: Minimum seconds between GC operations when force=False
        lastGC: Timestamp of the last garbage collection

    Example:
        >>> d = TTLDict[str, int]()
        >>> d.setDefaultTTL(10)  # Default TTL of 10 seconds
        >>> d.set("a", 1, ttl=5)  # Custom TTL of 5 seconds
        >>> d["b"] = 2  # Uses default TTL of 10 seconds
        >>> d.set("c", 3, ttl=None)  # Never expires
        >>> d.gc(force=True)  # Remove expired entries
    """

    def __init__(self, *args: Any, defaultTtl: Optional[int] = None, **kwargs: Any) -> None:
        """Initialize TTLDict with optional initial data.

        Args:
            *args: Positional arguments passed to dict.__init__()
            defaultTtl: Optional default time-to-live in seconds applied to
                every entry inserted without an explicit ``ttl`` override.
                Mirrors :meth:`setDefaultTTL`. ``None`` (the default) means
                entries never expire unless an explicit TTL is supplied at
                insertion time.
            **kwargs: Keyword arguments passed to dict.__init__()
        """
        super().__init__(*args, **kwargs)
        self.defaultTTL: Optional[int] = defaultTtl
        self.gcTimeout: int = 60
        self.lastGC: float = time.time()  # Initialize to current time to avoid premature GC on first call
        self._lock: RLock = RLock()
        self._expirations: Dict[K, Optional[float]] = {}

    def setDefaultTTL(self, ttlSeconds: Optional[int]) -> Self:
        """Set the default TTL for new entries.

        Args:
            ttlSeconds: Default TTL in seconds for new entries. None means entries
                never expire by default.

        Example:
            >>> d = TTLDict()
            >>> d.setDefaultTTL(60)  # Entries expire after 60 seconds by default
            >>> d.setDefaultTTL(None)  # Entries never expire by default
        """
        with self._lock:
            self.defaultTTL = ttlSeconds

        # Return self for chaining ability
        return self

    def setGCTimeout(self, timeout: int) -> Self:
        """Set the minimum time between automatic GC operations.

        Args:
            timeout: Minimum seconds between GC operations when force=False

        Example:
            >>> d = TTLDict()
            >>> d.setGCTimeout(30)  # GC will only run if 30 seconds have passed
        """
        with self._lock:
            self.gcTimeout = timeout

        # Return self for chaining ability
        return self

    def gc(self, force: bool = False) -> int:
        """Remove expired entries from the dictionary.

        Args:
            force: If True, always remove expired entries. If False, only remove
                if the last GC was more than gcTimeout seconds ago.

        Returns:
            Number of entries removed

        Example:
            >>> d = TTLDict()
            >>> d.set("key", "value", ttl=1)
            >>> import time
            >>> time.sleep(2)
            >>> removed = d.gc(force=True)
            >>> print(f"Removed {removed} expired entries")
        """
        with self._lock:
            currentTime = time.time()

            # Check if we should run GC
            if not force and (currentTime - self.lastGC) < self.gcTimeout:
                return 0

            # Find and remove expired entries
            expiredKeys: list[K] = []
            for key, expiration in self._expirations.items():
                if expiration is not None and currentTime >= expiration:
                    expiredKeys.append(key)

            # Remove expired entries
            for key in expiredKeys:
                if key in self:
                    super().__delitem__(key)
                if key in self._expirations:
                    del self._expirations[key]

            self.lastGC = currentTime
            return len(expiredKeys)

    def set(self, key: K, value: V, ttl: Optional[int] | "_TTLDictSentinel" = _UNSPECIFIED) -> None:
        """Set a key-value pair with optional TTL.

        Args:
            key: The key to set
            value: The value to associate with the key
            ttl: Time-to-live in seconds for this entry. If not provided, uses defaultTTL.
                If None is explicitly passed, the entry never expires.

        Example:
            >>> d = TTLDict()
            >>> d.setDefaultTTL(60)
            >>> d.set("key1", "value1")  # Uses default TTL of 60 seconds
            >>> d.set("key2", "value2", ttl=120)  # Custom TTL of 120 seconds
            >>> d.set("key3", "value3", ttl=None)  # Never expires
        """
        with self._lock:
            # Use provided TTL or fall back to default
            if ttl is None or isinstance(ttl, int):
                actualTTL = ttl
            else:
                actualTTL = self.defaultTTL

            # Store the value and expiration
            super().__setitem__(key, value)
            if actualTTL is not None:
                self._expirations[key] = time.time() + actualTTL
            else:
                # Explicit ttl=None: clear any previous expiration so the entry never expires
                self._expirations.pop(key, None)

            # Run GC after setting
            self.gc(force=False)

    def __setitem__(self, key: K, value: V) -> None:
        """Set a key-value pair using the default TTL.

        Args:
            key: The key to set
            value: The value to associate with the key

        Note:
            To set a custom TTL, use the set() method instead.

        Example:
            >>> d = TTLDict()
            >>> d.setDefaultTTL(60)
            >>> d["key1"] = "value1"  # Uses default TTL of 60 seconds
        """
        self.set(key, value)

    def __delitem__(self, key: K) -> None:
        """Delete a key-value pair from the dictionary.

        Args:
            key: The key to delete

        Raises:
            KeyError: If the key is not found in the dictionary

        Example:
            >>> d = TTLDict()
            >>> d["temp"] = "temporary"
            >>> del d["temp"]
        """
        with self._lock:
            super().__delitem__(key)
            if key in self._expirations:
                del self._expirations[key]

    def pop(self, key: K, default: Optional[V] = None) -> Optional[V]:  # type: ignore[override]
        """Remove and return a value from the dictionary.

        Args:
            key: The key to pop
            default: The value to return if the key is not found (default: None)

        Returns:
            The value associated with the key, or the default if the key is not found

        Raises:
            KeyError: If the key is not found and no default is provided

        Example:
            >>> d = TTLDict()
            >>> d["a"] = 1
            >>> d["b"] = 2
            >>> d.pop("a")  # 1
            >>> d.pop("c", 0)  # 0
        """
        with self._lock:
            if key in self._expirations:
                del self._expirations[key]
            return super().pop(key, default)  # type: ignore[misc]

    def clear(self) -> None:
        """Remove all items from the dictionary.

        Example:
            >>> d = TTLDict()
            >>> d["a"] = 1
            >>> d["b"] = 2
            >>> d.clear()
            >>> len(d)  # 0
        """
        with self._lock:
            super().clear()
            self._expirations.clear()

    def setdefault(self, key: K, default: Optional[V] = None, /) -> Optional[V]:  # type: ignore[override]
        """Insert key with a value of default if key is not in the dictionary.

        Args:
            key: The key to set if not present
            default: The value to set if the key is not found (default: None)

        Returns:
            The value for key if key is in the dictionary, otherwise default

        Example:
            >>> d = TTLDict[str, int]()
            >>> d.setDefaultTTL(60)
            >>> d.setdefault("a", 1)  # 1
            >>> d.setdefault("a", 2)  # 1
        """
        with self._lock:
            if key in self:
                return self[key]
            result = super().setdefault(key, default)  # pyright: ignore[reportArgumentType]
            # Use default TTL, same as __setitem__ behavior
            if isinstance(self.defaultTTL, int):
                self._expirations[key] = time.time() + self.defaultTTL
            self.gc(force=False)
            return result

    def update(self, *args: Any, **kwargs: V) -> None:
        """Update the dictionary with the key-value pairs from other, overwriting existing keys.

        NOTE: This method WILL NOT update TTL for existing keys
        Args:
            *args: Positional arguments (dictionary or iterable of pairs)
            **kwargs: Keyword arguments to update from

        Example:
            >>> d = TTLDict[str, int]()
            >>> d.setDefaultTTL(60)
            >>> d.update({"a": 1, "b": 2})
            >>> d.update(c=3, d=4)
        """
        with self._lock:
            # Track which keys exist before the update
            beforeKeys = set(self.keys())

            # Perform the update
            super().update(*args, **kwargs)

            # Find which keys are new (not modified)
            afterKeys = set(self.keys())
            newKeys = afterKeys - beforeKeys

            # For new keys, set expiration to None (use default TTL)
            if self.defaultTTL is not None:
                expireAt = time.time() + self.defaultTTL
                for key in newKeys:
                    self._expirations[key] = expireAt

            self.gc(force=False)

    def popitem(self) -> Tuple[K, V]:
        """Remove and return a (key, value) pair from the dictionary.

        Returns:
            A (key, value) tuple

        Raises:
            KeyError: If the dictionary is empty

        Example:
            >>> d = TTLDict()
            >>> d["a"] = 1
            >>> d["b"] = 2
            >>> d.popitem()
        """
        with self._lock:
            key, value = super().popitem()
            if key in self._expirations:
                del self._expirations[key]
            return key, value

    def __repr__(self) -> str:
        """Return a string representation of the TTLDict.

        Returns:
            A string representation showing the dictionary contents and TTL settings

        Example:
            >>> d = TTLDict()
            >>> d["a"] = 1
            >>> repr(d)
        """
        return f"TTLDict({dict(self.items())}).setDefaultTTL({self.defaultTTL}).setGCTimeout({self.gcTimeout})"
