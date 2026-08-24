"""
Tests for cache repository.

This module tests the CacheRepository class including:
- Cache storage operations (set, get, unset)
- Cache data type handling for storage
"""

import pytest

from internal.database import Database
from lib.db.manager import DatabaseManagerConfig


@pytest.fixture
async def db():
    """Create a database instance for testing."""
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


class TestCacheStorage:
    """Tests for cache storage operations."""

    @pytest.mark.asyncio
    async def test_set_cache_storage(self, db):
        """Test cache storage upsert."""
        repo = db.cache
        result = await repo.setCacheStorage("test", "key1", "value1")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_cache_storage(self, db):
        """Test getting cache storage entries."""
        repo = db.cache

        # Set cache entries
        await repo.setCacheStorage("test", "key1", "value1")
        await repo.setCacheStorage("test", "key2", "value2")

        # Get all entries
        entries = await repo.getCacheStorage()
        assert len(entries) == 2
        assert entries[0]["namespace"] == "test"
        assert entries[0]["key"] in ["key1", "key2"]

    @pytest.mark.asyncio
    async def test_unset_cache_storage(self, db):
        """Test deleting cache storage entry."""
        repo = db.cache

        # Set cache entry
        await repo.setCacheStorage("test", "key1", "value1")

        # Verify it exists
        entries = await repo.getCacheStorage()
        assert len(entries) == 1

        # Delete it
        result = await repo.unsetCacheStorage("test", "key1")
        assert result is True

        # Verify it's gone
        entries = await repo.getCacheStorage()
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_update_cache_storage(self, db):
        """Test updating cache storage entry."""
        repo = db.cache

        # Set initial value
        await repo.setCacheStorage("test", "key1", "value1")

        # Update it
        await repo.setCacheStorage("test", "key1", "value2")

        # Verify updated value
        entries = await repo.getCacheStorage()
        assert len(entries) == 1
        assert entries[0]["value"] == "value2"


class TestCacheDataTypes:
    """Tests for cache data type handling."""

    @pytest.mark.asyncio
    async def test_cache_storage_with_json_data(self, db):
        """Test cache storage with JSON data."""
        repo = db.cache

        # Set JSON data
        jsonData = '{"key": "value", "number": 123}'
        await repo.setCacheStorage("test", "key1", jsonData)

        # Get and verify
        entries = await repo.getCacheStorage()
        assert len(entries) == 1
        assert entries[0]["value"] == jsonData

    @pytest.mark.asyncio
    async def test_cache_storage_with_special_characters(self, db):
        """Test cache storage with special characters."""
        repo = db.cache

        # Set data with special characters
        specialData = "test with 'quotes' and \"double quotes\" and \n newlines"
        await repo.setCacheStorage("test", "key1", specialData)

        # Get and verify
        entries = await repo.getCacheStorage()
        assert len(entries) == 1
        assert entries[0]["value"] == specialData
