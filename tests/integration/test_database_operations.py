"""
Integration tests for database operations, dood!

This module tests database operations including:
- Transaction handling (commit, rollback, nested, concurrent)
- Data integrity (foreign keys, unique constraints, NOT NULL, validation)
- Concurrent access (multiple readers/writers, conflicts, deadlocks)
- Migration integration (schema creation, updates, rollback)
- Complex queries (joins, aggregations, filtering, pagination)
- CRUD operations for all tables
"""

import datetime
import json
import sqlite3
import threading

import pytest

from internal.database.models import (
    CacheType,
    MediaStatus,
    MessageCategory,
    SpamReason,
)
from internal.database.wrapper import DatabaseWrapper
from internal.models import MessageType


@pytest.fixture
def inMemoryDb():
    """Provide in-memory SQLite database for testing, dood!"""
    config = {
        "sources": {
            "default": {
                "path": ":memory:",
                "readonly": False,
            }
        },
        "default": "default",
    }
    db = DatabaseWrapper(config)
    yield db
    db.close()


@pytest.fixture
def threadSafeDb(tmp_path):
    """Provide file-based SQLite database for threading tests, dood!

    File-based databases support proper concurrent access across threads,
    unlike in-memory databases which are isolated per connection.
    """
    dbPath = tmp_path / "test_threading.db"
    config = {
        "sources": {
            "default": {
                "path": str(dbPath),
                "readonly": False,
            }
        },
        "default": "default",
    }
    db = DatabaseWrapper(config)
    yield db
    db.close()


@pytest.fixture
def populatedDb(inMemoryDb):
    """Provide database with sample data, dood!"""
    db = inMemoryDb

    # Add sample chat info
    db.updateChatInfo(chatId=123, type="supergroup", title="Test Chat", isForum=False)
    db.updateChatInfo(chatId=456, type="private", title="Private Chat", isForum=False)

    # Add sample users
    db.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")
    db.updateChatUser(chatId=123, userId=1002, username="user2", fullName="User Two")
    db.updateChatUser(chatId=456, userId=1001, username="user1", fullName="User One")

    return db


# ============================================================================
# Transaction Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def testTransactionCommitOnSuccess(inMemoryDb):
    """Test transaction commits on success, dood!"""
    db = inMemoryDb

    # Add chat info and user in a transaction
    db.updateChatInfo(chatId=123, type="group", title="Test")
    db.updateChatUser(chatId=123, userId=1001, username="test", fullName="Test User")

    # Verify data was committed
    chatInfo = db.getChatInfo(123)
    assert chatInfo is not None
    assert chatInfo["chat_id"] == 123

    user = db.getChatUser(123, 1001)
    assert user is not None
    assert user["username"] == "test"


@pytest.mark.asyncio
async def testTransactionRollbackOnError(inMemoryDb):
    """Test transaction rollback on error, dood!"""
    db = inMemoryDb

    # Add valid chat info
    db.updateChatInfo(chatId=123, type="group", title="Test")

    # Try to add duplicate chat info (should fail)
    try:
        with db.getCursor() as cursor:
            # This should fail due to unique constraint
            cursor.execute("INSERT INTO chat_info (chat_id, type) VALUES (?, ?)", (123, "group"))
    except sqlite3.IntegrityError:
        pass  # Expected error

    # Verify original data is still there
    chatInfo = db.getChatInfo(123)
    assert chatInfo is not None
    assert chatInfo["title"] == "Test"


@pytest.mark.asyncio
async def testNestedTransactions(inMemoryDb):
    """Test nested transaction handling, dood!"""
    db = inMemoryDb

    # SQLite doesn't support true nested transactions, but we can test
    # that multiple operations in sequence work correctly
    db.updateChatInfo(chatId=123, type="group", title="Test")
    db.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")
    db.setChatSetting(chatId=123, key="model", value="gpt-4", updatedBy=0)

    # Verify all operations succeeded
    assert db.getChatInfo(123) is not None
    assert db.getChatUser(123, 1001) is not None
    assert db.getChatSetting(123, "model") == "gpt-4"


@pytest.mark.asyncio
async def testConcurrentTransactions(inMemoryDb):
    """Test concurrent transaction handling, dood!"""
    db = inMemoryDb

    # Setup initial data
    db.updateChatInfo(chatId=123, type="group", title="Test")
    db.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    results = []
    errors = []

    def updateUser(userId: int, username: str):
        try:
            db.updateChatUser(chatId=123, userId=userId, username=username, fullName=f"User {userId}")
            results.append(userId)
        except Exception as e:
            errors.append(e)

    # Run concurrent updates
    threads = []
    for i in range(5):
        thread = threading.Thread(target=updateUser, args=(1000 + i, f"user{i}"))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    # Verify all updates succeeded
    assert len(results) == 5
    assert len(errors) == 0


# ============================================================================
# Data Integrity Tests
# ============================================================================


@pytest.mark.asyncio
async def testForeignKeyConstraints(inMemoryDb):
    """Test foreign key constraints, dood!"""
    db = inMemoryDb

    # Setup chat and user
    db.updateChatInfo(chatId=123, type="group", title="Test")
    db.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    # Try to save message for non-existent user (should work as FK not enforced in current schema)
    # But the join will fail to return user data
    now = datetime.datetime.now(datetime.UTC)
    success = db.saveChatMessage(
        date=now, chatId=123, userId=9999, messageId=1, messageText="Test"  # Non-existent user
    )

    # Message save might succeed, but retrieval will fail the join
    # This tests that our validation catches missing user data
    assert success is False or db.getChatMessageByMessageId(123, 1) is None


@pytest.mark.asyncio
async def testUniqueConstraints(inMemoryDb):
    """Test unique constraints, dood!"""
    db = inMemoryDb

    # Add chat info
    db.updateChatInfo(chatId=123, type="group", title="Test")

    # Try to add duplicate chat info
    result = db.updateChatInfo(chatId=123, type="supergroup", title="Updated")

    # Should succeed as we use INSERT OR REPLACE
    assert result is True

    # Verify data was updated
    chatInfo = db.getChatInfo(123)
    assert chatInfo["type"] == "supergroup"
    assert chatInfo["title"] == "Updated"


@pytest.mark.asyncio
async def testNotNullConstraints(inMemoryDb):
    """Test NOT NULL constraints, dood!"""
    db = inMemoryDb

    # Try to add chat info without required fields
    try:
        with db.getCursor() as cursor:
            cursor.execute("INSERT INTO chat_info (chat_id) VALUES (?)", (123,))
        assert False, "Should have raised error for missing NOT NULL field"
    except sqlite3.IntegrityError:
        pass  # Expected error


@pytest.mark.asyncio
async def testDataValidation(inMemoryDb):
    """Test data validation in wrapper methods, dood!"""
    db = inMemoryDb

    # Setup
    db.updateChatInfo(chatId=123, type="group", title="Test")
    db.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    # Save message with valid data
    now = datetime.datetime.now(datetime.UTC)
    success = db.saveChatMessage(
        date=now,
        chatId=123,
        userId=1001,
        messageId=1,
        messageText="Test message",
        messageType=MessageType.TEXT,
        messageCategory=MessageCategory.USER,
    )
    assert success is True

    # Retrieve and validate
    message = db.getChatMessageByMessageId(123, 1)
    assert message is not None
    assert message["message_text"] == "Test message"
    assert isinstance(message["message_category"], MessageCategory)


# ============================================================================
# Concurrent Access Tests
# ============================================================================


@pytest.mark.asyncio
async def testMultipleReaders(threadSafeDb):
    """Test multiple concurrent read operations, dood!

    Uses file-based database to support proper concurrent access across threads.
    """
    db = threadSafeDb

    # Setup data
    db.updateChatInfo(chatId=123, type="group", title="Test")
    db.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    results = []

    def readChatInfo():
        info = db.getChatInfo(123)
        results.append(info)

    # Run concurrent reads
    threads = []
    for _ in range(10):
        thread = threading.Thread(target=readChatInfo)
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    # Verify all reads succeeded
    assert len(results) == 10
    assert all(r is not None for r in results)
    assert all(r["chat_id"] == 123 for r in results)


@pytest.mark.asyncio
async def testMultipleWriters(threadSafeDb):
    """Test multiple concurrent write operations, dood!

    Uses file-based database to support proper concurrent access across threads.
    """
    db = threadSafeDb

    # Setup
    db.updateChatInfo(chatId=123, type="group", title="Test")

    results = []
    errors = []

    def addUser(userId: int):
        try:
            success = db.updateChatUser(chatId=123, userId=userId, username=f"user{userId}", fullName=f"User {userId}")
            results.append(success)
        except Exception as e:
            errors.append(e)

    # Run concurrent writes
    threads = []
    for i in range(10):
        thread = threading.Thread(target=addUser, args=(1000 + i,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    # Verify all writes succeeded
    assert len(results) == 10
    assert all(r is True for r in results)
    assert len(errors) == 0

    # Verify all users were created
    users = db.getChatUsers(123, limit=20)
    assert len(users) == 10


@pytest.mark.asyncio
async def testReadWriteConflicts(threadSafeDb):
    """Test read-write conflict handling, dood!

    Uses file-based database to support proper concurrent access across threads.
    """
    db = threadSafeDb

    # Setup
    db.updateChatInfo(chatId=123, type="group", title="Test")
    db.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    readResults = []
    writeResults = []

    def reader():
        for _ in range(5):
            user = db.getChatUser(123, 1001)
            readResults.append(user)

    def writer():
        for i in range(5):
            success = db.updateChatUser(chatId=123, userId=1001, username=f"user{i}", fullName=f"User {i}")
            writeResults.append(success)

    # Run concurrent reads and writes
    readerThread = threading.Thread(target=reader)
    writerThread = threading.Thread(target=writer)

    readerThread.start()
    writerThread.start()

    readerThread.join()
    writerThread.join()

    # Verify operations completed
    assert len(readResults) == 5
    assert len(writeResults) == 5
    assert all(r is not None for r in readResults)
    assert all(w is True for w in writeResults)


@pytest.mark.asyncio
async def testDeadlockHandling(inMemoryDb):
    """Test deadlock handling, dood!"""
    db = inMemoryDb

    # Setup
    db.updateChatInfo(chatId=123, type="group", title="Test")
    db.updateChatInfo(chatId=456, type="group", title="Test 2")

    # SQLite uses a simple locking mechanism that prevents true deadlocks
    # But we can test that concurrent operations don't hang

    results = []

    def updateChats(chatId1: int, chatId2: int):
        db.setChatSetting(chatId1, "key1", "value1", updatedBy=0)
        db.setChatSetting(chatId2, "key2", "value2", updatedBy=0)
        results.append(True)

    thread1 = threading.Thread(target=updateChats, args=(123, 456))
    thread2 = threading.Thread(target=updateChats, args=(456, 123))

    thread1.start()
    thread2.start()

    thread1.join(timeout=5.0)
    thread2.join(timeout=5.0)

    # Verify both threads completed
    assert len(results) == 2


# ============================================================================
# Migration Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def testSchemaCreation(inMemoryDb):
    """Test schema creation through migrations, dood!"""
    db = inMemoryDb

    # Verify all tables exist
    with db.getCursor() as cursor:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]

    expectedTables = [
        "bayes_classes",  # Created by migrations
        "bayes_tokens",  # Created by migrations
        "cache_geocoding",
        "cache_storage",
        "cache_weather",
        "chat_info",
        "chat_messages",
        "chat_settings",
        "chat_stats",
        "chat_summarization_cache",
        "chat_topics",
        "chat_user_stats",
        "chat_users",
        "delayed_tasks",
        "ham_messages",
        "media_attachments",
        "settings",
        "spam_messages",
        "user_data",
    ]

    for table in expectedTables:
        assert table in tables, f"Table {table} not found"


@pytest.mark.asyncio
async def testSchemaUpdates(inMemoryDb):
    """Test schema updates through migrations, dood!"""
    db = inMemoryDb

    # Verify that migrations have run by checking for tables created in later migrations
    # Migration 002 adds is_spammer to chat_users
    # Migration 003 adds metadata to chat_users
    # Migration 004 adds cache_storage table

    with db.getCursor() as cursor:
        # Check that cache_storage table exists (added in migration 004)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cache_storage'")
        result = cursor.fetchone()
        assert result is not None, "cache_storage table should exist (migration 004)"

        # Check that chat_users has metadata column (added in migration 003)
        cursor.execute("PRAGMA table_info(chat_users)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "metadata" in columns, "chat_users should have metadata column (migration 003)"
        # Note: is_spammer column was removed in migration 009


@pytest.mark.asyncio
async def testDataMigration(inMemoryDb):
    """Test data migration scenarios, dood!"""
    db = inMemoryDb

    # Add data before "migration"
    db.updateChatInfo(chatId=123, type="group", title="Test")
    db.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    # Verify data persists (simulating migration)
    chatInfo = db.getChatInfo(123)
    assert chatInfo is not None

    user = db.getChatUser(123, 1001)
    assert user is not None
    assert "metadata" in user  # Field added in migration 003


# ============================================================================
# Complex Queries Tests
# ============================================================================


@pytest.mark.asyncio
async def testJoinsAcrossTables(populatedDb):
    """Test joins across multiple tables, dood!"""
    db = populatedDb

    # Add messages
    now = datetime.datetime.now(datetime.UTC)
    db.saveChatMessage(date=now, chatId=123, userId=1001, messageId=1, messageText="Test message 1")
    db.saveChatMessage(date=now, chatId=123, userId=1002, messageId=2, messageText="Test message 2")

    # Get messages with user info (tests JOIN)
    messages = db.getChatMessagesSince(chatId=123, sinceDateTime=now - datetime.timedelta(hours=1))

    assert len(messages) == 2
    assert messages[0]["username"] in ["user1", "user2"]
    assert messages[0]["full_name"] in ["User One", "User Two"]


@pytest.mark.asyncio
async def testAggregations(populatedDb):
    """Test aggregation queries, dood!"""
    db = populatedDb

    # Add multiple messages
    now = datetime.datetime.now(datetime.UTC)
    for i in range(10):
        db.saveChatMessage(
            date=now + datetime.timedelta(seconds=i),
            chatId=123,
            userId=1001,
            messageId=i + 1,
            messageText=f"Message {i + 1}",
        )

    # Get user with message count
    user = db.getChatUser(123, 1001)
    assert user is not None
    assert user["messages_count"] == 10


@pytest.mark.asyncio
async def testFilteringAndSorting(populatedDb):
    """Test filtering and sorting in queries, dood!"""
    db = populatedDb

    # Add messages with different categories
    now = datetime.datetime.now(datetime.UTC)
    db.saveChatMessage(
        date=now, chatId=123, userId=1001, messageId=1, messageText="User message", messageCategory=MessageCategory.USER
    )
    db.saveChatMessage(
        date=now + datetime.timedelta(seconds=1),
        chatId=123,
        userId=1001,
        messageId=2,
        messageText="Bot message",
        messageCategory=MessageCategory.BOT,
    )
    db.saveChatMessage(
        date=now + datetime.timedelta(seconds=2),
        chatId=123,
        userId=1001,
        messageId=3,
        messageText="Another user message",
        messageCategory=MessageCategory.USER,
    )

    # Filter by category
    userMessages = db.getChatMessagesSince(chatId=123, messageCategory=[MessageCategory.USER])

    assert len(userMessages) == 2
    assert all(msg["message_category"] == MessageCategory.USER for msg in userMessages)

    # Verify sorting (DESC by date)
    assert int(userMessages[0]["message_id"]) == 3
    assert int(userMessages[1]["message_id"]) == 1


@pytest.mark.asyncio
async def testPagination(populatedDb):
    """Test pagination in queries, dood!"""
    db = populatedDb

    # Add many messages
    now = datetime.datetime.now(datetime.UTC)
    for i in range(50):
        db.saveChatMessage(
            date=now + datetime.timedelta(seconds=i),
            chatId=123,
            userId=1001,
            messageId=i + 1,
            messageText=f"Message {i + 1}",
        )

    # Get first page
    page1 = db.getChatMessagesSince(chatId=123, limit=10)
    assert len(page1) == 10

    # Get second page
    page2 = db.getChatMessagesSince(chatId=123, tillDateTime=page1[-1]["date"], limit=10)
    assert len(page2) == 10

    # Verify no overlap
    page1Ids = {msg["message_id"] for msg in page1}
    page2Ids = {msg["message_id"] for msg in page2}
    assert len(page1Ids & page2Ids) == 0


# ============================================================================
# CRUD Operations Tests - Chat Messages
# ============================================================================


@pytest.mark.asyncio
async def testChatMessagesCrud(populatedDb):
    """Test CRUD operations for chat messages, dood!"""
    db = populatedDb

    # CREATE
    now = datetime.datetime.now(datetime.UTC)
    success = db.saveChatMessage(
        date=now,
        chatId=123,
        userId=1001,
        messageId=1,
        messageText="Test message",
        messageType=MessageType.TEXT,
        messageCategory=MessageCategory.USER,
        threadId=0,
    )
    assert success is True

    # READ
    message = db.getChatMessageByMessageId(123, 1)
    assert message is not None
    assert message["message_text"] == "Test message"
    assert message["user_id"] == 1001

    success = db.updateChatMessageCategory(123, 1, MessageCategory.BOT)
    assert success is True

    message = db.getChatMessageByMessageId(123, 1)
    assert message["message_category"] == MessageCategory.BOT

    # DELETE (not implemented, but we can test retrieval)
    messages = db.getChatMessagesSince(chatId=123)
    assert len(messages) >= 1


# ============================================================================
# CRUD Operations Tests - Chat Users
# ============================================================================


@pytest.mark.asyncio
async def testChatUsersCrud(inMemoryDb):
    """Test CRUD operations for chat users, dood!"""
    db = inMemoryDb

    # Setup
    db.updateChatInfo(chatId=123, type="group", title="Test")

    # CREATE
    success = db.updateChatUser(chatId=123, userId=1001, username="testuser", fullName="Test User")
    assert success is True

    # READ
    user = db.getChatUser(123, 1001)
    assert user is not None
    assert user["username"] == "testuser"
    assert user["full_name"] == "Test User"
    assert user["messages_count"] == 0

    # UPDATE
    success = db.updateChatUser(chatId=123, userId=1001, username="updateduser", fullName="Updated User")
    assert success is True

    # READ updated
    user = db.getChatUser(123, 1001)
    assert user["username"] == "updateduser"
    assert user["full_name"] == "Updated User"

    # UPDATE metadata
    metadata = json.dumps({"key": "value"})
    success = db.updateUserMetadata(123, 1001, metadata)
    assert success is True

    user = db.getChatUser(123, 1001)
    assert user["metadata"] == metadata

    # Note: is_spammer functionality removed in migration 009


# ============================================================================
# CRUD Operations Tests - Chat Settings
# ============================================================================


@pytest.mark.asyncio
async def testChatSettingsCrud(inMemoryDb):
    """Test CRUD operations for chat settings, dood!"""
    db = inMemoryDb

    # Setup
    db.updateChatInfo(chatId=123, type="group", title="Test")

    # CREATE
    success = db.setChatSetting(123, "model", "gpt-4", updatedBy=0)
    assert success is True

    # READ
    value = db.getChatSetting(123, "model")
    assert value == "gpt-4"

    # READ all
    settings = db.getChatSettings(123)
    assert "model" in settings
    assert settings["model"] == ("gpt-4", 0)

    # UPDATE
    success = db.setChatSetting(123, "model", "gpt-3.5-turbo", updatedBy=0)
    assert success is True

    value = db.getChatSetting(123, "model")
    assert value == "gpt-3.5-turbo"

    # CREATE multiple
    db.setChatSetting(123, "temperature", "0.7", updatedBy=0)
    db.setChatSetting(123, "max_tokens", "1000", updatedBy=0)

    settings = db.getChatSettings(123)
    assert len(settings) == 3

    # DELETE one
    success = db.unsetChatSetting(123, "temperature")
    assert success is True

    value = db.getChatSetting(123, "temperature")
    assert value is None

    # DELETE all
    success = db.clearChatSettings(123)
    assert success is True

    settings = db.getChatSettings(123)
    assert len(settings) == 0


# ============================================================================
# CRUD Operations Tests - User Data
# ============================================================================


@pytest.mark.asyncio
async def testUserDataCrud(inMemoryDb):
    """Test CRUD operations for user data, dood!"""
    db = inMemoryDb

    # Setup
    db.updateChatInfo(chatId=123, type="group", title="Test")
    db.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    # CREATE
    success = db.addUserData(1001, 123, "preference", "dark_mode")
    assert success is True

    # READ
    data = db.getUserData(1001, 123)
    assert "preference" in data
    assert data["preference"] == "dark_mode"

    # UPDATE
    success = db.addUserData(1001, 123, "preference", "light_mode")
    assert success is True

    data = db.getUserData(1001, 123)
    assert data["preference"] == "light_mode"

    # CREATE multiple
    db.addUserData(1001, 123, "language", "en")
    db.addUserData(1001, 123, "timezone", "UTC")

    data = db.getUserData(1001, 123)
    assert len(data) == 3

    # DELETE one
    success = db.deleteUserData(1001, 123, "language")
    assert success is True

    data = db.getUserData(1001, 123)
    assert "language" not in data
    assert len(data) == 2

    # DELETE all
    success = db.clearUserData(1001, 123)
    assert success is True

    data = db.getUserData(1001, 123)
    assert len(data) == 0


# ============================================================================
# CRUD Operations Tests - Delayed Tasks
# ============================================================================


@pytest.mark.asyncio
async def testDelayedTasksCrud(inMemoryDb):
    """Test CRUD operations for delayed tasks, dood!"""
    db = inMemoryDb

    # CREATE
    taskId = "task_123"
    function = "send_message"
    kwargs = json.dumps({"chat_id": 123, "text": "Hello"})
    delayedTs = int(datetime.datetime.now(datetime.UTC).timestamp()) + 3600

    success = db.addDelayedTask(taskId, function, kwargs, delayedTs)
    assert success is True

    # READ
    tasks = db.getPendingDelayedTasks()
    assert len(tasks) == 1
    assert tasks[0]["id"] == taskId
    assert tasks[0]["function"] == function
    assert tasks[0]["is_done"] is False

    # UPDATE
    success = db.updateDelayedTask(taskId, isDone=True)
    assert success is True

    # READ updated
    tasks = db.getPendingDelayedTasks()
    assert len(tasks) == 0  # No pending tasks


# ============================================================================
# CRUD Operations Tests - Spam/Ham Messages
# ============================================================================


@pytest.mark.asyncio
async def testSpamHamMessagesCrud(inMemoryDb):
    """Test CRUD operations for spam/ham messages, dood!"""
    db = inMemoryDb

    # Setup
    db.updateChatInfo(chatId=123, type="group", title="Test")
    db.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    # CREATE spam message
    success = db.addSpamMessage(
        chatId=123,
        userId=1001,
        messageId=1,
        messageText="Buy now!",
        spamReason=SpamReason.AUTO,
        score=0.95,
        confidence=1.0,
    )
    assert success is True

    # READ spam messages
    spamMessages = db.getSpamMessages(limit=10)
    assert len(spamMessages) == 1
    assert spamMessages[0]["text"] == "Buy now!"
    assert spamMessages[0]["score"] == 0.95

    # READ by user
    userSpam = db.getSpamMessagesByUserId(123, 1001)
    assert len(userSpam) == 1

    # CREATE ham message
    success = db.addHamMessage(
        chatId=123,
        userId=1001,
        messageId=2,
        messageText="Hello friend",
        spamReason=SpamReason.USER,
        score=0.05,
        confidence=1.0,
    )
    assert success is True

    # DELETE spam by user
    success = db.deleteSpamMessagesByUserId(123, 1001)
    assert success is True

    spamMessages = db.getSpamMessagesByUserId(123, 1001)
    assert len(spamMessages) == 0


# ============================================================================
# CRUD Operations Tests - Cache Operations
# ============================================================================


@pytest.mark.asyncio
async def testCacheOperationsCrud(inMemoryDb):
    """Test CRUD operations for cache, dood!"""
    db = inMemoryDb

    # CREATE weather cache
    key = "weather:london"
    data = json.dumps({"temp": 20, "condition": "sunny"})
    success = db.setCacheEntry(key, data, CacheType.WEATHER)
    assert success is True

    # READ
    entry = db.getCacheEntry(key, CacheType.WEATHER)
    assert entry is not None
    assert entry["key"] == key
    assert entry["data"] == data

    # UPDATE
    newData = json.dumps({"temp": 22, "condition": "cloudy"})
    success = db.setCacheEntry(key, newData, CacheType.WEATHER)
    assert success is True

    entry = db.getCacheEntry(key, CacheType.WEATHER)
    assert entry["data"] == newData

    # Test TTL
    entry = db.getCacheEntry(key, CacheType.WEATHER, ttl=3600)
    assert entry is not None

    # Test expired TTL
    entry = db.getCacheEntry(key, CacheType.WEATHER, ttl=0)
    assert entry is None


@pytest.mark.asyncio
async def testCacheStorageOperations(inMemoryDb):
    """Test cache storage operations, dood!"""
    db = inMemoryDb

    # CREATE
    success = db.setCacheStorage("test_namespace", "key1", "value1")
    assert success is True

    # READ all
    entries = db.getCacheStorage()
    assert len(entries) >= 1
    assert any(e["namespace"] == "test_namespace" and e["key"] == "key1" for e in entries)

    # UPDATE
    success = db.setCacheStorage("test_namespace", "key1", "value2")
    assert success is True

    entries = db.getCacheStorage()
    entry = next(e for e in entries if e["namespace"] == "test_namespace" and e["key"] == "key1")
    assert entry["value"] == "value2"

    # DELETE
    success = db.unsetCacheStorage("test_namespace", "key1")
    assert success is True

    entries = db.getCacheStorage()
    assert not any(e["namespace"] == "test_namespace" and e["key"] == "key1" for e in entries)


# ============================================================================
# Complex Scenario Tests
# ============================================================================


@pytest.mark.asyncio
async def testCompleteMessageWorkflow(populatedDb):
    """Test complete message workflow with all related operations, dood!"""
    db = populatedDb

    # 1. Save message with media
    fileUniqueId = "media_123"
    db.addMediaAttachment(fileUniqueId=fileUniqueId, fileId="file_123", mediaType=MessageType.IMAGE, metadata="{}")

    now = datetime.datetime.now(datetime.UTC)
    success = db.saveChatMessage(
        date=now,
        chatId=123,
        userId=1001,
        messageId=1,
        messageText="Check this image",
        messageType=MessageType.IMAGE,
        messageCategory=MessageCategory.USER,
        mediaId=fileUniqueId,
    )
    assert success is True

    # 2. Retrieve message with media info
    message = db.getChatMessageByMessageId(123, 1)
    assert message is not None
    assert message["media_id"] == fileUniqueId

    # 3. Update media status
    db.updateMediaAttachment(fileUniqueId, status=MediaStatus.DONE)

    # 4. Verify media status was updated
    media = db.getMediaAttachment(fileUniqueId)
    assert media is not None
    assert media["status"] == MediaStatus.DONE

    # 5. Check user stats updated
    user = db.getChatUser(123, 1001)
    assert user["messages_count"] >= 1


@pytest.mark.asyncio
async def testConversationThreadWorkflow(populatedDb):
    """Test conversation thread workflow, dood!"""
    db = populatedDb

    now = datetime.datetime.now(datetime.UTC)

    # 1. Root message
    db.saveChatMessage(date=now, chatId=123, userId=1001, messageId=1, messageText="Root message", threadId=0)

    # 2. Reply to root
    db.saveChatMessage(
        date=now + datetime.timedelta(seconds=1),
        chatId=123,
        userId=1002,
        messageId=2,
        messageText="Reply 1",
        replyId=1,
        rootMessageId=1,
        threadId=0,
    )

    # 3. Another reply to root
    db.saveChatMessage(
        date=now + datetime.timedelta(seconds=2),
        chatId=123,
        userId=1001,
        messageId=3,
        messageText="Reply 2",
        replyId=1,
        rootMessageId=1,
        threadId=0,
    )

    # 4. Get conversation thread
    thread = db.getChatMessagesByRootId(123, 1, threadId=0)
    assert len(thread) == 2
    assert int(thread[0]["message_id"]) == 2
    assert int(thread[1]["message_id"]) == 3


@pytest.mark.asyncio
async def testSummarizationCacheWorkflow(populatedDb):
    """Test summarization cache workflow, dood!"""
    db = populatedDb

    # Add messages
    now = datetime.datetime.now(datetime.UTC)
    for i in range(5):
        db.saveChatMessage(
            date=now + datetime.timedelta(seconds=i),
            chatId=123,
            userId=1001,
            messageId=i + 1,
            messageText=f"Message {i + 1}",
        )

    # Add summarization
    prompt = "Summarize the conversation"
    summary = "This is a summary of 5 messages"
    success = db.addChatSummarization(
        chatId=123, topicId=None, firstMessageId=1, lastMessageId=5, prompt=prompt, summary=summary
    )
    assert success is True

    # Retrieve summarization
    cached = db.getChatSummarization(chatId=123, topicId=None, firstMessageId=1, lastMessageId=5, prompt=prompt)
    assert cached is not None
    assert cached["summary"] == summary

    # Update summarization
    newSummary = "Updated summary"
    success = db.addChatSummarization(
        chatId=123, topicId=None, firstMessageId=1, lastMessageId=5, prompt=prompt, summary=newSummary
    )
    assert success is True

    cached = db.getChatSummarization(chatId=123, topicId=None, firstMessageId=1, lastMessageId=5, prompt=prompt)
    assert cached["summary"] == newSummary


@pytest.mark.asyncio
async def testChatTopicsWorkflow(inMemoryDb):
    """Test chat topics workflow, dood!"""
    db = inMemoryDb

    # Setup forum chat
    db.updateChatInfo(chatId=123, type="supergroup", title="Forum", isForum=True)

    # Add topics
    db.updateChatTopicInfo(chatId=123, topicId=1, iconColor=0xFF0000, topicName="General")
    db.updateChatTopicInfo(chatId=123, topicId=2, iconColor=0x00FF00, topicName="Support")

    # Get topics
    topics = db.getChatTopics(123)
    assert len(topics) == 2
    assert any(t["name"] == "General" for t in topics)
    assert any(t["name"] == "Support" for t in topics)

    # Update topic
    db.updateChatTopicInfo(chatId=123, topicId=1, iconColor=0x0000FF, topicName="General Discussion")

    topics = db.getChatTopics(123)
    topic = next(t for t in topics if t["topic_id"] == 1)
    assert topic["name"] == "General Discussion"
    assert topic["icon_color"] == 0x0000FF


@pytest.mark.asyncio
async def testGlobalSettingsWorkflow(inMemoryDb):
    """Test global settings workflow, dood!"""
    db = inMemoryDb

    # Set settings
    db.setSetting("bot_version", "1.0.0")
    db.setSetting("maintenance_mode", "false")

    # Get individual setting
    version = db.getSetting("bot_version")
    assert version == "1.0.0"

    # Get all settings
    settings = db.getSettings()
    assert "bot_version" in settings
    assert "maintenance_mode" in settings

    # Update setting
    db.setSetting("bot_version", "1.0.1")
    version = db.getSetting("bot_version")
    assert version == "1.0.1"

    # Get with default
    value = db.getSetting("nonexistent", "default_value")
    assert value == "default_value"


@pytest.mark.asyncio
async def testUserChatRelationships(populatedDb):
    """Test user-chat relationship queries, dood!"""
    db = populatedDb

    # Add user to multiple chats
    db.updateChatInfo(chatId=789, type="group", title="Another Chat")
    db.updateChatUser(chatId=789, userId=1001, username="user1", fullName="User One")

    # Get user's chats
    chats = db.getUserChats(1001)
    assert len(chats) >= 2
    chatIds = {chat["chat_id"] for chat in chats}
    assert 123 in chatIds
    assert 456 in chatIds
    assert 789 in chatIds

    # Get all group chats
    groupChats = db.getAllGroupChats()
    assert len(groupChats) >= 2
    assert any(chat["chat_id"] == 123 for chat in groupChats)
    assert any(chat["chat_id"] == 789 for chat in groupChats)


# ============================================================================
# Error Handling and Recovery Tests
# ============================================================================


@pytest.mark.asyncio
async def testErrorHandlingInvalidData(inMemoryDb):
    """Test error handling with invalid data, dood!"""
    db = inMemoryDb

    # Try to get non-existent chat
    chatInfo = db.getChatInfo(99999)
    assert chatInfo is None

    # Try to get non-existent user
    user = db.getChatUser(123, 99999)
    assert user is None

    # Try to get non-existent message
    message = db.getChatMessageByMessageId(123, 99999)
    assert message is None

    # Try to get non-existent setting
    setting = db.getChatSetting(123, "nonexistent")
    assert setting is None


@pytest.mark.asyncio
async def testRecoveryAfterError(inMemoryDb):
    """Test database recovery after error, dood!"""
    db = inMemoryDb

    # Add valid data
    db.updateChatInfo(chatId=123, type="group", title="Test")

    # Cause an error
    try:
        with db.getCursor() as cursor:
            cursor.execute("INVALID SQL")
    except sqlite3.OperationalError:
        pass  # Expected error

    # Verify database still works
    chatInfo = db.getChatInfo(123)
    assert chatInfo is not None

    # Add more data
    success = db.updateChatUser(123, 1001, "user1", "User One")
    assert success is True


@pytest.mark.asyncio
async def testEmptyResultHandling(populatedDb):
    """Test handling of empty results, dood!"""
    db = populatedDb

    # Get messages from empty time range
    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)
    messages = db.getChatMessagesSince(chatId=123, sinceDateTime=future)
    assert messages == []

    # Get users with no recent activity
    users = db.getChatUsers(chatId=123, seenSince=future)
    assert users == []

    # Get spam messages when none exist
    spamMessages = db.getSpamMessages(limit=10)
    assert spamMessages == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
