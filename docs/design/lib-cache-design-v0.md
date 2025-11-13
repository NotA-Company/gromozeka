# lib.cache - Generic Cache Library Design v0

**Status:** Draft  
**Created:** 2025-11-13  
**Author:** SourceCraft Code Assistant (Prinny Mode)  

## Overview, dood!

This document describes the design for `lib.cache` - a generic, reusable caching library that extracts and unifies the caching patterns already implemented in [`lib/yandex_search/`](../../lib/yandex_search/) and [`lib/openweathermap/`](../../lib/openweathermap/), dood!

## Problem Statement

Currently, we have two separate cache implementations:
- [`lib/yandex_search/cache_interface.py`](../../lib/yandex_search/cache_interface.py) + [`dict_cache.py`](../../lib/yandex_search/dict_cache.py)
- [`lib/openweathermap/cache_interface.py`](../../lib/openweathermap/cache_interface.py) + [`dict_cache.py`](../../lib/openweathermap/dict_cache.py)

Both implementations share similar patterns but are domain-specific and cannot be reused. We need a generic cache library that can be used across different domains while maintaining the proven patterns, dood!

## Analysis of Existing Implementations

### Common Patterns Found

Both implementations share these core patterns, dood:

1. **Abstract Interface Pattern**
   - Use ABC with `@abstractmethod` decorators
   - Async methods for get/set operations
   - Optional TTL parameter support
   - Return `Optional[T]` for get, `bool` for set

2. **Dict-Based Implementation**
   - Store data as `(data, timestamp)` tuples
   - Helper methods: `_is_expired()`, `_cleanup_expired()`
   - Utility methods: `clear()`, `get_stats()`
   - Automatic cleanup on access

3. **TTL Management**
   - Default TTL configurable at initialization
   - Per-operation TTL override support
   - Automatic expiration checking
   - Lazy cleanup strategy

### Key Differences

**Yandex Search Cache** (more sophisticated, dood):
- ✅ Thread safety with `threading.RLock`
- ✅ Max size enforcement with LRU-like eviction
- ✅ SHA512 hash-based cache key generation
- ✅ Comprehensive documentation
- ✅ Single cache type (focused)
- ⚠️ Complex key generation from objects

**OpenWeatherMap Cache** (simpler, dood):
- ❌ No thread safety
- ❌ No size limits
- ✅ Simple string keys
- ⚠️ Less documentation
- ✅ Multiple cache types in one class
- ✅ Straightforward implementation

## Design Goals

1. **Generic & Reusable** - Work with any data type, not domain-specific
2. **Type-Safe** - Use Python generics for proper typing
3. **Flexible Keys** - Support both simple strings and complex objects
4. **Thread-Safe** - Optional thread safety for concurrent usage
5. **Size Management** - Optional max size with configurable eviction
6. **Easy to Use** - Simple API, sensible defaults
7. **Well-Documented** - Clear examples and comprehensive docstrings
8. **Testable** - Easy to test

## Proposed Architecture

### Module Structure

```
lib/cache/
├── __init__.py           # Public API exports
├── interface.py          # Abstract cache interface
├── dict_cache.py         # Dictionary-based implementation
├── null_cache.py         # No-op cache for testing
├── types.py              # Type definitions and protocols
├── key_generator.py      # Cache key generation utilities
├── README.md             # Usage documentation
└── test_*.py             # Unit tests
```

### Core Components

#### 1. Generic Cache Interface

```python
from abc import ABC, abstractmethod
from typing import Generic, Optional, TypeVar

K = TypeVar('K')  # Key type
V = TypeVar('V')  # Value type

class CacheInterface(ABC, Generic[K, V]):
    """Generic cache interface for any key-value storage, dood!"""
    
    @abstractmethod
    async def get(self, key: K, ttl: Optional[int] = None) -> Optional[V]:
        """Get cached value by key, dood!"""
        pass
    
    @abstractmethod
    async def set(self, key: K, value: V) -> bool:
        """Store value in cache, dood!"""
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """Clear all cached data, dood!"""
        pass
    
    @abstractmethod
    def getStats(self) -> dict:
        """Get cache statistics, dood!"""
        pass
```

#### 2. Key Generator Protocol

```python
from typing import Protocol, TypeVar

T = TypeVar('T')

class KeyGenerator(Protocol[T]):
    """Protocol for generating cache keys from objects, dood!"""
    
    def generateKey(self, obj: T) -> str:
        """Generate string cache key from object, dood!"""
        ...
```

**Built-in Generators:**
- `StringKeyGenerator` - Pass-through for string keys
- `HashKeyGenerator` - SHA512 hash for complex objects
- `JsonKeyGenerator` - JSON serialization + hash

#### 3. Dict Cache Implementation

```python
from typing import Dict, Generic, Optional, Tuple, TypeVar
import threading
import time

K = TypeVar('K')
V = TypeVar('V')

class DictCache(CacheInterface[K, V]):
    """Thread-safe dictionary-based cache with TTL and size limits, dood!"""
    
    def __init__(
        self,
        keyGenerator: KeyGenerator[K],
        defaultTtl: int = 3600,
        maxSize: Optional[int] = 1000,
        threadSafe: bool = True
    ):
        """Initialize cache with configuration, dood!
        
        Args:
            keyGenerator: Strategy for converting keys to strings
            defaultTtl: Default TTL in seconds (default: 1 hour)
            maxSize: Maximum cache entries (None = unlimited)
            threadSafe: Enable thread safety with RLock
        """
        self._cache: Dict[str, Tuple[V, float]] = {}
        self._keyGenerator = keyGenerator
        self._defaultTtl = defaultTtl
        self._maxSize = maxSize
        self._lock = threading.RLock() if threadSafe else None
```

**Features:**
- Generic types for type safety
- Pluggable key generation strategy
- Optional thread safety
- Optional size limits with LRU eviction
- Automatic cleanup on access
- Comprehensive statistics

#### 4. Null Cache Implementation

```python
class NullCache(CacheInterface[K, V]):
    """No-op cache that never stores anything, dood!
    
    Useful for:
    - Testing without cache side effects
    - Disabling cache in production
    - Benchmarking cache impact
    """
    
    async def get(self, key: K, ttl: Optional[int] = None) -> Optional[V]:
        return None
    
    async def set(self, key: K, value: V) -> bool:
        return True
    
    def clear(self) -> None:
        pass
    
    def getStats(self) -> dict:
        return {"enabled": False}
```

## Migration Strategy

### Phase 1: Create lib.cache

1. Implement core interfaces and types
2. Implement `DictCache` with all features from yandex-search
3. Implement key generators
4. Implement `NullCache`
5. Write comprehensive tests
6. Write documentation and examples

### Phase 2: Migrate Yandex Search

1. Create `SearchCacheAdapter` that wraps `CacheInterface[SearchRequest, SearchResponse]`
2. Update `YandexSearchClient` to use adapter
3. Keep old interface for backward compatibility (deprecated)
4. Update tests to use new cache
5. Update documentation

### Phase 3: Migrate OpenWeatherMap

1. Create separate cache instances for weather and geocoding
2. Update `OpenWeatherMapClient` to use two cache instances
3. Keep old interface for backward compatibility (deprecated)
4. Update tests to use new cache
5. Update documentation

### Phase 4: Cleanup

1. Mark old cache interfaces as deprecated
2. Add migration guide to documentation
3. Plan removal in future version

## Usage Examples

### Basic Usage with String Keys

```python
from lib.cache import DictCache, StringKeyGenerator

# Simple string-keyed cache, dood!
cache = DictCache[str, dict](
    keyGenerator=StringKeyGenerator(),
    defaultTtl=3600,
    maxSize=1000
)

# Store data
await cache.set("user:123", {"name": "Prinny", "level": 99})

# Retrieve data
userData = await cache.get("user:123")
if userData:
    print(f"Found user: {userData['name']}, dood!")
```

### Complex Object Keys with Hashing

```python
from lib.cache import DictCache, JsonKeyGenerator
from dataclasses import dataclass

@dataclass
class SearchQuery:
    query: str
    filters: dict
    page: int

# Cache with complex keys, dood!
cache = DictCache[SearchQuery, list](
    keyGenerator=JsonKeyGenerator(),
    defaultTtl=1800,
    maxSize=500
)

query = SearchQuery(query="prinny", filters={"type": "demon"}, page=1)
await cache.set(query, [{"id": 1, "name": "Prinny Squad"}])

results = await cache.get(query)
```

### Custom Key Generator

```python
from lib.cache import DictCache, KeyGenerator
import hashlib
import json

class CustomKeyGenerator(KeyGenerator[SearchRequest]):
    """Custom key generator for SearchRequest, dood!"""
    
    def generateKey(self, request: SearchRequest) -> str:
        # Custom logic for key generation
        keyData = {
            "query": request["query"],
            "sortSpec": request.get("sortSpec"),
            # ... other fields
        }
        jsonStr = json.dumps(keyData, sort_keys=True)
        return hashlib.sha512(jsonStr.encode()).hexdigest()

cache = DictCache[SearchRequest, SearchResponse](
    keyGenerator=CustomKeyGenerator(),
    defaultTtl=3600
)
```

### Disabling Cache for Testing

```python
from lib.cache import NullCache

# No-op cache for testing, dood!
cache = NullCache[str, dict]()

await cache.set("key", {"data": "value"})
result = await cache.get("key")  # Always returns None
```

### Thread-Safe vs Non-Thread-Safe

```python
# Thread-safe cache (default), dood!
threadSafeCache = DictCache[str, dict](
    keyGenerator=StringKeyGenerator(),
    threadSafe=True  # Uses RLock
)

# Non-thread-safe cache (faster for single-threaded), dood!
simpleCache = DictCache[str, dict](
    keyGenerator=StringKeyGenerator(),
    threadSafe=False  # No locking overhead
)
```

### Monitoring Cache Performance

```python
cache = DictCache[str, dict](
    keyGenerator=StringKeyGenerator(),
    maxSize=1000
)

# Get statistics, dood!
stats = cache.getStats()
print(f"Entries: {stats['entries']}/{stats['maxSize']}")
print(f"Utilization: {stats['entries'] / stats['maxSize'] * 100:.1f}%")
print(f"Default TTL: {stats['defaultTtl']}s")

# Clear cache if needed
if stats['entries'] > 900:
    cache.clear()
    print("Cache cleared, dood!")
```

## API Reference

### CacheInterface[K, V]

Generic cache interface with type parameters:
- `K`: Key type (any hashable type)
- `V`: Value type (any type)

**Methods:**

- `async get(key: K, ttl: Optional[int] = None) -> Optional[V]`
  - Retrieve cached value by key
  - Returns `None` if not found or expired
  - Optional TTL override for this operation

- `async set(key: K, value: V) -> bool`
  - Store value in cache
  - Returns `True` if successful, `False` otherwise
  - Uses current timestamp for TTL calculation

- `clear() -> None`
  - Remove all cached entries
  - Resets cache to empty state

- `getStats() -> dict`
  - Get cache statistics
  - Returns dict with implementation-specific metrics

### DictCache[K, V]

Dictionary-based cache implementation.

**Constructor Parameters:**

- `keyGenerator: KeyGenerator[K]` - Strategy for key conversion
- `defaultTtl: int = 3600` - Default TTL in seconds
- `maxSize: Optional[int] = 1000` - Max entries (None = unlimited)
- `threadSafe: bool = True` - Enable thread safety

**Statistics Keys:**

- `entries: int` - Current number of entries
- `maxSize: Optional[int]` - Maximum size limit
- `defaultTtl: int` - Default TTL in seconds

### KeyGenerator[T]

Protocol for generating cache keys.

**Method:**

- `generateKey(obj: T) -> str` - Convert object to string key

**Built-in Implementations:**

- `StringKeyGenerator()` - Pass-through for strings
- `HashKeyGenerator()` - SHA512 hash of repr()
- `JsonKeyGenerator()` - SHA512 hash of JSON

## Testing Strategy

### Unit Tests

1. **Interface Tests** - Test abstract interface contract
2. **DictCache Tests** - Test all cache operations
3. **Key Generator Tests** - Test key generation strategies
4. **Thread Safety Tests** - Test concurrent access
5. **TTL Tests** - Test expiration behavior
6. **Size Limit Tests** - Test eviction behavior
7. **NullCache Tests** - Test no-op behavior

### Integration Tests

1. **Migration Tests** - Test backward compatibility
2. **Performance Tests** - Benchmark cache operations
3. **Memory Tests** - Test memory usage patterns

## Performance Considerations

### Time Complexity

- `get()`: O(1) average, O(n) worst case with cleanup
- `set()`: O(1) average, O(n log n) worst case with eviction
- `clear()`: O(n)
- `getStats()`: O(n) with cleanup

### Memory Usage

- Base overhead: ~100 bytes per entry (tuple + timestamp)
- Key overhead: Depends on key generator (32-128 bytes)
- Value overhead: Depends on value type
- Lock overhead: ~80 bytes if thread-safe

### Optimization Tips

1. Use `threadSafe=False` for single-threaded apps
2. Set appropriate `maxSize` to prevent unbounded growth
3. Use `StringKeyGenerator` when possible (fastest)
4. Adjust `defaultTtl` based on data volatility
5. Monitor `getStats()` for cache efficiency

## Security Considerations

1. **Key Collision** - SHA512 provides excellent collision resistance
2. **Memory Exhaustion** - Use `maxSize` to prevent DoS
3. **Sensitive Data** - Cache doesn't encrypt data at rest
4. **Thread Safety** - Enable for concurrent access
5. **TTL Bypass** - Negative TTL disables expiration (use carefully)

## Future Enhancements

### Phase 2 Features

1. **Async Cleanup** - Background task for expired entry removal
2. **Cache Warming** - Pre-populate cache on startup
3. **Metrics Export** - Prometheus/StatsD integration
4. **Persistence** - Optional disk-based storage
5. **Distributed Cache** - Redis/Memcached backends

### Phase 3 Features

1. **Cache Hierarchies** - L1/L2 cache layers
2. **Smart Eviction** - LFU, LRU, ARC algorithms
3. **Compression** - Automatic value compression
4. **Encryption** - At-rest encryption support
5. **Replication** - Multi-node cache sync

## Open Questions

1. **Should we support sync methods?** - Currently all async, but some use cases might benefit from sync API
2. **Should we include Redis backend in v0?** - Or keep it simple with just dict cache?
3. **How to handle serialization?** - Should cache handle it or leave to user?
4. **Should we support cache namespaces?** - For multi-tenant scenarios
5. **What about cache invalidation patterns?** - Tag-based invalidation, pattern matching, etc.

## Decision Log

### 2025-11-13: Initial Design

**Decision:** Create generic cache library based on existing patterns, dood!

**Rationale:**
- Two implementations already exist with similar patterns
- Code duplication across domains
- Need for reusable caching infrastructure
- Proven patterns from production use

**Alternatives Considered:**
1. Keep separate implementations - Rejected due to duplication
2. Use external library (cachetools, aiocache) - Rejected due to specific requirements
3. Create domain-specific base class - Rejected as less flexible

**Implementation Details:**
- Use Python generics for type safety
- Extract best features from both implementations
- Maintain backward compatibility during migration
- Focus on simplicity and ease of use, dood!

## References

- [Yandex Search Cache Implementation](../../lib/yandex_search/cache_interface.py)
- [OpenWeatherMap Cache Implementation](../../lib/openweathermap/cache_interface.py)
- [Rate Limiter Library Design](./rate-limiter-library-design-v1.md) - Similar pattern
- Python typing documentation
- Cache replacement policies (LRU, LFU, ARC)

## Conclusion

This design provides a solid foundation for a generic, reusable cache library that unifies the patterns from our existing implementations while adding flexibility and type safety. The migration strategy ensures backward compatibility while moving toward a cleaner architecture, dood!

The library will be easy to use, well-tested, and ready for future enhancements like distributed caching and advanced eviction strategies. Let's make it happen, dood! 🐧