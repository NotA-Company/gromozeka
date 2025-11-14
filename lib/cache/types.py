"""
Core type definitions and protocols for lib.cache, dood!

This module contains the fundamental type definitions and protocols
used throughout the cache library, providing type safety and
extensibility for different cache implementations, dood!
"""

from typing import Protocol, TypeVar

# Type variables for generic cache operations, dood!
K = TypeVar("K")  # Key type - can be any hashable type
V = TypeVar("V")  # Value type - can be any type
T = TypeVar("T", contravariant=True)  # Generic object type for key generators


class KeyGenerator(Protocol[T]):
    """
    Protocol for generating cache keys from objects, dood!

    This protocol defines the interface for converting arbitrary objects
    into string cache keys. Different implementations can use various
    strategies like hashing, serialization, or custom logic, dood!

    Type Parameters:
        T: The type of objects that can be converted to cache keys

    Example:
        >>> class StringKeyGenerator(KeyGenerator[str]):
        ...     def generateKey(self, obj: str) -> str:
        ...         return obj
        >>>
        >>> generator = StringKeyGenerator()
        >>> key = generator.generateKey("user:123")
        >>> print(key)  # "user:123"
    """

    def generateKey(self, obj: T) -> str:
        """
        Generate string cache key from object, dood!

        Args:
            obj: The object to convert to a cache key

        Returns:
            str: A string representation suitable for use as a cache key

        Example:
            >>> generator = HashKeyGenerator()
            >>> key = generator.generateKey({"query": "test", "page": 1})
            >>> print(key)  # "a1b2c3d4e5f6..." (SHA512 hash)
        """
        ...


class ValueConverter(Protocol[V]):
    """
    Protocol for converting objects to cache and back

    Type Parameters:
        T: The type of objects that can be converted to cache values

    """

    def encode(self, obj: V) -> str:
        """
        Convert object to cache value, dood!

        Args:
            obj: The object to convert to a cache value

        Returns:
            str: A string representation suitable for use as a cache value
        """
        ...

    def decode(self, value: str) -> V:
        """
        Decode cache value to object, dood!

        Args:
            value: The cache value to decode

        Returns:
            T: The decoded object
        """
        ...
