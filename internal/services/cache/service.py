"""
Cache service: Singleton cache service with LRU eviction and selective persistence
"""

import json
import logging
import time
from collections import OrderedDict
from threading import RLock
from typing import TYPE_CHECKING, Any, Dict, Optional

from internal.database.models import ChatInfoDict, ChatTopicInfoDict
from internal.services.queue_service.service import QueueService
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction
from lib import utils

from .models import CacheNamespace, CachePersistenceLevel
from .types import (
    HCChatAdminsDict,
    HCChatCacheDict,
    HCChatPersistentCacheDict,
    HCChatUserCacheDict,
    HCSpamWarningMessageInfo,
    HCUserCacheDict,
    UserActiveActionEnum,
    UserActiveConfigurationDict,
    UserDataType,
    UserDataValueType,
)

if TYPE_CHECKING:
    from ...bot.models.chat_settings import ChatSettingsKey, ChatSettingsValue
    from ...database.wrapper import DatabaseWrapper

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
                LRUCache[int, HCChatCacheDict]
                | LRUCache[str, HCChatUserCacheDict]
                | LRUCache[int, HCUserCacheDict]
                | LRUCache[int, HCChatPersistentCacheDict],
            ] = {
                CacheNamespace.CHATS: LRUCache[int, HCChatCacheDict](self.maxCacheSize),
                CacheNamespace.CHAT_PERSISTENT: LRUCache[int, HCChatPersistentCacheDict](self.maxCacheSize),
                CacheNamespace.CHAT_USERS: LRUCache[str, HCChatUserCacheDict](self.maxCacheSize),
                CacheNamespace.USERS: LRUCache[int, HCUserCacheDict](self.maxCacheSize),
            }

            # Track what needs persistence
            self.dirtyKeys: Dict[CacheNamespace, set[str | int]] = {
                CacheNamespace.CHATS: set(),
                CacheNamespace.CHAT_PERSISTENT: set(),
                CacheNamespace.CHAT_USERS: set(),
                CacheNamespace.USERS: set(),
            }

            # Register on shutdown handler
            QueueService.getInstance().registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, self._doExitHandler)
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

    @property
    def chatPersistent(self) -> LRUCache[int, HCChatPersistentCacheDict]:
        """Access chatPersistent namespace"""
        return self._caches[CacheNamespace.CHAT_PERSISTENT]  # pyright: ignore[reportReturnType]

    def injectDatabase(self, dbWrapper: "DatabaseWrapper") -> None:
        """Inject database wrapper for persistence"""
        self.dbWrapper = dbWrapper
        # Load persisted data on injection
        self.loadFromDatabase()
        logger.info("Database injected into CacheService, dood!")

    async def _doExitHandler(self, task: DelayedTask) -> None:
        """Handle delayed exit task"""
        logger.info("doExit: persisting cache to database")
        if self.dbWrapper:
            self.persistAll()
        else:
            logger.error("doExit: database wrapper not injected, dood!")

    # ## Convenience methods

    # # ChatSettings
    def getChatSettings(self, chatId: int) -> Dict["ChatSettingsKey", "ChatSettingsValue"]:
        """Get chat settings with cache"""
        # Preventing circullar dependencies
        from internal.bot.models.chat_settings import ChatSettingsKey, ChatSettingsValue

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

    def setChatSetting(self, chatId: int, key: "ChatSettingsKey", value: "ChatSettingsValue") -> None:
        """Update a single chat setting for a specific chat, dood!

        Updates one setting key-value pair in the cache and persists it to the database
        if available. Existing settings are preserved and only the specified key is updated.

        Args:
            chatId: The unique identifier of the chat to update settings for
            key: The setting key to update
            value: The new value for the setting

        Side Effects:
            - Loads existing chat settings from database if not already in cache
            - Updates the in-memory cache for the specified chat with the new key-value pair
            - If dbWrapper is available:
                - Persists the setting to the database (converted to string via value.toStr())
            - If dbWrapper is not available:
                - Logs an error message
            - Logs debug information about the update

        Note:
            Settings are stored as strings in the database using the value's toStr() method.
        """
        # Populate chat settings from db if any
        self.getChatSettings(chatId)
        chatCache = self.chats.get(chatId, {})
        if "settings" not in chatCache:
            chatCache["settings"] = {}
        chatCache["settings"][key] = value
        self.chats.set(chatId, chatCache)

        # For critical settings, persist in DB
        if self.dbWrapper:
            self.dbWrapper.setChatSetting(chatId, key, value.toStr())
        else:
            logger.error(f"No dbWrapper found, can't save chatSettings for {chatId}")

        logger.debug(f"Updated chat settings for {chatId}, dood!")

    def unsetChatSetting(self, chatId: int, key: "ChatSettingsKey") -> None:
        """Unset specified chat setting for a specific chat, dood!"""
        # Populate chat settings from db if any
        self.getChatSettings(chatId)
        chatCache = self.chats.get(chatId, {})
        if "settings" in chatCache:
            # Use pop to safely remove key, even if it doesn't exist
            chatCache["settings"].pop(key, None)
            self.chats.set(chatId, chatCache)
            if self.dbWrapper:
                self.dbWrapper.unsetChatSetting(chatId, key)
            else:
                logger.error(f"No dbWrapper found, can't unset chatSettings for {chatId}")
        logger.debug(f"Unset chat setting {key} for {chatId}, dood!")

    # # Chat Info

    def getChatInfo(self, chatId: int) -> Optional[ChatInfoDict]:
        """Get chat info from cache or database"""
        chatCache = self.chats.get(chatId, {})
        info = chatCache.get("info", None)

        # If not in cache, try loading from database
        if info is None and self.dbWrapper:
            info = self.dbWrapper.getChatInfo(chatId)
            if info:
                # Cache it for future use
                chatCache["info"] = info
                self.chats.set(chatId, chatCache)

        return info

    def setChatInfo(self, chatId: int, info: ChatInfoDict) -> None:
        """Update chat info in cache"""
        chatCache = self.chats.get(chatId, {})
        chatCache["info"] = info
        self.chats.set(chatId, chatCache)
        if self.dbWrapper:
            self.dbWrapper.updateChatInfo(
                chatId=chatId,
                type=info["type"],
                title=info["title"],
                username=info["username"],
                isForum=info["is_forum"],
            )
        else:
            logger.error(f"No dbWrapper found, can't save chat info for {chatId}")
        logger.debug(f"Updated chat info for {chatId}, dood!")

    # # Chat Topics Info

    def getChatTopicsInfo(self, chatId: int) -> Dict[int, ChatTopicInfoDict]:
        """Get all known topics info from cache or DB"""
        chatCache = self.chats.get(chatId, {})

        if "topicInfo" not in chatCache:
            chatCache["topicInfo"] = {}
            if self.dbWrapper:
                chatTopics = self.dbWrapper.getChatTopics(chatId)
                for topicInfo in chatTopics:
                    chatCache["topicInfo"][topicInfo["topic_id"]] = topicInfo
                self.chats.set(chatId, chatCache)
                logger.debug(f"Loaded topics info for {chatId} from DB, found {len(chatTopics)} topics, dood!")
            else:
                logger.error(f"No dbWrapper found, can't load topics info for {chatId}")
                return {}

        return chatCache["topicInfo"]

    def getChatTopicInfo(self, chatId: int, topicId: int) -> Optional[ChatTopicInfoDict]:
        """Get topic info from cache"""
        # Populate given chat topics from DB if any
        allTopicsInfo = self.getChatTopicsInfo(chatId)
        return allTopicsInfo.get(topicId, None)

    def setChatTopicInfo(self, chatId: int, topicId: int, info: ChatTopicInfoDict) -> None:
        """Update topic info in cache"""
        # Populate topics info from db if any
        self.getChatTopicsInfo(chatId)
        chatCache = self.chats.get(chatId, {})
        if "topicInfo" not in chatCache:
            chatCache["topicInfo"] = {}

        chatCache["topicInfo"][topicId] = info
        self.chats.set(chatId, chatCache)
        if self.dbWrapper:
            self.dbWrapper.updateChatTopicInfo(
                chatId=chatId,
                topicId=topicId,
                iconColor=info["icon_color"],
                customEmojiId=info["icon_custom_emoji_id"],
                topicName=info["name"],
            )
        else:
            logger.error(f"No dbWrapper found, can't save topic info for {chatId}:{topicId}")
        logger.debug(f"Updated topic info for {chatId}:{topicId}, dood!")

    # Chat admin list
    def getChatAdmins(self, chatId: int, ttl: Optional[int] = 300) -> Optional[Dict[int, str]]:
        """Get chat info from cache or database"""
        chatCache = self.chats.get(chatId, {})
        admins = chatCache.get("admins", None)

        # If not in cache, try loading from database
        if admins is None:
            return None

        if ttl is not None:
            if time.time() > admins["updatedAt"] + ttl:
                # Should we grop cache? No, do not want to
                return None
        return admins["admins"]

    def setChatAdmins(self, chatId: int, admins: Dict[int, str]) -> None:
        """Update chat info in cache"""
        chatCache = self.chats.get(chatId, {})
        adminsDict: HCChatAdminsDict = {
            "admins": admins.copy(),
            "updatedAt": time.time(),
        }
        chatCache["admins"] = adminsDict
        self.chats.set(chatId, chatCache)
        logger.debug(f"Updated chat admins list for {chatId}, dood!")

    # ## ChatUser UserData
    def _getChatUserKey(self, chatId: int, userId: int) -> str:
        """Get key for chat user data"""
        return f"{chatId}:{userId}"

    def getChatUserData(self, chatId: int, userId: int) -> UserDataType:
        """Get user data for a specific chat"""
        userKey = self._getChatUserKey(chatId, userId)
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

    def setChatUserData(self, chatId: int, userId: int, key: str, value: UserDataValueType) -> None:
        """Set user data for a specific chat"""
        userKey = self._getChatUserKey(chatId, userId)
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

    def unsetChatUserData(self, chatId: int, userId: int, key: str) -> None:
        """Unset user data for a specific chat"""
        userKey = self._getChatUserKey(chatId, userId)
        # Populate UserData from DB if any
        self.getChatUserData(chatId, userId)
        userCache = self.chatUsers.get(userKey, {})
        if "data" not in userCache:
            return

        userData = userCache["data"]
        userData.pop(key, None)
        self.chatUsers.set(userKey, userCache)

        if self.dbWrapper:
            self.dbWrapper.deleteUserData(userId=userId, chatId=chatId, key=key)
        else:
            logger.error(f"No dbWrapper found, can't delete user data for {userKey} ({key})")
        logger.debug(f"Unset user data for {userKey}, key={key}, dood!")

    def clearChatUserData(self, chatId: int, userId: int) -> None:
        """Clear user data for a specific chat"""
        userKey = self._getChatUserKey(chatId, userId)

        if self.dbWrapper:
            self.dbWrapper.clearUserData(userId=userId, chatId=chatId)
        else:
            logger.error(f"No dbWrapper found, can't clear user data for {userKey}")

        userCache = self.chatUsers.get(userKey, {})
        if "data" not in userCache:
            return

        userCache.pop("data", None)
        self.chatUsers.set(userKey, userCache)
        logger.debug(f"Cleared user data for {userKey}, dood!")

    # ## User State

    def getUserState(
        self, userId: int, stateKey: UserActiveActionEnum, default: Optional[UserActiveConfigurationDict] = None
    ) -> Optional[UserActiveConfigurationDict]:
        """Get temporary user state (persisted on shutdown)"""
        userState = self.users.get(userId, {})
        return userState.get(stateKey.value, default)

    def setUserState(self, userId: int, stateKey: UserActiveActionEnum, value: UserActiveConfigurationDict) -> None:
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

    # ## ChatPersistent spamWarningMessages

    def getSpamWarningMessageInfo(self, chatId: int, messageId: int) -> Optional[HCSpamWarningMessageInfo]:
        """..."""
        chatPCache = self.chatPersistent.get(chatId, {})
        messages = chatPCache.get("spamWarningMessages", {})
        return messages.get(messageId, None)

    def addSpamWarningMessage(self, chatId: int, messageId: int, data: HCSpamWarningMessageInfo) -> None:
        """..."""
        chatPCache = self.chatPersistent.get(chatId, {})
        if "spamWarningMessages" not in chatPCache:
            chatPCache["spamWarningMessages"] = {}

        chatPCache["spamWarningMessages"][messageId] = data

        self.chatPersistent.set(chatId, chatPCache)
        self.dirtyKeys[CacheNamespace.CHAT_PERSISTENT].add(chatId)
        logger.debug(f"Updated spamWarningMessage {messageId} for {chatId}, dood!")

    def removeSpamWarningMessageInfo(self, chatId: int, messageId: int) -> None:
        """..."""
        chatPCache = self.chatPersistent.get(chatId, {})
        if "spamWarningMessages" not in chatPCache:
            return

        messages = chatPCache.get("spamWarningMessages", {})
        messages.pop(messageId, None)

        self.chatPersistent.set(chatId, chatPCache)
        self.dirtyKeys[CacheNamespace.CHAT_PERSISTENT].add(chatId)
        logger.debug(f"Removed spamWarningMessage {messageId} for {chatId}, dood!")

    # Common methods
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
