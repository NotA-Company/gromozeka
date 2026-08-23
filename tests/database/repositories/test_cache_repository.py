"""
Tests for cache repository.

This module tests the CacheRepository class including:
- Cache storage operations (set, get, unset)
- Cache entry operations with TTL
- Cache clearing operations
"""

import datetime

import pytest

from internal.database import Database
from internal.database import utils as dbUtils
from internal.database.models import CacheType
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


class TestCacheEntry:
    """Tests for cache entry operations with TTL."""

    @pytest.mark.asyncio
    async def test_set_cache_entry(self, db):
        """Test setting cache entry."""
        repo = db.cache
        result = await repo.setCacheEntry("key1", "data1", CacheType.WEATHER)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_cache_entry(self, db):
        """Test getting cache entry."""
        repo = db.cache

        # Set cache entry
        await repo.setCacheEntry("key1", "data1", CacheType.WEATHER)

        # Get it
        entry = await repo.getCacheEntry("key1", CacheType.WEATHER)
        assert entry is not None
        assert entry["key"] == "key1"
        assert entry["data"] == "data1"

    @pytest.mark.asyncio
    async def test_cache_entry_ttl(self, db):
        """Test cache entry with TTL."""
        repo = db.cache

        # Set cache entry
        await repo.setCacheEntry("key1", "data1", CacheType.WEATHER)

        # Should return entry (TTL not expired)
        entry = await repo.getCacheEntry("key1", CacheType.WEATHER, ttl=3600)
        assert entry is not None

        # Should not return entry (TTL expired)
        entry = await repo.getCacheEntry("key1", CacheType.WEATHER, ttl=-1)
        assert entry is None

    @pytest.mark.asyncio
    async def test_cache_entry_different_types(self, db):
        """Test cache entries with different types."""
        repo = db.cache

        # Set entries with different types
        await repo.setCacheEntry("key1", "data1", CacheType.WEATHER)
        await repo.setCacheEntry("key1", "data2", CacheType.GEOCODING)

        # Get by type
        weatherEntry = await repo.getCacheEntry("key1", CacheType.WEATHER)
        geocodeEntry = await repo.getCacheEntry("key1", CacheType.GEOCODING)

        assert weatherEntry is not None
        assert weatherEntry["data"] == "data1"
        assert geocodeEntry is not None
        assert geocodeEntry["data"] == "data2"

    @pytest.mark.asyncio
    async def test_clear_cache_by_type(self, db):
        """Test clearing cache by type."""
        repo = db.cache

        # Set entries with different types
        await repo.setCacheEntry("key1", "data1", CacheType.WEATHER)
        await repo.setCacheEntry("key2", "data2", CacheType.WEATHER)
        await repo.setCacheEntry("key1", "data3", CacheType.GEOCODING)

        # Clear weather entries
        await repo.clearCache(CacheType.WEATHER)

        # Verify only geocode entries remain
        weatherEntry = await repo.getCacheEntry("key1", CacheType.WEATHER)
        geocodeEntry = await repo.getCacheEntry("key1", CacheType.GEOCODING)

        assert weatherEntry is None
        assert geocodeEntry is not None


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
    async def test_cache_entry_with_json_data(self, db):
        """Test cache entry with JSON data."""
        repo = db.cache

        # Set JSON data
        jsonData = '{"key": "value", "number": 123}'
        await repo.setCacheEntry("key1", jsonData, CacheType.WEATHER)

        # Get and verify
        entry = await repo.getCacheEntry("key1", CacheType.WEATHER)
        assert entry is not None
        assert entry["data"] == jsonData

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

    @pytest.mark.asyncio
    async def test_cache_entry_with_special_characters(self, db):
        """Test cache entry with special characters."""
        repo = db.cache

        # Set data with special characters
        specialData = "test with 'quotes' and \"double quotes\" and \n newlines"
        await repo.setCacheEntry("key1", specialData, CacheType.WEATHER)

        # Get and verify
        entry = await repo.getCacheEntry("key1", CacheType.WEATHER)
        assert entry is not None
        assert entry["data"] == specialData


class TestClearOldCacheEntries:
    """Tests for CacheRepository.clearOldCacheEntries.

    Covers the age-based purge logic: default all-namespace sweep, per-namespace
    aggressive TTL, ttl=0 nukes, recent-entry survival, and the bool return value.
    """

    @pytest.mark.asyncio
    async def testDefaultTtlSweepAllNamespaces(self, db):
        """Default 365-day sweep purges old entries across every namespace.

        Args:
            db: In-memory Database fixture.
        """
        repo = db.cache

        # Insert entries in two namespaces
        await repo.setCacheEntry("oldWeather", "data1", CacheType.WEATHER)
        await repo.setCacheEntry("oldGeocoding", "data2", CacheType.GEOCODING)
        await repo.setCacheEntry("recentWeather", "data3", CacheType.WEATHER)

        # Back-date two of them beyond 365 days
        provider = await db.manager.getProvider()
        pastTimestamp = dbUtils.getCurrentTimestamp() - datetime.timedelta(days=400)
        await provider.execute(
            "UPDATE cache SET updated_at = :ts WHERE key IN ('oldWeather', 'oldGeocoding')",
            {"ts": pastTimestamp},
        )

        result = await repo.clearOldCacheEntries(ttl=365 * 86400)

        assert result is True
        assert await repo.getCacheEntry("oldWeather", CacheType.WEATHER) is None
        assert await repo.getCacheEntry("oldGeocoding", CacheType.GEOCODING) is None
        assert await repo.getCacheEntry("recentWeather", CacheType.WEATHER) is not None

    @pytest.mark.asyncio
    async def testSpecificNamespaceAggressiveTtl(self, db):
        """Aggressive per-namespace TTL only touches the named namespace.

        Args:
            db: In-memory Database fixture.
        """
        repo = db.cache

        # Insert entries in two namespaces
        await repo.setCacheEntry("key1", "data1", CacheType.WEATHER)
        await repo.setCacheEntry("key2", "data2", CacheType.GEOCODING)

        # Back-date both beyond 7 days
        provider = await db.manager.getProvider()
        pastTimestamp = dbUtils.getCurrentTimestamp() - datetime.timedelta(days=10)
        await provider.execute("UPDATE cache SET updated_at = :ts", {"ts": pastTimestamp})

        result = await repo.clearOldCacheEntries(ttl=7 * 86400, cacheType=CacheType.WEATHER)

        assert result is True
        assert await repo.getCacheEntry("key1", CacheType.WEATHER) is None
        assert await repo.getCacheEntry("key2", CacheType.GEOCODING) is not None

    @pytest.mark.asyncio
    async def testTtlZeroDeletesEverything(self, db):
        """ttl=0 (or None) removes every entry regardless of namespace.

        Args:
            db: In-memory Database fixture.
        """
        repo = db.cache

        await repo.setCacheEntry("key1", "data1", CacheType.WEATHER)
        await repo.setCacheEntry("key2", "data2", CacheType.GEOCODING)
        await repo.setCacheEntry("key3", "data3", CacheType.YANDEX_SEARCH)

        result = await repo.clearOldCacheEntries(ttl=0)

        assert result is True
        assert await repo.getCacheEntry("key1", CacheType.WEATHER) is None
        assert await repo.getCacheEntry("key2", CacheType.GEOCODING) is None
        assert await repo.getCacheEntry("key3", CacheType.YANDEX_SEARCH) is None

    @pytest.mark.asyncio
    async def testRecentEntriesSurviveAggressiveTtl(self, db):
        """Entries younger than the aggressive TTL threshold survive.

        Args:
            db: In-memory Database fixture.
        """
        repo = db.cache

        await repo.setCacheEntry("key1", "data1", CacheType.WEATHER)

        # Back-date to 3 days — within the 7-day aggressive window
        provider = await db.manager.getProvider()
        recentTimestamp = dbUtils.getCurrentTimestamp() - datetime.timedelta(days=3)
        await provider.execute("UPDATE cache SET updated_at = :ts", {"ts": recentTimestamp})

        result = await repo.clearOldCacheEntries(ttl=7 * 86400, cacheType=CacheType.WEATHER)

        assert result is True
        assert await repo.getCacheEntry("key1", CacheType.WEATHER) is not None

    @pytest.mark.asyncio
    async def testReturnsTrueOnSuccess(self, db):
        """clearOldCacheEntries returns True on a successful no-op sweep.

        Args:
            db: In-memory Database fixture.
        """
        repo = db.cache

        result = await repo.clearOldCacheEntries(ttl=365 * 86400)

        assert result is True
