# lib.cache - Generic Cache Library

A generic, reusable caching library for the Gromozeka project that provides type-safe, flexible caching with support for multiple key generation strategies, TTL management, and optional thread safety, dood!

## Overview, dood!

lib.cache is a comprehensive caching library that extracts and unifies the caching patterns from existing implementations while providing a generic, type-safe interface that can be used across different domains. It's designed to be simple yet powerful, with sensible defaults and extensive customization options, dood!

### Key Features and Benefits

- **Type-Safe**: Uses Python generics for compile-time type checking
- **Flexible Keys**: Support for simple strings and complex objects with automatic key generation
- **TTL Management**: Configurable time-to-live with automatic expiration
- **Size Management**: Optional max size with LRU-like eviction to prevent memory bloat
- **Thread Safety**: Optional thread safety for concurrent applications
- **Multiple Backends**: Dictionary-based implementation and null cache for testing
- **Key Generation Strategies**: Built-in generators for strings, hashes, and JSON serialization
- **Comprehensive Statistics**: Monitor cache performance and utilization
- **Easy Testing**: NullCache implementation for unit testing

### When to Use This Library

- **API Response Caching**: Cache expensive API calls to reduce latency and rate limiting
- **Database Query Results**: Cache frequently accessed database queries
- **Computed Values**: Cache expensive calculations or data processing results
- **Session Data**: Store user session information with automatic expiration
- **Configuration Data**: Cache configuration that changes infrequently
- **Any Key-Value Storage**: Generic caching for any application data

## Installation/Setup, dood!

The lib.cache library is part of the Gromozeka project and is available as a standard Python module.

### Basic Import

```python
from lib.cache import DictCache, StringKeyGenerator, NullCache
```

### Complete Import

```python
from lib.cache import (
    DictCache,           # Main cache implementation
    NullCache,           # No-op cache for testing
    CacheInterface,      # Abstract interface
    StringKeyGenerator,  # String key generator
    HashKeyGenerator,    # Hash-based key generator
    JsonKeyGenerator,    # JSON-based key generator
)
```

## Quick Start, dood!

Get up and running with lib.cache in just a few lines of code:

```python
from lib.cache import DictCache, StringKeyGenerator

# Create a simple string-keyed cache
cache = DictCache[str, dict](
    keyGenerator=StringKeyGenerator(),
    defaultTtl=3600,  # 1 hour TTL
    maxSize=1000      # Max 1000 entries
)

# Store some data
await cache.set("user:123", {"name": "Prinny", "level": 99})

# Retrieve the data
userData = await cache.get("user:123")
if userData:
    print(f"Found user: {userData['name']}, dood!")

# Check cache statistics
stats = cache.getStats()
print(f"Cache entries: {stats['entries']}/{stats['maxSize']}")
```

That's it! You now have a fully functional cache with TTL management, size limits, and thread safety, dood!

## Core Concepts, dood!

### Cache Interface

The `CacheInterface[K, V]` defines the contract for all cache implementations:

- **K**: Key type (any hashable type)
- **V**: Value type (any type)

All caches implement these core methods:
- `async get(key, ttl=None)` - Retrieve cached value
- `async set(key, value)` - Store value in cache
- `clear()` - Remove all entries
- `getStats()` - Get cache statistics

### Key Generators

Key generators convert complex objects into cache keys:

- **StringKeyGenerator**: Pass-through for string keys (fastest)
- **HashKeyGenerator**: SHA512 hash of object's repr() (secure)
- **JsonKeyGenerator**: SHA512 hash of JSON serialization (consistent)

### TTL and Size Management

- **TTL (Time-To-Live)**: Automatic expiration after specified seconds
- **Default TTL**: Configurable per cache instance
- **Size Limits**: Optional maximum entries with LRU-like eviction
- **Lazy Cleanup**: Expired entries removed on access

### Thread Safety

- **Thread-Safe Mode**: Uses `threading.RLock` for concurrent access (default)
- **Non-Thread-Safe Mode**: Faster for single-threaded applications
- **Per-Operation Locking**: Minimal contention for high performance

## Usage Examples, dood!

### Basic String Key Caching

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

### JSON-Serializable Objects

```python
from lib.cache import DictCache, JsonKeyGenerator
from typing import Dict, Any

# Cache for API responses
cache = DictCache[Dict[str, Any], Dict[str, Any]](
    keyGenerator=JsonKeyGenerator(),
    defaultTtl=300  # 5 minutes
)

# Complex request object
request = {
    "endpoint": "/search",
    "params": {"q": "prinny", "limit": 10},
    "headers": {"accept": "application/json"}
}

# Cache the response
response = {"results": [{"id": 1, "name": "Prinny"}]}
await cache.set(request, response)

# Retrieve with same request structure
cached_response = await cache.get(request)
```

### Custom Key Generator

```python
from lib.cache import DictCache, KeyGenerator
import hashlib
import json
from typing import Dict, Any

class CustomKeyGenerator(KeyGenerator[Dict[str, Any]]):
    """Custom key generator for API requests, dood!"""
    
    def generateKey(self, request: Dict[str, Any]) -> str:
        # Only include relevant fields for key generation
        keyData = {
            "endpoint": request["endpoint"],
            "params": request.get("params", {}),
            # Skip headers, auth tokens, etc.
        }
        jsonStr = json.dumps(keyData, sort_keys=True)
        return hashlib.sha512(jsonStr.encode()).hexdigest()

cache = DictCache[Dict[str, Any], Dict[str, Any]](
    keyGenerator=CustomKeyGenerator(),
    defaultTtl=3600
)
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

### Disabling Cache for Testing (NullCache)

```python
from lib.cache import NullCache

# No-op cache for testing, dood!
cache = NullCache[str, dict]()

await cache.set("key", {"data": "value"})
result = await cache.get("key")  # Always returns None

# Useful for dependency injection
def createService(cache=None):
    if cache is None:
        cache = NullCache()  # Default for testing
    return MyService(cache)
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

### Advanced Usage with Multiple Cache Types

```python
from lib.cache import DictCache, StringKeyGenerator, JsonKeyGenerator

# User session cache (short TTL, high size limit)
sessionCache = DictCache[str, dict](
    keyGenerator=StringKeyGenerator(),
    defaultTtl=1800,  # 30 minutes
    maxSize=10000
)

# API response cache (longer TTL, smaller size)
apiCache = DictCache[dict, dict](
    keyGenerator=JsonKeyGenerator(),
    defaultTtl=3600,  # 1 hour
    maxSize=1000
)

# Configuration cache (very long TTL, tiny size)
configCache = DictCache[str, Any](
    keyGenerator=StringKeyGenerator(),
    defaultTtl=86400,  # 24 hours
    maxSize=100
)
```

## API Reference, dood!

### CacheInterface[K, V]

Generic cache interface with type parameters:
- `K`: Key type (any hashable type)
- `V`: Value type (any type)

#### Methods

##### `async get(key: K, ttl: Optional[int] = None) -> Optional[V]`

Retrieve cached value by key.

**Parameters:**
- `key`: The cache key to retrieve
- `ttl`: Optional TTL override for this operation in seconds

**Returns:**
- `Optional[V]`: The cached value if found and not expired, None otherwise

**Example:**
```python
result = await cache.get("user:123")
result_with_ttl = await cache.get("user:123", ttl=60)
```

##### `async set(key: K, value: V) -> bool`

Store value in cache.

**Parameters:**
- `key`: The cache key to store the value under
- `value`: The value to cache

**Returns:**
- `bool`: True if the value was successfully stored, False otherwise

**Example:**
```python
success = await cache.set("user:123", {"name": "Prinny"})
```

##### `clear() -> None`

Remove all cached entries.

**Example:**
```python
cache.clear()
stats = cache.getStats()
print(stats['entries'])  # 0
```

##### `getStats() -> dict`

Get cache statistics.

**Returns:**
- `dict`: Dictionary containing cache statistics

**Example:**
```python
stats = cache.getStats()
print(f"Entries: {stats['entries']}")
print(f"Max size: {stats['maxSize']}")
```

### DictCache[K, V]

Dictionary-based cache implementation with full feature support.

#### Constructor Parameters

- `keyGenerator: KeyGenerator[K]` - Strategy for key conversion (required)
- `defaultTtl: int = 3600` - Default TTL in seconds
- `maxSize: Optional[int] = 1000` - Max entries (None = unlimited)
- `threadSafe: bool = True` - Enable thread safety

#### Statistics Keys

- `entries: int` - Current number of entries
- `maxSize: Optional[int]` - Maximum size limit
- `defaultTtl: int` - Default TTL in seconds

#### Example

```python
cache = DictCache[str, dict](
    keyGenerator=StringKeyGenerator(),
    defaultTtl=1800,
    maxSize=500,
    threadSafe=True
)
```

### NullCache[K, V]

No-op cache implementation for testing.

#### Constructor Parameters

None required.

#### Statistics Keys

- `enabled: bool` - Always False

#### Example

```python
cache = NullCache[str, dict]()
stats = cache.getStats()
print(stats['enabled'])  # False
```

### KeyGenerator[T]

Protocol for generating cache keys from objects.

#### Method

##### `generateKey(obj: T) -> str`

Convert object to string cache key.

**Parameters:**
- `obj`: The object to convert to a key

**Returns:**
- `str`: String representation suitable for use as cache key

### Built-in Key Generators

#### StringKeyGenerator

Pass-through generator for string keys.

**Use Case:** When your keys are already strings
**Performance:** Fastest option
**Example:**
```python
generator = StringKeyGenerator()
key = generator.generateKey("user:123")  # "user:123"
```

#### HashKeyGenerator

SHA512 hash generator using object's repr().

**Use Case:** Complex objects that have meaningful repr()
**Performance:** Medium speed, high collision resistance
**Example:**
```python
generator = HashKeyGenerator()
key = generator.generateKey(complex_object)  # SHA512 hash
```

#### JsonKeyGenerator

SHA512 hash generator using JSON serialization.

**Use Case:** JSON-serializable objects, consistent key generation
**Performance:** Medium speed, very consistent
**Example:**
```python
generator = JsonKeyGenerator()
key = generator.generateKey({"query": "test", "page": 1})  # SHA512 hash
```

## Best Practices, dood!

### When to Use Which Key Generator

- **StringKeyGenerator**: Use when keys are already strings or simple identifiers
- **HashKeyGenerator**: Use for complex objects with good repr() implementations
- **JsonKeyGenerator**: Use for JSON-serializable objects requiring consistent keys

### TTL Recommendations

- **User Sessions**: 15-30 minutes (900-1800 seconds)
- **API Responses**: 5-60 minutes (300-3600 seconds)
- **Database Queries**: 1-24 hours (3600-86400 seconds)
- **Configuration Data**: 24+ hours (86400+ seconds)
- **Computed Results**: Based on computation cost and data volatility

### Size Limit Guidelines

- **Small Applications**: 100-1000 entries
- **Medium Applications**: 1000-10000 entries
- **Large Applications**: 10000+ entries
- **Memory-Constrained**: Use smaller limits and shorter TTLs

### Thread Safety Considerations

- **Enable Thread Safety**: For web applications, background workers, or any concurrent access
- **Disable Thread Safety**: For single-threaded scripts, CLI tools, or performance-critical code
- **Mixed Usage**: Use separate cache instances for different thread safety requirements

### Performance Optimization Tips

1. **Choose the Right Key Generator**: StringKeyGenerator is fastest, use it when possible
2. **Set Appropriate TTLs**: Balance freshness with cache hit ratio
3. **Monitor Cache Statistics**: Use getStats() to track utilization and hit ratios
4. **Use Size Limits**: Prevent memory bloat with appropriate maxSize settings
5. **Consider NullCache**: Use for testing or when caching is not needed
6. **Batch Operations**: Group related cache operations when possible

## Testing, dood!

### How to Test Code That Uses Caches

Testing cached code requires careful handling of cache state and TTL behavior.

### Using NullCache for Testing

```python
import pytest
from lib.cache import NullCache, DictCache, StringKeyGenerator

class UserService:
    def __init__(self, cache):
        self.cache = cache
    
    async def getUser(self, userId):
        # Try cache first
        cached = await self.cache.get(f"user:{userId}")
        if cached:
            return cached
        
        # Simulate database call
        user = {"id": userId, "name": f"User {userId}"}
        await self.cache.set(f"user:{userId}", user)
        return user

# Test with NullCache (no caching)
@pytest.mark.asyncio
async def test_user_service_no_cache():
    service = UserService(NullCache[str, dict]())
    
    user1 = await service.getUser("123")
    user2 = await service.getUser("123")
    
    # Always returns fresh data
    assert user1["id"] == "123"
    assert user1 == user2

# Test with real cache
@pytest.mark.asyncio
async def test_user_service_with_cache():
    cache = DictCache[str, dict](StringKeyGenerator(), defaultTtl=60)
    service = UserService(cache)
    
    user1 = await service.getUser("123")
    user2 = await service.getUser("123")
    
    # Second call returns cached data
    assert user1 == user2
    assert cache.getStats()['entries'] == 1
```

### Example Test Patterns

#### Dependency Injection Pattern

```python
class MyService:
    def __init__(self, cache=None):
        self.cache = cache or NullCache()  # Default to no cache
    
    async def getData(self, key):
        cached = await self.cache.get(key)
        if cached:
            return cached
        # ... fetch data ...
        await self.cache.set(key, data)
        return data

# Tests
async def test_with_null_cache():
    service = MyService()  # Uses NullCache by default
    # Test logic without caching

async def test_with_real_cache():
    cache = DictCache[str, dict](StringKeyGenerator())
    service = MyService(cache)
    # Test caching behavior
```

#### Cache State Management

```python
@pytest.mark.asyncio
async def test_cache_expiration():
    cache = DictCache[str, str](StringKeyGenerator(), defaultTtl=1)
    
    await cache.set("key", "value")
    assert await cache.get("key") == "value"
    
    # Wait for expiration
    await asyncio.sleep(1.1)
    assert await cache.get("key") is None

@pytest.mark.asyncio
async def test_cache_size_limit():
    cache = DictCache[str, str](StringKeyGenerator(), maxSize=2)
    
    await cache.set("key1", "value1")
    await cache.set("key2", "value2")
    await cache.set("key3", "value3")  # Should evict oldest
    
    assert await cache.get("key1") is None  # Evicted
    assert await cache.get("key2") == "value2"
    assert await cache.get("key3") == "value3"
```

#### Mock Cache for Testing

```python
from unittest.mock import AsyncMock

class MockCache:
    def __init__(self):
        self.get = AsyncMock(return_value=None)
        self.set = AsyncMock(return_value=True)
        self.clear = Mock()
        self.getStats = Mock(return_value={"entries": 0, "maxSize": 100})

async def test_service_with_mock():
    mock_cache = MockCache()
    service = MyService(mock_cache)
    
    result = await service.getData("test")
    
    # Verify cache interactions
    mock_cache.get.assert_called_with("test")
    mock_cache.set.assert_called_once()
```

## Performance Considerations, dood!

### Time Complexity

- `get()`: O(1) average, O(n) worst case with cleanup
- `set()`: O(1) average, O(n log n) worst case with eviction
- `clear()`: O(n)
- `getStats()`: O(n) with cleanup

### Memory Usage

- **Base overhead**: ~100 bytes per entry (tuple + timestamp)
- **Key overhead**: Depends on key generator (32-128 bytes)
- **Value overhead**: Depends on value type
- **Lock overhead**: ~80 bytes if thread-safe

### Optimization Tips

1. **Use threadSafe=False** for single-threaded applications (eliminates lock overhead)
2. **Set appropriate maxSize** to prevent unbounded memory growth
3. **Use StringKeyGenerator** when possible (fastest key generation)
4. **Adjust defaultTtl** based on data volatility and access patterns
5. **Monitor getStats()** regularly to track cache efficiency
6. **Consider cache warming** for frequently accessed data
7. **Use NullCache** in testing or when caching provides no benefit

### Performance Benchmarks

Approximate performance characteristics (varies by system):

| Operation | Thread-Safe | Non-Thread-Safe | Notes |
|-----------|-------------|------------------|-------|
| String get/set | ~50μs | ~30μs | Fastest with StringKeyGenerator |
| Hash get/set | ~100μs | ~70μs | With HashKeyGenerator |
| JSON get/set | ~120μs | ~80μs | With JsonKeyGenerator |
| Cache hit | ~10μs | ~5μs | When key exists and not expired |
| Cache miss | ~20μs | ~15μs | When key doesn't exist |

## Migration Guide, dood!

### How to Migrate from Yandex Search Cache

The old yandex search cache can be easily replaced with lib.cache:

#### Old Code
```python
from lib.yandex_search.cache_interface import CacheInterface
from lib.yandex_search.dict_cache import DictCache

class YandexSearchClient:
    def __init__(self, cache=None):
        self.cache = cache or DictCache()
```

#### New Code
```python
from lib.cache import DictCache, StringKeyGenerator

class YandexSearchClient:
    def __init__(self, cache=None):
        if cache is None:
            self.cache = DictCache[str, dict](
                keyGenerator=StringKeyGenerator(),
                defaultTtl=3600,
                maxSize=1000
            )
        else:
            self.cache = cache
```

### How to Migrate from OpenWeatherMap Cache

The OpenWeatherMap cache had multiple cache types in one class:

#### Old Code
```python
from lib.openweathermap.cache_interface import CacheInterface
from lib.openweathermap.dict_cache import DictCache

class OpenWeatherMapClient:
    def __init__(self):
        self.cache = DictCache()
    
    async def getWeather(self, location):
        return await self.cache.getWeather(location)
    
    async def getGeocoding(self, query):
        return await self.cache.getGeocoding(query)
```

#### New Code
```python
from lib.cache import DictCache, StringKeyGenerator

class OpenWeatherMapClient:
    def __init__(self):
        self.weatherCache = DictCache[str, dict](
            keyGenerator=StringKeyGenerator(),
            defaultTtl=1800,  # 30 minutes
            maxSize=1000
        )
        self.geocodingCache = DictCache[str, list](
            keyGenerator=StringKeyGenerator(),
            defaultTtl=86400,  # 24 hours
            maxSize=500
        )
    
    async def getWeather(self, location):
        return await self.weatherCache.get(location)
    
    async def getGeocoding(self, query):
        return await self.geocodingCache.get(query)
```

### Migration Benefits

- **Type Safety**: Generic types prevent runtime errors
- **Better Performance**: Optimized key generation and storage
- **More Features**: Size limits, better statistics, flexible TTL
- **Easier Testing**: NullCache for unit testing
- **Consistent API**: Same interface across all cache usage

### Backward Compatibility

For gradual migration, you can create adapter classes:

```python
from lib.cache import DictCache, StringKeyGenerator

class YandexCacheAdapter:
    """Adapter for backward compatibility with old yandex cache interface"""
    
    def __init__(self):
        self._cache = DictCache[str, dict](
            keyGenerator=StringKeyGenerator(),
            defaultTtl=3600,
            maxSize=1000
        )
    
    async def get(self, key):
        return await self._cache.get(key)
    
    async def set(self, key, value):
        return await self._cache.set(key, value)
    
    def clear(self):
        return self._cache.clear()
    
    def getStats(self):
        return self._cache.getStats()
```

---

*Remember: Good caching strategy can dramatically improve application performance, dood! Choose the right cache configuration for your specific use case and monitor performance regularly.*