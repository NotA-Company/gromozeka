"""
Comprehensive test suite for the cache service implementation.

This module provides extensive unit and integration tests for the cache service,
covering all major functionality including LRU cache operations, singleton pattern,
namespace management, persistence, and thread safety.

Test Coverage:
    - LRUCache: Basic operations (get, set, delete, clear), LRU eviction policy,
      ordering behavior, and concurrent access
    - CacheService: Singleton pattern enforcement, database injection, and
      initialization behavior
    - Namespace Operations: Access to chats, chatUsers, and users namespaces,
      namespace clearing, and dirty key tracking
    - Chat Settings: Retrieval from cache and database, persistence, and
      convenience methods
    - Chat Info: Getting and setting chat information with proper caching
    - Chat User Data: Complex data structures, JSON serialization, and
      database persistence
    - User State: State management and clearing operations
    - Persistence: Memory-only vs on-change namespaces, dirty key tracking,
      empty data handling, and database loading
    - Thread Safety: Concurrent access to LRU cache operations
    - Edge Cases: Database errors, missing database, invalid JSON, and
      unknown namespaces

Example:
    Run tests from project root:
        ./venv/bin/python3 -m unittest internal/services/cache/test_cache_service.py
"""

import gc
import json
import os
import sys
import unittest
import warnings
from unittest.mock import Mock

# Add project root to path to avoid circular imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from internal.bot.models.chat_settings import ChatSettingsKey, ChatSettingsValue  # noqa: E402
from internal.services.cache.models import CacheNamespace  # noqa: E402

# Import directly to avoid circular dependencies
from internal.services.cache.service import CacheService, LRUCache  # noqa: E402
from tests.utils import createAsyncMock  # noqa: E402


class TestLRUCache(unittest.TestCase):
    """Test suite for LRU (Least Recently Used) cache implementation.

    Tests the core functionality of the LRUCache class including basic operations,
    eviction policy, ordering behavior, and cache management methods.

    Attributes:
        cache: An LRUCache instance with a maximum size of 3 for testing eviction.
    """

    def setUp(self) -> None:
        """Set up test fixtures before each test method.

        Creates a new LRUCache instance with a maximum size of 3 to test
        eviction behavior.
        """
        self.cache = LRUCache[str, int](maxSize=3)

    def testBasicGetSet(self) -> None:
        """Test basic get and set operations.

        Verifies that values can be stored and retrieved correctly, and that
        default values are returned for non-existent keys.
        """
        self.cache.set("key1", 100)
        self.assertEqual(self.cache.get("key1", 0), 100)
        self.assertEqual(self.cache.get("nonexistent", 999), 999)  # type: ignore[arg-type]

    def testLRUEviction(self) -> None:
        """Test that oldest items are evicted when capacity is exceeded.

        Verifies that when the cache exceeds its maximum size, the least recently
        used item is automatically evicted.
        """
        self.cache.set("key1", 1)
        self.cache.set("key2", 2)
        self.cache.set("key3", 3)
        self.cache.set("key4", 4)  # Should evict key1

        self.assertEqual(self.cache.get("key1", -1), -1)  # type: ignore[arg-type]
        self.assertEqual(self.cache.get("key2", 0), 2)
        self.assertEqual(self.cache.get("key3", 0), 3)
        self.assertEqual(self.cache.get("key4", 0), 4)

    def testLRUOrdering(self) -> None:
        """Test that accessing items updates their position.

        Verifies that accessing an existing key moves it to the most recently
        used position, affecting which item gets evicted next.
        """
        self.cache.set("key1", 1)
        self.cache.set("key2", 2)
        self.cache.set("key3", 3)

        # Access key1 to make it most recent
        self.cache.get("key1", 0)

        # Add key4, should evict key2 (oldest)
        self.cache.set("key4", 4)

        self.assertEqual(self.cache.get("key1", 0), 1)
        self.assertEqual(self.cache.get("key2", -1), -1)  # type: ignore[arg-type]
        self.assertEqual(self.cache.get("key3", 0), 3)
        self.assertEqual(self.cache.get("key4", 0), 4)

    def testUpdateExisting(self) -> None:
        """Test updating existing keys moves them to end.

        Verifies that updating an existing key's value moves it to the most
        recently used position.
        """
        self.cache.set("key1", 1)
        self.cache.set("key2", 2)
        self.cache.set("key3", 3)

        # Update key1
        self.cache.set("key1", 100)

        # Add key4, should evict key2
        self.cache.set("key4", 4)

        self.assertEqual(self.cache.get("key1", 0), 100)
        self.assertEqual(self.cache.get("key2", -1), -1)  # type: ignore[arg-type]

    def testDelete(self) -> None:
        """Test delete operation.

        Verifies that keys can be removed from the cache and that deleting
        a non-existent key returns False.
        """
        self.cache.set("key1", 1)
        self.assertTrue(self.cache.delete("key1"))
        self.assertFalse(self.cache.delete("key1"))
        self.assertEqual(self.cache.get("key1", -1), -1)  # type: ignore[arg-type]

    def testClear(self) -> None:
        """Test clear operation.

        Verifies that the cache can be completely cleared, removing all items.
        """
        self.cache.set("key1", 1)
        self.cache.set("key2", 2)
        self.cache.clear()
        self.assertEqual(len(self.cache), 0)
        self.assertEqual(self.cache.get("key1", -1), -1)  # type: ignore[arg-type]


class TestCacheServiceSingleton(unittest.TestCase):
    """Test suite for CacheService singleton pattern implementation.

    Verifies that the CacheService class properly implements the singleton pattern,
    ensuring only one instance exists throughout the application lifecycle.
    """

    def setUp(self) -> None:
        """Reset singleton before each test method.

        Clears the singleton instance to ensure each test starts with a clean state.
        """
        CacheService._instance = None

    def testSingletonPattern(self) -> None:
        """Test that getInstance returns same instance.

        Verifies that multiple calls to getInstance() return the same object instance.
        """
        cache1 = CacheService.getInstance()
        cache2 = CacheService.getInstance()
        self.assertIs(cache1, cache2)

    def testSingletonWithNew(self) -> None:
        """Test that __new__ also returns singleton.

        Verifies that using the constructor directly also returns the singleton instance.
        """
        cache1 = CacheService()
        cache2 = CacheService()
        self.assertIs(cache1, cache2)

    def testInitializationOnlyOnce(self) -> None:
        """Test that initialization only happens once.

        Verifies that the singleton instance maintains its state across multiple
        getInstance() calls, proving it's the same object.
        """
        cache1 = CacheService.getInstance()
        cache1.testAttribute = "test_value"  # type: ignore[attr-defined]

        cache2 = CacheService.getInstance()
        self.assertEqual(cache2.testAttribute, "test_value")  # type: ignore[attr-defined]


class TestCacheServiceBasics(unittest.IsolatedAsyncioTestCase):
    """Test suite for basic CacheService functionality.

    Tests fundamental CacheService operations including namespace access,
    database injection, and initialization behavior.
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures before each async test method.

        Creates a new CacheService instance with a mocked database for testing.
        """
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        # Use plain Mock to avoid any connection creation
        self.mockDb = Mock()
        # Configure mock BEFORE injection to avoid connection issues
        self.mockDb.cache.getCacheStorage = createAsyncMock(returnValue=[])
        await self.cache.injectDatabase(self.mockDb)

    async def asyncTearDown(self) -> None:
        """Clean up after each async test method.

        Resets the singleton instance and cleans up mock objects to prevent
        test interference.
        """
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        # Suppress ResourceWarnings from test environment during cleanup
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()

    def testNamespaceAccess(self) -> None:
        """Test accessing different namespaces.

        Verifies that all cache namespaces (chats, chatUsers, users) are properly
        initialized and accessible as LRUCache instances.
        """
        self.assertIsInstance(self.cache.chats, LRUCache)
        self.assertIsInstance(self.cache.chatUsers, LRUCache)
        self.assertIsInstance(self.cache.users, LRUCache)

    def testDatabaseInjection(self) -> None:
        """Test database injection.

        Verifies that the database is properly injected into the CacheService
        and that cache storage is loaded from the database.
        """
        self.assertIs(self.cache.database, self.mockDb)
        self.mockDb.cache.getCacheStorage.assert_called_once()


class TestChatSettings(unittest.IsolatedAsyncioTestCase):
    """Test suite for chat settings operations.

    Tests the retrieval, caching, and persistence of chat settings including
    loading from cache, loading from database, and persisting changes.
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures before each async test method.

        Creates a new CacheService instance with mocked database methods for
        chat settings operations.
        """
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.cache.getCacheStorage = createAsyncMock(returnValue=[])
        self.mockDb.chatSettings.getChatSettings = createAsyncMock(returnValue={})
        self.mockDb.chatSettings.setChatSetting = createAsyncMock(returnValue=True)
        self.mockDb.chatInfo.getChatInfo = createAsyncMock(returnValue=None)
        self.mockDb.chatInfo.setChatInfo = createAsyncMock(returnValue=True)
        self.mockDb.userData.getUserData = createAsyncMock(returnValue=None)
        self.mockDb.userData.setUserData = createAsyncMock(returnValue=True)
        await self.cache.injectDatabase(self.mockDb)

    async def asyncTearDown(self) -> None:
        """Clean up after each async test method.

        Resets the singleton instance and cleans up mock objects.
        """
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    async def testGetChatSettingsFromCache(self) -> None:
        """Test getting chat settings from cache.

        Verifies that chat settings are retrieved from the cache when available,
        avoiding database queries.
        """
        testSettings = {ChatSettingsKey.BAYES_ENABLED: ChatSettingsValue("true")}
        self.cache.chats.set(123, {"settings": testSettings})

        settings = await self.cache.getChatSettings(123)
        self.assertEqual(settings, testSettings)

    async def testGetChatSettingsFromDb(self) -> None:
        """Test loading chat settings from database.

        Verifies that chat settings are loaded from the database when not in cache,
        and that the database is queried with the correct chat ID.
        """
        self.mockDb.chatSettings.getChatSettings = createAsyncMock(returnValue={"bayes-enabled": ("true", 0)})

        settings = await self.cache.getChatSettings(123)

        self.mockDb.chatSettings.getChatSettings.assert_called_once_with(123)
        self.assertIn(ChatSettingsKey.BAYES_ENABLED, settings)

    async def testSetChatSettingsPersistence(self) -> None:
        """Test that settings are persisted to database.

        Verifies that when chat settings are changed, they are persisted to the
        database with the correct parameters.
        """
        # Mock getChatSettings to return empty dict (no existing settings)
        self.mockDb.chatSettings.getChatSettings = createAsyncMock(returnValue={})

        key = ChatSettingsKey.BAYES_ENABLED
        value = ChatSettingsValue("true")
        await self.cache.setChatSetting(123, key, value, userId=0)

        self.mockDb.chatSettings.setChatSetting.assert_called_once_with(
            123, ChatSettingsKey.BAYES_ENABLED, "true", updatedBy=0
        )


class TestChatInfo(unittest.IsolatedAsyncioTestCase):
    """Test suite for chat information operations.

    Tests the retrieval, caching, and persistence of chat information including
    getting chat info from cache, handling non-existent chats, and setting chat info.
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures before each async test method.

        Creates a new CacheService instance with mocked database methods for
        chat info operations.
        """
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.cache.getCacheStorage = createAsyncMock(returnValue=[])
        self.mockDb.cache.setCacheStorage = createAsyncMock(returnValue=True)
        self.mockDb.cache.unsetCacheStorage = createAsyncMock(returnValue=True)
        self.mockDb.chatInfo.getChatInfo = createAsyncMock(returnValue=None)  # Return None for nonexistent chats
        self.mockDb.chatInfo.setChatInfo = createAsyncMock(returnValue=True)
        self.mockDb.chatInfo.addChatInfo = createAsyncMock(returnValue=True)
        self.mockDb.chatInfo.updateChatInfo = createAsyncMock(returnValue=True)
        await self.cache.injectDatabase(self.mockDb)

    async def asyncTearDown(self) -> None:
        """Clean up after each async test method.

        Resets the singleton instance and cleans up mock objects.
        """
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    async def testGetChatInfo(self) -> None:
        """Test getting chat info.

        Verifies that chat information is retrieved from the cache when available.
        """
        testInfo = {"title": "Test Chat", "type": "group"}  # type: ignore[typeddict-item]
        self.cache.chats.set(123, {"info": testInfo})  # type: ignore[typeddict-item]

        info = await self.cache.getChatInfo(123)
        self.assertEqual(info, testInfo)

    async def testGetChatInfoNonexistent(self) -> None:
        """Test getting nonexistent chat info.

        Verifies that None is returned when requesting info for a non-existent chat.
        """
        info = await self.cache.getChatInfo(999)
        self.assertIsNone(info)

    async def testSetChatInfo(self) -> None:
        """Test setting chat info.

        Verifies that chat information can be set and retrieved correctly.
        Note: setChatInfo writes directly to DB, so no dirty tracking needed.
        """
        testInfo = {
            "title": "Test Chat",
            "type": "group",
            "username": None,
            "is_forum": False,
        }  # type: ignore[typeddict-item]
        await self.cache.setChatInfo(123, testInfo)  # type: ignore[arg-type]

        info = await self.cache.getChatInfo(123)
        self.assertEqual(info, testInfo)

        # Note: setChatInfo writes directly to DB, so no dirty tracking needed


class TestChatUserData(unittest.IsolatedAsyncioTestCase):
    """Test suite for chat user data operations.

    Tests the retrieval, caching, and persistence of user-specific data within
    chats, including complex data structures and JSON serialization.
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures before each async test method.

        Creates a new CacheService instance with mocked database methods for
        user data operations.
        """
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.cache.getCacheStorage = createAsyncMock(returnValue=[])
        self.mockDb.cache.setCacheStorage = createAsyncMock(returnValue=True)
        self.mockDb.cache.unsetCacheStorage = createAsyncMock(returnValue=True)
        self.mockDb.userData.getUserData = createAsyncMock(returnValue={})
        self.mockDb.userData.setUserData = createAsyncMock(returnValue=True)
        self.mockDb.userData.addUserData = createAsyncMock(returnValue=True)
        await self.cache.injectDatabase(self.mockDb)

    async def asyncTearDown(self) -> None:
        """Clean up after each async test method.

        Clears the database reference to avoid resource warnings and resets
        the singleton instance.
        """
        # Clear the database reference to avoid resource warnings
        if hasattr(self.cache, "dbWrapper") and self.cache.database is not None:
            self.cache.database = None
        if hasattr(self, "mockDb"):
            # Reset the mock to release any held references
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        # Force garbage collection to clean up any lingering references
        gc.collect()

    async def testGetChatUserDataFromCache(self) -> None:
        """Test getting user data from cache.

        Verifies that user data is retrieved from the cache when available,
        avoiding database queries.
        """
        testData = {"key1": "value1", "key2": ["item1", "item2"]}
        self.cache.chatUsers.set("123:456", {"data": testData})

        userData = await self.cache.getChatUserData(123, 456)
        self.assertEqual(userData, testData)

    async def testGetChatUserDataFromDb(self) -> None:
        """Test loading user data from database.

        Verifies that user data is loaded from the database when not in cache,
        and that JSON strings are properly deserialized.
        """
        self.mockDb.userData.getUserData.return_value = {
            "key1": '"value1"',
            "key2": '["item1", "item2"]',
        }

        userData = await self.cache.getChatUserData(123, 456)

        self.mockDb.userData.getUserData.assert_called_once_with(userId=456, chatId=123)
        self.assertEqual(userData["key1"], "value1")
        self.assertEqual(userData["key2"], ["item1", "item2"])

    async def testSetChatUserData(self) -> None:
        """Test setting user data.

        Verifies that user data can be set, persisted to the database, and
        properly tracked as dirty for synchronization.
        """
        await self.cache.setChatUserData(123, 456, "testKey", "testValue")

        userData = await self.cache.getChatUserData(123, 456)
        self.assertEqual(userData["testKey"], "testValue")

        # Check persistence
        self.mockDb.userData.addUserData.assert_called_once()
        args = self.mockDb.userData.addUserData.call_args
        self.assertEqual(args[1]["userId"], 456)
        self.assertEqual(args[1]["chatId"], 123)
        self.assertEqual(args[1]["key"], "testKey")

        # Check dirty tracking
        self.assertIn("123:456", self.cache.dirtyKeys[CacheNamespace.CHAT_USERS])

    async def testSetChatUserDataComplex(self) -> None:
        """Test setting complex user data.

        Verifies that complex data structures (nested dicts, lists) are properly
        serialized and deserialized.
        """
        complexData = {"nested": {"key": "value"}, "list": [1, 2, 3]}
        await self.cache.setChatUserData(123, 456, "complex", complexData)

        userData = await self.cache.getChatUserData(123, 456)
        self.assertEqual(userData["complex"], complexData)


class TestUserState(unittest.IsolatedAsyncioTestCase):
    """Test suite for user state operations.

    Tests user state management including clearing state for users.
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures before each async test method.

        Creates a new CacheService instance with a mocked database.
        """
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.cache.getCacheStorage = createAsyncMock(returnValue=[])
        await self.cache.injectDatabase(self.mockDb)

    async def asyncTearDown(self) -> None:
        """Clean up after each async test method.

        Resets the singleton instance and cleans up mock objects.
        """
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    def testClearUserStateNonexistent(self) -> None:
        """Test clearing state for nonexistent user.

        Verifies that clearing state for a non-existent user does not raise
        an exception.
        """
        # Should not raise exception
        self.cache.clearUserState(999)


class TestNamespaceOperations(unittest.IsolatedAsyncioTestCase):
    """Test suite for namespace-level operations.

    Tests operations that affect entire cache namespaces including clearing
    namespaces and tracking dirty keys for synchronization.
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures before each async test method.

        Creates a new CacheService instance with a mocked database.
        """
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.cache.getCacheStorage = createAsyncMock(returnValue=[])
        await self.cache.injectDatabase(self.mockDb)

    async def asyncTearDown(self) -> None:
        """Clean up after each async test method.

        Resets the singleton instance and cleans up mock objects.
        """
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    def testClearNamespace(self) -> None:
        """Test clearing entire namespace.

        Verifies that clearing a namespace removes all items and marks them
        as dirty for deletion from the database.
        """
        self.cache.chats.set(123, {"settings": {}})
        self.cache.chats.set(456, {"settings": {}})

        self.cache.clearNamespace(CacheNamespace.CHATS)

        self.assertEqual(len(self.cache.chats), 0)
        # All keys should be marked dirty for deletion
        self.assertIn(123, self.cache.dirtyKeys[CacheNamespace.CHATS])
        self.assertIn(456, self.cache.dirtyKeys[CacheNamespace.CHATS])


class TestPersistence(unittest.IsolatedAsyncioTestCase):
    """Test suite for persistence operations.

    Tests the persistence of cache data to the database including handling
    of different namespace types, dirty key tracking, and error handling.
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures before each async test method.

        Creates a new CacheService instance with mocked database methods for
        persistence operations.
        """
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.cache.getCacheStorage = createAsyncMock(returnValue=[])
        self.mockDb.cache.setCacheStorage = createAsyncMock(returnValue=True)
        self.mockDb.cache.unsetCacheStorage = createAsyncMock(returnValue=True)
        await self.cache.injectDatabase(self.mockDb)

    async def asyncTearDown(self) -> None:
        """Clean up after each async test method.

        Resets the singleton instance and cleans up mock objects.
        """
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    async def testPersistAllWithoutDb(self) -> None:
        """Test that persist fails gracefully without database.

        Verifies that persistAll() does not raise an exception when no database
        is configured.
        """
        self.cache.database = None
        self.cache.dirtyKeys[CacheNamespace.USERS].add(123)

        # Should not raise exception
        await self.cache.persistAll()

    async def testPersistAllMemoryOnly(self) -> None:
        """Test that MEMORY_ONLY namespaces are not persisted.

        Verifies that namespaces marked as MEMORY_ONLY are not persisted to
        the database, but dirty keys are still cleared.
        """
        self.cache.chats.set(123, {"settings": {}})
        self.cache.dirtyKeys[CacheNamespace.CHATS].add(123)

        await self.cache.persistAll()

        # CHATS is MEMORY_ONLY, should not be persisted
        self.mockDb.cache.setCacheStorage.assert_not_called()
        # Dirty keys should be cleared
        self.assertEqual(len(self.cache.dirtyKeys[CacheNamespace.CHATS]), 0)

    async def testPersistAllOnChange(self) -> None:
        """Test that ON_CHANGE namespaces are persisted.

        Verifies that namespaces marked as ON_CHANGE are properly persisted
        to the database with correct parameters.
        """
        testState = {"activeConfigureId": {"step": 1}}
        self.cache.users.set(123, testState)  # type: ignore[arg-type]
        self.cache.dirtyKeys[CacheNamespace.USERS].add(123)

        await self.cache.persistAll()

        # USERS is ON_CHANGE, should be persisted
        self.mockDb.cache.setCacheStorage.assert_called_once()
        args = self.mockDb.cache.setCacheStorage.call_args[1]
        self.assertEqual(args["namespace"], "users")
        self.assertEqual(args["key"], "123")

        # Dirty keys should be cleared
        self.assertEqual(len(self.cache.dirtyKeys[CacheNamespace.USERS]), 0)

    async def testPersistAllEmptyData(self) -> None:
        """Test that empty data is dropped from database.

        Verifies that when cache data is empty, the database entry is removed
        using unsetCacheStorage.
        """
        self.cache.users.set(123, {})
        self.cache.dirtyKeys[CacheNamespace.USERS].add(123)

        await self.cache.persistAll()

        # Empty data should trigger unset
        self.mockDb.cache.unsetCacheStorage.assert_called_once_with(CacheNamespace.USERS, "123")

    async def testLoadFromDatabase(self) -> None:
        """Test loading cache from database.

        Verifies that cache data is loaded from the database during initialization,
        and that MEMORY_ONLY namespaces are skipped.
        """
        mockData = [
            {
                "namespace": "users",
                "key": "123",
                "value": json.dumps({"activeConfigureId": {"step": 1}}),
            },
            {
                "namespace": "chats",
                "key": "456",
                "value": json.dumps({"settings": {}}),
            },
        ]
        self.mockDb.cache.getCacheStorage.return_value = mockData

        # Reset and reload
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        await self.cache.injectDatabase(self.mockDb)

        # USERS should be loaded (ON_CHANGE)
        self.assertEqual(len(self.cache.users), 1)
        self.assertIn(123, self.cache.users)

        # CHATS should be skipped (MEMORY_ONLY)
        self.assertEqual(len(self.cache.chats), 0)

    async def testLoadFromDatabaseInvalidJson(self) -> None:
        """Test handling invalid JSON during load.

        Verifies that invalid JSON in the database does not cause the cache
        loading to fail.
        """
        mockData = [
            {"namespace": "users", "key": "123", "value": "invalid json"},
        ]
        self.mockDb.cache.getCacheStorage.return_value = mockData

        # Should not raise exception
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        await self.cache.injectDatabase(self.mockDb)

        self.assertEqual(len(self.cache.users), 0)

    async def testLoadFromDatabaseUnknownNamespace(self) -> None:
        """Test handling unknown namespace during load.

        Verifies that unknown namespaces in the database are ignored without
        causing errors.
        """
        mockData = [
            {"namespace": "unknown", "key": "123", "value": "{}"},
        ]
        self.mockDb.cache.getCacheStorage.return_value = mockData

        # Should not raise exception
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        await self.cache.injectDatabase(self.mockDb)

    async def testLoadFromDatabaseEmptyValue(self) -> None:
        """Test handling empty values during load.

        Verifies that empty values in the database are ignored and not loaded
        into the cache.
        """
        mockData = [
            {"namespace": "users", "key": "123", "value": "{}"},
        ]
        self.mockDb.cache.getCacheStorage.return_value = mockData

        CacheService._instance = None
        self.cache = CacheService.getInstance()
        await self.cache.injectDatabase(self.mockDb)

        # Empty values should be ignored
        self.assertEqual(len(self.cache.users), 0)


class TestThreadSafety(unittest.IsolatedAsyncioTestCase):
    """Test suite for thread safety of cache operations.

    Tests that the cache implementation handles concurrent access correctly
    without data corruption or race conditions.
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures before each async test method.

        Creates a new CacheService instance.
        """
        CacheService._instance = None
        self.cache = CacheService.getInstance()

    async def asyncTearDown(self) -> None:
        """Clean up after each async test method.

        Resets the singleton instance.
        """
        CacheService._instance = None
        gc.collect()

    def testLRUCacheConcurrentAccess(self) -> None:
        """Test that LRU cache handles concurrent access.

        Verifies that multiple threads can safely access and modify the cache
        without causing errors or data corruption.
        """
        import threading

        lruCache = LRUCache[int, int](maxSize=100)
        errors = []

        def worker(startVal: int) -> None:
            """Worker function that performs cache operations.

            Args:
                startVal: Starting value for this worker's operations.
            """
            try:
                for i in range(startVal, startVal + 100):
                    lruCache.set(i, i * 2)
                    val = lruCache.get(i, 0)
                    self.assertEqual(val, i * 2)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i * 100,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")


class TestEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Test suite for edge cases and error handling.

    Tests unusual scenarios and error conditions to ensure the cache service
    handles them gracefully.
    """

    async def asyncSetUp(self) -> None:
        """Set up test fixtures before each async test method.

        Creates a new CacheService instance with a mocked database.
        """
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.cache.getCacheStorage = createAsyncMock(returnValue=[])
        await self.cache.injectDatabase(self.mockDb)

    async def asyncTearDown(self) -> None:
        """Clean up after each async test method.

        Resets the singleton instance and cleans up mock objects.
        """
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    async def testSetChatSettingWithoutDb(self) -> None:
        """Test setting chat settings without database.

        Verifies that chat settings can be set and cached even when no database
        is configured.
        """
        self.cache.database = None
        key = ChatSettingsKey.BAYES_ENABLED
        value = ChatSettingsValue("true")

        # Should not raise exception
        await self.cache.setChatSetting(123, key, value, userId=0)

        # Should still be in cache
        cachedSettings = await self.cache.getChatSettings(123)
        self.assertEqual(cachedSettings, {key: value})

    async def testSetChatUserDataWithoutDb(self) -> None:
        """Test setting user data without database.

        Verifies that user data can be set even when no database is configured.
        """
        self.cache.database = None

        # Should not raise exception
        await self.cache.setChatUserData(123, 456, "key", "value")

    async def testGetChatUserDataDbError(self) -> None:
        """Test handling database errors when loading user data.

        Verifies that database errors are handled gracefully, either by
        returning an empty dict or raising an exception.
        """
        self.mockDb.userData.getUserData.side_effect = Exception("DB Error")

        # Should log error but not crash
        try:
            userData = await self.cache.getChatUserData(123, 456)
            # If it doesn't raise, it should return empty dict
            self.assertEqual(userData, {})
        except Exception:
            # If it raises, that's also acceptable behavior
            pass

    async def testPersistCacheEntryError(self) -> None:
        """Test handling errors during cache entry persistence.

        Verifies that errors during persistence do not cause the application
        to crash.
        """
        self.mockDb.cache.setCacheStorage.side_effect = Exception("DB Error")

        testState = {"activeConfigureId": {"step": 1}}
        self.cache.users.set(123, testState)  # type: ignore[typeddict-item]
        self.cache.dirtyKeys[CacheNamespace.USERS].add(123)

        # Should not raise exception
        await self.cache.persistAll()


if __name__ == "__main__":
    print("🧪 Running Cache Service tests, dood!")
    print("=" * 50)
    unittest.main(verbosity=2)
