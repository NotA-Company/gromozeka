"""Tests for GenericDatabaseCache (lib/cache/sql_cache.py).

This module tests the lib/cache SQL implementation including:
- Cache entry operations with TTL
- Cache clearing operations (clear, clearOld)
- Namespace isolation
- str-subclass namespace acceptance
- dataSource routing
- Error-swallow contract
- JSON and special-character values
"""

import datetime
from unittest.mock import AsyncMock, patch

import pytest

from internal.database import Database
from internal.database.models import CacheType
from lib.cache import GenericDatabaseCache
from lib.cache.key_generator import StringKeyGenerator
from lib.cache.value_converter import JsonValueConverter
from lib.db import utils as dbUtils
from lib.db.manager import DatabaseManager, DatabaseManagerConfig


@pytest.fixture
async def cacheManager():
    """Create a database manager with migrations for testing.

    Yields:
        DatabaseManager instance with cache table migrated.
    """
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
    yield db.manager
    await db.manager.closeAll()


@pytest.fixture
async def multiSourceCacheManager():
    """Create a multi-source database manager with migrations for testing.

    Yields:
        DatabaseManager instance with two in-memory sources and cache table migrated.
    """
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            },
            "second": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            },
        },
    }
    db = Database(config)
    # Initialize both sources by getting providers (triggers migration)
    await db.manager.getProvider(dataSource="default")
    await db.manager.getProvider(dataSource="second")
    yield db.manager
    await db.manager.closeAll()


class TestCacheEntry:
    """Tests for cache entry operations with TTL."""

    @pytest.mark.asyncio
    async def test_set_cache_entry(self, cacheManager):
        """Test setting cache entry.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)
        result = await cache.set("key1", "data1")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_cache_entry(self, cacheManager):
        """Test getting cache entry.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        # Set cache entry
        await cache.set("key1", "data1")

        # Get it
        entry = await cache.get("key1")
        assert entry == "data1"

    @pytest.mark.asyncio
    async def test_cache_entry_ttl(self, cacheManager):
        """Test cache entry with TTL.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        # Set cache entry
        await cache.set("key1", "data1")

        # Should return entry (TTL not expired)
        entry = await cache.get("key1", ttl=3600)
        assert entry == "data1"

        # Should not return entry (TTL expired)
        entry = await cache.get("key1", ttl=-1)
        assert entry is None

    @pytest.mark.asyncio
    async def test_cache_entry_different_namespaces(self, cacheManager):
        """Test cache entries with different namespaces.

        Args:
            cacheManager: Database manager fixture.
        """
        weatherCache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)
        geocodeCache = GenericDatabaseCache(cacheManager, namespace=CacheType.GEOCODING)

        # Set entries with different namespaces
        await weatherCache.set("key1", "data1")
        await geocodeCache.set("key1", "data2")

        # Get by namespace
        weatherEntry = await weatherCache.get("key1")
        geocodeEntry = await geocodeCache.get("key1")

        assert weatherEntry == "data1"
        assert geocodeEntry == "data2"

    @pytest.mark.asyncio
    async def test_clear_cache_by_namespace(self, cacheManager):
        """Test clearing cache by namespace.

        Args:
            cacheManager: Database manager fixture.
        """
        weatherCache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)
        geocodeCache = GenericDatabaseCache(cacheManager, namespace=CacheType.GEOCODING)

        # Set entries with different namespaces
        await weatherCache.set("key1", "data1")
        await weatherCache.set("key2", "data2")
        await geocodeCache.set("key1", "data3")

        # Clear weather entries
        await weatherCache.clear()

        # Verify only geocode entries remain
        weatherEntry = await weatherCache.get("key1")
        geocodeEntry = await geocodeCache.get("key1")

        assert weatherEntry is None
        assert geocodeEntry == "data3"


class TestCacheDataTypes:
    """Tests for cache data type handling."""

    @pytest.mark.asyncio
    async def test_cache_entry_with_json_data(self, cacheManager):
        """Test cache entry with JSON data.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        # Set JSON data
        jsonData = {"key": "value", "number": 123}
        await cache.set("key1", jsonData)

        # Get and verify
        entry = await cache.get("key1")
        assert entry == jsonData

    @pytest.mark.asyncio
    async def test_cache_entry_with_special_characters(self, cacheManager):
        """Test cache entry with special characters.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        # Set data with special characters
        specialData = "test with 'quotes' and \"double quotes\" and \n newlines"
        await cache.set("key1", specialData)

        # Get and verify
        entry = await cache.get("key1")
        assert entry == specialData


class TestClearOld:
    """Tests for GenericDatabaseCache.clearOld.

    Covers the age-based purge logic: per-namespace sweep, per-namespace
    aggressive TTL, ttl=0 nukes, recent-entry survival, and the bool return value.
    """

    @pytest.mark.asyncio
    async def test_default_ttl_sweep_all_namespaces(self, cacheManager):
        """Default 365-day sweep purges old entries in this instance's namespace.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER, keyGenerator=StringKeyGenerator())

        # Insert entries
        await cache.set("oldWeather", "data1")
        await cache.set("recentWeather", "data2")

        # Back-date one entry beyond 365 days
        provider = await cacheManager.getProvider()
        pastTimestamp = dbUtils.getCurrentTimestamp() - datetime.timedelta(days=400)
        await provider.execute(
            "UPDATE cache SET updated_at = :ts WHERE key = 'oldWeather' AND namespace = :ns",
            {"ts": pastTimestamp, "ns": CacheType.WEATHER},
        )

        result = await cache.clearOld(ttl=365 * 86400)

        assert result is True
        assert await cache.get("oldWeather") is None
        assert await cache.get("recentWeather") == "data2"

    @pytest.mark.asyncio
    async def test_specific_namespace_aggressive_ttl(self, cacheManager):
        """Aggressive per-namespace TTL only touches that namespace instance.

        Args:
            cacheManager: Database manager fixture.
        """
        weatherCache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)
        geocodeCache = GenericDatabaseCache(cacheManager, namespace=CacheType.GEOCODING)

        # Insert entries in two namespaces
        await weatherCache.set("key1", "data1")
        await geocodeCache.set("key2", "data2")

        # Back-date both beyond 7 days
        provider = await cacheManager.getProvider()
        pastTimestamp = dbUtils.getCurrentTimestamp() - datetime.timedelta(days=10)
        await provider.execute("UPDATE cache SET updated_at = :ts", {"ts": pastTimestamp})

        result = await weatherCache.clearOld(ttl=7 * 86400)

        assert result is True
        assert await weatherCache.get("key1") is None
        assert await geocodeCache.get("key2") == "data2"

    @pytest.mark.asyncio
    async def test_ttl_zero_deletes_everything(self, cacheManager):
        """ttl=0 (or None) removes every entry of this namespace.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        await cache.set("key1", "data1")
        await cache.set("key2", "data2")

        result = await cache.clearOld(ttl=0)

        assert result is True
        assert await cache.get("key1") is None
        assert await cache.get("key2") is None

    @pytest.mark.asyncio
    async def test_ttl_none_deletes_everything(self, cacheManager):
        """ttl=None removes every entry of this namespace (same as ttl=0).

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        await cache.set("key1", "data1")
        await cache.set("key2", "data2")

        result = await cache.clearOld(ttl=None)

        assert result is True
        assert await cache.get("key1") is None
        assert await cache.get("key2") is None

    @pytest.mark.asyncio
    async def test_recent_entries_survive_aggressive_ttl(self, cacheManager):
        """Entries younger than the aggressive TTL threshold survive.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        await cache.set("key1", "data1")

        # Back-date to 3 days — within the 7-day aggressive window
        provider = await cacheManager.getProvider()
        recentTimestamp = dbUtils.getCurrentTimestamp() - datetime.timedelta(days=3)
        await provider.execute(
            "UPDATE cache SET updated_at = :ts WHERE key = 'key1' AND namespace = :ns",
            {"ts": recentTimestamp, "ns": CacheType.WEATHER},
        )

        result = await cache.clearOld(ttl=7 * 86400)

        assert result is True
        assert await cache.get("key1") == "data1"

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, cacheManager):
        """clearOld returns True on a successful no-op sweep.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        result = await cache.clearOld(ttl=365 * 86400)

        assert result is True


class TestParity:
    """Parity regression tests from design doc §4.

    These tests lock in the exact semantics moved from the repository
    to prevent TTL drift and ensure behavior preservation.
    """

    @pytest.mark.asyncio
    async def test_set_get_round_trip_via_generator_converter(self, cacheManager):
        """set → get round-trip through keyGenerator/valueConverter.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(
            cacheManager,
            namespace=CacheType.WEATHER,
            keyGenerator=StringKeyGenerator(),
            valueConverter=JsonValueConverter(),
        )

        # Test with dict value (requires JSON conversion)
        value = {"temp": 20, "humidity": 50}
        result = await cache.set("moscow", value)
        assert result is True

        retrieved = await cache.get("moscow")
        assert retrieved == value

    @pytest.mark.asyncio
    async def test_ttl_hit_and_expired(self, cacheManager):
        """TTL hit (ttl=3600) / expired (row backdated via UPDATE) → None.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER, keyGenerator=StringKeyGenerator())

        await cache.set("key1", "data1")

        # TTL hit - should return value
        entry = await cache.get("key1", ttl=3600)
        assert entry == "data1"

        # Back-date entry to make it expired
        provider = await cacheManager.getProvider()
        pastTimestamp = dbUtils.getCurrentTimestamp() - datetime.timedelta(hours=2)
        await provider.execute(
            "UPDATE cache SET updated_at = :ts WHERE key = 'key1' AND namespace = :ns",
            {"ts": pastTimestamp, "ns": CacheType.WEATHER},
        )

        # TTL expired - should return None
        entry = await cache.get("key1", ttl=3600)
        assert entry is None

    @pytest.mark.asyncio
    async def test_ttl_zero_returns_none_without_querying(self, cacheManager):
        """ttl=0 → None without querying (impossible future entry early-return).

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        # Set an entry
        await cache.set("key1", "data1")

        # ttl=0 should return None immediately without querying
        entry = await cache.get("key1", ttl=0)
        assert entry is None

    @pytest.mark.asyncio
    async def test_namespace_isolation(self, cacheManager):
        """Same key in two namespaces returns each namespace's value.

        Args:
            cacheManager: Database manager fixture.
        """
        weatherCache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)
        geocodeCache = GenericDatabaseCache(cacheManager, namespace=CacheType.GEOCODING)

        await weatherCache.set("key1", "weather_value")
        await geocodeCache.set("key1", "geocode_value")

        assert await weatherCache.get("key1") == "weather_value"
        assert await geocodeCache.get("key1") == "geocode_value"

    @pytest.mark.asyncio
    async def test_clear_namespace_scoped(self, cacheManager):
        """clear() scoped to the instance's own namespace only.

        Args:
            cacheManager: Database manager fixture.
        """
        weatherCache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)
        geocodeCache = GenericDatabaseCache(cacheManager, namespace=CacheType.GEOCODING)

        await weatherCache.set("key1", "data1")
        await weatherCache.set("key2", "data2")
        await geocodeCache.set("key1", "data3")
        await geocodeCache.set("key2", "data4")

        # Clear weather only
        await weatherCache.clear()

        assert await weatherCache.get("key1") is None
        assert await weatherCache.get("key2") is None
        assert await geocodeCache.get("key1") == "data3"
        assert await geocodeCache.get("key2") == "data4"

    @pytest.mark.asyncio
    async def test_clearold_instance_semantics(self, cacheManager):
        """clearOld instance semantics: per-namespace sweep deletes only backdated entries.

        Args:
            cacheManager: Database manager fixture.
        """
        weatherCache = GenericDatabaseCache(
            cacheManager, namespace=CacheType.WEATHER, keyGenerator=StringKeyGenerator()
        )
        geocodeCache = GenericDatabaseCache(
            cacheManager, namespace=CacheType.GEOCODING, keyGenerator=StringKeyGenerator()
        )

        await weatherCache.set("old1", "data1")
        await weatherCache.set("recent1", "data2")
        await geocodeCache.set("old2", "data3")
        await geocodeCache.set("recent2", "data4")

        # Back-date old entries
        provider = await cacheManager.getProvider()
        pastTimestamp = dbUtils.getCurrentTimestamp() - datetime.timedelta(days=400)
        await provider.execute(
            "UPDATE cache SET updated_at = :ts WHERE key IN ('old1', 'old2')",
            {"ts": pastTimestamp},
        )

        # Clear old entries from weather namespace only
        result = await weatherCache.clearOld(ttl=365 * 86400)
        assert result is True

        assert await weatherCache.get("old1") is None
        assert await weatherCache.get("recent1") == "data2"
        # Geocode entries should be untouched
        assert await geocodeCache.get("old2") == "data3"
        assert await geocodeCache.get("recent2") == "data4"

    @pytest.mark.asyncio
    async def test_clearold_shorter_aggressive_ttl(self, cacheManager):
        """Shorter (aggressive) TTL on the same namespace.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER, keyGenerator=StringKeyGenerator())

        await cache.set("old", "data1")
        await cache.set("recent", "data2")

        # Back-date old entry
        provider = await cacheManager.getProvider()
        pastTimestamp = dbUtils.getCurrentTimestamp() - datetime.timedelta(days=10)
        await provider.execute(
            "UPDATE cache SET updated_at = :ts WHERE key = 'old' AND namespace = :ns",
            {"ts": pastTimestamp, "ns": CacheType.WEATHER},
        )

        # Aggressive 7-day TTL
        result = await cache.clearOld(ttl=7 * 86400)
        assert result is True

        assert await cache.get("old") is None
        assert await cache.get("recent") == "data2"

    @pytest.mark.asyncio
    async def test_clearold_ttl_zero_and_none_delete_all(self, cacheManager):
        """clearOld(None) and clearOld(0) delete every namespace entry.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        await cache.set("key1", "data1")
        await cache.set("key2", "data2")

        # Test ttl=0
        result = await cache.clearOld(ttl=0)
        assert result is True
        assert await cache.get("key1") is None
        assert await cache.get("key2") is None

        # Re-populate and test ttl=None
        await cache.set("key3", "data3")
        await cache.set("key4", "data4")

        result = await cache.clearOld(ttl=None)
        assert result is True
        assert await cache.get("key3") is None
        assert await cache.get("key4") is None

    @pytest.mark.asyncio
    async def test_clearold_recent_entries_survive(self, cacheManager):
        """Recent entries survive the sweep.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER, keyGenerator=StringKeyGenerator())

        await cache.set("old", "data1")
        await cache.set("recent", "data2")

        # Back-date old entry
        provider = await cacheManager.getProvider()
        pastTimestamp = dbUtils.getCurrentTimestamp() - datetime.timedelta(days=10)
        await provider.execute(
            "UPDATE cache SET updated_at = :ts WHERE key = 'old' AND namespace = :ns",
            {"ts": pastTimestamp, "ns": CacheType.WEATHER},
        )

        # 7-day TTL - recent should survive
        result = await cache.clearOld(ttl=7 * 86400)
        assert result is True

        assert await cache.get("old") is None
        assert await cache.get("recent") == "data2"

    @pytest.mark.asyncio
    async def test_clearold_true_on_success_including_noop(self, cacheManager):
        """clearOld returns True on success including no-op.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        # No-op sweep on empty cache
        result = await cache.clearOld(ttl=365 * 86400)
        assert result is True

    @pytest.mark.asyncio
    async def test_clearold_false_logged_on_provider_failure(self, cacheManager):
        """clearOld returns False + logged (never raised) on provider failure.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        # Mock provider.execute to raise an exception (class-level patch for __slots__ class)
        with patch.object(
            DatabaseManager,
            "getProvider",
            return_value=AsyncMock(execute=AsyncMock(side_effect=Exception("DB failure"))),
        ):
            result = await cache.clearOld(ttl=365 * 86400)
            assert result is False

    @pytest.mark.asyncio
    async def test_getstats_shape(self, cacheManager):
        """getStats shape: backend="database", namespace as plain str, generator/converter class names.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(
            cacheManager,
            namespace=CacheType.WEATHER,
            keyGenerator=StringKeyGenerator(),
            valueConverter=JsonValueConverter(),
        )

        stats = cache.getStats()

        assert stats["enabled"] is True
        assert stats["namespace"] == CacheType.WEATHER  # Should be plain str
        assert stats["backend"] == "database"
        assert stats["keyGenerator"] == "StringKeyGenerator"
        assert stats["valueConverter"] == "JsonValueConverter"

    @pytest.mark.asyncio
    async def test_str_subclass_namespace_acceptance(self, cacheManager):
        """str-subclass namespace acceptance (proves StrEnum compat).

        Args:
            cacheManager: Database manager fixture.
        """

        # Create a fake str subclass to prove StrEnum compatibility
        class FakeNamespace(str):
            """Fake namespace subclass for testing."""

            pass

        fakeNamespace = FakeNamespace("fake_namespace")
        cache = GenericDatabaseCache(cacheManager, namespace=fakeNamespace)

        # Should work without issues
        result = await cache.set("key1", "data1")
        assert result is True

        entry = await cache.get("key1")
        assert entry == "data1"

    @pytest.mark.asyncio
    async def test_datasource_routing(self, multiSourceCacheManager):
        """Constructor dataSource routing (entries land in the named source).

        Args:
            multiSourceCacheManager: Multi-source database manager fixture.
        """
        # Create two cache instances with different dataSource
        defaultCache = GenericDatabaseCache(multiSourceCacheManager, namespace=CacheType.WEATHER, dataSource="default")
        secondCache = GenericDatabaseCache(multiSourceCacheManager, namespace=CacheType.WEATHER, dataSource="second")

        # Set entry in default source
        result = await defaultCache.set("key1", "data1")
        assert result is True

        # Set entry in second source
        result = await secondCache.set("key2", "data2")
        assert result is True

        # Verify entries land in the named sources
        # Entry in default source should be retrievable via defaultCache
        assert await defaultCache.get("key1") == "data1"
        # Entry in default source should NOT be retrievable via secondCache
        assert await secondCache.get("key1") is None

        # Entry in second source should be retrievable via secondCache
        assert await secondCache.get("key2") == "data2"
        # Entry in second source should NOT be retrievable via defaultCache
        assert await defaultCache.get("key2") is None

    @pytest.mark.asyncio
    async def test_error_swallow_get_returns_none(self, cacheManager):
        """Error-swallow contract: get → None on provider failure.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        # Mock provider.executeFetchOne to raise an exception (class-level patch for __slots__ class)
        with patch.object(
            DatabaseManager,
            "getProvider",
            return_value=AsyncMock(executeFetchOne=AsyncMock(side_effect=Exception("DB failure"))),
        ):
            entry = await cache.get("key1")
            assert entry is None

    @pytest.mark.asyncio
    async def test_error_swallow_set_returns_false(self, cacheManager):
        """Error-swallow contract: set → False on provider failure.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        # Mock provider.upsert to raise an exception (class-level patch for __slots__ class)
        with patch.object(
            DatabaseManager,
            "getProvider",
            return_value=AsyncMock(upsert=AsyncMock(side_effect=Exception("DB failure"))),
        ):
            result = await cache.set("key1", "data1")
            assert result is False

    @pytest.mark.asyncio
    async def test_json_and_special_char_values(self, cacheManager):
        """JSON and special-character values through the converters.

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        # Test JSON value
        jsonValue = {"key": "value", "nested": {"number": 123, "array": [1, 2, 3]}}
        await cache.set("json_key", jsonValue)
        retrieved = await cache.get("json_key")
        assert retrieved == jsonValue

        # Test special characters
        specialValue = "test with 'quotes' and \"double quotes\" and \n newlines and \t tabs"
        await cache.set("special_key", specialValue)
        retrieved = await cache.get("special_key")
        assert retrieved == specialValue

    @pytest.mark.asyncio
    async def test_clearold_negative_ttl_deletes_all(self, cacheManager):
        """Negative TTL deletes everything (legacy SQL behavior parity).

        Args:
            cacheManager: Database manager fixture.
        """
        cache = GenericDatabaseCache(cacheManager, namespace=CacheType.WEATHER)

        await cache.set("key1", "data1")
        await cache.set("key2", "data2")

        # Negative TTL should delete everything (legacy behavior)
        result = await cache.clearOld(ttl=-1)
        assert result is True

        assert await cache.get("key1") is None
        assert await cache.get("key2") is None
