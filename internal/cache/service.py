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

from .types import HCChatCacheDict, HCChatUserCacheDict, HCUserCacheDict, UserActiveActionEnum
from .models import CacheNamespace, CachePersistenceLevel

if TYPE_CHECKING:
    from ..database.wrapper import DatabaseWrapper

logger = logging.getLogger(__name__)


class LRUCache[K, V](OrderedDict[K, V]):
    """Simple LRU cache implementation with thread safety"""

    def __init__(self, maxSize: int = 1000):
        """
        Initialize LRU cache with maximum size and thread safety.

        Args:
            maxSize: Maximum number of entries before eviction (default: 1000)
        """
        super().__init__()
        self.maxSize = maxSize
        self.lock = RLock()

    def get(self, key: K, default: V) -> V:  # pyright: ignore[reportIncompatibleMethodOverride]
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

    _instance: Optional["CacheService"] = None
    _lock = RLock()

    def __new__(cls) -> "CacheService":
        """
        Create or return singleton instance with thread safety.

        Returns:
            The singleton CacheService instance
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        """
        Initialize cache service with namespaces and dirty tracking.

        Only runs once due to singleton pattern. Sets up:
        - LRU caches for chats, chat_users, and users namespaces
        - Dirty key tracking for persistence
        - Database wrapper placeholder
        """
        if not hasattr(self, "initialized"):
            self.dbWrapper: Optional["DatabaseWrapper"] = None
            self.maxCacheSize = 1000  # Per namespace

            # Initialize namespaces with LRU caches
            self._caches: Dict[
                CacheNamespace,
                LRUCache[int, HCChatCacheDict] | LRUCache[str, HCChatUserCacheDict] | LRUCache[int, HCUserCacheDict],
            ] = {
                CacheNamespace.CHATS: LRUCache[int, HCChatCacheDict](self.maxCacheSize),
                CacheNamespace.CHAT_USERS: LRUCache[str, HCChatUserCacheDict](self.maxCacheSize),
                CacheNamespace.USERS: LRUCache[int, HCUserCacheDict](self.maxCacheSize),
            }

            # Track what needs persistence
            self.dirtyKeys: Dict[CacheNamespace, set[str | int]] = {
                CacheNamespace.CHATS: set(),
                CacheNamespace.CHAT_USERS: set(),
                CacheNamespace.USERS: set(),
            }

            self.initialized = True
            logger.info("CacheService initialized, dood!")

    @classmethod
    def getInstance(cls) -> "CacheService":
        """Get singleton instance"""
        return cls()

    @property
    def chats(self) -> LRUCache[int, HCChatCacheDict]:
        """Access chats namespace"""
        return self._caches[CacheNamespace.CHATS]  # pyright: ignore[reportReturnType]

    @property
    def chatUsers(self) -> LRUCache[str, HCChatUserCacheDict]:
        """Access chatUsers namespace"""
        return self._caches[CacheNamespace.CHAT_USERS]  # pyright: ignore[reportReturnType]

    @property
    def users(self) -> LRUCache[int, HCUserCacheDict]:
        """Access users namespace"""
        return self._caches[CacheNamespace.USERS]  # pyright: ignore[reportReturnType]

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

    def setChatSettings(
        self, chatId: int, settings: Dict[ChatSettingsKey, ChatSettingsValue], rewrite: bool = False
    ) -> None:
        """Update chat settings for a specific chat, dood!

        Updates the chat settings in cache and persists them to the database if available.
        Can either merge with existing settings or completely rewrite them.

        Args:
            chatId: The unique identifier of the chat to update settings for
            settings: Dictionary mapping setting keys to their values
            rewrite: If True, replaces all existing settings with the provided ones.
                    If False (default), merges the provided settings with existing ones,
                    updating only the specified keys while preserving others.

        Side Effects:
            - Updates the in-memory cache for the specified chat
            - If dbWrapper is available:
                - Clears all existing settings in DB when rewrite=True
                - Persists each setting key-value pair to the database
            - Logs an error if dbWrapper is not available
            - Logs debug information about the update

        Note:
            Settings are stored as strings in the database regardless of their original type.
        """
        chatCache = self.chats.get(chatId, {})
        if rewrite or "settings" not in chatCache:
            chatCache["settings"] = settings
        else:
            chatCache["settings"].update(settings)

        self.chats.set(chatId, chatCache)

        # For critical settings, persist in DB
        if self.dbWrapper:
            if rewrite:
                self.dbWrapper.clearChatSettings(chatId)
            for key, value in settings.items():
                self.dbWrapper.setChatSetting(chatId, key, str(value))
        else:
            logger.error(f"No dbWrapper found, can't save chatSettings for {chatId}")

        logger.debug(f"Updated chat settings for {chatId}, dood!")

    def getChatInfo(self, chatId: int) -> Optional[ChatInfoDict]:
        """Get chat info from cache"""
        chatCache = self.chats.get(chatId, {})
        return chatCache.get("info", None)

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

        if "data" not in userCache:
            if self.dbWrapper:
                # Load from DB
                userData = {
                    k: json.loads(v) for k, v in self.dbWrapper.getUserData(userId=userId, chatId=chatId).items()
                }
                userCache["data"] = userData
                self.chatUsers.set(userKey, userCache)
                logger.debug(f"Loaded user data for {userKey} from DB, dood!")
            else:
                logger.error(f"No dbWrapper found, can't load user data for {userKey}")
                userCache["data"] = {}
                self.chatUsers.set(userKey, userCache)

        return userCache.get("data", {})

    def setChatUserData(self, chatId: int, userId: int, key: str, value: Any) -> None:
        """Set user data for a specific chat"""
        userKey = f"{chatId}:{userId}"
        userCache = self.chatUsers.get(userKey, {})
        # load userData from DB or initialise as empty dict
        self.getChatUserData(chatId, userId)

        if "data" not in userCache:
            userCache["data"] = {}

        userCache["data"][key] = value
        self.chatUsers.set(userKey, userCache)

        # Mark as dirty
        self.dirtyKeys[CacheNamespace.CHAT_USERS].add(userKey)

        # Persist to DB immediately for user data
        if self.dbWrapper:
            self.dbWrapper.addUserData(userId=userId, chatId=chatId, key=key, data=utils.jsonDumps(value))
        else:
            logger.error(f"No dbWrapper found, can't save user data for {userKey} ({key}->{value})")

        logger.debug(f"Updated user data for {userKey}, key={key}, dood!")

    def getUserState(
        self, userId: int, stateKey: UserActiveActionEnum, default: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Get temporary user state (persisted on shutdown)"""
        userState = self.users.get(userId, {})
        return userState.get(stateKey.value, default)

    def setUserState(self, userId: int, stateKey: UserActiveActionEnum, value: Dict[str, Any]) -> None:
        """Set temporary user state (persisted on shutdown)"""
        userState = self.users.get(userId, {})
        userState[stateKey.value] = value
        self.users.set(userId, userState)
        self.dirtyKeys[CacheNamespace.USERS].add(userId)
        logger.debug(f"Updated user state for {userId}, key={stateKey}, dood!")

    def clearUserState(self, userId: int, stateKey: Optional[UserActiveActionEnum] = None) -> None:
        """
        Clear user state from cache.

        Removes one or all state keys for a user. If the user has no cached state,
        the operation is skipped. The user is marked as dirty for persistence.

        Args:
            userId: The user ID whose state should be cleared
            stateKey: Specific state key to clear. If None, clears all state keys
                     from UserActiveActionEnum
        """
        if userId not in self.users:
            logger.debug(f"No cache for user #{userId}, nothing to clear")
            return
        userState = self.users.get(userId, {})
        stateList = [stateKey] if stateKey else [k for k in UserActiveActionEnum]
        for k in stateList:
            userState.pop(k.value, None)
            logger.debug(f"Cleared user state for #{userId}, key={stateKey}, dood!")

        self.users.set(userId, userState)
        self.dirtyKeys[CacheNamespace.USERS].add(userId)

    def clearNamespace(self, namespace: CacheNamespace) -> None:
        """Clear all entries in a namespace"""
        # Mark all keys dirty for deleteing them on save
        self.dirtyKeys[namespace].update(self._caches[namespace].keys())
        self._caches[namespace].clear()
        logger.info(f"Cleared namespace {namespace.value}, dood!")

    def persistAll(self) -> None:
        """Persist all dirty entries to database"""
        if not self.dbWrapper:
            logger.error("Cannot persist: no database wrapper, dood!")
            return

        totalPersisted = 0
        totalDropped = 0

        # Persist each namespace based on its persistence level
        for namespace in CacheNamespace:
            persistenceLevel = namespace.getPersistenceLevel()

            if persistenceLevel == CachePersistenceLevel.MEMORY_ONLY:
                self.dirtyKeys[namespace].clear()
                continue  # Skip persisting MEMORY_ONLY namespaces

            dirtyKeys = self.dirtyKeys[namespace]
            if not dirtyKeys:
                continue

            cache = self._caches[namespace]

            for key in list(dirtyKeys):
                data = cache.get(key, {})  # pyright: ignore[reportArgumentType]
                if data:
                    self._persistCacheEntry(namespace, str(key), data)  # pyright: ignore[reportArgumentType]
                    totalPersisted += 1
                else:
                    # If there is no data, drop it from DB as well to not load outdated cache from DB
                    self.dbWrapper.unsetCacheStorage(namespace, str(key))
                    totalDropped += 1

            # Clear dirty markers
            dirtyKeys.clear()

        logger.info(f"Persisted {totalPersisted} and dropped {totalDropped} cache entries, dood!")

    def loadFromDatabase(self) -> None:
        """Load persisted cache from database on startup"""
        if not self.dbWrapper:
            logger.warning("Cannot load: no database wrapper, dood!")
            return

        try:
            cachedData = self.dbWrapper.getCacheStorage()
            loadedCount = 0
            ignoredCount = 0

            for item in cachedData:
                namespaceStr = item["namespace"]
                key = item["key"]
                value = None
                try:
                    value = json.loads(item["value"])
                except json.JSONDecodeError as e:
                    logger.error(f"Error decoding cache value: {item}")
                    logger.exception(e)
                    ignoredCount += 1
                    continue

                # No need to set empty values
                if not value:
                    logger.error(f"Loaded empty cache value: {item}")
                    ignoredCount += 1
                    continue

                # Find matching namespace
                namespace = None
                for ns in CacheNamespace:
                    if ns.value == namespaceStr:
                        namespace = ns
                        break

                if namespace is None:
                    logger.error(f"Unknown namespace: {namespaceStr} in stored data {item}, dood!")
                    ignoredCount += 1
                    continue

                # Skip MEMORY_ONLY namespaces
                if namespace.getPersistenceLevel() == CachePersistenceLevel.MEMORY_ONLY:
                    logger.warning(f"Skipping MEMORY_ONLY namespace: {namespaceStr} (stored data is {item}), dood!")
                    ignoredCount += 1
                    continue

                cache = self._caches[namespace]

                # Convert key to appropriate type
                if namespace in (CacheNamespace.CHATS, CacheNamespace.USERS):
                    key = int(key)

                cache.set(key, value)  # pyright: ignore[reportArgumentType]
                loadedCount += 1

            logger.info(f"Loaded {loadedCount} and ignored {ignoredCount} cache entries from database, dood!")

        except Exception as e:
            logger.error(f"Error loading cache from database: {e}, dood!")
            logger.exception(e)

    def _persistCacheEntry(self, namespace: CacheNamespace, key: str, value: Dict[str, Any]) -> None:
        """Persist a single cache entry"""
        if not self.dbWrapper:
            return

        try:
            serialized = utils.jsonDumps(value)
            self.dbWrapper.setCacheStorage(
                namespace=namespace.value,
                key=key,
                value=serialized,
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
                "persistenceLevel": namespace.getPersistenceLevel().value,
            }

        return stats
