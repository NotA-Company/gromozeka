# CacheService Design Proposal

## Overview

This document outlines the design for a new `CacheService` that will replace the current TypedDict-based cache implementation in `handlers.main.py`. The service will provide a centralized, singleton-based caching solution with selective persistence capabilities.

## Current State Analysis

### Existing Implementation
- **Location**: `internal/bot/handlers/main.py` (lines 140-144)
- **Structure**: TypedDict (`HandlersCacheDict`) with three main sections:
  - `chats`: Chat-specific data (settings, info, topics)
  - `chatUsers`: User data per chat (composite key: "chatId:userId")
  - `users`: User-specific temporary state

### Current Issues
1. Cache is tightly coupled with the handlers module
2. No persistence mechanism for important cached data
3. No thread-safety guarantees
4. No TTL/expiration mechanism
5. Difficult to share across modules when splitting the codebase

## Design Goals

1. **Modularity**: Can be used across different modules without circular dependencies
2. **Persistence**: Selective persistence to database for critical data
3. **Thread-Safety**: Safe for concurrent access
4. **Performance**: Minimal overhead compared to current implementation
5. **Backward Compatibility**: Maintain existing API where possible
6. **Scalability**: Support for cache expiration and memory management

## Proposed Architecture

### Core Components

```
internal/
├── cache/
│   ├── __init__.py          # Public API exports
│   ├── service.py           # Main CacheService class
│   ├── models.py            # Cache data models
│   ├── persistence.py       # Persistence layer
│   ├── decorators.py        # Caching decorators
│   └── strategies.py        # Cache strategies (TTL, LRU, etc.)
```

### Class Design

```python
# internal/cache/models.py
from enum import Enum
from typing import Any, Dict, Optional, Set
from datetime import datetime, timedelta

class CachePersistenceLevel(Enum):
    """Defines persistence behavior for cache entries"""
    MEMORY_ONLY = "memory"      # Never persisted
    ON_CHANGE = "on_change"      # Persisted immediately on change
    ON_SHUTDOWN = "on_shutdown"  # Persisted when service stops
    PERIODIC = "periodic"        # Persisted periodically

class CacheEntry:
    """Wrapper for cached values with metadata"""
    def __init__(
        self,
        value: Any,
        ttl: Optional[timedelta] = None,
        persistence_level: CachePersistenceLevel = CachePersistenceLevel.MEMORY_ONLY,
        created_at: Optional[datetime] = None,
        accessed_at: Optional[datetime] = None,
        access_count: int = 0
    ):
        self.value = value
        self.ttl = ttl
        self.persistence_level = persistence_level
        self.created_at = created_at or datetime.now()
        self.accessed_at = accessed_at or datetime.now()
        self.access_count = access_count
        self.dirty = False  # Track if value changed since last persist

# internal/cache/service.py
import asyncio
from typing import Any, Dict, Optional, Callable, TypeVar, Generic
from threading import RLock
import json
from datetime import datetime, timedelta

T = TypeVar('T')

class CacheNamespace:
    """Represents a cache namespace (e.g., 'chats', 'users', 'chatUsers')"""
    def __init__(self, name: str, cache_service: 'CacheService'):
        self.name = name
        self.cache_service = cache_service
        self._data: Dict[Any, CacheEntry] = {}
        self._lock = RLock()
    
    def get(self, key: Any, default: Any = None) -> Any:
        """Get value from namespace"""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default
            
            # Check TTL
            if entry.ttl and (datetime.now() - entry.created_at) > entry.ttl:
                del self._data[key]
                return default
            
            # Update access metadata
            entry.accessed_at = datetime.now()
            entry.access_count += 1
            
            return entry.value
    
    def set(
        self, 
        key: Any, 
        value: Any,
        ttl: Optional[timedelta] = None,
        persistence_level: CachePersistenceLevel = CachePersistenceLevel.MEMORY_ONLY
    ) -> None:
        """Set value in namespace"""
        with self._lock:
            entry = CacheEntry(
                value=value,
                ttl=ttl,
                persistence_level=persistence_level
            )
            self._data[key] = entry
            
            # Handle immediate persistence
            if persistence_level == CachePersistenceLevel.ON_CHANGE:
                self.cache_service._persist_entry(self.name, key, entry)
    
    def delete(self, key: Any) -> bool:
        """Delete key from namespace"""
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all entries in namespace"""
        with self._lock:
            self._data.clear()

class CacheService:
    """
    Singleton cache service with namespace support and selective persistence.
    
    Usage:
        cache = CacheService.get_instance()
        
        # Basic usage
        cache.chats[123] = {"settings": {...}}
        settings = cache.chats.get(123)
        
        # With TTL
        cache.users.set(456, {"temp": "data"}, ttl=timedelta(hours=1))
        
        # With persistence
        cache.chatUsers.set(
            "123:456", 
            {"data": {...}},
            persistence_level=CachePersistenceLevel.ON_CHANGE
        )
    """
    
    _instance: Optional['CacheService'] = None
    _lock = RLock()
    
    def __new__(cls) -> 'CacheService':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance
    
    def __init__(self):
        # Initialize only once
        if not hasattr(self, '_initialized'):
            self._namespaces: Dict[str, CacheNamespace] = {}
            self._db_wrapper: Optional[Any] = None  # Will be injected
            self._persistence_task: Optional[asyncio.Task] = None
            self._initialized = True
            
            # Initialize default namespaces
            self.chats = self._get_or_create_namespace("chats")
            self.chatUsers = self._get_or_create_namespace("chatUsers")  
            self.users = self._get_or_create_namespace("users")
    
    @classmethod
    def get_instance(cls) -> 'CacheService':
        """Get singleton instance"""
        return cls()
    
    def inject_database(self, db_wrapper: Any) -> None:
        """Inject database wrapper for persistence"""
        self._db_wrapper = db_wrapper
        
    def _get_or_create_namespace(self, name: str) -> CacheNamespace:
        """Get or create a cache namespace"""
        if name not in self._namespaces:
            self._namespaces[name] = CacheNamespace(name, self)
        return self._namespaces[name]
    
    def __getattr__(self, name: str) -> CacheNamespace:
        """Dynamic namespace access"""
        return self._get_or_create_namespace(name)
    
    async def start_persistence_worker(self, interval: timedelta = timedelta(minutes=5)):
        """Start background persistence worker"""
        async def worker():
            while True:
                await asyncio.sleep(interval.total_seconds())
                await self.persist_dirty_entries()
        
        self._persistence_task = asyncio.create_task(worker())
    
    async def stop_persistence_worker(self):
        """Stop persistence worker and save all persistent data"""
        if self._persistence_task:
            self._persistence_task.cancel()
            try:
                await self._persistence_task
            except asyncio.CancelledError:
                pass
        
        # Persist all data marked for shutdown persistence
        await self.persist_all_entries()
    
    def _persist_entry(self, namespace: str, key: Any, entry: CacheEntry) -> None:
        """Persist a single cache entry to database"""
        if not self._db_wrapper:
            return
        
        # Serialize the entry
        data = {
            "namespace": namespace,
            "key": str(key),
            "value": json.dumps(entry.value, default=str),
            "created_at": entry.created_at.isoformat(),
            "persistence_level": entry.persistence_level.value
        }
        
        # Store in database (settings table can be reused for now)
        self._db_wrapper.setCacheSetting(
            namespace=namespace,
            key=str(key),
            value=data["value"],
            metadata=json.dumps({
                "created_at": data["created_at"],
                "persistence_level": data["persistence_level"]
            })
        )
        
        entry.dirty = False
    
    async def persist_dirty_entries(self) -> None:
        """Persist all entries marked as dirty"""
        for namespace_name, namespace in self._namespaces.items():
            with namespace._lock:
                for key, entry in namespace._data.items():
                    if entry.dirty and entry.persistence_level in [
                        CachePersistenceLevel.PERIODIC,
                        CachePersistenceLevel.ON_SHUTDOWN
                    ]:
                        self._persist_entry(namespace_name, key, entry)
    
    async def persist_all_entries(self) -> None:
        """Persist all entries that should be persisted"""
        for namespace_name, namespace in self._namespaces.items():
            with namespace._lock:
                for key, entry in namespace._data.items():
                    if entry.persistence_level != CachePersistenceLevel.MEMORY_ONLY:
                        self._persist_entry(namespace_name, key, entry)
    
    async def load_from_database(self) -> None:
        """Load persisted cache entries from database"""
        if not self._db_wrapper:
            return
        
        # Load cache settings from database
        cached_data = self._db_wrapper.getCacheSettings()
        
        for item in cached_data:
            namespace_name = item["namespace"]
            key = item["key"]
            
            try:
                value = json.loads(item["value"])
                metadata = json.loads(item.get("metadata", "{}"))
                
                namespace = self._get_or_create_namespace(namespace_name)
                entry = CacheEntry(
                    value=value,
                    persistence_level=CachePersistenceLevel(
                        metadata.get("persistence_level", "memory")
                    ),
                    created_at=datetime.fromisoformat(metadata.get("created_at"))
                    if "created_at" in metadata else None
                )
                
                # Restore with appropriate key type
                if namespace_name == "chats" or namespace_name == "users":
                    key = int(key) if key.isdigit() else key
                    
                namespace._data[key] = entry
                
            except (json.JSONDecodeError, ValueError) as e:
                # Log error but continue loading other entries
                pass
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        stats = {
            "namespaces": {}
        }
        
        for name, namespace in self._namespaces.items():
            with namespace._lock:
                ns_stats = {
                    "total_entries": len(namespace._data),
                    "memory_only": 0,
                    "persistent": 0,
                    "expired": 0,
                    "total_access_count": 0
                }
                
                now = datetime.now()
                for key, entry in namespace._data.items():
                    if entry.persistence_level == CachePersistenceLevel.MEMORY_ONLY:
                        ns_stats["memory_only"] += 1
                    else:
                        ns_stats["persistent"] += 1
                    
                    if entry.ttl and (now - entry.created_at) > entry.ttl:
                        ns_stats["expired"] += 1
                    
                    ns_stats["total_access_count"] += entry.access_count
                
                stats["namespaces"][name] = ns_stats
        
        return stats
```

### Decorators for Caching

```python
# internal/cache/decorators.py
from functools import wraps
from typing import Callable, Optional, Any
from datetime import timedelta

def cached(
    namespace: str = "default",
    ttl: Optional[timedelta] = None,
    key_generator: Optional[Callable] = None,
    persistence_level: CachePersistenceLevel = CachePersistenceLevel.MEMORY_ONLY
):
    """
    Decorator for caching function results
    
    Usage:
        @cached(namespace="weather", ttl=timedelta(minutes=30))
        async def get_weather(city: str):
            # expensive API call
            return weather_data
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache = CacheService.get_instance()
            
            # Generate cache key
            if key_generator:
                cache_key = key_generator(*args, **kwargs)
            else:
                cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Check cache
            ns = getattr(cache, namespace)
            cached_value = ns.get(cache_key)
            
            if cached_value is not None:
                return cached_value
            
            # Call function and cache result
            result = await func(*args, **kwargs)
            ns.set(cache_key, result, ttl=ttl, persistence_level=persistence_level)
            
            return result
        
        return wrapper
    return decorator
```

## Migration Strategy

### Phase 1: Parallel Implementation
1. Implement CacheService alongside existing cache
2. Add adapter layer to sync both caches
3. Test thoroughly in development

### Phase 2: Gradual Migration
1. Replace cache usage in less critical areas first
2. Monitor for issues
3. Migrate critical paths

### Phase 3: Cleanup
1. Remove old cache implementation
2. Remove adapter layer
3. Optimize persistence queries

## Persistence Strategy

### What Gets Persisted

| Data Type | Persistence Level | Rationale |
|-----------|------------------|-----------|
| Chat Settings | ON_CHANGE | Already persisted, critical for functionality |
| Chat Info | ON_SHUTDOWN | Relatively static, can be reloaded |
| User Data | PERIODIC | Important but not critical for immediate persistence |
| Topics | ON_SHUTDOWN | Relatively static |
| Temporary UI State | MEMORY_ONLY | No need to persist (activeConfigureId, etc.) |

### Database Schema Changes

Add new table for cache storage:

```sql
CREATE TABLE IF NOT EXISTS cache_storage (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (namespace, key)
);

CREATE INDEX idx_cache_namespace ON cache_storage(namespace);
CREATE INDEX idx_cache_updated ON cache_storage(updated_at);
```

## Usage Examples

### Basic Usage

```python
# In BotHandlers.__init__
from internal.cache import CacheService

class BotHandlers(CommandHandlerMixin):
    def __init__(self, configManager, database, llmManager):
        super().__init__()
        
        # Initialize cache service
        self.cache = CacheService.get_instance()
        self.cache.inject_database(database)
        
        # Start persistence worker
        asyncio.create_task(self.cache.start_persistence_worker())

# Getting chat settings (backward compatible)
def getChatSettings(self, chatId: Optional[int], returnDefault: bool = True):
    if chatId is None:
        return self.chatDefaults.copy()
    
    # Check cache first
    chat_cache = self.cache.chats.get(chatId, {})
    if "settings" not in chat_cache:
        # Load from DB and cache
        settings = {
            ChatSettingsKey(k): ChatSettingsValue(v) 
            for k, v in self.db.getChatSettings(chatId).items()
        }
        chat_cache["settings"] = settings
        self.cache.chats.set(
            chatId, 
            chat_cache,
            persistence_level=CachePersistenceLevel.ON_SHUTDOWN
        )
    
    return chat_cache.get("settings", {})
```

### With Decorators

```python
@cached(
    namespace="weather",
    ttl=timedelta(minutes=30),
    key_generator=lambda city, country=None: f"{city}:{country}"
)
async def get_weather_cached(city: str, country: Optional[str] = None):
    return await self.openWeatherMapClient.getWeatherByCity(city, country)
```

## Benefits

1. **Separation of Concerns**: Cache logic separated from business logic
2. **Reusability**: Can be used across all modules
3. **Persistence**: Critical data survives restarts
4. **Performance**: TTL and expiration prevent memory bloat
5. **Observability**: Built-in statistics and monitoring
6. **Thread-Safety**: Proper locking mechanisms
7. **Flexibility**: Different persistence strategies for different data types

## Considerations

1. **Memory Management**: Implement LRU eviction for memory-constrained environments
2. **Serialization**: Complex objects may need custom serializers
3. **Database Load**: Batch persistence operations to reduce DB load
4. **Testing**: Comprehensive test suite needed for cache behaviors
5. **Monitoring**: Add metrics for cache hit/miss rates

## Next Steps

1. Review and approve design
2. Implement core CacheService
3. Add database migration for cache_storage table
4. Create adapter layer for backward compatibility
5. Write comprehensive tests
6. Implement gradual migration
7. Monitor and optimize

## Alternative Approaches Considered

1. **Redis**: Rejected due to additional infrastructure complexity
2. **SQLite In-Memory**: Rejected due to persistence requirements
3. **Shelf/Pickle**: Rejected due to thread-safety concerns
4. **Direct DB Access**: Rejected due to performance overhead

## Conclusion

This CacheService design provides a robust, scalable solution that addresses all identified requirements while maintaining backward compatibility and enabling gradual migration. The singleton pattern ensures global access, while the namespace approach maintains logical separation of different cache domains.