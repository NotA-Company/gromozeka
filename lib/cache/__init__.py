"""
lib.cache - Generic cache library for Gromozeka, dood!

This library provides a generic, reusable caching infrastructure that can be
used across different domains while maintaining type safety and flexibility, dood!

Core Components:
- CacheInterface: Abstract base class for all cache implementations
- KeyGenerator: Protocol for generating cache keys from objects
- DictCache: Thread-safe dictionary-based cache implementation
- NullCache: No-op cache for testing and debugging

Example Usage:
    >>> from lib.cache import DictCache, StringKeyGenerator
    >>>
    >>> # Create a simple string-keyed cache
    >>> cache = DictCache[str, dict](
    ...     keyGenerator=StringKeyGenerator(),
    ...     defaultTtl=3600,
    ...     maxSize=1000
    ... )
    >>>
    >>> # Store and retrieve data
    >>> await cache.set("user:123", {"name": "Prinny", "level": 99})
    >>> userData = await cache.get("user:123")
    >>> if userData:
    ...     print(f"Found user: {userData['name']}, dood!")
"""

# Export cache implementations
from .dict_cache import DictCache
from .interface import CacheInterface

# Export key generators
from .key_generator import HashKeyGenerator, JsonKeyGenerator, StringKeyGenerator
from .null_cache import NullCache

# Export core types and interfaces
from .types import K, KeyGenerator, T, V, ValueConverter
from .value_converter import JsonValueConverter, StringValueConverter

__version__ = "0.1.0"
__author__ = "SourceCraft Code Assistant (Prinny Mode)"

__all__ = [
    # Core types
    "KeyGenerator",
    "ValueConverter",
    "K",
    "V",
    "T",
    # Interfaces
    "CacheInterface",
    # Implementations
    "DictCache",
    "NullCache",
    # Key generators
    "StringKeyGenerator",
    "HashKeyGenerator",
    "JsonKeyGenerator",
    # Value Converters
    "StringValueConverter",
    "JsonValueConverter",
]
