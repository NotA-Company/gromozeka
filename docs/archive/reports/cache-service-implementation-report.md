# CacheService Implementation Report

## Overview

Successfully implemented a centralized CacheService for the Gromozeka bot to replace the TypedDict-based cache in handlers/main.py. The service provides singleton access, LRU eviction, and selective persistence.

## Implementation Date

2025-10-25

## What Was Implemented

### 1. Core Cache Module (`internal/cache/`)

Created a new cache module with the following structure:

- **`__init__.py`**: Public API exports
- **`models.py`**: Cache enums and data structures
- **`service.py`**: Main CacheService implementation

### 2. Cache Models (`internal/cache/models.py`)

Implemented two key enums:

#### CachePersistenceLevel
```python
class CachePersistenceLevel(Enum):
    MEMORY_ONLY = "memory"      # Never persisted (UI state)
    ON_CHANGE = "on_change"     # Persisted immediately (critical data)
    ON_SHUTDOWN = "on_shutdown" # Persisted when service stops
```

#### CacheNamespace
```python
class CacheNamespace(Enum):
    CHATS = "chats"           # ON_SHUTDOWN persistence
    CHAT_USERS = "chatUsers"  # ON_CHANGE persistence
    USERS = "users"           # MEMORY_ONLY persistence
```

Each namespace automatically determines its persistence level via `getPersistenceLevel()` method.

### 3. CacheService (`internal/cache/service.py`)

#### Key Features

1. **Singleton Pattern**: Global access via `CacheService.getInstance()`
2. **LRU Caching**: Each namespace has an LRU cache with configurable max size (default: 1000)
3. **Thread-Safety**: Uses `RLock` for concurrent access protection
4. **Automatic Persistence**: Service decides what to persist based on namespace type
5. **camelCase Naming**: All methods and attributes follow project conventions

#### Core Components

**LRUCache Class**
- Extends `OrderedDict` for efficient LRU implementation
- Thread-safe operations with `RLock`
- Automatic eviction when capacity exceeded
- Methods: `get()`, `set()`, `delete()`, `clear()`

**CacheService Class**
- Singleton instance management
- Three namespace properties: `chats`, `chatUsers`, `users`
- Dirty key tracking for persistence
- Database injection for persistence operations

#### Convenience Methods

```python
# Chat settings
getChatSettings(chatId: int) -> Dict[str, Any]
setChatSettings(chatId: int, settings: Dict[str, Any]) -> None

# Chat info
getChatInfo(chatId: int) -> Optional[Dict[str, Any]]
setChatInfo(chatId: int, info: Dict[str, Any]) -> None

# User data (per chat)
getUserData(chatId: int, userId: int) -> Dict[str, Any]
setUserData(chatId: int, userId: int, key: str, value: Any) -> None

# User state (temporary, not persisted)
getUserState(userId: int, stateKey: str, default: Any = None) -> Any
setUserState(userId: int, stateKey: str, value: Any) -> None
clearUserState(userId: int, stateKey: Optional[str] = None) -> None

# Namespace management
clearNamespace(namespace: CacheNamespace) -> None

# Persistence
persistAll() -> None
loadFromDatabase() -> None

# Statistics
getStats() -> Dict[str, Any]
```

### 4. Database Support

#### New Methods in DatabaseWrapper (`internal/database/wrapper.py`)

```python
def getCacheStorage() -> List[Dict[str, Any]]
    """Get all cache storage entries"""

def setCacheStorage(namespace: str, key: str, value: str) -> bool
    """Store cache entry in cache_storage table"""
```

#### Database Migration (`migration_004_add_cache_storage_table.py`)

Created migration to add `cache_storage` table:

```sql
CREATE TABLE IF NOT EXISTS cache_storage (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (namespace, key)
);

CREATE INDEX IF NOT EXISTS idx_cache_namespace 
ON cache_storage(namespace);
```

## Usage Examples

### Basic Usage

```python
from internal.cache import CacheService

# Get singleton instance
cache = CacheService.getInstance()

# Inject database for persistence
cache.injectDatabase(dbWrapper)

# Direct namespace access (backward compatible)
cache.chats[123] = {"settings": {...}}
settings = cache.chats.get(123)

# Using convenience methods
settings = cache.getChatSettings(123)
cache.setUserData(123, 456, "preferences", {"theme": "dark"})
cache.setUserState(456, "activeConfigureId", {...})
```

### Persistence

```python
# Automatic persistence based on namespace:
# - CHATS: persisted on shutdown
# - CHAT_USERS: persisted immediately on change
# - USERS: never persisted

# Manual persistence (e.g., on shutdown)
cache.persistAll()

# Load from database on startup
cache.loadFromDatabase()
```

### Statistics

```python
stats = cache.getStats()
# Returns:
# {
#     "chats": {
#         "size": 10,
#         "maxSize": 1000,
#         "dirty": 2,
#         "persistenceLevel": "on_shutdown"
#     },
#     "chatUsers": {...},
#     "users": {...}
# }
```

## Design Decisions

### 1. CacheNamespace Enum Usage

**Decision**: Use `CacheNamespace` enum throughout instead of raw strings.

**Rationale**:
- Type safety and IDE autocomplete
- Easier refactoring if namespace names change
- Centralized persistence level management
- Prevents typos in namespace names

### 2. LRU Instead of TTL

**Decision**: Use LRU eviction policy instead of TTL (Time-To-Live).

**Rationale**:
- Simpler implementation
- More predictable memory usage
- Sufficient for bot's use case
- Avoids complexity of TTL management

### 3. Automatic Persistence Levels

**Decision**: Persistence level determined by namespace type, not per-entry.

**Rationale**:
- Simpler API - users don't need to specify persistence
- Consistent behavior across similar data types
- Easier to reason about what gets persisted
- Reduces configuration overhead

### 4. Singleton Pattern

**Decision**: Use singleton pattern for global cache access.

**Rationale**:
- Single source of truth for cached data
- Easy access from any module
- Prevents multiple cache instances
- Matches existing bot architecture patterns

## Benefits

1. **Modularity**: Cache can be used across different modules without circular dependencies
2. **Type Safety**: CacheNamespace enum prevents typos and provides autocomplete
3. **Simplicity**: Automatic persistence management based on data type
4. **Performance**: LRU eviction prevents memory bloat
5. **Thread-Safety**: Built-in locking for concurrent access
6. **Backward Compatible**: Similar API to existing TypedDict cache
7. **Observability**: Built-in statistics for monitoring

## Migration Path

### Current Code (handlers/main.py)
```python
self.cache: HandlersCacheDict = {
    "chats": {},
    "chatUsers": {},
    "users": {},
}

# Getting settings
if chatId not in self.cache["chats"]:
    self.cache["chats"][chatId] = {}
```

### New Code
```python
from internal.cache import CacheService

self.cache = CacheService.getInstance()
self.cache.injectDatabase(database)

# Getting settings - much simpler!
settings = cache.getChatSettings(chatId)
```

## Testing

To test the implementation:

```bash
# Run migration tests
./venv/bin/python3 internal/database/migrations/test_migrations.py

# Test cache service (to be implemented)
./venv/bin/python3 -m pytest tests/test_cache_service.py
```

## Next Steps

1. **Update BotHandlers**: Replace TypedDict cache with CacheService
2. **Add Shutdown Hook**: Call `cache.persistAll()` on bot shutdown
3. **Write Tests**: Create comprehensive test suite for CacheService
4. **Monitor Performance**: Track cache hit/miss rates and memory usage
5. **Documentation**: Update bot documentation with cache usage examples

## Files Created/Modified

### Created
- `internal/cache/__init__.py`
- `internal/cache/models.py`
- `internal/cache/service.py`
- `internal/database/migrations/versions/migration_004_add_cache_storage_table.py`
- `docs/design/cache-service-design-v2.md`
- `docs/reports/cache-service-implementation-report.md`

### Modified
- `internal/database/wrapper.py` (added `getCacheStorage()` and `setCacheStorage()`)

## Conclusion

The CacheService implementation provides a robust, type-safe, and maintainable caching solution for the Gromozeka bot. The use of `CacheNamespace` enum throughout ensures consistency and prevents errors, while the automatic persistence management simplifies usage. The service is ready for integration into the bot handlers, dood!