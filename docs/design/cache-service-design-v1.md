# CacheService Design Proposal (Simplified v2)

## Overview

A simplified, bot-specific `CacheService` that replaces the current TypedDict-based cache implementation with automatic persistence management and LRU eviction.

## Design Goals

1. **Simplicity**: Straightforward API tailored to the bot's needs
2. **Automatic Persistence**: Service decides what to persist based on data type
3. **camelCase**: Follow project naming conventions
4. **LRU Eviction**: Memory management without TTL complexity
5. **Backward Compatibility**: Minimal changes to existing code

## Core Design

### File Structure
```
internal/
├── cache/
│   ├── __init__.py       # Public exports
│   ├── service.py        # Main CacheService
│   └── models.py         # Cache data models
```

### Simplified Implementation

```python
# internal/cache/models.py
from enum import Enum
from typing import Any, Dict, Optional
from collections import OrderedDict

class CachePersistenceLevel(Enum):
    """Persistence behavior for cache entries"""
    MEMORY_ONLY = "memory"     # Never persisted (e.g., UI state)
    ON_CHANGE = "on-change"    # Persisted immediately (critical data)
    ON_SHUTDOWN = "on-shutdown" # Persisted when service stops

class CacheNamespace(StrEnum):
    """Predefined cache namespaces with their persistence rules"""
    CHATS = "chats"           # MEMORY_ONLY - can be reloaded from DB
    CHAT_USERS = "chatUsers"  # MEMORY_ONLY - can be reloaded from DB  
    USERS = "users"           # ON_CHANGE - UI state

    def getPersistenceLevel(self) -> CachePersistenceLevel:
        """Auto-determine persistence level based on namespace"""
        match self:
            case CacheNamespace.USERS:
                return CachePersistenceLevel.ON_CHANGE
            case _:
                return CachePersistenceLevel.MEMORY_ONLY

# internal/cache/service.py
import json
from typing import Any, Dict, Optional, Union
from threading import RLock
from collections import OrderedDict
from enum import Enum

class LRUCache(OrderedDict):
    """Simple LRU cache implementation"""
    def __init__(self, maxSize: int = 1000):
        super().__init__()
        self.maxSize = maxSize
        self.lock = RLock()
    
    def get(self, key: Any, default: Any = None) -> Any:
        with self.lock:
            if key not in self:
                return default
            # Move to end (most recently used)
            self.move_to_end(key)
            return self[key]
    
    def set(self, key: Any, value: Any) -> None:
        with self.lock:
            if key in self:
                # Update and move to end
                self.move_to_end(key)
            self[key] = value
            # Evict oldest if over capacity
            if len(self) > self.maxSize:
                self.popitem(last=False)
    
    def delete(self, key: Any) -> bool:
        with self.lock:
            if key in self:
                del self[key]
                return True
            return False

class CacheService:
    """
    Singleton cache service for Gromozeka bot.
    
    Usage:
        cache = CacheService.getInstance()
        
        # Access namespaces directly
        cache.chats[123] = {"settings": {...}}
        settings = cache.chats.get(123)
        
        # Or use methods
        cache.getChatSettings(123)
        cache.setChatSettings(123, settings)
    """
    
    _instance: Optional['CacheService'] = None
    _lock = RLock()
    
    def __new__(cls) -> 'CacheService':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance
    
    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.dbWrapper: Optional[Any] = None
            self.maxCacheSize = 1000  # Per namespace
            
            # Initialize namespaces with LRU caches
            self.chats = LRUCache(self.maxCacheSize)
            self.chatUsers = LRUCache(self.maxCacheSize)
            self.users = LRUCache(self.maxCacheSize)
            
            # Track what needs persistence
            self.dirtyKeys: Dict[str, set] = {
                "chats": set(),
                "chatUsers": set(),
                "users": set()
            }
            
            self.initialized = True
    
    @classmethod
    def getInstance(cls) -> 'CacheService':
        """Get singleton instance"""
        return cls()
    
    def injectDatabase(self, dbWrapper: Any) -> None:
        """Inject database wrapper for persistence"""
        self.dbWrapper = dbWrapper
        # Load persisted data on injection
        self.loadFromDatabase()
    
    # Convenience methods for backward compatibility
    def getChatSettings(self, chatId: int) -> Dict[str, Any]:
        """Get chat settings with cache"""
        chatCache = self.chats.get(chatId, {})
        
        if "settings" not in chatCache:
            if self.dbWrapper:
                # Load from DB
                settings = {
                    k: v for k, v in self.dbWrapper.getChatSettings(chatId).items()
                }
                chatCache["settings"] = settings
                self.chats.set(chatId, chatCache)
        
        return chatCache.get("settings", {})
    
    def setChatSettings(self, chatId: int, settings: Dict[str, Any]) -> None:
        """Update chat settings"""
        chatCache = self.chats.get(chatId, {})
        chatCache["settings"] = settings
        self.chats.set(chatId, chatCache)
        
        # Mark as dirty for persistence
        self.dirtyKeys["chats"].add(chatId)
        
        # For critical settings, persist immediately
        if self.dbWrapper:
            for key, value in settings.items():
                self.dbWrapper.setChatSetting(chatId, key, str(value))
    
    def getChatInfo(self, chatId: int) -> Optional[Dict[str, Any]]:
        """Get chat info from cache"""
        chatCache = self.chats.get(chatId, {})
        return chatCache.get("info")
    
    def setChatInfo(self, chatId: int, info: Dict[str, Any]) -> None:
        """Update chat info in cache"""
        chatCache = self.chats.get(chatId, {})
        chatCache["info"] = info
        self.chats.set(chatId, chatCache)
        self.dirtyKeys["chats"].add(chatId)
    
    def getUserData(self, chatId: int, userId: int) -> Dict[str, Any]:
        """Get user data for a specific chat"""
        userKey = f"{chatId}:{userId}"
        userCache = self.chatUsers.get(userKey, {})
        
        if "data" not in userCache and self.dbWrapper:
            # Load from DB
            userData = {
                k: json.loads(v) 
                for k, v in self.dbWrapper.getUserData(userId=userId, chatId=chatId).items()
            }
            userCache["data"] = userData
            self.chatUsers.set(userKey, userCache)
        
        return userCache.get("data", {})
    
    def setUserData(self, chatId: int, userId: int, key: str, value: Any) -> None:
        """Set user data for a specific chat"""
        userKey = f"{chatId}:{userId}"
        userCache = self.chatUsers.get(userKey, {})
        
        if "data" not in userCache:
            userCache["data"] = {}
        
        userCache["data"][key] = value
        self.chatUsers.set(userKey, userCache)
        
        # Persist to DB immediately for user data
        if self.dbWrapper:
            self.dbWrapper.addUserData(
                userId=userId,
                chatId=chatId,
                key=key,
                data=json.dumps(value, default=str)
            )
    
    def getUserState(self, userId: int, stateKey: str, default: Any = None) -> Any:
        """Get temporary user state (not persisted)"""
        userState = self.users.get(userId, {})
        return userState.get(stateKey, default)
    
    def setUserState(self, userId: int, stateKey: str, value: Any) -> None:
        """Set temporary user state (not persisted)"""
        userState = self.users.get(userId, {})
        userState[stateKey] = value
        self.users.set(userId, userState)
    
    def clearUserState(self, userId: int, stateKey: Optional[str] = None) -> None:
        """Clear user state"""
        if stateKey:
            userState = self.users.get(userId, {})
            userState.pop(stateKey, None)
            self.users.set(userId, userState)
        else:
            self.users.delete(userId)
    
    def persistAll(self) -> None:
        """Persist all dirty entries to database"""
        if not self.dbWrapper:
            return
        
        # Persist chats
        for chatId in self.dirtyKeys["chats"]:
            chatData = self.chats.get(chatId)
            if chatData:
                # Store in a cache table
                self._persistCacheEntry("chats", str(chatId), chatData)
        
        # Persist chatUsers  
        for userKey in self.dirtyKeys["chatUsers"]:
            userData = self.chatUsers.get(userKey)
            if userData:
                self._persistCacheEntry("chatUsers", userKey, userData)
        
        # Clear dirty markers
        for namespace in self.dirtyKeys:
            self.dirtyKeys[namespace].clear()
    
    def loadFromDatabase(self) -> None:
        """Load persisted cache from database on startup"""
        if not self.dbWrapper:
            return
        
        # Load from cache storage table
        try:
            cachedData = self.dbWrapper.getCacheStorage()
            
            for item in cachedData:
                namespace = item["namespace"]
                key = item["key"]
                value = json.loads(item["value"])
                
                if namespace == "chats":
                    # Convert key to int for chat IDs
                    self.chats.set(int(key), value)
                elif namespace == "chatUsers":
                    self.chatUsers.set(key, value)
                # Users namespace is not loaded (MEMORY_ONLY)
                    
        except Exception as e:
            # Table might not exist yet, that's okay
            pass
    
    def _persistCacheEntry(self, namespace: str, key: str, value: Any) -> None:
        """Persist a single cache entry"""
        if not self.dbWrapper:
            return
        
        try:
            serialized = json.dumps(value, default=str)
            self.dbWrapper.setCacheStorage(
                namespace=namespace,
                key=key,
                value=serialized
            )
        except Exception as e:
            # Log error but don't crash
            pass
    
    def getStats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "chats": {
                "size": len(self.chats),
                "maxSize": self.chats.maxSize,
                "dirty": len(self.dirtyKeys["chats"])
            },
            "chatUsers": {
                "size": len(self.chatUsers),
                "maxSize": self.chatUsers.maxSize,
                "dirty": len(self.dirtyKeys["chatUsers"])
            },
            "users": {
                "size": len(self.users),
                "maxSize": self.users.maxSize
            }
        }
```

## Database Schema

Simple cache storage table:

```sql
CREATE TABLE IF NOT EXISTS cache_storage (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (namespace, key)
);

CREATE INDEX idx_cache_namespace ON cache_storage(namespace);
```

## Migration Example

### Current Code (handlers/main.py):
```python
# Before
self.cache: HandlersCacheDict = {
    "chats": {},
    "chatUsers": {},
    "users": {},
}

# Getting settings
if chatId not in self.cache["chats"]:
    self.cache["chats"][chatId] = {}
if "settings" not in self.cache["chats"][chatId]:
    self.cache["chats"][chatId]["settings"] = {...}
```

### New Code:
```python
# After
self.cache = CacheService.getInstance()
self.cache.injectDatabase(database)

# Getting settings - much simpler!
settings = self.cache.getChatSettings(chatId)

# Or direct namespace access
chatCache = self.cache.chats.get(chatId, {})
```

## Key Simplifications

1. **No TTL**: Just LRU eviction when cache gets full
2. **Auto Persistence**: Service knows what to persist based on namespace
3. **camelCase**: Follows project conventions
4. **No PERIODIC**: Only MEMORY_ONLY, ON_CHANGE, and ON_SHUTDOWN
5. **Bot-Specific**: Methods tailored to bot's actual usage patterns

## Persistence Rules

| Namespace | Persistence | Reason |
|-----------|------------|---------|
| chats | ON_SHUTDOWN | Can reload from DB/Telegram |
| chatUsers | ON_CHANGE | Important user data |
| users | MEMORY_ONLY | Temporary UI state |

## Benefits

1. **Simple API**: Direct namespace access like current implementation
2. **Automatic**: No manual persistence management
3. **Thread-Safe**: Built-in locking
4. **Memory Efficient**: LRU eviction prevents bloat
5. **Minimal Changes**: Works with existing code structure

## Implementation Steps

1. Create `internal/cache/` module
2. Implement CacheService with LRU caches
3. Add database migration for cache_storage table
4. Update BotHandlers to use CacheService
5. Test and monitor

This simplified design maintains the benefits of centralized caching while keeping the implementation straightforward and tailored to your bot's specific needs.