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

import asyncio
import datetime
import json
import sqlite3

import pytest

from internal.database import Database
from internal.database.manager import DatabaseManagerConfig
from internal.database.models import (
    CacheType,
    MediaStatus,
    MessageCategory,
    SpamReason,
)
from internal.models import MessageType


@pytest.fixture
async def inMemoryDb():
    """Provide in-memory SQLite database for testing, dood!"""
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            }
        },
    }
    db = Database(config)
    # Initialize database by getting a provider (triggers migration)
    await db.manager.getProvider()
    yield db


@pytest.fixture
async def threadSafeDb(tmp_path):
    """Provide file-based SQLite database for threading tests, dood!

    File-based databases support proper concurrent access across threads,
    unlike in-memory databases which are isolated per connection.
    """
    dbPath = tmp_path / "test_threading.db"
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": str(dbPath),
                },
            }
        },
    }
    db = Database(config)
    # Initialize database by getting a provider (triggers migration)
    await db.manager.getProvider()
    yield db


@pytest.fixture
async def populatedDb(inMemoryDb):
    """Provide database with sample data, dood!"""
    db = inMemoryDb

    # Add sample chat info
    await db.chatInfo.updateChatInfo(chatId=123, type="supergroup", title="Test Chat", isForum=False)
    await db.chatInfo.updateChatInfo(chatId=456, type="private", title="Private Chat", isForum=False)

    # Add sample users
    await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")
    await db.chatUsers.updateChatUser(chatId=123, userId=1002, username="user2", fullName="User Two")
    await db.chatUsers.updateChatUser(chatId=456, userId=1001, username="user1", fullName="User One")

    return db


# ============================================================================
# Transaction Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def testTransactionCommitOnSuccess(inMemoryDb):
    """Test transaction commits on success, dood!"""
    db = inMemoryDb

    # Add chat info and user in a transaction
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")
    await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="test", fullName="Test User")

    # Verify data was committed
    chatInfo = await db.chatInfo.getChatInfo(123)
    assert chatInfo is not None
    assert chatInfo["chat_id"] == 123

    user = await db.chatUsers.getChatUser(123, 1001)
    assert user is not None
    assert user["username"] == "test"


@pytest.mark.asyncio
async def testTransactionRollbackOnError(inMemoryDb):
    """Test transaction rollback on error, dood!"""
    db = inMemoryDb

    # Add valid chat info
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")

    # Try to add duplicate chat info (should fail)
    try:
        provider = await db.manager.getProvider(chatId=123, readonly=False)
        # This should fail due to unique constraint
        await provider.execute("INSERT INTO chat_info (chat_id, type) VALUES (?, ?)", (123, "group"))
    except Exception:
        pass  # Expected error

    # Verify original data is still there
    chatInfo = await db.chatInfo.getChatInfo(123)
    assert chatInfo is not None
    assert chatInfo["title"] == "Test"


@pytest.mark.asyncio
async def testNestedTransactions(inMemoryDb):
    """Test nested transaction handling, dood!"""
    db = inMemoryDb

    # SQLite doesn't support true nested transactions, but we can test
    # that multiple operations in sequence work correctly
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")
    await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")
    await db.chatSettings.setChatSetting(chatId=123, key="model", value="gpt-4", updatedBy=0)

    # Verify all operations succeeded
    chatInfo = await db.chatInfo.getChatInfo(123)
    assert chatInfo is not None
    user = await db.chatUsers.getChatUser(123, 1001)
    assert user is not None
    setting = await db.chatSettings.getChatSetting(123, "model")
    assert setting == "gpt-4"


@pytest.mark.asyncio
async def testConcurrentTransactions(inMemoryDb):
    """Test concurrent transaction handling, dood!"""
    db = inMemoryDb

    # Setup initial data
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")
    await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    results = []
    errors = []

    async def updateUser(userId: int, username: str):
        try:
            await db.chatUsers.updateChatUser(chatId=123, userId=userId, username=username, fullName=f"User {userId}")
            results.append(userId)
        except Exception as e:
            errors.append(e)

    # Run concurrent updates using asyncio
    tasks = []
    for i in range(5):
        task = asyncio.create_task(updateUser(1000 + i, f"user{i}"))
        tasks.append(task)

    await asyncio.gather(*tasks)

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
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")
    await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    # Try to save message for non-existent user (should work as FK not enforced in current schema)
    # But the join will fail to return user data
    now = datetime.datetime.now(datetime.UTC)
    success = await db.chatMessages.saveChatMessage(
        date=now, chatId=123, userId=9999, messageId=1, messageText="Test"  # Non-existent user
    )

    # Message save might succeed, but retrieval will fail the join
    # This tests that our validation catches missing user data
    assert success is False or await db.chatMessages.getChatMessageByMessageId(123, 1) is None


@pytest.mark.asyncio
async def testUniqueConstraints(inMemoryDb):
    """Test unique constraints, dood!"""
    db = inMemoryDb

    # Add chat info
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")

    # Try to add duplicate chat info
    result = await db.chatInfo.updateChatInfo(chatId=123, type="supergroup", title="Updated")

    # Should succeed as we use INSERT OR REPLACE
    assert result is True

    # Verify data was updated
    chatInfo = await db.chatInfo.getChatInfo(123)
    assert chatInfo["type"] == "supergroup"
    assert chatInfo["title"] == "Updated"


@pytest.mark.asyncio
async def testNotNullConstraints(inMemoryDb):
    """Test NOT NULL constraints, dood!"""
    db = inMemoryDb

    # Try to add chat info without required fields
    try:
        provider = await db.manager.getProvider(readonly=False)
        await provider.execute("INSERT INTO chat_info (chat_id) VALUES (?)", (123,))
        assert False, "Should have raised error for missing NOT NULL field"
    except sqlite3.IntegrityError:
        pass  # Expected error


@pytest.mark.asyncio
async def testDataValidation(inMemoryDb):
    """Test data validation in wrapper methods, dood!"""
    db = inMemoryDb

    # Setup
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")
    await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    # Save message with valid data
    now = datetime.datetime.now(datetime.UTC)
    success = await db.chatMessages.saveChatMessage(
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
    message = await db.chatMessages.getChatMessageByMessageId(123, 1)
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
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")
    await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    results = []

    async def readChatInfo():
        info = await db.chatInfo.getChatInfo(123)
        results.append(info)

    # Run concurrent reads using asyncio
    tasks = [asyncio.create_task(readChatInfo()) for _ in range(10)]
    await asyncio.gather(*tasks)

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
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")

    results = []
    errors = []

    async def addUser(userId: int):
        try:
            success = await db.chatUsers.updateChatUser(
                chatId=123, userId=userId, username=f"user{userId}", fullName=f"User {userId}"
            )
            results.append(success)
        except Exception as e:
            errors.append(e)

    # Run concurrent writes using asyncio
    tasks = [asyncio.create_task(addUser(1000 + i)) for i in range(10)]
    await asyncio.gather(*tasks)

    # Verify all writes succeeded
    assert len(results) == 10
    assert all(r is True for r in results)
    assert len(errors) == 0

    # Verify all users were created
    users = await db.getChatUsers(123, limit=20)
    assert len(users) == 10


@pytest.mark.asyncio
async def testReadWriteConflicts(threadSafeDb):
    """Test read-write conflict handling, dood!

    Uses file-based database to support proper concurrent access across threads.
    """
    db = threadSafeDb

    # Setup
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")
    await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    readResults = []
    writeResults = []

    async def reader():
        for _ in range(5):
            user = await db.chatUsers.getChatUser(123, 1001)
            readResults.append(user)

    async def writer():
        for i in range(5):
            success = await db.chatUsers.updateChatUser(
                chatId=123, userId=1001, username=f"user{i}", fullName=f"User {i}"
            )
            writeResults.append(success)

    # Run concurrent reads and writes using asyncio
    await asyncio.gather(
        asyncio.create_task(reader()),
        asyncio.create_task(writer())
    )

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
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")
    await db.chatInfo.updateChatInfo(chatId=456, type="group", title="Test 2")

    # SQLite uses a simple locking mechanism that prevents true deadlocks
    # But we can test that concurrent operations don't hang

    results = []

    async def updateChats(chatId1: int, chatId2: int):
        await db.chatSettings.setChatSetting(chatId1, "key1", "value1", updatedBy=0)
        await db.chatSettings.setChatSetting(chatId2, "key2", "value2", updatedBy=0)
        results.append(True)

    # Run concurrent operations using asyncio
    await asyncio.gather(
        asyncio.create_task(updateChats(123, 456)),
        asyncio.create_task(updateChats(456, 123))
    )

    # Verify both operations completed
    assert len(results) == 2


# ============================================================================
# Migration Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def testSchemaCreation(inMemoryDb):
    """Test schema creation through migrations, dood!"""
    db = inMemoryDb

    # Verify all tables exist
    provider = await db.manager.getProvider(readonly=True)
    rows = await provider.executeFetchAll("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row["name"] for row in rows]

    expectedTables = [
        "bayes_classes",  # Created by migrations
        "bayes_tokens",  # Created by migrations
        "cache",
        "cache_storage",
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
        "media_groups",
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

    provider = await db.manager.getProvider(readonly=True)
    # Check that cache_storage table exists (added in migration 004)
    rows = await provider.executeFetchAll("SELECT name FROM sqlite_master WHERE type='table' AND name='cache_storage'")
    assert len(rows) > 0, "cache_storage table should exist (migration 004)"

    # Check that chat_users has metadata column (added in migration 003)
    columns = [row["name"] for row in await provider.executeFetchAll("PRAGMA table_info(chat_users)")]
    assert "metadata" in columns, "chat_users should have metadata column (migration 003)"
    # Note: is_spammer column was removed in migration 009


@pytest.mark.asyncio
async def testDataMigration(inMemoryDb):
    """Test data migration scenarios, dood!"""
    db = inMemoryDb

    # Add data before "migration"
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")
    await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    # Verify data persists (simulating migration)
    chatInfo = await db.chatInfo.getChatInfo(123)
    assert chatInfo is not None

    user = await db.chatUsers.getChatUser(123, 1001)
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
    await db.chatMessages.saveChatMessage(date=now, chatId=123, userId=1001, messageId=1, messageText="Test message 1")
    await db.chatMessages.saveChatMessage(date=now, chatId=123, userId=1002, messageId=2, messageText="Test message 2")

    # Get messages with user info (tests JOIN)
    messages = await db.chatMessages.getChatMessagesSince(chatId=123, sinceDateTime=now - datetime.timedelta(hours=1))

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
        await db.chatMessages.saveChatMessage(
            date=now + datetime.timedelta(seconds=i),
            chatId=123,
            userId=1001,
            messageId=i + 1,
            messageText=f"Message {i + 1}",
        )

    # Get user with message count
    user = await db.chatUsers.getChatUser(123, 1001)
    assert user is not None
    assert user["messages_count"] == 10


@pytest.mark.asyncio
async def testFilteringAndSorting(populatedDb):
    """Test filtering and sorting in queries, dood!"""
    db = populatedDb

    # Add messages with different categories
    now = datetime.datetime.now(datetime.UTC)
    await db.chatMessages.saveChatMessage(
        date=now, chatId=123, userId=1001, messageId=1, messageText="User message", messageCategory=MessageCategory.USER
    )
    await db.chatMessages.saveChatMessage(
        date=now + datetime.timedelta(seconds=1),
        chatId=123,
        userId=1001,
        messageId=2,
        messageText="Bot message",
        messageCategory=MessageCategory.BOT,
    )
    await db.chatMessages.saveChatMessage(
        date=now + datetime.timedelta(seconds=2),
        chatId=123,
        userId=1001,
        messageId=3,
        messageText="Another user message",
        messageCategory=MessageCategory.USER,
    )

    # Filter by category
    userMessages = await db.chatMessages.getChatMessagesSince(chatId=123, messageCategory=[MessageCategory.USER])

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
        await db.chatMessages.saveChatMessage(
            date=now + datetime.timedelta(seconds=i),
            chatId=123,
            userId=1001,
            messageId=i + 1,
            messageText=f"Message {i + 1}",
        )

    # Get first page
    page1 = await db.chatMessages.getChatMessagesSince(chatId=123, limit=10)
    assert len(page1) == 10

    # Get second page
    page2 = await db.chatMessages.getChatMessagesSince(chatId=123, tillDateTime=page1[-1]["date"], limit=10)
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
    success = await db.chatMessages.saveChatMessage(
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
    message = await db.chatMessages.getChatMessageByMessageId(123, 1)
    assert message is not None
    assert message["message_text"] == "Test message"
    assert message["user_id"] == 1001

    success = await db.chatMessages.updateChatMessageCategory(123, 1, MessageCategory.BOT)
    assert success is True

    message = await db.chatMessages.getChatMessageByMessageId(123, 1)
    assert message["message_category"] == MessageCategory.BOT

    # DELETE (not implemented, but we can test retrieval)
    messages = await db.chatMessages.getChatMessagesSince(chatId=123)
    assert len(messages) >= 1


# ============================================================================
# CRUD Operations Tests - Chat Users
# ============================================================================


@pytest.mark.asyncio
async def testChatUsersCrud(inMemoryDb):
    """Test CRUD operations for chat users, dood!"""
    db = inMemoryDb

    # Setup
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")

    # CREATE
    success = await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="testuser", fullName="Test User")
    assert success is True

    # READ
    user = await db.chatUsers.getChatUser(123, 1001)
    assert user is not None
    assert user["username"] == "testuser"
    assert user["full_name"] == "Test User"
    assert user["messages_count"] == 0

    # UPDATE
    success = await db.chatUsers.updateChatUser(
        chatId=123, userId=1001, username="updateduser", fullName="Updated User"
    )
    assert success is True

    # READ updated
    user = await db.chatUsers.getChatUser(123, 1001)
    assert user["username"] == "updateduser"
    assert user["full_name"] == "Updated User"

    # UPDATE metadata
    metadataDict = {"key": "value"}
    success = await db.updateUserMetadata(123, 1001, metadataDict)
    assert success is True

    user = await db.chatUsers.getChatUser(123, 1001)
    assert user["metadata"] == json.dumps(metadataDict)

    # Note: is_spammer functionality removed in migration 009


# ============================================================================
# CRUD Operations Tests - Chat Settings
# ============================================================================


@pytest.mark.asyncio
async def testChatSettingsCrud(inMemoryDb):
    """Test CRUD operations for chat settings, dood!"""
    db = inMemoryDb

    # Setup
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")

    # CREATE
    success = await db.chatSettings.setChatSetting(123, "model", "gpt-4", updatedBy=0)
    assert success is True

    # READ
    value = await db.chatSettings.getChatSetting(123, "model")
    assert value == "gpt-4"

    # READ all
    settings = await db.getChatSettings(123)
    assert "model" in settings
    assert settings["model"] == ("gpt-4", 0)

    # UPDATE
    success = await db.chatSettings.setChatSetting(123, "model", "gpt-3.5-turbo", updatedBy=0)
    assert success is True

    value = await db.chatSettings.getChatSetting(123, "model")
    assert value == "gpt-3.5-turbo"

    # CREATE multiple
    await db.chatSettings.setChatSetting(123, "temperature", "0.7", updatedBy=0)
    await db.chatSettings.setChatSetting(123, "max_tokens", "1000", updatedBy=0)

    settings = await db.getChatSettings(123)
    assert len(settings) == 3

    # DELETE one
    success = await db.unsetChatSetting(123, "temperature")
    assert success is True

    value = await db.chatSettings.getChatSetting(123, "temperature")
    assert value is None

    # DELETE all
    success = await db.clearChatSettings(123)
    assert success is True

    settings = await db.getChatSettings(123)
    assert len(settings) == 0


# ============================================================================
# CRUD Operations Tests - User Data
# ============================================================================


@pytest.mark.asyncio
async def testUserDataCrud(inMemoryDb):
    """Test CRUD operations for user data, dood!"""
    db = inMemoryDb

    # Setup
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")
    await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    # CREATE
    success = await db.addUserData(1001, 123, "preference", "dark_mode")
    assert success is True

    # READ
    data = await db.getUserData(1001, 123)
    assert "preference" in data
    assert data["preference"] == "dark_mode"

    # UPDATE
    success = await db.addUserData(1001, 123, "preference", "light_mode")
    assert success is True

    data = await db.getUserData(1001, 123)
    assert data["preference"] == "light_mode"

    # CREATE multiple
    await db.addUserData(1001, 123, "language", "en")
    await db.addUserData(1001, 123, "timezone", "UTC")

    data = await db.getUserData(1001, 123)
    assert len(data) == 3

    # DELETE one
    success = await db.deleteUserData(1001, 123, "language")
    assert success is True

    data = await db.getUserData(1001, 123)
    assert "language" not in data
    assert len(data) == 2

    # DELETE all
    success = await db.clearUserData(1001, 123)
    assert success is True

    data = await db.getUserData(1001, 123)
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

    success = await db.delayedTasks.addDelayedTask(taskId, function, kwargs, delayedTs)
    assert success is True

    # READ
    tasks = await db.getPendingDelayedTasks()
    assert len(tasks) == 1
    assert tasks[0]["id"] == taskId
    assert tasks[0]["function"] == function
    assert tasks[0]["is_done"] is False

    # UPDATE
    success = await db.updateDelayedTask(taskId, isDone=True)
    assert success is True

    # READ updated
    tasks = await db.getPendingDelayedTasks()
    assert len(tasks) == 0  # No pending tasks


# ============================================================================
# CRUD Operations Tests - Spam/Ham Messages
# ============================================================================


@pytest.mark.asyncio
async def testSpamHamMessagesCrud(inMemoryDb):
    """Test CRUD operations for spam/ham messages, dood!"""
    db = inMemoryDb

    # Setup
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")
    await db.chatUsers.updateChatUser(chatId=123, userId=1001, username="user1", fullName="User One")

    # CREATE spam message
    success = await db.addSpamMessage(
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
    spamMessages = await db.getSpamMessages(limit=10)
    assert len(spamMessages) == 1
    assert spamMessages[0]["text"] == "Buy now!"
    assert spamMessages[0]["score"] == 0.95

    # READ by user
    userSpam = await db.getSpamMessagesByUserId(123, 1001)
    assert len(userSpam) == 1

    # CREATE ham message
    success = await db.addHamMessage(
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
    success = await db.deleteSpamMessagesByUserId(123, 1001)
    assert success is True

    spamMessages = await db.getSpamMessagesByUserId(123, 1001)
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
    success = await db.setCacheEntry(key, data, CacheType.WEATHER)
    assert success is True

    # READ
    entry = await db.getCacheEntry(key, CacheType.WEATHER)
    assert entry is not None
    assert entry["key"] == key
    assert entry["data"] == data

    # UPDATE
    newData = json.dumps({"temp": 22, "condition": "cloudy"})
    success = await db.setCacheEntry(key, newData, CacheType.WEATHER)
    assert success is True

    entry = await db.getCacheEntry(key, CacheType.WEATHER)
    assert entry["data"] == newData

    # Test TTL
    entry = await db.getCacheEntry(key, CacheType.WEATHER, ttl=3600)
    assert entry is not None

    # Test expired TTL
    entry = await db.getCacheEntry(key, CacheType.WEATHER, ttl=0)
    assert entry is None


@pytest.mark.asyncio
async def testCacheStorageOperations(inMemoryDb):
    """Test cache storage operations, dood!"""
    db = inMemoryDb

    # CREATE
    success = await db.setCacheStorage("test_namespace", "key1", "value1")
    assert success is True

    # READ all
    entries = await db.getCacheStorage()
    assert len(entries) >= 1
    assert any(e["namespace"] == "test_namespace" and e["key"] == "key1" for e in entries)

    # UPDATE
    success = await db.setCacheStorage("test_namespace", "key1", "value2")
    assert success is True

    entries = await db.getCacheStorage()
    entry = next(e for e in entries if e["namespace"] == "test_namespace" and e["key"] == "key1")
    assert entry["value"] == "value2"

    # DELETE
    success = await db.unsetCacheStorage("test_namespace", "key1")
    assert success is True

    entries = await db.getCacheStorage()
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
    await db.addMediaAttachment(
        fileUniqueId=fileUniqueId, fileId="file_123", mediaType=MessageType.IMAGE, metadata="{}"
    )

    now = datetime.datetime.now(datetime.UTC)
    success = await db.chatMessages.saveChatMessage(
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
    message = await db.chatMessages.getChatMessageByMessageId(123, 1)
    assert message is not None
    assert message["media_id"] == fileUniqueId

    # 3. Update media status
    await db.updateMediaAttachment(mediaId=fileUniqueId, status=MediaStatus.DONE)

    # 4. Verify media status was updated
    media = await db.getMediaAttachment(fileUniqueId)
    assert media is not None
    assert media["status"] == MediaStatus.DONE

    # 5. Check user stats updated
    user = await db.chatUsers.getChatUser(123, 1001)
    assert user["messages_count"] >= 1


@pytest.mark.asyncio
async def testConversationThreadWorkflow(populatedDb):
    """Test conversation thread workflow, dood!"""
    db = populatedDb

    now = datetime.datetime.now(datetime.UTC)

    # 1. Root message
    await db.chatMessages.saveChatMessage(
        date=now, chatId=123, userId=1001, messageId=1, messageText="Root message", threadId=0
    )

    # 2. Reply to root
    await db.chatMessages.saveChatMessage(
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
    await db.chatMessages.saveChatMessage(
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
    thread = await db.chatMessages.getChatMessagesByRootId(123, 1, threadId=0)
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
        await db.chatMessages.saveChatMessage(
            date=now + datetime.timedelta(seconds=i),
            chatId=123,
            userId=1001,
            messageId=i + 1,
            messageText=f"Message {i + 1}",
        )

    # Add summarization
    prompt = "Summarize the conversation"
    summary = "This is a summary of 5 messages"
    success = await db.addChatSummarization(
        chatId=123, topicId=None, firstMessageId=1, lastMessageId=5, prompt=prompt, summary=summary
    )
    assert success is True

    # Retrieve summarization
    cached = await db.getChatSummarization(chatId=123, topicId=None, firstMessageId=1, lastMessageId=5, prompt=prompt)
    assert cached is not None
    assert cached["summary"] == summary

    # Update summarization
    newSummary = "Updated summary"
    success = await db.addChatSummarization(
        chatId=123, topicId=None, firstMessageId=1, lastMessageId=5, prompt=prompt, summary=newSummary
    )
    assert success is True

    cached = await db.getChatSummarization(chatId=123, topicId=None, firstMessageId=1, lastMessageId=5, prompt=prompt)
    assert cached["summary"] == newSummary


@pytest.mark.asyncio
async def testChatTopicsWorkflow(inMemoryDb):
    """Test chat topics workflow, dood!"""
    db = inMemoryDb

    # Setup forum chat
    await db.chatInfo.updateChatInfo(chatId=123, type="supergroup", title="Forum", isForum=True)

    # Add topics
    await db.updateChatTopicInfo(chatId=123, topicId=1, iconColor=0xFF0000, topicName="General")
    await db.updateChatTopicInfo(chatId=123, topicId=2, iconColor=0x00FF00, topicName="Support")

    # Get topics
    topics = await db.getChatTopics(123)
    assert len(topics) == 2
    assert any(t["name"] == "General" for t in topics)
    assert any(t["name"] == "Support" for t in topics)

    # Update topic
    await db.updateChatTopicInfo(chatId=123, topicId=1, iconColor=0x0000FF, topicName="General Discussion")

    topics = await db.getChatTopics(123)
    topic = next(t for t in topics if t["topic_id"] == 1)
    assert topic["name"] == "General Discussion"
    assert topic["icon_color"] == 0x0000FF


@pytest.mark.asyncio
async def testGlobalSettingsWorkflow(inMemoryDb):
    """Test global settings workflow, dood!"""
    db = inMemoryDb

    # Set settings
    await db.setSetting("bot_version", "1.0.0")
    await db.setSetting("maintenance_mode", "false")

    # Get individual setting
    version = await db.getSetting("bot_version")
    assert version == "1.0.0"

    # Get all settings
    settings = await db.getSettings()
    assert "bot_version" in settings
    assert "maintenance_mode" in settings

    # Update setting
    await db.setSetting("bot_version", "1.0.1")
    version = await db.getSetting("bot_version")
    assert version == "1.0.1"

    # Get with default
    value = await db.getSetting("nonexistent", "default_value")
    assert value == "default_value"


@pytest.mark.asyncio
async def testUserChatRelationships(populatedDb):
    """Test user-chat relationship queries, dood!"""
    db = populatedDb

    # Add user to multiple chats
    await db.chatInfo.updateChatInfo(chatId=789, type="group", title="Another Chat")
    await db.chatUsers.updateChatUser(chatId=789, userId=1001, username="user1", fullName="User One")

    # Get user's chats
    chats = await db.getUserChats(1001)
    assert len(chats) >= 2
    chatIds = {chat["chat_id"] for chat in chats}
    assert 123 in chatIds
    assert 456 in chatIds
    assert 789 in chatIds

    # Get all group chats
    groupChats = await db.getAllGroupChats()
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
    chatInfo = await db.chatInfo.getChatInfo(99999)
    assert chatInfo is None

    # Try to get non-existent user
    user = await db.chatUsers.getChatUser(123, 99999)
    assert user is None

    # Try to get non-existent message
    message = await db.chatMessages.getChatMessageByMessageId(123, 99999)
    assert message is None

    # Try to get non-existent setting
    setting = await db.chatSettings.getChatSetting(123, "nonexistent")
    assert setting is None


@pytest.mark.asyncio
async def testRecoveryAfterError(inMemoryDb):
    """Test database recovery after error, dood!"""
    db = inMemoryDb

    # Add valid data
    await db.chatInfo.updateChatInfo(chatId=123, type="group", title="Test")

    # Cause an error
    try:
        provider = await db.manager.getProvider(readonly=False)
        await provider.execute("INVALID SQL")
    except sqlite3.OperationalError:
        pass  # Expected error

    # Verify database still works
    chatInfo = await db.chatInfo.getChatInfo(123)
    assert chatInfo is not None

    # Add more data
    success = await db.chatUsers.updateChatUser(123, 1001, "user1", "User One")
    assert success is True


@pytest.mark.asyncio
async def testEmptyResultHandling(populatedDb):
    """Test handling of empty results, dood!"""
    db = populatedDb

    # Get messages from empty time range
    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)
    messages = await db.chatMessages.getChatMessagesSince(chatId=123, sinceDateTime=future)
    assert messages == []

    # Get users with no recent activity
    users = await db.getChatUsers(chatId=123, seenSince=future)
    assert users == []

    # Get spam messages when none exist
    spamMessages = await db.getSpamMessages(limit=10)
    assert spamMessages == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
