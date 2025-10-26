"""
Cache service: Singleton cache service with LRU eviction and selective persistence
"""

import json
import logging
from typing import Any, Dict, Optional, TYPE_CHECKING
from threading import RLock
from collections import OrderedDict

from internal.bot.models import ChatSettingsKey, ChatSettingsValue
from internal.database.models import ChatInfoDict
from lib import utils

from .types import HCChatCacheDict
from .models import CacheNamespace, CachePersistenceLevel

if TYPE_CHECKING:
    from ..database.wrapper import DatabaseWrapper

logger = logging.getLogger(__name__)


class LRUCache[K, V](OrderedDict[K, V]):
    """Simple LRU cache implementation with thread safety"""
    
    def __init__(self, maxSize: int = 1000):
        super().__init__()
        self.maxSize = maxSize
        self.lock = RLock()
    
    def get(self, key: K, default: V) -> V: # pyright: ignore[reportIncompatibleMethodOverride]
        """Get value from cache, moving it to end (most recently used)"""
        with self.lock:
            if key not in self:
                return default
            # Move to end (most recently used)
            self.move_to_end(key)
            return self[key]
    
    def set(self, key: K, value: V) -> None:
        """Set value in cache, evicting oldest if over capacity"""
        with self.lock:
            if key in self:
                # Update and move to end
                self.move_to_end(key)
            self[key] = value
            # Evict oldest if over capacity
            if len(self) > self.maxSize:
                oldest = self.popitem(last=False)
                logger.debug(f"LRU evicted key: {oldest[0]}")
    
    def delete(self, key: K) -> bool:
        """Delete key from cache"""
        with self.lock:
            if key in self:
                del self[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all entries"""
        with self.lock:
            super().clear()


class CacheService:
    """
    Singleton cache service for Gromozeka bot.
    
    Usage:
        cache = CacheService.getInstance()
        cache.injectDatabase(dbWrapper)
        
        # Access namespaces directly
        cache.chats[123] = {"settings": {...}}
        settings = cache.chats.get(123)
        
        # Or use convenience methods
        cache.getChatSettings(123)
        cache.setUserData(123, 456, "key", "value")
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
            self.dbWrapper: Optional["DatabaseWrapper"] = None
            self.maxCacheSize = 1000  # Per namespace

            # Initialize namespaces with LRU caches
            self._caches: Dict[
                CacheNamespace,
                LRUCache[int, HCChatCacheDict] | LRUCache[str, Dict[str, Any]] | LRUCache[int, Dict[str, Any]],
            ] = {
                CacheNamespace.CHATS: LRUCache[int, HCChatCacheDict](self.maxCacheSize),
                CacheNamespace.CHAT_USERS: LRUCache[str, Dict[str, Any]](self.maxCacheSize),
                CacheNamespace.USERS: LRUCache[int, Dict[str, Any]](self.maxCacheSize),
            }

            # Track what needs persistence
            self.dirtyKeys: Dict[CacheNamespace, set] = {
                CacheNamespace.CHATS: set(),
                CacheNamespace.CHAT_USERS: set(),
                CacheNamespace.USERS: set(),
            }

            self.initialized = True
            logger.info("CacheService initialized, dood!")

    @classmethod
    def getInstance(cls) -> 'CacheService':
        """Get singleton instance"""
        return cls()

    @property
    def chats(self) -> LRUCache[int, HCChatCacheDict]:
        """Access chats namespace"""
        return self._caches[CacheNamespace.CHATS] # pyright: ignore[reportReturnType]

    @property
    def chatUsers(self) -> LRUCache[str, Dict[str, Any]]:
        """Access chatUsers namespace"""
        return self._caches[CacheNamespace.CHAT_USERS] # pyright: ignore[reportReturnType]

    @property
    def users(self) -> LRUCache[int, Dict[str, Any]]:
        """Access users namespace"""
        return self._caches[CacheNamespace.USERS] # pyright: ignore[reportReturnType]

    def injectDatabase(self, dbWrapper: "DatabaseWrapper") -> None:
        """Inject database wrapper for persistence"""
        self.dbWrapper = dbWrapper
        # Load persisted data on injection
        self.loadFromDatabase()
        logger.info("Database injected into CacheService, dood!")

    # Convenience methods for backward compatibility

    def getChatSettings(self, chatId: int) -> Dict[ChatSettingsKey, ChatSettingsValue]:
        """Get chat settings with cache"""
        chatCache = self.chats.get(chatId, {})

        if "settings" not in chatCache:
            if self.dbWrapper:
                # Load from DB
                settings = {
                      ChatSettingsKey(k): ChatSettingsValue(v) for k, v in self.dbWrapper.getChatSettings(chatId).items()
                }
                chatCache["settings"] = settings
                self.chats.set(chatId, chatCache)
                logger.debug(f"Loaded chat settings for {chatId} from DB, dood!")

        return chatCache.get("settings", {})

    def setChatSettings(self, chatId: int, settings: Dict[ChatSettingsKey, ChatSettingsValue]) -> None:
        """Update chat settings"""
        chatCache = self.chats.get(chatId, {})
        chatCache["settings"] = settings
        self.chats.set(chatId, chatCache)

        # Mark as dirty for persistence
        self.dirtyKeys[CacheNamespace.CHATS].add(chatId)

        # For critical settings, persist immediately
        if self.dbWrapper:
            for key, value in settings.items():
                self.dbWrapper.setChatSetting(chatId, key, str(value))

        logger.debug(f"Updated chat settings for {chatId}, dood!")

    def getChatInfo(self, chatId: int) -> Optional[ChatInfoDict]:
        """Get chat info from cache"""
        chatCache = self.chats.get(chatId, {})
        return chatCache.get("info")

    def setChatInfo(self, chatId: int, info: ChatInfoDict) -> None:
        """Update chat info in cache"""
        chatCache = self.chats.get(chatId, {})
        chatCache["info"] = info
        self.chats.set(chatId, chatCache)
        self.dirtyKeys[CacheNamespace.CHATS].add(chatId)
        logger.debug(f"Updated chat info for {chatId}, dood!")

    def getChatUserData(self, chatId: int, userId: int) -> Dict[str, Any]:
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
            logger.debug(f"Loaded user data for {userKey} from DB, dood!")

        return userCache.get("data", {})

    def setChatUserData(self, chatId: int, userId: int, key: str, value: Any) -> None:
        """Set user data for a specific chat"""
        userKey = f"{chatId}:{userId}"
        userCache = self.chatUsers.get(userKey, {})

        if "data" not in userCache:
            userCache["data"] = {}

        userCache["data"][key] = value
        self.chatUsers.set(userKey, userCache)

        # Mark as dirty
        self.dirtyKeys[CacheNamespace.CHAT_USERS].add(userKey)

        # Persist to DB immediately for user data (ON_CHANGE)
        if self.dbWrapper:
            self.dbWrapper.addUserData(
                userId=userId,
                chatId=chatId,
                key=key,
                data=json.dumps(value, default=str)
            )

        logger.debug(f"Updated user data for {userKey}, key={key}, dood!")

    def getUserState(self, userId: int, stateKey: str, default: Any = None) -> Any:
        """Get temporary user state (persisted on shutdown)"""
        userState = self.users.get(userId, {})
        return userState.get(stateKey, default)

    def setUserState(self, userId: int, stateKey: str, value: Any) -> None:
        """Set temporary user state (persisted on shutdown)"""
        userState = self.users.get(userId, {})
        userState[stateKey] = value
        self.users.set(userId, userState)
        logger.debug(f"Updated user state for {userId}, key={stateKey}, dood!")

    def clearUserState(self, userId: int, stateKey: Optional[str] = None) -> None:
        """Clear user state"""
        if stateKey:
            userState = self.users.get(userId, {})
            userState.pop(stateKey, None)
            self.users.set(userId, userState)
            logger.debug(f"Cleared user state for {userId}, key={stateKey}, dood!")
        else:
            self.users.delete(userId)
            logger.debug(f"Cleared all user state for {userId}, dood!")

    def clearNamespace(self, namespace: CacheNamespace) -> None:
        """Clear all entries in a namespace"""
        self._caches[namespace].clear()
        self.dirtyKeys[namespace].clear()
        logger.info(f"Cleared namespace {namespace.value}, dood!")

    def persistAll(self) -> None:
        """Persist all dirty entries to database"""
        if not self.dbWrapper:
            logger.warning("Cannot persist: no database wrapper, dood!")
            return

        totalPersisted = 0

        # Persist each namespace based on its persistence level
        for namespace in CacheNamespace:
            persistenceLevel = namespace.getPersistenceLevel()

            if persistenceLevel == CachePersistenceLevel.MEMORY_ONLY:
                continue  # Skip persisting MEMORY_ONLY namespaces

            dirtyKeys = self.dirtyKeys[namespace]
            if not dirtyKeys:
                continue

            cache = self._caches[namespace]

            for key in list(dirtyKeys):
                data = cache.get(key, {})
                if data:
                    self._persistCacheEntry(namespace, str(key), data)
                    totalPersisted += 1

            # Clear dirty markers
            dirtyKeys.clear()

        if totalPersisted > 0:
            logger.info(f"Persisted {totalPersisted} cache entries, dood!")

    def loadFromDatabase(self) -> None:
        """Load persisted cache from database on startup"""
        if not self.dbWrapper:
            logger.warning("Cannot load: no database wrapper, dood!")
            return

        try:
            cachedData = self.dbWrapper.getCacheStorage()
            loadedCount = 0

            for item in cachedData:
                namespaceStr = item["namespace"]
                key = item["key"]
                value = json.loads(item["value"])

                # Find matching namespace
                namespace = None
                for ns in CacheNamespace:
                    if ns.value == namespaceStr:
                        namespace = ns
                        break

                if namespace is None:
                    logger.warning(f"Unknown namespace: {namespaceStr}, dood!")
                    continue

                # Skip MEMORY_ONLY namespaces
                if namespace.getPersistenceLevel() == CachePersistenceLevel.MEMORY_ONLY:
                    continue

                cache = self._caches[namespace]

                # Convert key to appropriate type
                if namespace in (CacheNamespace.CHATS, CacheNamespace.USERS):
                    key = int(key)

                cache.set(key, value)  # pyright: ignore[reportArgumentType]
                loadedCount += 1

            if loadedCount > 0:
                logger.info(f"Loaded {loadedCount} cache entries from database, dood!")

        except Exception as e:
            logger.error(f"Error loading cache from database: {e}, dood!")
            logger.exception(e)

    def _persistCacheEntry(self, namespace: CacheNamespace, key: str, value: Any) -> None:
        """Persist a single cache entry"""
        if not self.dbWrapper:
            return

        try:
            serialized = utils.jsonDumps(value)
            self.dbWrapper.setCacheStorage(
                namespace=namespace.value,
                key=key,
                value=serialized
            )
        except Exception as e:
            logger.error(f"Error persisting cache entry {namespace.value}:{key}: {e}, dood!")

    def getStats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        stats = {}

        for namespace in CacheNamespace:
            cache = self._caches[namespace]
            stats[namespace.value] = {
                "size": len(cache),
                "maxSize": cache.maxSize,
                "dirty": len(self.dirtyKeys[namespace]),
                "persistenceLevel": namespace.getPersistenceLevel().value
            }

        return stats
