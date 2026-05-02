"""
Performance benchmarks for database queries.

This module contains performance tests for:
- Cache operations
- Chat message operations
- Chat user operations
- Upsert operations
- Batch operations
"""

import time

import pytest

from internal.database import Database
from internal.database.manager import DatabaseManagerConfig
from internal.database.models import CacheType


@pytest.fixture
async def db():
    """Create a database instance for performance testing."""
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
    await db.manager.closeAll()


class TestCachePerformance:
    """Performance tests for cache operations."""

    @pytest.mark.asyncio
    async def test_cache_performance(self, db):
        """Test cache query performance."""
        repo = db.cache

        # Insert 1000 cache entries
        start = time.time()
        for i in range(1000):
            await repo.setCacheEntry(f"key{i}", f"data{i}", CacheType.WEATHER)
        insertTime = time.time() - start

        # Query 1000 cache entries
        start = time.time()
        for i in range(1000):
            await repo.getCacheEntry(f"key{i}", CacheType.WEATHER)
        queryTime = time.time() - start

        print(f"Cache Insert: {insertTime:.3f}s, Query: {queryTime:.3f}s")
        assert insertTime < 10.0  # Should complete in under 10 seconds
        assert queryTime < 5.0  # Should complete in under 5 seconds

    @pytest.mark.asyncio
    async def test_cache_storage_performance(self, db):
        """Test cache storage performance."""
        repo = db.cache

        # Insert 1000 cache storage entries
        start = time.time()
        for i in range(1000):
            await repo.setCacheStorage("test", f"key{i}", f"value{i}")
        insertTime = time.time() - start

        # Query all entries
        start = time.time()
        entries = await repo.getCacheStorage()
        queryTime = time.time() - start

        print(f"Cache Storage Insert: {insertTime:.3f}s, Query: {queryTime:.3f}s")
        assert len(entries) == 1000
        assert insertTime < 10.0
        assert queryTime < 5.0

    @pytest.mark.asyncio
    async def test_cache_clear_performance(self, db):
        """Test cache clear performance."""
        repo = db.cache

        # Insert 1000 entries
        for i in range(1000):
            await repo.setCacheEntry(f"key{i}", f"data{i}", CacheType.WEATHER)

        # Clear all entries
        start = time.time()
        await repo.clearCacheEntries()
        clearTime = time.time() - start

        print(f"Cache Clear: {clearTime:.3f}s")
        assert clearTime < 5.0

        # Verify all cleared
        entries = await repo.getCacheEntries()
        assert len(entries) == 0


class TestChatMessagePerformance:
    """Performance tests for chat message operations."""

    @pytest.mark.asyncio
    async def test_chat_message_insert_performance(self, db):
        """Test chat message insert performance."""
        repo = db.chatMessages

        # Insert 1000 messages
        start = time.time()
        for i in range(1000):
            await repo.saveChatMessage(
                chatId=100,
                userId=1,
                messageId=i,
                messageText=f"Message {i}",
                date="2024-01-01T00:00:00",
            )
        insertTime = time.time() - start

        print(f"Chat Message Insert: {insertTime:.3f}s")
        assert insertTime < 10.0

    @pytest.mark.asyncio
    async def test_chat_message_query_performance(self, db):
        """Test chat message query performance."""
        repo = db.chatMessages

        # Insert 1000 messages
        for i in range(1000):
            await repo.saveChatMessage(
                chatId=100,
                userId=1,
                messageId=i,
                messageText=f"Message {i}",
                date="2024-01-01T00:00:00",
            )

        # Query all messages
        start = time.time()
        messages = await repo.getChatMessages(100)
        queryTime = time.time() - start

        print(f"Chat Message Query: {queryTime:.3f}s")
        assert len(messages) == 1000
        assert queryTime < 5.0

    @pytest.mark.asyncio
    async def test_chat_message_pagination_performance(self, db):
        """Test chat message pagination performance."""
        repo = db.chatMessages

        # Insert 1000 messages
        for i in range(1000):
            await repo.saveChatMessage(
                chatId=100,
                userId=1,
                messageId=i,
                messageText=f"Message {i}",
                date="2024-01-01T00:00:00",
            )

        # Query with pagination
        start = time.time()
        messages = await repo.getChatMessages(100, limit=100, offset=0)
        queryTime = time.time() - start

        print(f"Chat Message Pagination: {queryTime:.3f}s")
        assert len(messages) == 100
        assert queryTime < 1.0


class TestChatUserPerformance:
    """Performance tests for chat user operations."""

    @pytest.mark.asyncio
    async def test_chat_user_upsert_performance(self, db):
        """Test chat user upsert performance."""
        repo = db.chatUsers

        # Upsert 1000 users
        start = time.time()
        for i in range(1000):
            await repo.updateChatUser(
                chatId=100,
                userId=i,
                username=f"@user{i}",
                firstName=f"User {i}",
            )
        upsertTime = time.time() - start

        print(f"Chat User Upsert: {upsertTime:.3f}s")
        assert upsertTime < 10.0

    @pytest.mark.asyncio
    async def test_chat_user_query_performance(self, db):
        """Test chat user query performance."""
        repo = db.chatUsers

        # Insert 1000 users
        for i in range(1000):
            await repo.updateChatUser(
                chatId=100,
                userId=i,
                username=f"@user{i}",
                firstName=f"User {i}",
            )

        # Query all users
        start = time.time()
        users = await repo.getChatUsers(100)
        queryTime = time.time() - start

        print(f"Chat User Query: {queryTime:.3f}s")
        assert len(users) == 1000
        assert queryTime < 5.0


class TestUpsertPerformance:
    """Performance tests for upsert operations."""

    @pytest.mark.asyncio
    async def test_upsert_insert_performance(self, db):
        """Test upsert insert performance."""
        provider = await db.manager.getProvider(readonly=False)

        # Create test table
        await provider.execute("CREATE TABLE test_upsert (id INTEGER PRIMARY KEY, name TEXT, value INTEGER)")

        # Insert 1000 records
        start = time.time()
        for i in range(1000):
            await provider.upsert(
                table="test_upsert",
                values={"id": i, "name": f"test{i}", "value": i},
                conflictColumns=["id"],
            )
        insertTime = time.time() - start

        print(f"Upsert Insert: {insertTime:.3f}s")
        assert insertTime < 10.0

    @pytest.mark.asyncio
    async def test_upsert_update_performance(self, db):
        """Test upsert update performance."""
        provider = await db.manager.getProvider(readonly=False)

        # Create test table
        await provider.execute("CREATE TABLE test_upsert (id INTEGER PRIMARY KEY, name TEXT, value INTEGER)")

        # Insert initial records
        for i in range(1000):
            await provider.upsert(
                table="test_upsert",
                values={"id": i, "name": f"test{i}", "value": i},
                conflictColumns=["id"],
            )

        # Update all records
        start = time.time()
        for i in range(1000):
            await provider.upsert(
                table="test_upsert",
                values={"id": i, "name": f"updated{i}", "value": i * 2},
                conflictColumns=["id"],
            )
        updateTime = time.time() - start

        print(f"Upsert Update: {updateTime:.3f}s")
        assert updateTime < 10.0


class TestBatchPerformance:
    """Performance tests for batch operations."""

    @pytest.mark.asyncio
    async def test_batch_insert_performance(self, db):
        """Test batch insert performance."""
        provider = await db.manager.getProvider(readonly=False)

        # Create test table
        await provider.execute("CREATE TABLE test_batch (id INTEGER PRIMARY KEY, name TEXT)")

        # Prepare batch queries
        from internal.database.providers.base import ParametrizedQuery

        queries = [
            ParametrizedQuery("INSERT INTO test_batch (id, name) VALUES (:id, :name)", {"id": i, "name": f"test{i}"})
            for i in range(1000)
        ]

        # Execute batch
        start = time.time()
        await provider.batchExecute(queries)
        batchTime = time.time() - start

        print(f"Batch Insert: {batchTime:.3f}s")
        assert batchTime < 10.0

    @pytest.mark.asyncio
    async def test_batch_vs_individual_performance(self, db):
        """Compare batch vs individual insert performance."""
        provider = await db.manager.getProvider(readonly=False)

        # Create test tables
        await provider.execute("CREATE TABLE test_individual (id INTEGER PRIMARY KEY, name TEXT)")
        await provider.execute("CREATE TABLE test_batch (id INTEGER PRIMARY KEY, name TEXT)")

        # Individual inserts
        start = time.time()
        for i in range(100):
            await provider.execute(
                "INSERT INTO test_individual (id, name) VALUES (:id, :name)", {"id": i, "name": f"test{i}"}
            )
        individualTime = time.time() - start

        # Batch inserts
        from internal.database.providers.base import ParametrizedQuery

        queries = [
            ParametrizedQuery("INSERT INTO test_batch (id, name) VALUES (:id, :name)", {"id": i, "name": f"test{i}"})
            for i in range(100)
        ]

        start = time.time()
        await provider.batchExecute(queries)
        batchTime = time.time() - start

        print(f"Individual Insert: {individualTime:.3f}s, Batch Insert: {batchTime:.3f}s")
        print(f"Batch is {individualTime / batchTime:.2f}x faster")

        # Batch should be faster (or at least not significantly slower)
        assert batchTime < individualTime * 2


class TestComplexQueryPerformance:
    """Performance tests for complex queries."""

    @pytest.mark.asyncio
    async def test_join_query_performance(self, db):
        """Test join query performance."""
        # Insert test data
        for i in range(100):
            await db.chatUsers.updateChatUser(
                chatId=100,
                userId=i,
                username=f"@user{i}",
                firstName=f"User {i}",
            )
            await db.chatMessages.saveChatMessage(
                chatId=100,
                userId=i,
                messageId=i,
                messageText=f"Message {i}",
                date="2024-01-01T00:00:00",
            )

        # Query with join (simulated by getting users and messages)
        start = time.time()
        users = await db.chatUsers.getChatUsers(100)
        messages = await db.chatMessages.getChatMessages(100)
        queryTime = time.time() - start

        print(f"Join-like Query: {queryTime:.3f}s")
        assert len(users) == 100
        assert len(messages) == 100
        assert queryTime < 5.0

    @pytest.mark.asyncio
    async def test_aggregation_query_performance(self, db):
        """Test aggregation query performance."""
        # Insert test data
        for i in range(1000):
            await db.chatMessages.saveChatMessage(
                chatId=100,
                userId=i % 10,  # 10 different users
                messageId=i,
                messageText=f"Message {i}",
                date="2024-01-01T00:00:00",
            )

        # Count messages
        start = time.time()
        messages = await db.chatMessages.getChatMessages(100)
        count = len(messages)
        queryTime = time.time() - start

        print(f"Aggregation Query: {queryTime:.3f}s, Count: {count}")
        assert count == 1000
        assert queryTime < 5.0
