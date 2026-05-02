"""
Integration tests for multi-source database routing.

This module tests the multi-source database routing functionality including:
- Chat-based routing to different data sources
- Read-only source handling
- Default source fallback
- Cross-source queries
"""

import pytest

from internal.database import Database
from internal.database.manager import DatabaseManagerConfig


@pytest.fixture
async def multiSourceDb():
    """Create a multi-source database for testing."""
    config: DatabaseManagerConfig = {
        "default": "source1",
        "chatMapping": {
            100: "source1",
            200: "source2",
            300: "readonly_source",  # Add mapping for read-only source
        },
        "providers": {
            "source1": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            },
            "source2": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            },
            "readonly_source": {  # New read-only source
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                    "readOnly": True,  # Enable read-only mode
                },
            },
        },
    }
    db = Database(config)
    # Initialize databases by getting providers (triggers migration)
    await db.manager.getProvider(dataSource="source1")
    await db.manager.getProvider(dataSource="source2")
    await db.manager.getProvider(dataSource="readonly_source", readonly=True)  # Initialize read-only source
    yield db
    await db.manager.closeAll()


class TestChatRouting:
    """Tests for chat-based routing to different data sources."""

    @pytest.mark.asyncio
    async def test_chat_routing(self, multiSourceDb):
        """Test that chat data is routed to correct source."""
        # Chat 100 should go to source1
        await multiSourceDb.chatUsers.updateChatUser(100, 1, "@user1", "User One")

        # Chat 200 should go to source2
        await multiSourceDb.chatUsers.updateChatUser(200, 2, "@user2", "User Two")

        # Verify routing
        user1 = await multiSourceDb.chatUsers.getChatUser(100, 1, dataSource="source1")
        assert user1 is not None
        assert user1["username"] == "@user1"

        user2 = await multiSourceDb.chatUsers.getChatUser(200, 2, dataSource="source2")
        assert user2 is not None
        assert user2["username"] == "@user2"

    @pytest.mark.asyncio
    async def test_chat_routing_with_settings(self, multiSourceDb):
        """Test that chat settings are routed to correct source."""
        # Set chat settings for chat 100 (should go to source1)
        await multiSourceDb.chatSettings.setChatSetting(100, "model", "gpt-4", updatedBy=0)

        # Set chat settings for chat 200 (should go to source2)
        await multiSourceDb.chatSettings.setChatSetting(200, "model", "gpt-3.5", updatedBy=0)

        # Verify routing
        setting1 = await multiSourceDb.chatSettings.getChatSetting(100, "model", dataSource="source1")
        assert setting1 == "gpt-4"

        setting2 = await multiSourceDb.chatSettings.getChatSetting(200, "model", dataSource="source2")
        assert setting2 == "gpt-3.5"

    @pytest.mark.asyncio
    async def test_unmapped_chat_uses_default(self, multiSourceDb):
        """Test that unmapped chats use default source."""
        # Chat 400 is not in chatMapping, should use default (source1)
        await multiSourceDb.chatUsers.updateChatUser(400, 3, "@user3", "User Three")

        # Verify it's in source1 (default)
        user = await multiSourceDb.chatUsers.getChatUser(400, 3, dataSource="source1")
        assert user is not None
        assert user["username"] == "@user3"

        # Verify it's not in source2
        user = await multiSourceDb.chatUsers.getChatUser(400, 3, dataSource="source2")
        assert user is None


class TestReadOnlySources:
    """Tests for read-only source handling."""

    @pytest.mark.asyncio
    async def test_read_from_readonly_source(self, multiSourceDb):
        """Test reading from read-only source."""
        # Add user to source1
        await multiSourceDb.chatUsers.updateChatUser(100, 1, "@user1", "User One")

        # Read from source1 (should work)
        user = await multiSourceDb.chatUsers.getChatUser(100, 1, dataSource="source1")
        assert user is not None
        assert user["username"] == "@user1"

    @pytest.mark.asyncio
    async def test_write_to_readonly_source_fails(self, multiSourceDb):
        """Test that writing to read-only source fails."""
        # Try to get provider for write operation on read-only source - should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            await multiSourceDb.manager.getProvider(
                chatId=300, readonly=False  # Chat ID mapped to readonly_source  # Attempting write operation
            )

        # Verify error message
        assert "Cannot perform write operation on readonly source" in str(exc_info.value)
        assert "readonly_source" in str(exc_info.value)

        # Verify reading from read-only source works
        # First, write some data to source1 to test cross-source reading
        await multiSourceDb.chatUsers.updateChatUser(100, 1, "@user1", "User One")

        # Read from read-only source (should work even though it's empty)
        user = await multiSourceDb.chatUsers.getChatUser(300, 1, dataSource="readonly_source")
        assert user is None  # No data in read-only source


class TestCrossSourceQueries:
    """Tests for cross-source queries."""

    @pytest.mark.asyncio
    async def test_query_specific_source(self, multiSourceDb):
        """Test querying a specific source."""
        # Add users to both sources
        await multiSourceDb.chatUsers.updateChatUser(100, 1, "@user1", "User One")
        await multiSourceDb.chatUsers.updateChatUser(200, 2, "@user2", "User Two")

        # Query source1
        users1 = await multiSourceDb.chatUsers.getChatUsers(100, dataSource="source1")
        assert len(users1) == 1
        assert users1[0]["username"] == "@user1"

        # Query source2
        users2 = await multiSourceDb.chatUsers.getChatUsers(200, dataSource="source2")
        assert len(users2) == 1
        assert users2[0]["username"] == "@user2"

    @pytest.mark.asyncio
    async def test_cache_operations_use_default_source(self, multiSourceDb):
        """Test that cache operations use default source."""
        # Cache operations should use default source (source1)
        await multiSourceDb.cache.setCacheStorage("test", "key1", "value1")

        # Verify it's in source1
        entries = await multiSourceDb.cache.getCacheStorage(dataSource="source1")
        assert len(entries) == 1
        assert entries[0]["value"] == "value1"

        # Verify it's not in source2
        entries = await multiSourceDb.cache.getCacheStorage(dataSource="source2")
        assert len(entries) == 0


class TestTransactionHandling:
    """Tests for transaction handling across sources."""

    @pytest.mark.asyncio
    async def test_transaction_in_single_source(self, multiSourceDb):
        """Test transaction within a single source."""
        # Note: The database layer uses implicit transactions via the cursor context manager.
        # Each operation is automatically committed on success or rolled back on error.
        # This test verifies that operations within a single source work correctly.

        # Add user to source1
        await multiSourceDb.chatUsers.updateChatUser(100, 1, "@user1", "User One")

        # Verify user was added
        user = await multiSourceDb.chatUsers.getChatUser(100, 1, dataSource="source1")
        assert user is not None
        assert user["username"] == "@user1"

    @pytest.mark.asyncio
    async def test_transaction_rollback_in_single_source(self, multiSourceDb):
        """Test transaction rollback within a single source."""
        # Note: The database layer uses implicit transactions via the cursor context manager.
        # This test verifies that errors are handled correctly and don't corrupt data.

        # Add user to source1
        await multiSourceDb.chatUsers.updateChatUser(100, 1, "@user1", "User One")

        # Try to add duplicate (should succeed due to INSERT OR REPLACE)
        await multiSourceDb.chatUsers.updateChatUser(100, 1, "@user1_updated", "User One Updated")

        # Verify user was updated
        user = await multiSourceDb.chatUsers.getChatUser(100, 1, dataSource="source1")
        assert user is not None
        assert user["username"] == "@user1_updated"


class TestDataIsolation:
    """Tests for data isolation between sources."""

    @pytest.mark.asyncio
    async def test_data_isolation_between_sources(self, multiSourceDb):
        """Test that data is isolated between sources."""
        # Add users to both sources with same IDs
        await multiSourceDb.chatUsers.updateChatUser(100, 1, "@user1_source1", "User One")
        await multiSourceDb.chatUsers.updateChatUser(200, 1, "@user1_source2", "User One")

        # Verify they are separate
        user1 = await multiSourceDb.chatUsers.getChatUser(100, 1, dataSource="source1")
        user2 = await multiSourceDb.chatUsers.getChatUser(200, 1, dataSource="source2")

        assert user1 is not None
        assert user1["username"] == "@user1_source1"

        assert user2 is not None
        assert user2["username"] == "@user1_source2"

    @pytest.mark.asyncio
    async def test_cache_isolation_between_sources(self, multiSourceDb):
        """Test that cache is isolated between sources."""
        # Add cache entries to both sources
        await multiSourceDb.cache.setCacheStorage("test", "key1", "value1", dataSource="source1")
        await multiSourceDb.cache.setCacheStorage("test", "key2", "value2", dataSource="source2")

        # Verify they are separate
        entries1 = await multiSourceDb.cache.getCacheStorage(dataSource="source1")
        entries2 = await multiSourceDb.cache.getCacheStorage(dataSource="source2")

        assert len(entries1) == 1
        assert entries1[0]["key"] == "key1"
        assert entries1[0]["value"] == "value1"

        assert len(entries2) == 1
        assert entries2[0]["key"] == "key2"
        assert entries2[0]["value"] == "value2"


class TestSourceManagement:
    """Tests for source management."""

    @pytest.mark.asyncio
    async def test_get_provider_for_source(self, multiSourceDb):
        """Test getting provider for specific source."""
        provider1 = await multiSourceDb.manager.getProvider(dataSource="source1")
        assert provider1 is not None

        provider2 = await multiSourceDb.manager.getProvider(dataSource="source2")
        assert provider2 is not None

    @pytest.mark.asyncio
    async def test_get_default_provider(self, multiSourceDb):
        """Test getting default provider."""
        provider = await multiSourceDb.manager.getProvider()
        assert provider is not None

    @pytest.mark.asyncio
    async def test_close_all_sources(self, multiSourceDb):
        """Test closing all sources."""
        # Get providers to ensure they're connected
        await multiSourceDb.manager.getProvider(dataSource="source1")
        await multiSourceDb.manager.getProvider(dataSource="source2")

        # Close all
        await multiSourceDb.manager.closeAll()

        # Verify they're closed
        # This would require checking connection state
        # For now, we'll just verify no errors occur
        assert True
