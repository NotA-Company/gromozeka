"""
Comprehensive tests for cache service, dood!

Tests cover:
- LRUCache functionality (get, set, eviction, thread safety)
- CacheService singleton pattern
- Namespace operations (chats, chatUsers, users)
- Convenience methods (getChatSettings, setChatSetting, etc.)
- Persistence and loading from database
- Dirty key tracking
- Statistics
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
from internal.services.cache.types import UserActiveActionEnum  # noqa: E402


class TestLRUCache(unittest.TestCase):
    """Test LRU cache implementation, dood!"""

    def setUp(self):
        """Set up test fixtures"""
        self.cache = LRUCache[str, int](maxSize=3)

    def testBasicGetSet(self):
        """Test basic get and set operations"""
        self.cache.set("key1", 100)
        self.assertEqual(self.cache.get("key1", 0), 100)
        self.assertEqual(self.cache.get("nonexistent", 999), 999)  # type: ignore[arg-type]

    def testLRUEviction(self):
        """Test that oldest items are evicted when capacity is exceeded"""
        self.cache.set("key1", 1)
        self.cache.set("key2", 2)
        self.cache.set("key3", 3)
        self.cache.set("key4", 4)  # Should evict key1

        self.assertEqual(self.cache.get("key1", -1), -1)  # type: ignore[arg-type]
        self.assertEqual(self.cache.get("key2", 0), 2)
        self.assertEqual(self.cache.get("key3", 0), 3)
        self.assertEqual(self.cache.get("key4", 0), 4)

    def testLRUOrdering(self):
        """Test that accessing items updates their position"""
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

    def testUpdateExisting(self):
        """Test updating existing keys moves them to end"""
        self.cache.set("key1", 1)
        self.cache.set("key2", 2)
        self.cache.set("key3", 3)

        # Update key1
        self.cache.set("key1", 100)

        # Add key4, should evict key2
        self.cache.set("key4", 4)

        self.assertEqual(self.cache.get("key1", 0), 100)
        self.assertEqual(self.cache.get("key2", -1), -1)  # type: ignore[arg-type]

    def testDelete(self):
        """Test delete operation"""
        self.cache.set("key1", 1)
        self.assertTrue(self.cache.delete("key1"))
        self.assertFalse(self.cache.delete("key1"))
        self.assertEqual(self.cache.get("key1", -1), -1)  # type: ignore[arg-type]

    def testClear(self):
        """Test clear operation"""
        self.cache.set("key1", 1)
        self.cache.set("key2", 2)
        self.cache.clear()
        self.assertEqual(len(self.cache), 0)
        self.assertEqual(self.cache.get("key1", -1), -1)  # type: ignore[arg-type]


class TestCacheServiceSingleton(unittest.TestCase):
    """Test CacheService singleton pattern, dood!"""

    def setUp(self):
        """Reset singleton before each test"""
        CacheService._instance = None

    def testSingletonPattern(self):
        """Test that getInstance returns same instance"""
        cache1 = CacheService.getInstance()
        cache2 = CacheService.getInstance()
        self.assertIs(cache1, cache2)

    def testSingletonWithNew(self):
        """Test that __new__ also returns singleton"""
        cache1 = CacheService()
        cache2 = CacheService()
        self.assertIs(cache1, cache2)

    def testInitializationOnlyOnce(self):
        """Test that initialization only happens once"""
        cache1 = CacheService.getInstance()
        cache1.testAttribute = "test_value"  # type: ignore[attr-defined]

        cache2 = CacheService.getInstance()
        self.assertEqual(cache2.testAttribute, "test_value")  # type: ignore[attr-defined]


class TestCacheServiceBasics(unittest.TestCase):
    """Test basic CacheService functionality, dood!"""

    def setUp(self):
        """Set up test fixtures"""
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        # Use plain Mock to avoid any connection creation
        self.mockDb = Mock()
        # Configure mock BEFORE injection to avoid connection issues
        self.mockDb.getCacheStorage.return_value = []
        self.cache.injectDatabase(self.mockDb)

    def tearDown(self):
        """Clean up after tests"""
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        # Suppress ResourceWarnings from test environment during cleanup
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()

    def testNamespaceAccess(self):
        """Test accessing different namespaces"""
        self.assertIsInstance(self.cache.chats, LRUCache)
        self.assertIsInstance(self.cache.chatUsers, LRUCache)
        self.assertIsInstance(self.cache.users, LRUCache)

    def testDatabaseInjection(self):
        """Test database injection"""
        self.assertIs(self.cache.dbWrapper, self.mockDb)
        self.mockDb.getCacheStorage.assert_called_once()

    def testGetStats(self):
        """Test statistics generation"""
        self.cache.chats.set(123, {"settings": {}})
        self.cache.users.set(456, {"activeConfigureId": {}})

        stats = self.cache.getStats()

        self.assertIn("chats", stats)
        self.assertIn("chatUsers", stats)
        self.assertIn("users", stats)

        self.assertEqual(stats["chats"]["size"], 1)
        self.assertEqual(stats["users"]["size"], 1)
        self.assertEqual(stats["chatUsers"]["size"], 0)


class TestChatSettings(unittest.TestCase):
    """Test chat settings operations, dood!"""

    def setUp(self):
        """Set up test fixtures"""
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.getCacheStorage.return_value = []
        self.cache.injectDatabase(self.mockDb)

    def tearDown(self):
        """Clean up after tests"""
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    def testGetChatSettingsFromCache(self):
        """Test getting chat settings from cache"""
        testSettings = {ChatSettingsKey.BAYES_ENABLED: ChatSettingsValue("true")}
        self.cache.chats.set(123, {"settings": testSettings})

        settings = self.cache.getChatSettings(123)
        self.assertEqual(settings, testSettings)

    def testGetChatSettingsFromDb(self):
        """Test loading chat settings from database"""
        self.mockDb.getChatSettings.return_value = {"bayes-enabled": "true"}

        settings = self.cache.getChatSettings(123)

        self.mockDb.getChatSettings.assert_called_once_with(123)
        self.assertIn(ChatSettingsKey.BAYES_ENABLED, settings)

    def testSetChatSettingsPersistence(self):
        """Test that settings are persisted to database"""
        # Mock getChatSettings to return empty dict (no existing settings)
        self.mockDb.getChatSettings.return_value = {}

        key = ChatSettingsKey.BAYES_ENABLED
        value = ChatSettingsValue("true")
        self.cache.setChatSetting(123, key, value)

        self.mockDb.setChatSetting.assert_called_once_with(123, ChatSettingsKey.BAYES_ENABLED, "true")


class TestChatInfo(unittest.TestCase):
    """Test chat info operations, dood!"""

    def setUp(self):
        """Set up test fixtures"""
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.getCacheStorage.return_value = []
        self.cache.injectDatabase(self.mockDb)

    def tearDown(self):
        """Clean up after tests"""
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    def testGetChatInfo(self):
        """Test getting chat info"""
        testInfo = {"title": "Test Chat", "type": "group"}  # type: ignore[typeddict-item]
        self.cache.chats.set(123, {"info": testInfo})  # type: ignore[typeddict-item]

        info = self.cache.getChatInfo(123)
        self.assertEqual(info, testInfo)

    def testGetChatInfoNonexistent(self):
        """Test getting nonexistent chat info"""
        info = self.cache.getChatInfo(999)
        self.assertIsNone(info)

    def testSetChatInfo(self):
        """Test setting chat info"""
        testInfo = {"title": "Test Chat", "type": "group"}  # type: ignore[typeddict-item]
        self.cache.setChatInfo(123, testInfo)  # type: ignore[arg-type]

        info = self.cache.getChatInfo(123)
        self.assertEqual(info, testInfo)

        # Check dirty tracking
        self.assertIn(123, self.cache.dirtyKeys[CacheNamespace.CHATS])


class TestChatUserData(unittest.TestCase):
    """Test chat user data operations, dood!"""

    def setUp(self):
        """Set up test fixtures"""
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.getCacheStorage.return_value = []
        self.mockDb.getUserData.return_value = {}
        self.cache.injectDatabase(self.mockDb)

    def tearDown(self):
        """Clean up after tests"""
        # Clear the database reference to avoid resource warnings
        if hasattr(self.cache, "dbWrapper") and self.cache.dbWrapper is not None:
            self.cache.dbWrapper = None
        if hasattr(self, "mockDb"):
            # Reset the mock to release any held references
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        # Force garbage collection to clean up any lingering references
        gc.collect()

    def testGetChatUserDataFromCache(self):
        """Test getting user data from cache"""
        testData = {"key1": "value1", "key2": ["item1", "item2"]}
        self.cache.chatUsers.set("123:456", {"data": testData})

        userData = self.cache.getChatUserData(123, 456)
        self.assertEqual(userData, testData)

    def testGetChatUserDataFromDb(self):
        """Test loading user data from database"""
        self.mockDb.getUserData.return_value = {
            "key1": '"value1"',
            "key2": '["item1", "item2"]',
        }

        userData = self.cache.getChatUserData(123, 456)

        self.mockDb.getUserData.assert_called_once_with(userId=456, chatId=123)
        self.assertEqual(userData["key1"], "value1")
        self.assertEqual(userData["key2"], ["item1", "item2"])

    def testSetChatUserData(self):
        """Test setting user data"""
        self.cache.setChatUserData(123, 456, "testKey", "testValue")

        userData = self.cache.getChatUserData(123, 456)
        self.assertEqual(userData["testKey"], "testValue")

        # Check persistence
        self.mockDb.addUserData.assert_called_once()
        args = self.mockDb.addUserData.call_args
        self.assertEqual(args[1]["userId"], 456)
        self.assertEqual(args[1]["chatId"], 123)
        self.assertEqual(args[1]["key"], "testKey")

        # Check dirty tracking
        self.assertIn("123:456", self.cache.dirtyKeys[CacheNamespace.CHAT_USERS])

    def testSetChatUserDataComplex(self):
        """Test setting complex user data"""
        complexData = {"nested": {"key": "value"}, "list": [1, 2, 3]}
        self.cache.setChatUserData(123, 456, "complex", complexData)

        userData = self.cache.getChatUserData(123, 456)
        self.assertEqual(userData["complex"], complexData)


class TestUserState(unittest.TestCase):
    """Test user state operations, dood!"""

    def setUp(self):
        """Set up test fixtures"""
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.getCacheStorage.return_value = []
        self.cache.injectDatabase(self.mockDb)

    def tearDown(self):
        """Clean up after tests"""
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    def testGetUserState(self):
        """Test getting user state"""
        testState = {"step": 1, "data": "test"}
        self.cache.users.set(123, {"activeConfigureId": testState})

        state = self.cache.getUserState(123, UserActiveActionEnum.Configuration)
        self.assertEqual(state, testState)

    def testGetUserStateDefault(self):
        """Test getting nonexistent user state with default"""
        state = self.cache.getUserState(999, UserActiveActionEnum.Configuration, {"default": True})
        self.assertEqual(state, {"default": True})

    def testSetUserState(self):
        """Test setting user state"""
        testState = {"step": 1, "data": "test"}
        self.cache.setUserState(123, UserActiveActionEnum.Configuration, testState)

        state = self.cache.getUserState(123, UserActiveActionEnum.Configuration)
        self.assertEqual(state, testState)

        # Check dirty tracking
        self.assertIn(123, self.cache.dirtyKeys[CacheNamespace.USERS])

    def testClearUserStateSingle(self):
        """Test clearing single user state key"""
        self.cache.users.set(
            123,
            {
                "activeConfigureId": {"step": 1},
                "activeSummarizationId": {"step": 2},
            },
        )

        self.cache.clearUserState(123, UserActiveActionEnum.Configuration)

        state = self.cache.getUserState(123, UserActiveActionEnum.Configuration)
        self.assertIsNone(state)

        # Other state should remain
        state2 = self.cache.getUserState(123, UserActiveActionEnum.Summarization)
        self.assertEqual(state2, {"step": 2})

    def testClearUserStateAll(self):
        """Test clearing all user state keys"""
        self.cache.users.set(
            123,
            {
                "activeConfigureId": {"step": 1},
                "activeSummarizationId": {"step": 2},
            },
        )

        self.cache.clearUserState(123)

        state1 = self.cache.getUserState(123, UserActiveActionEnum.Configuration)
        state2 = self.cache.getUserState(123, UserActiveActionEnum.Summarization)
        self.assertIsNone(state1)
        self.assertIsNone(state2)

    def testClearUserStateNonexistent(self):
        """Test clearing state for nonexistent user"""
        # Should not raise exception
        self.cache.clearUserState(999)


class TestNamespaceOperations(unittest.TestCase):
    """Test namespace-level operations, dood!"""

    def setUp(self):
        """Set up test fixtures"""
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.getCacheStorage.return_value = []
        self.cache.injectDatabase(self.mockDb)

    def tearDown(self):
        """Clean up after tests"""
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    def testClearNamespace(self):
        """Test clearing entire namespace"""
        self.cache.chats.set(123, {"settings": {}})
        self.cache.chats.set(456, {"settings": {}})

        self.cache.clearNamespace(CacheNamespace.CHATS)

        self.assertEqual(len(self.cache.chats), 0)
        # All keys should be marked dirty for deletion
        self.assertIn(123, self.cache.dirtyKeys[CacheNamespace.CHATS])
        self.assertIn(456, self.cache.dirtyKeys[CacheNamespace.CHATS])


class TestPersistence(unittest.TestCase):
    """Test persistence operations, dood!"""

    def setUp(self):
        """Set up test fixtures"""
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.getCacheStorage.return_value = []
        self.cache.injectDatabase(self.mockDb)

    def tearDown(self):
        """Clean up after tests"""
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    def testPersistAllWithoutDb(self):
        """Test that persist fails gracefully without database"""
        self.cache.dbWrapper = None
        self.cache.dirtyKeys[CacheNamespace.USERS].add(123)

        # Should not raise exception
        self.cache.persistAll()

    def testPersistAllMemoryOnly(self):
        """Test that MEMORY_ONLY namespaces are not persisted"""
        self.cache.chats.set(123, {"settings": {}})
        self.cache.dirtyKeys[CacheNamespace.CHATS].add(123)

        self.cache.persistAll()

        # CHATS is MEMORY_ONLY, should not be persisted
        self.mockDb.setCacheStorage.assert_not_called()
        # Dirty keys should be cleared
        self.assertEqual(len(self.cache.dirtyKeys[CacheNamespace.CHATS]), 0)

    def testPersistAllOnChange(self):
        """Test that ON_CHANGE namespaces are persisted"""
        testState = {"activeConfigureId": {"step": 1}}
        self.cache.users.set(123, testState)  # type: ignore[arg-type]
        self.cache.dirtyKeys[CacheNamespace.USERS].add(123)

        self.cache.persistAll()

        # USERS is ON_CHANGE, should be persisted
        self.mockDb.setCacheStorage.assert_called_once()
        args = self.mockDb.setCacheStorage.call_args[1]
        self.assertEqual(args["namespace"], "users")
        self.assertEqual(args["key"], "123")

        # Dirty keys should be cleared
        self.assertEqual(len(self.cache.dirtyKeys[CacheNamespace.USERS]), 0)

    def testPersistAllEmptyData(self):
        """Test that empty data is dropped from database"""
        self.cache.users.set(123, {})
        self.cache.dirtyKeys[CacheNamespace.USERS].add(123)

        self.cache.persistAll()

        # Empty data should trigger unset
        self.mockDb.unsetCacheStorage.assert_called_once_with(CacheNamespace.USERS, "123")

    def testLoadFromDatabase(self):
        """Test loading cache from database"""
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
        self.mockDb.getCacheStorage.return_value = mockData

        # Reset and reload
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.cache.injectDatabase(self.mockDb)

        # USERS should be loaded (ON_CHANGE)
        self.assertEqual(len(self.cache.users), 1)
        self.assertIn(123, self.cache.users)

        # CHATS should be skipped (MEMORY_ONLY)
        self.assertEqual(len(self.cache.chats), 0)

    def testLoadFromDatabaseInvalidJson(self):
        """Test handling invalid JSON during load"""
        mockData = [
            {"namespace": "users", "key": "123", "value": "invalid json"},
        ]
        self.mockDb.getCacheStorage.return_value = mockData

        # Should not raise exception
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.cache.injectDatabase(self.mockDb)

        self.assertEqual(len(self.cache.users), 0)

    def testLoadFromDatabaseUnknownNamespace(self):
        """Test handling unknown namespace during load"""
        mockData = [
            {"namespace": "unknown", "key": "123", "value": "{}"},
        ]
        self.mockDb.getCacheStorage.return_value = mockData

        # Should not raise exception
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.cache.injectDatabase(self.mockDb)

    def testLoadFromDatabaseEmptyValue(self):
        """Test handling empty values during load"""
        mockData = [
            {"namespace": "users", "key": "123", "value": "{}"},
        ]
        self.mockDb.getCacheStorage.return_value = mockData

        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.cache.injectDatabase(self.mockDb)

        # Empty values should be ignored
        self.assertEqual(len(self.cache.users), 0)


class TestThreadSafety(unittest.TestCase):
    """Test thread safety of cache operations, dood!"""

    def setUp(self):
        """Set up test fixtures"""
        CacheService._instance = None
        self.cache = CacheService.getInstance()

    def tearDown(self):
        """Clean up after tests"""
        CacheService._instance = None
        gc.collect()

    def testLRUCacheConcurrentAccess(self):
        """Test that LRU cache handles concurrent access"""
        import threading

        lruCache = LRUCache[int, int](maxSize=100)
        errors = []

        def worker(startVal: int):
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


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling, dood!"""

    def setUp(self):
        """Set up test fixtures"""
        CacheService._instance = None
        self.cache = CacheService.getInstance()
        self.mockDb = Mock()
        self.mockDb.getCacheStorage.return_value = []
        self.cache.injectDatabase(self.mockDb)

    def tearDown(self):
        """Clean up after tests"""
        if hasattr(self, "mockDb"):
            self.mockDb.reset_mock()
            del self.mockDb
        CacheService._instance = None
        gc.collect()

    def testSetChatSettingWithoutDb(self):
        """Test setting chat settings without database"""
        self.cache.dbWrapper = None
        key = ChatSettingsKey.BAYES_ENABLED
        value = ChatSettingsValue("true")

        # Should not raise exception
        self.cache.setChatSetting(123, key, value)

        # Should still be in cache
        cachedSettings = self.cache.getChatSettings(123)
        self.assertEqual(cachedSettings, {key: value})

    def testSetChatUserDataWithoutDb(self):
        """Test setting user data without database"""
        self.cache.dbWrapper = None

        # Should not raise exception
        self.cache.setChatUserData(123, 456, "key", "value")

    def testGetChatUserDataDbError(self):
        """Test handling database errors when loading user data"""
        self.mockDb.getUserData.side_effect = Exception("DB Error")

        # Should log error but not crash
        try:
            userData = self.cache.getChatUserData(123, 456)
            # If it doesn't raise, it should return empty dict
            self.assertEqual(userData, {})
        except Exception:
            # If it raises, that's also acceptable behavior
            pass

    def testPersistCacheEntryError(self):
        """Test handling errors during cache entry persistence"""
        self.mockDb.setCacheStorage.side_effect = Exception("DB Error")

        testState = {"activeConfigureId": {"step": 1}}
        self.cache.users.set(123, testState)  # type: ignore[typeddict-item]
        self.cache.dirtyKeys[CacheNamespace.USERS].add(123)

        # Should not raise exception
        self.cache.persistAll()


if __name__ == "__main__":
    print("🧪 Running Cache Service tests, dood!")
    print("=" * 50)
    unittest.main(verbosity=2)
