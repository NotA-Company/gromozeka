"""
Built-in key generator implementations for lib.cache, dood!

This module provides three standard key generator implementations that cover
the most common use cases for cache key generation, dood!

Available Generators:
    - StringKeyGenerator: Pass-through for string keys
    - HashKeyGenerator: SHA512 hash for complex objects using repr()
    - JsonKeyGenerator: JSON serialization + SHA512 hash for structured data
"""

import hashlib
from typing import Any

import lib.utils as utils

from .types import KeyGenerator


class StringKeyGenerator(KeyGenerator[str]):
    """
    Pass-through key generator for string keys, dood!

    This generator simply returns the input string as-is, making it ideal
    for cases where you already have well-formatted string keys and don't
    need any transformation, dood!

    Type: KeyGenerator[str]

    Example:
        >>> generator = StringKeyGenerator()
        >>> key = generator.generateKey("user:123")
        >>> print(key)  # "user:123"
        >>>
        >>> # Works with any string
        >>> key = generator.generateKey("cache:session:abc123")
        >>> print(key)  # "cache:session:abc123"

    Note:
        This generator validates that the input is actually a string.
        If you pass a non-string value, it will raise a TypeError, dood!
    """

    def generateKey(self, obj: str) -> str:
        """
        Generate cache key from string input, dood!

        Args:
            obj: String to use as cache key

        Returns:
            str: The same string passed as input

        Raises:
            TypeError: If obj is not a string

        Example:
            >>> generator = StringKeyGenerator()
            >>> key = generator.generateKey("test:key")
            >>> print(key)  # "test:key"
        """
        if not isinstance(obj, str):
            raise TypeError(f"StringKeyGenerator expects string input, got {type(obj).__name__}, dood!")

        return obj


class HashKeyGenerator(KeyGenerator[Any]):
    """
    SHA512 hash key generator for complex objects, dood!

    This generator converts any object to a string using repr() and then
    creates a SHA512 hash. It's perfect for complex objects, dictionaries,
    or any data structure that can be represented as a string, dood!

    Type: KeyGenerator[Any]

    Example:
        >>> generator = HashKeyGenerator()
        >>> key = generator.generateKey({"query": "test", "page": 1})
        >>> print(key)  # "a1b2c3d4e5f6..." (128-character SHA512 hash)
        >>>
        >>> # Works with any object
        >>> class User:
        ...     def __init__(self, id, name):
        ...         self.id = id
        ...         self.name = name
        >>> user = User(123, "Alice")
        >>> key = generator.generateKey(user)
        >>> print(key)  # "9f8e7d6c5b4a..." (128-character SHA512 hash)

    Note:
        The hash is deterministic - the same object will always produce
        the same hash. However, objects with the same logical content but
        different internal representations might produce different hashes, dood!
    """

    def generateKey(self, obj: Any) -> str:
        """
        Generate SHA512 hash from any object, dood!

        Args:
            obj: Any object to convert to cache key

        Returns:
            str: 128-character SHA512 hexadecimal hash

        Example:
            >>> generator = HashKeyGenerator()
            >>> key = generator.generateKey({"a": 1, "b": 2})
            >>> print(len(key))  # 128
            >>> print(key[:10])  # First 10 chars of hash
        """
        if obj is None:
            # Handle None explicitly to avoid issues with repr(None)
            obj_str = "None"
        else:
            # Use repr() to get string representation
            obj_str = repr(obj)

        # Create SHA512 hash
        return hashlib.sha512(obj_str.encode("utf-8")).hexdigest()


class JsonKeyGenerator(KeyGenerator[Any]):
    """
    JSON serialization (+ optional SHA512 hash) key generator, dood!

    This generator serializes objects to JSON with optionaly sorted keys and then
    creates a SHA512 hash if enabled. It's ideal for structured data like dictionaries
    and lists where you want consistent hashing regardless of key ordering, dood!

    Type: KeyGenerator[Any]

    Example:
        >>> generator = JsonKeyGenerator()
        >>> # Order doesn't matter - same hash!
        >>> key1 = generator.generateKey({"a": 1, "b": 2})
        >>> key2 = generator.generateKey({"b": 2, "a": 1})
        >>> print(key1 == key2)  # True
        >>>
        >>> # Works with nested structures
        >>> data = {"user": {"id": 123, "name": "Alice"}, "tags": ["admin", "active"]}
        >>> key = generator.generateKey(data)
        >>> print(len(key))  # 128

    Note:
        Objects that cannot be JSON serialized will be converted to strings
        using the default=str parameter. This ensures the generator never
        fails, but may result in different hashes for logically equivalent
        objects that can't be properly serialized, dood!
    """

    __slots__ = ("sort_keys", "hash")

    def __init__(self, *, sort_keys: bool = True, hash: bool = True):
        """
        Initialize JsonKeyGenerator with configuration options, dood!

        Args:
            sort_keys: Whether to sort JSON keys for consistent serialization.
                      Defaults to True for deterministic hashing regardless of
                      dictionary key order, dood!
            hash: Whether to create SHA512 hash of the JSON string.
                 If False, returns the JSON string directly. Defaults to True
                 for consistent key length and security, dood!

        Example:
            >>> # Default behavior - sorted keys + hash
            >>> gen = JsonKeyGenerator()
            >>> key = gen.generateKey({"b": 2, "a": 1})
            >>> print(len(key))  # 128 (SHA512 hash)
            >>>
            >>> # No hashing - returns JSON string
            >>> gen = JsonKeyGenerator(hash=False)
            >>> key = gen.generateKey({"b": 2, "a": 1})
            >>> print(key)  # '{"a": 1, "b": 2}'
            >>>
            >>> # No sorting - preserves key order
            >>> gen = JsonKeyGenerator(sort_keys=False)
            >>> key1 = gen.generateKey({"a": 1, "b": 2})
            >>> key2 = gen.generateKey({"b": 2, "a": 1})
            >>> print(key1 == key2)  # False
        """
        self.sort_keys = sort_keys
        self.hash = hash

    def generateKey(self, obj: Any) -> str:
        """
        Generate SHA512 hash from JSON-serialized object, dood!

        Args:
            obj: Any object to convert to cache key

        Returns:
            str: 128-character SHA512 hexadecimal hash

        Raises:
            Never raises - all objects are handled gracefully

        Example:
            >>> generator = JsonKeyGenerator()
            >>> key = generator.generateKey({"query": "test", "page": 1})
            >>> print(len(key))  # 128
            >>> print(key[:10])  # First 10 chars of hash
        """
        try:
            # Serialize to JSON with sorted keys for consistency
            jsonStr = utils.jsonDumps(obj, sort_keys=self.sort_keys)
        except (TypeError, ValueError):
            # Fallback to string representation if JSON serialization fails
            jsonStr = str(obj)

        # Create SHA512 hash
        if self.hash:
            return hashlib.sha512(jsonStr.encode("utf-8")).hexdigest()
        else:
            return jsonStr
