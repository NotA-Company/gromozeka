"""Cache service module for Gromozeka bot.

This module provides a singleton cache service with LRU (Least Recently Used) eviction
and selective persistence capabilities. It manages multiple cache namespaces for different
types of data including chat settings, user data, and persistent cache entries.

The cache service integrates with the database for persistence and provides thread-safe
operations through the use of locks. It supports automatic eviction when cache size
exceeds limits and tracks dirty keys for selective persistence.

Key Features:
    - Thread-safe LRU cache implementation
    - Multiple cache namespaces (CHATS, CHAT_PERSISTENT, CHAT_USERS, USERS)
    - Selective persistence based on namespace configuration
    - Automatic cache eviction when capacity is exceeded
    - Database integration for persistent storage
    - Dirty key tracking for efficient persistence

Example:
    >>> cache = CacheService.getInstance()
    >>> cache.injectDatabase(dbWrapper)
    >>> cache.setChatSetting(123, ChatSettingsKey.LANGUAGE, ChatSettingsValue("en"), userId=1)
    >>> settings = await cache.getChatSettings(123)
"""

import json
import logging
import time
from collections import OrderedDict
from threading import RLock
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from internal.database.models import ChatInfoDict, ChatTopicInfoDict
from internal.models import MessageIdType
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
    from internal.bot.models.chat_settings import ChatSettingsKey, ChatSettingsValue
    from internal.database import Database

logger = logging.getLogger(__name__)


class LRUCache[K, V](OrderedDict[K, V]):
    """Thread-safe LRU (Least Recently Used) cache implementation.

    This class provides a simple LRU cache with automatic eviction of the oldest
    entries when the cache size exceeds the specified maximum. All operations are
    thread-safe through the use of a reentrant lock.

    The cache maintains entries in order of access, with the most recently used
    items at the end. When the cache is full, the least recently used item is
    automatically evicted.

    Type Parameters:
        K: The type of keys in the cache
        V: The type of values in the cache

    Attributes:
        maxSize: Maximum number of entries before eviction occurs
        lock: Reentrant lock for thread-safe operations

    Example:
        >>> cache = LRUCache[int, str](maxSize=100)
        >>> cache.set(1, "value1")
        >>> value = cache.get(1, "default")
        >>> cache.delete(1)
    """

    maxSize: int
    """Maximum number of entries before eviction occurs."""

    lock: RLock
    """Reentrant lock for thread-safe operations."""

    def __init__(self, maxSize: int = 1000) -> None:
        """Initialize LRU cache with maximum size and thread safety.

        Args:
            maxSize: Maximum number of entries before eviction (default: 1000)
        """
        super().__init__()
        self.maxSize = maxSize
        self.lock = RLock()

    def get(self, key: K, default: V) -> V:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Get value from cache, moving it to end (most recently used).

        Retrieves the value associated with the key and moves it to the end of
        the ordered dictionary to mark it as most recently used. If the key is
        not found, returns the default value.

        Args:
            key: The key to retrieve from the cache
            default: The value to return if the key is not found

        Returns:
            The cached value if found, otherwise the default value
        """
        with self.lock:
            if key not in self:
                return default
            # Move to end (most recently used)
            self.move_to_end(key)
            return self[key]

    def set(self, key: K, value: V) -> None:
        """Set value in cache, evicting oldest if over capacity.

        Stores the key-value pair in the cache. If the key already exists,
        its value is updated and it's moved to the end (most recently used).
        If the cache exceeds maxSize after insertion, the least recently used
        entry is evicted.

        Args:
            key: The key to store in the cache
            value: The value to associate with the key
        """
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
        """Delete key from cache.

        Removes the specified key and its associated value from the cache.

        Args:
            key: The key to delete from the cache

        Returns:
            True if the key was found and deleted, False otherwise
        """
        with self.lock:
            if key in self:
                del self[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all entries from the cache.

        Removes all key-value pairs from the cache, resetting it to an empty state.
        """
        with self.lock:
            super().clear()


class CacheService:
    """Singleton cache service for Gromozeka bot with LRU eviction and selective persistence.

    This service provides a centralized caching mechanism with multiple namespaces for
    different types of data. It implements the singleton pattern to ensure only one
    instance exists throughout the application lifecycle. The cache supports automatic
    eviction when capacity is exceeded and selective persistence based on namespace
    configuration.

    The service integrates with the database for persistent storage and tracks dirty
    keys to optimize persistence operations. It automatically persists cache data on
    shutdown and loads persisted data on startup.

    Namespaces:
        - CHATS: Chat-specific data including settings, info, and topics
        - CHAT_PERSISTENT: Persistent chat data like spam warning messages
        - CHAT_USERS: User data scoped to specific chats
        - USERS: User-specific state and configuration data

    Example:
        >>> cache = CacheService.getInstance()
        >>> cache.injectDatabase(dbWrapper)
        >>>
        >>> # Access namespaces directly
        >>> cache.chats[123] = {"settings": {...}}
        >>> settings = cache.chats.get(123)
        >>>
        >>> # Or use convenience methods
        >>> settings = await cache.getChatSettings(123)
        >>> await cache.setChatSetting(123, ChatSettingsKey.LANGUAGE, ChatSettingsValue("en"), userId=1)
        >>> await cache.setUserData(123, 456, "key", "value")
    """

    _instance: Optional["CacheService"] = None
    """Singleton instance of the CacheService."""

    _lock: RLock = RLock()
    """Class-level lock for thread-safe singleton instantiation."""

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
            self.database: Optional["Database"] = None
            """Database wrapper for persistence operations."""

            self.maxCacheSize = 1000  # Per namespace
            """Maximum number of entries per namespace before eviction occurs."""

            # Initialize namespaces with LRU caches
            self._caches: Dict[
                CacheNamespace,
                LRUCache[int | str, HCChatCacheDict]
                | LRUCache[str, HCChatUserCacheDict]
                | LRUCache[int, HCUserCacheDict]
                | LRUCache[int, HCChatPersistentCacheDict],
            ] = {
                CacheNamespace.CHATS: LRUCache[int | str, HCChatCacheDict](self.maxCacheSize),
                CacheNamespace.CHAT_PERSISTENT: LRUCache[int, HCChatPersistentCacheDict](self.maxCacheSize),
                CacheNamespace.CHAT_USERS: LRUCache[str, HCChatUserCacheDict](self.maxCacheSize),
                CacheNamespace.USERS: LRUCache[int, HCUserCacheDict](self.maxCacheSize),
            }
            """Dictionary mapping cache namespaces to their LRU cache instances."""

            # Track what needs persistence
            self.dirtyKeys: Dict[CacheNamespace, set[str | int]] = {
                CacheNamespace.CHATS: set(),
                CacheNamespace.CHAT_PERSISTENT: set(),
                CacheNamespace.CHAT_USERS: set(),
                CacheNamespace.USERS: set(),
            }
            """Dictionary tracking keys that have been modified and need persistence."""

            # Register on shutdown handler
            QueueService.getInstance().registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, self._doExitHandler)
            self.initialized = True
            """Flag indicating whether the service has been initialized."""
            logger.info("CacheService initialized, dood!")

    @classmethod
    def getInstance(cls) -> "CacheService":
        """Get singleton instance.

        Returns the singleton CacheService instance, creating it if necessary.
        This is the preferred way to access the cache service.

        Returns:
            The singleton CacheService instance
        """
        return cls()

    @property
    def chats(self) -> LRUCache[int | str, HCChatCacheDict]:
        """Access chats namespace.

        Provides direct access to the CHATS namespace cache which stores
        chat-specific data including settings, info, topics, and admins.

        Returns:
            The LRU cache for the CHATS namespace
        """
        return self._caches[CacheNamespace.CHATS]  # pyright: ignore[reportReturnType]

    @property
    def chatUsers(self) -> LRUCache[str, HCChatUserCacheDict]:
        """Access chatUsers namespace.

        Provides direct access to the CHAT_USERS namespace cache which stores
        user data scoped to specific chats.

        Returns:
            The LRU cache for the CHAT_USERS namespace
        """
        return self._caches[CacheNamespace.CHAT_USERS]  # pyright: ignore[reportReturnType]

    @property
    def users(self) -> LRUCache[int, HCUserCacheDict]:
        """Access users namespace.

        Provides direct access to the USERS namespace cache which stores
        user-specific state and configuration data.

        Returns:
            The LRU cache for the USERS namespace
        """
        return self._caches[CacheNamespace.USERS]  # pyright: ignore[reportReturnType]

    @property
    def chatPersistent(self) -> LRUCache[int, HCChatPersistentCacheDict]:
        """Access chatPersistent namespace.

        Provides direct access to the CHAT_PERSISTENT namespace cache which stores
        persistent chat data like spam warning messages.

        Returns:
            The LRU cache for the CHAT_PERSISTENT namespace
        """
        return self._caches[CacheNamespace.CHAT_PERSISTENT]  # pyright: ignore[reportReturnType]

    async def injectDatabase(self, database: "Database") -> None:
        """Inject database wrapper for persistence.

        Sets the database wrapper for persistence operations and loads any
        previously persisted cache data from the database. This should be
        called once during application initialization.

        Args:
            database: The database wrapper instance for persistence operations
        """
        self.database = database
        # Load persisted data on injection
        await self.loadFromDatabase()
        logger.info("Database injected into CacheService, dood!")

    async def _doExitHandler(self, task: DelayedTask) -> None:
        """Handle delayed exit task.

        Called when the application is shutting down to persist all dirty
        cache entries to the database before termination.

        Args:
            task: The delayed task triggering the exit handler
        """
        logger.info("doExit: persisting cache to database")
        if self.database:
            await self.persistAll()
        else:
            logger.error("doExit: database wrapper not injected, dood!")

    # ## Convenience methods

    # # ChatSettings
    def setDefaultChatSettings(self, key: Optional[str], value: Dict["ChatSettingsKey", "ChatSettingsValue"]) -> None:
        """Set default chat settings for a given key in the cache.

        Updates the settings for the specified key in the chats cache. If the key
        doesn't exist in the cache, a new entry will be created. The settings
        are stored under the 'settings' key in the chat cache dictionary.

        Note:
            This method only updates the in-memory cache and does not persist
            to the database. Settings may be lost if evicted from cache.

        Args:
            key: The key to identify the chat settings (typically chat ID or 'default')
            value: A dictionary mapping ChatSettingsKey to ChatSettingsValue
                   containing the settings to be stored
        """
        key = str(key)
        chatCache = self.chats.get(key, {})
        chatCache["settings"] = value.copy()
        self.chats.set(key, chatCache)

        # TODO: Should we persist it in DB to ensure it won't be wanished from cache?
        logger.debug(f"Updated default chat settings for {key}, dood!")

    def getDefaultChatSettings(self, key: Optional[str]) -> Dict["ChatSettingsKey", "ChatSettingsValue"]:
        """Get default chat settings for a given key from the cache.

        Retrieves the chat settings for the specified key from the chats cache.
        If the key doesn't exist in the cache or has no settings, an empty
        dictionary is returned.

        Note:
            This method only reads from the in-memory cache and does not load
            from the database. Returns a copy to prevent mutation of cached data.

        Args:
            key: The key to identify the chat settings (typically chat ID or 'default')

        Returns:
            A dictionary mapping ChatSettingsKey to ChatSettingsValue containing
            the retrieved settings, or an empty dictionary if no settings exist
        """
        key = str(key)
        chatCache = self.chats.get(key, {})

        # TODO: Should I add loading from DB?
        return chatCache.get("settings", {}).copy()

    async def getChatSettings(self, chatId: int) -> Dict["ChatSettingsKey", "ChatSettingsValue"]:
        """Get chat settings with cache and database fallback.

        Retrieves chat settings from the cache. If not present in cache, loads
        them from the database and caches the result. Returns an empty dictionary
        if settings are not found in either cache or database.

        Args:
            chatId: The unique identifier of the chat to get settings for

        Returns:
            A dictionary mapping ChatSettingsKey to ChatSettingsValue containing
            the chat settings, or an empty dictionary if no settings exist
        """
        # Preventing circullar dependencies TODO: Do something with it
        from internal.bot.models.chat_settings import ChatSettingsKey, ChatSettingsValue

        chatCache = self.chats.get(chatId, {})

        if "settings" not in chatCache:
            if self.database:
                # Load from DB
                settings = {
                    ChatSettingsKey(k): ChatSettingsValue(v1, v2)
                    for k, (v1, v2) in (await self.database.chatSettings.getChatSettings(chatId)).items()
                }
                chatCache["settings"] = settings
                self.chats.set(chatId, chatCache)
                logger.debug(f"Loaded chat settings for {chatId} from DB, dood!")

        return chatCache.get("settings", {})

    async def setChatSetting(
        self, chatId: int, key: "ChatSettingsKey", value: "ChatSettingsValue", *, userId: int
    ) -> None:
        """Update a single chat setting for a specific chat.

        Updates one setting key-value pair in the cache and persists it to the database
        if available. Existing settings are preserved and only the specified key is updated.

        Args:
            chatId: The unique identifier of the chat to update settings for
            key: The setting key to update
            value: The new value for the setting
            userId: The ID of the user making the change (for audit trail)

        Side Effects:
            - Clears any cached settings for the chat
            - Loads existing chat settings from database if not already in cache
            - Updates the in-memory cache for the specified chat with the new key-value pair
            - If database is available:
                - Persists the setting to the database (converted to string via value.toStr())
            - If database is not available:
                - Logs an error message
            - Logs debug information about the update

        Note:
            Settings are stored as strings in the database using the value's toStr() method.
        """

        self.clearCachedChatSettings(chatId)

        # Populate chat settings from db if any
        await self.getChatSettings(chatId)
        chatCache = self.chats.get(chatId, {})
        if "settings" not in chatCache:
            chatCache["settings"] = {}
        chatCache["settings"][key] = value
        self.chats.set(chatId, chatCache)

        # For critical settings, persist in DB
        if self.database:
            await self.database.chatSettings.setChatSetting(chatId, key, value.toStr(), updatedBy=userId)
        else:
            logger.error(f"No dbWrapper found, can't save chatSettings for {chatId}")

        logger.debug(f"Updated chat settings for {chatId}, dood!")

    async def unsetChatSetting(self, chatId: int, key: "ChatSettingsKey") -> None:
        """Unset specified chat setting for a specific chat.

        Removes the specified setting key from the chat's settings in both cache
        and database. If the key doesn't exist, the operation is a no-op.

        Args:
            chatId: The unique identifier of the chat to update settings for
            key: The setting key to remove

        Side Effects:
            - Clears any cached settings for the chat
            - Loads existing chat settings from database if not already in cache
            - Removes the specified key from the in-memory cache
            - If database is available:
                - Removes the setting from the database
            - If database is not available:
                - Logs an error message
            - Logs debug information about the update
        """

        self.clearCachedChatSettings(chatId)

        # Populate chat settings from db if any
        await self.getChatSettings(chatId)
        chatCache = self.chats.get(chatId, {})
        if "settings" in chatCache:
            # Use pop to safely remove key, even if it doesn't exist
            chatCache["settings"].pop(key, None)
            self.chats.set(chatId, chatCache)
            if self.database:
                await self.database.chatSettings.unsetChatSetting(chatId, key)
            else:
                logger.error(f"No dbWrapper found, can't unset chatSettings for {chatId}")

        logger.debug(f"Unset chat setting {key} for {chatId}, dood!")

    # Cached chat settings
    def getCachedChatSettings(
        self, chatId: int, ttl: Optional[int] = 600
    ) -> Optional[Dict["ChatSettingsKey", "ChatSettingsValue"]]:
        """Get cached chat settings with TTL validation.

        Retrieves cached chat settings if they exist and haven't expired based on
        the time-to-live (TTL) parameter. Returns None if settings are not cached
        or have expired.

        Args:
            chatId: The unique identifier of the chat to get cached settings for
            ttl: Time-to-live in seconds for the cached settings (default: 600).
                 If None, TTL validation is skipped

        Returns:
            The cached settings dictionary if found and not expired, None otherwise
        """
        # Preventing circullar dependencies TODO: Do something with it
        from internal.bot.models.chat_settings import ChatSettingsKey

        chatCache = self.chats.get(chatId, {})
        cachedSettings = chatCache.get("cachedSettings", None)

        # If not in cache, try loading from database
        if cachedSettings is None:
            return None

        if ttl is not None:
            if time.time() > cachedSettings[ChatSettingsKey.CACHED_TS].toFloat() + ttl:
                # Should we drop cache? No, do not want to
                return None
        return cachedSettings

    def cacheChatSettings(self, chatId: int, settings: Dict["ChatSettingsKey", "ChatSettingsValue"]) -> None:
        """Cache chat settings with a timestamp for TTL validation.

        Stores the provided settings in the cache with a timestamp that can be used
        for time-to-live (TTL) validation. This is useful for caching settings that
        may change frequently and need to be refreshed periodically.

        Args:
            chatId: The unique identifier of the chat to cache settings for
            settings: A dictionary mapping ChatSettingsKey to ChatSettingsValue
                     containing the settings to cache

        Note:
            A CACHED_TS timestamp is automatically added to the settings for TTL
            validation purposes.
        """
        # Preventing circullar dependencies TODO: Do something with it
        from internal.bot.models.chat_settings import ChatSettingsKey, ChatSettingsValue

        settings[ChatSettingsKey.CACHED_TS] = ChatSettingsValue(time.time())

        chatCache = self.chats.get(chatId, {})
        chatCache["cachedSettings"] = settings
        self.chats.set(chatId, chatCache)

        logger.debug(f"cache chat settings for {chatId}, dood!")

    def clearCachedChatSettings(self, chatId: int) -> None:
        """Clear cached chat settings for a specific chat.

        Removes the cached settings for the specified chat from the cache. This
        forces the next call to getCachedChatSettings to return None, which will
        trigger a reload from the database.

        Args:
            chatId: The unique identifier of the chat to clear cached settings for
        """
        chatCache = self.chats.get(chatId, {})
        if "cachedSettings" in chatCache:
            del chatCache["cachedSettings"]
            self.chats.set(chatId, chatCache)
        logger.debug(f"Cleared cached chat settings for {chatId}, dood!")

    # # Chat Info

    async def getChatInfo(self, chatId: int) -> Optional[ChatInfoDict]:
        """Get chat info from cache or database.

        Retrieves chat information from the cache. If not present in cache, loads
        it from the database and caches the result. Returns None if chat info is
        not found in either cache or database.

        Args:
            chatId: The unique identifier of the chat to get info for

        Returns:
            A ChatInfoDict containing the chat information, or None if not found
        """
        chatCache = self.chats.get(chatId, {})
        info = chatCache.get("info", None)

        # If not in cache, try loading from database
        if info is None and self.database:
            info = await self.database.chatInfo.getChatInfo(chatId)
            if info:
                # Cache it for future use
                chatCache["info"] = info
                self.chats.set(chatId, chatCache)

        return info

    async def setChatInfo(self, chatId: int, info: ChatInfoDict) -> None:
        """Update chat info in cache and database.

        Updates the chat information in the cache and persists it to the database
        if available. This method should be called when chat information changes.

        Args:
            chatId: The unique identifier of the chat to update info for
            info: A ChatInfoDict containing the updated chat information

        Side Effects:
            - Updates the in-memory cache with the new chat info
            - If database is available:
                - Persists the chat info to the database
            - If database is not available:
                - Logs an error message
            - Logs debug information about the update
        """
        chatCache = self.chats.get(chatId, {})
        chatCache["info"] = info
        self.chats.set(chatId, chatCache)
        if self.database:
            await self.database.chatInfo.updateChatInfo(
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

    async def getChatTopicsInfo(self, chatId: int) -> Dict[int, ChatTopicInfoDict]:
        """Get all known topics info from cache or database.

        Retrieves all topic information for a chat from the cache. If not present
        in cache, loads them from the database and caches the result. Returns an
        empty dictionary if no topics are found or database is unavailable.

        Args:
            chatId: The unique identifier of the chat to get topics info for

        Returns:
            A dictionary mapping topic IDs to ChatTopicInfoDict containing the
            topic information, or an empty dictionary if no topics exist
        """
        chatCache = self.chats.get(chatId, {})

        if "topicInfo" not in chatCache:
            chatCache["topicInfo"] = {}
            if self.database:
                chatTopics = await self.database.chatInfo.getChatTopics(chatId)
                for topicInfo in chatTopics:
                    chatCache["topicInfo"][topicInfo["topic_id"]] = topicInfo
                self.chats.set(chatId, chatCache)
                logger.debug(f"Loaded topics info for {chatId} from DB, found {len(chatTopics)} topics, dood!")
            else:
                logger.error(f"No dbWrapper found, can't load topics info for {chatId}")
                return {}

        return chatCache["topicInfo"]

    async def getChatTopicInfo(self, chatId: int, topicId: int) -> Optional[ChatTopicInfoDict]:
        """Get topic info from cache.

        Retrieves information for a specific topic within a chat. Loads all topics
        from the database if not already cached, then returns the requested topic.

        Args:
            chatId: The unique identifier of the chat
            topicId: The unique identifier of the topic to get info for

        Returns:
            A ChatTopicInfoDict containing the topic information, or None if the
            topic is not found
        """
        # Populate given chat topics from DB if any
        allTopicsInfo = await self.getChatTopicsInfo(chatId)
        return allTopicsInfo.get(topicId, None)

    async def setChatTopicInfo(self, chatId: int, topicId: int, info: ChatTopicInfoDict) -> None:
        """Update topic info in cache and database.

        Updates the topic information in the cache and persists it to the database
        if available. This method should be called when topic information changes.

        Args:
            chatId: The unique identifier of the chat
            topicId: The unique identifier of the topic to update
            info: A ChatTopicInfoDict containing the updated topic information

        Side Effects:
            - Loads all topics from database if not already cached
            - Updates the in-memory cache with the new topic info
            - If database is available:
                - Persists the topic info to the database
            - If database is not available:
                - Logs an error message
            - Logs debug information about the update
        """
        # Populate topics info from db if any
        await self.getChatTopicsInfo(chatId)
        chatCache = self.chats.get(chatId, {})
        if "topicInfo" not in chatCache:
            chatCache["topicInfo"] = {}

        chatCache["topicInfo"][topicId] = info
        self.chats.set(chatId, chatCache)
        if self.database:
            await self.database.chatInfo.updateChatTopicInfo(
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
    def getChatAdmins(self, chatId: int, ttl: Optional[int] = 300) -> Optional[Dict[int, Tuple[str, str]]]:
        """Get chat admins from cache with TTL validation.

        Retrieves the cached list of chat administrators if they exist and haven't
        expired based on the time-to-live (TTL) parameter. Returns None if admins
        are not cached or have expired.

        Args:
            chatId: The unique identifier of the chat to get admins for
            ttl: Time-to-live in seconds for the cached admins (default: 300).
                 If None, TTL validation is skipped

        Returns:
            A dictionary mapping user IDs to tuples of (username, full_name) for
            each admin, or None if not cached or expired
        """
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

    def setChatAdmins(self, chatId: int, admins: Dict[int, Tuple[str, str]]) -> None:
        """Update chat admins in cache with timestamp.

        Stores the list of chat administrators in the cache with a timestamp for
        TTL validation. This is useful for caching admin lists that may change
        periodically and need to be refreshed.

        Args:
            chatId: The unique identifier of the chat to update admins for
            admins: A dictionary mapping user IDs to tuples of (username, full_name)
                   for each admin

        Note:
            An updatedAt timestamp is automatically added for TTL validation purposes.
        """
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
        """Generate a unique key for chat user data.

        Creates a composite key string from chat ID and user ID for storing
        user data scoped to a specific chat.

        Args:
            chatId: The unique identifier of the chat
            userId: The unique identifier of the user

        Returns:
            A string key in the format "chatId:userId"
        """
        return f"{chatId}:{userId}"

    async def getChatUserData(self, chatId: int, userId: int) -> UserDataType:
        """Get user data for a specific chat.

        Retrieves user data scoped to a specific chat from the cache. If not
        present in cache, loads it from the database and caches the result.
        Returns an empty dictionary if no data is found or database is unavailable.

        Args:
            chatId: The unique identifier of the chat
            userId: The unique identifier of the user

        Returns:
            A UserDataType dictionary containing the user's data for the chat,
            or an empty dictionary if no data exists
        """
        userKey = self._getChatUserKey(chatId, userId)
        userCache = self.chatUsers.get(userKey, {})

        if "data" not in userCache:
            if self.database:
                # Load from DB
                userData = {
                    k: json.loads(v)
                    for k, v in (await self.database.userData.getUserData(userId=userId, chatId=chatId)).items()
                }
                userCache["data"] = userData
                self.chatUsers.set(userKey, userCache)
                logger.debug(f"Loaded user data for {userKey} from DB, dood!")
            else:
                logger.error(f"No dbWrapper found, can't load user data for {userKey}")
                userCache["data"] = {}
                self.chatUsers.set(userKey, userCache)

        return userCache.get("data", {})

    async def setChatUserData(self, chatId: int, userId: int, key: str, value: UserDataValueType) -> None:
        """Set user data for a specific chat.

        Stores a key-value pair in the user data scoped to a specific chat.
        The data is persisted to the database immediately and marked as dirty
        for cache persistence.

        Args:
            chatId: The unique identifier of the chat
            userId: The unique identifier of the user
            key: The data key to set
            value: The data value to store

        Side Effects:
            - Loads existing user data from database if not already cached
            - Updates the in-memory cache with the new key-value pair
            - Marks the user key as dirty for persistence
            - If database is available:
                - Persists the data to the database immediately
            - If database is not available:
                - Logs an error message
            - Logs debug information about the update
        """
        userKey = self._getChatUserKey(chatId, userId)
        userCache = self.chatUsers.get(userKey, {})
        # load userData from DB or initialise as empty dict
        await self.getChatUserData(chatId, userId)

        if "data" not in userCache:
            userCache["data"] = {}

        userCache["data"][key] = value
        self.chatUsers.set(userKey, userCache)

        # Mark as dirty
        self.dirtyKeys[CacheNamespace.CHAT_USERS].add(userKey)

        # Persist to DB immediately for user data
        if self.database:
            await self.database.userData.addUserData(userId=userId, chatId=chatId, key=key, data=utils.jsonDumps(value))
        else:
            logger.error(f"No dbWrapper found, can't save user data for {userKey} ({key}->{value})")

        logger.debug(f"Updated user data for {userKey}, key={key}, dood!")

    async def unsetChatUserData(self, chatId: int, userId: int, key: str) -> None:
        """Unset user data for a specific chat.

        Removes a specific key from the user data scoped to a specific chat.
        The key is removed from both the cache and the database.

        Args:
            chatId: The unique identifier of the chat
            userId: The unique identifier of the user
            key: The data key to remove

        Side Effects:
            - Loads existing user data from database if not already cached
            - Removes the specified key from the in-memory cache
            - If database is available:
                - Removes the key from the database
            - If database is not available:
                - Logs an error message
            - Logs debug information about the update
        """
        userKey = self._getChatUserKey(chatId, userId)
        # Populate UserData from DB if any
        await self.getChatUserData(chatId, userId)
        userCache = self.chatUsers.get(userKey, {})
        if "data" not in userCache:
            return

        userData = userCache["data"]
        userData.pop(key, None)
        self.chatUsers.set(userKey, userCache)

        if self.database:
            await self.database.userData.deleteUserData(userId=userId, chatId=chatId, key=key)
        else:
            logger.error(f"No dbWrapper found, can't delete user data for {userKey} ({key})")
        logger.debug(f"Unset user data for {userKey}, key={key}, dood!")

    async def clearChatUserData(self, chatId: int, userId: int) -> None:
        """Clear all user data for a specific chat.

        Removes all user data scoped to a specific chat from both the cache
        and the database.

        Args:
            chatId: The unique identifier of the chat
            userId: The unique identifier of the user

        Side Effects:
            - If database is available:
                - Removes all user data from the database
            - If database is not available:
                - Logs an error message
            - Removes all user data from the in-memory cache
            - Logs debug information about the update
        """
        userKey = self._getChatUserKey(chatId, userId)

        if self.database:
            await self.database.userData.clearUserData(userId=userId, chatId=chatId)
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
        """Get temporary user state.

        Retrieves a temporary user state value that is persisted on shutdown.
        This is useful for storing user-specific state that should survive
        application restarts.

        Args:
            userId: The unique identifier of the user
            stateKey: The state key to retrieve
            default: The default value to return if the state key is not found

        Returns:
            The user state value if found, otherwise the default value
        """
        userState = self.users.get(userId, {})
        return userState.get(stateKey, default)

    def setUserState(self, userId: int, stateKey: UserActiveActionEnum, value: UserActiveConfigurationDict) -> None:
        """Set temporary user state.

        Stores a temporary user state value that is persisted on shutdown.
        This is useful for storing user-specific state that should survive
        application restarts.

        Args:
            userId: The unique identifier of the user
            stateKey: The state key to set
            value: The state value to store

        Side Effects:
            - Updates the in-memory cache with the new state value
            - Marks the user as dirty for persistence
            - Logs debug information about the update
        """
        userState = self.users.get(userId, {})
        userState[stateKey] = value
        self.users.set(userId, userState)
        self.dirtyKeys[CacheNamespace.USERS].add(userId)
        logger.debug(f"Updated user state for {userId}, key={stateKey}, dood!")

    def clearUserState(self, userId: int, stateKey: Optional[UserActiveActionEnum] = None) -> None:
        """Clear user state from cache.

        Removes one or all state keys for a user. If the user has no cached state,
        the operation is skipped. The user is marked as dirty for persistence.

        Args:
            userId: The user ID whose state should be cleared
            stateKey: Specific state key to clear. If None, clears all state keys
                     from UserActiveActionEnum

        Side Effects:
            - Removes the specified state key or all state keys from the cache
            - Marks the user as dirty for persistence
            - Logs debug information about the update
        """
        if userId not in self.users:
            logger.debug(f"No cache for user #{userId}, nothing to clear")
            return
        userState = self.users.get(userId, {})
        stateList = [stateKey] if stateKey else [k for k in UserActiveActionEnum]
        for k in stateList:
            userState.pop(k, None)
            logger.debug(f"Cleared user state for #{userId}, key={stateKey}, dood!")

        self.users.set(userId, userState)
        self.dirtyKeys[CacheNamespace.USERS].add(userId)

    # ## ChatPersistent spamWarningMessages

    def getSpamWarningMessageInfo(self, chatId: int, messageId: MessageIdType) -> Optional[HCSpamWarningMessageInfo]:
        """Get spam warning message info from persistent cache.

        Args:
            chatId: The chat ID to get spam warning info for
            messageId: The message ID to get spam warning info for

        Returns:
            The spam warning message info if found, None otherwise
        """
        chatPCache = self.chatPersistent.get(chatId, {})
        messages = chatPCache.get("spamWarningMessages", {})
        return messages.get(messageId, None)

    def addSpamWarningMessage(self, chatId: int, messageId: MessageIdType, data: HCSpamWarningMessageInfo) -> None:
        """Add spam warning message info to persistent cache.

        Args:
            chatId: The chat ID to add spam warning info for
            messageId: The message ID to add spam warning info for
            data: The spam warning message info to add
        """
        chatPCache = self.chatPersistent.get(chatId, {})
        if "spamWarningMessages" not in chatPCache:
            chatPCache["spamWarningMessages"] = {}

        chatPCache["spamWarningMessages"][messageId] = data

        self.chatPersistent.set(chatId, chatPCache)
        self.dirtyKeys[CacheNamespace.CHAT_PERSISTENT].add(chatId)
        logger.debug(f"Updated spamWarningMessage {messageId} for {chatId}, dood!")

    def removeSpamWarningMessageInfo(self, chatId: int, messageId: MessageIdType) -> None:
        """Remove spam warning message info from persistent cache.

        Args:
            chatId: The chat ID to remove spam warning info for
            messageId: The message ID to remove spam warning info for
        """
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
        """Clear all entries in a namespace.

        Removes all entries from the specified cache namespace and marks all
        keys as dirty for deletion from the database on the next persist operation.

        Args:
            namespace: The cache namespace to clear

        Side Effects:
            - Marks all keys in the namespace as dirty
            - Clears all entries from the in-memory cache
            - Logs information about the operation
        """
        # Mark all keys dirty for deleteing them on save
        self.dirtyKeys[namespace].update(self._caches[namespace].keys())
        self._caches[namespace].clear()
        logger.info(f"Cleared namespace {namespace.value}, dood!")

    async def persistAll(self) -> None:
        """Persist all dirty entries to database.

        Persists all modified cache entries to the database based on their
        namespace's persistence level. Entries with no data are removed from
        the database to prevent loading stale data on startup.

        Note:
            - MEMORY_ONLY namespaces are skipped
            - Only dirty keys are persisted
            - Empty entries are removed from the database

        Side Effects:
            - Persists dirty cache entries to the database
            - Removes empty entries from the database
            - Clears dirty markers for persisted entries
            - Logs statistics about the operation
        """
        if not self.database:
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
                    await self._persistCacheEntry(namespace, str(key), data)  # pyright: ignore[reportArgumentType]
                    totalPersisted += 1
                else:
                    # If there is no data, drop it from DB as well to not load outdated cache from DB
                    await self.database.cache.unsetCacheStorage(namespace, str(key))
                    totalDropped += 1

            # Clear dirty markers
            dirtyKeys.clear()

        logger.info(f"Persisted {totalPersisted} and dropped {totalDropped} cache entries, dood!")

    async def loadFromDatabase(self) -> None:
        """Load persisted cache from database on startup.

        Loads all previously persisted cache entries from the database and
        populates the in-memory cache. Invalid or empty entries are skipped.

        Note:
            - MEMORY_ONLY namespaces are skipped
            - Invalid JSON values are logged and skipped
            - Empty values are logged and skipped
            - Unknown namespaces are logged and skipped

        Side Effects:
            - Populates the in-memory cache with data from the database
            - Logs statistics about loaded and ignored entries
            - Logs errors for invalid entries
        """
        if not self.database:
            logger.warning("Cannot load: no database wrapper, dood!")
            return

        try:
            cachedData = await self.database.cache.getCacheStorage()
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

    async def _persistCacheEntry(self, namespace: CacheNamespace, key: str, value: Dict[str, Any]) -> None:
        """Persist a single cache entry to the database.

        Serializes and stores a cache entry in the database. Errors are logged
        but do not prevent other entries from being persisted.

        Args:
            namespace: The cache namespace for the entry
            key: The cache key for the entry
            value: The cache value to persist

        Side Effects:
            - Stores the serialized cache entry in the database
            - Logs errors if persistence fails
        """
        if not self.database:
            return

        try:
            serialized = utils.jsonDumps(value)
            await self.database.cache.setCacheStorage(
                namespace=namespace.value,
                key=key,
                value=serialized,
            )
        except Exception as e:
            logger.error(f"Error persisting cache entry {namespace.value}:{key}: {e}, dood!")

    def getStats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns statistics about the current state of all cache namespaces,
        including size, maximum size, dirty key count, and persistence level.

        Returns:
            A dictionary mapping namespace names to their statistics, including:
            - size: Current number of entries in the namespace
            - maxSize: Maximum number of entries before eviction
            - dirty: Number of dirty keys pending persistence
            - persistenceLevel: The persistence level of the namespace
        """
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
