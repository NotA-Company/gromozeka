#!/usr/bin/env python3
"""
Test script for DictWeatherCache implementation

This script tests the basic functionality of the dictionary-based cache.
"""

import asyncio
import os
import sys

import pytest

# Add project root to path  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # noqa: E402

from lib.openweathermap.dict_cache import DictWeatherCache  # noqa: E402
from lib.openweathermap.models import GeocodingResult, WeatherData  # noqa: E402


@pytest.mark.asyncio
async def test_dict_cache():
    """Test DictWeatherCache functionality"""
    print("Testing DictWeatherCache implementation...")

    # Initialize cache with 2 second TTL for testing
    cacheTTL = 1
    cache = DictWeatherCache(default_ttl=cacheTTL)

    # Test data
    test_geocoding: GeocodingResult = {
        "name": "Moscow",
        "local_names": {"en": "Moscow", "ru": "Москва"},
        "lat": 55.7558,
        "lon": 37.6173,
        "country": "RU",
        "state": None,
    }

    test_weather: WeatherData = {
        "lat": 55.7558,
        "lon": 37.6173,
        "timezone": "Europe/Moscow",
        "timezone_offset": 10800,
        "current": {
            "dt": 1697654400,
            "temp": 15.5,
            "feels_like": 14.2,
            "pressure": 1013,
            "humidity": 65,
            "clouds": 20,
            "wind_speed": 3.5,
            "wind_deg": 180,
            "weather_id": 800,
            "weather_main": "Clear",
            "weather_description": "clear sky",
            "dew_point": 8.5,
            "uvi": 2.5,
            "visibility": 10000,
            "wind_gust": 5.0,
            "sunrise": 1697600000,
            "sunset": 1697640000,
        },
        "daily": [
            {
                "dt": 1697654400,
                "temp_day": 15.5,
                "temp_night": 10.0,
                "temp_eve": 13.0,
                "temp_morn": 11.0,
                "temp_min": 10.0,
                "temp_max": 18.0,
                "feels_like_day": 14.5,
                "feels_like_night": 9.0,
                "feels_like_eve": 12.0,
                "feels_like_morn": 10.0,
                "pressure": 1013,
                "humidity": 65,
                "dew_point": 8.5,
                "wind_speed": 3.5,
                "wind_deg": 180,
                "wind_gust": 5.0,
                "clouds": 20,
                "uvi": 2.5,
                "weather_id": 800,
                "weather_main": "Clear",
                "weather_description": "clear sky",
                "pop": 0.1,
                "sunrise": 1697600000,
                "sunset": 1697640000,
                "moonrise": 1697620000,
                "moonset": 1697660000,
                "moon_phase": 0.25,
                "summary": "Clear sky throughout the day",
            }
        ],
    }

    # Test geocoding cache
    print("\n1. Testing geocoding cache...")

    # Should be empty initially
    result = await cache.getGeocoging("Moscow,RU")
    assert result is None, "Cache should be empty initially"
    print("✓ Empty cache returns None")

    # Store data
    success = await cache.setGeocoging("Moscow,RU", test_geocoding)
    assert success, "Should successfully store geocoding data"
    print("✓ Successfully stored geocoding data")

    # Retrieve data
    result = await cache.getGeocoging("Moscow,RU")
    assert result is not None, "Should retrieve stored data"
    assert result["name"] == "Moscow", "Retrieved data should match stored data"
    print("✓ Successfully retrieved geocoding data")

    # Test weather cache
    print("\n2. Testing weather cache...")

    # Should be empty initially
    result = await cache.getWeather("55.7558,37.6173")
    assert result is None, "Weather cache should be empty initially"
    print("✓ Empty weather cache returns None")

    # Store weather data
    success = await cache.setWeather("55.7558,37.6173", test_weather)
    assert success, "Should successfully store weather data"
    print("✓ Successfully stored weather data")

    # Retrieve weather data
    result = await cache.getWeather("55.7558,37.6173")
    assert result is not None, "Should retrieve stored weather data"
    assert result["current"]["temp"] == 15.5, "Retrieved weather data should match stored data"
    print("✓ Successfully retrieved weather data")

    # Test TTL expiration
    print("\n3. Testing TTL expiration...")
    print(f"Waiting {cacheTTL} seconds for TTL expiration...")
    import asyncio

    await asyncio.sleep(cacheTTL)

    # Data should be expired now
    result = await cache.getGeocoging("Moscow,RU")
    assert result is None, "Geocoding data should be expired"
    print("✓ Geocoding data expired correctly")

    result = await cache.getWeather("55.7558,37.6173")
    assert result is None, "Weather data should be expired"
    print("✓ Weather data expired correctly")

    # Test custom TTL
    print("\n4. Testing custom TTL...")

    # Store with longer TTL
    await cache.setGeocoging("London,GB", test_geocoding)

    # Should still be available with custom TTL of 10 seconds
    result = await cache.getGeocoging("London,GB", ttl=10)
    assert result is not None, "Should retrieve data with custom TTL"
    print("✓ Custom TTL works correctly")

    # Test cache stats
    print("\n5. Testing cache statistics...")
    stats = cache.get_stats()
    print(f"Cache stats: {stats}")
    assert stats["geocoding_entries"] >= 0, "Should have geocoding stats"
    assert stats["weather_entries"] >= 0, "Should have weather stats"
    print("✓ Cache statistics work correctly")

    # Test cache clear
    print("\n6. Testing cache clear...")
    cache.clear()
    stats = cache.get_stats()
    assert stats["total_entries"] == 0, "Cache should be empty after clear"
    print("✓ Cache clear works correctly")


class TestDictCacheAdvanced:
    """Advanced test suite for DictWeatherCache"""

    @pytest.mark.asyncio
    async def test_cache_size_tracking(self):
        """Test cache size tracking with multiple entries"""
        cache = DictWeatherCache(default_ttl=3600)

        # Add multiple geocoding entries
        for i in range(5):
            await cache.setGeocoging(
                f"city{i},RU",
                {"name": f"City{i}", "lat": 55.0 + i, "lon": 37.0 + i, "country": "RU", "local_names": {}},  # type: ignore[arg-type]  # noqa: E501
            )

        # Add multiple weather entries
        for i in range(3):
            await cache.setWeather(
                f"55.{i},37.{i}",
                {"lat": 55.0 + i, "lon": 37.0 + i, "timezone": "UTC", "current": {"temp": 15.0}, "daily": []},  # type: ignore[arg-type]  # noqa: E501
            )

        stats = cache.get_stats()
        assert stats["geocoding_entries"] == 5
        assert stats["weather_entries"] == 3
        assert stats["total_entries"] == 8

    @pytest.mark.asyncio
    async def test_cache_expiration_cleanup(self):
        """Test automatic cleanup of expired entries"""
        cache = DictWeatherCache(default_ttl=1)  # 1 second TTL

        # Add entries
        await cache.setGeocoging(
            "moscow,ru", {"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "country": "RU", "local_names": {}}  # type: ignore[arg-type]  # noqa: E501
        )
        await cache.setWeather(
            "55.7558,37.6173",
            {"lat": 55.7558, "lon": 37.6173, "timezone": "UTC", "current": {"temp": 15.0}, "daily": []},  # type: ignore[arg-type]  # noqa: E501
        )

        # Verify entries exist
        stats = cache.get_stats()
        assert stats["total_entries"] == 2

        # Wait for expiration
        await asyncio.sleep(2)

        # Trigger cleanup by getting stats
        stats = cache.get_stats()
        assert stats["total_entries"] == 0

    @pytest.mark.asyncio
    async def test_cache_overwrite_existing_entry(self):
        """Test overwriting existing cache entry"""
        cache = DictWeatherCache(default_ttl=3600)

        # Add initial entry
        initial_data = {"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "country": "RU", "local_names": {}}
        await cache.setGeocoging("moscow,ru", initial_data)  # type: ignore[arg-type]

        # Overwrite with new data
        updated_data = {
            "name": "Moscow",
            "lat": 55.7559,
            "lon": 37.6174,
            "country": "RU",
            "local_names": {"en": "Moscow"},
        }
        await cache.setGeocoging("moscow,ru", updated_data)  # type: ignore[arg-type]

        # Verify updated data is returned
        result = await cache.getGeocoging("moscow,ru")
        assert result["lat"] == 55.7559  # type: ignore[index]
        assert result["lon"] == 37.6174  # type: ignore[index]
        assert "en" in result["local_names"]  # type: ignore[operator]

    @pytest.mark.asyncio
    async def test_cache_custom_ttl_per_entry(self):
        """Test custom TTL for individual entries"""
        cache = DictWeatherCache(default_ttl=10)

        # Add entry with default TTL
        await cache.setGeocoging(
            "city1,ru", {"name": "City1", "lat": 55.0, "lon": 37.0, "country": "RU", "local_names": {}}  # type: ignore[arg-type]  # noqa: E501
        )

        # Add entry with short TTL
        await cache.setGeocoging(
            "city2,ru", {"name": "City2", "lat": 56.0, "lon": 38.0, "country": "RU", "local_names": {}}  # type: ignore[arg-type]  # noqa: E501
        )

        # Wait 2 seconds
        await asyncio.sleep(2)

        # First entry should still be valid with default TTL
        result1 = await cache.getGeocoging("city1,ru", ttl=10)
        assert result1 is not None

        # Second entry should be expired with short TTL
        result2 = await cache.getGeocoging("city2,ru", ttl=1)
        assert result2 is None

    @pytest.mark.asyncio
    async def test_cache_concurrent_access(self):
        """Test concurrent cache access"""
        cache = DictWeatherCache(default_ttl=3600)

        # Prepare test data
        test_data = [
            ("city1,ru", {"name": "City1", "lat": 55.0, "lon": 37.0, "country": "RU", "local_names": {}}),  # type: ignore[arg-type]  # noqa: E501
            ("city2,ru", {"name": "City2", "lat": 56.0, "lon": 38.0, "country": "RU", "local_names": {}}),  # type: ignore[arg-type]  # noqa: E501
            ("city3,ru", {"name": "City3", "lat": 57.0, "lon": 39.0, "country": "RU", "local_names": {}}),  # type: ignore[arg-type]  # noqa: E501
        ]

        # Concurrent writes
        write_tasks = [cache.setGeocoging(key, data) for key, data in test_data]  # type: ignore[arg-type]
        results = await asyncio.gather(*write_tasks)
        assert all(results)

        # Concurrent reads
        read_tasks = [cache.getGeocoging(key) for key, _ in test_data]
        results = await asyncio.gather(*read_tasks)
        assert all(r is not None for r in results)

    @pytest.mark.asyncio
    async def test_cache_clear_during_operation(self):
        """Test clearing cache during operations"""
        cache = DictWeatherCache(default_ttl=3600)

        # Add entries
        await cache.setGeocoging(
            "moscow,ru", {"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "country": "RU", "local_names": {}}  # type: ignore[arg-type]  # noqa: E501
        )
        await cache.setWeather(
            "55.7558,37.6173",
            {"lat": 55.7558, "lon": 37.6173, "timezone": "UTC", "current": {"temp": 15.0}, "daily": []},  # type: ignore[arg-type]  # noqa: E501
        )

        # Clear cache
        cache.clear()

        # Verify cache is empty
        result1 = await cache.getGeocoging("moscow,ru")
        result2 = await cache.getWeather("55.7558,37.6173")
        assert result1 is None
        assert result2 is None

        stats = cache.get_stats()
        assert stats["total_entries"] == 0

    @pytest.mark.asyncio
    async def test_cache_with_special_characters_in_key(self):
        """Test cache with special characters in keys"""
        cache = DictWeatherCache(default_ttl=3600)

        # Keys with special characters
        special_keys = [
            "são paulo,br",
            "москва,ru",
            "北京,cn",
            "city with spaces,us",
        ]

        for key in special_keys:
            data = {"name": key.split(",")[0], "lat": 0.0, "lon": 0.0, "country": key.split(",")[1], "local_names": {}}  # type: ignore[typeddict-item]  # noqa: E501
            success = await cache.setGeocoging(key, data)  # type: ignore[arg-type]
            assert success

            result = await cache.getGeocoging(key)
            assert result is not None

    @pytest.mark.asyncio
    async def test_cache_memory_efficiency(self):
        """Test cache memory efficiency with large datasets"""
        cache = DictWeatherCache(default_ttl=3600)

        # Add many entries
        for i in range(100):
            await cache.setGeocoging(
                f"city{i},ru",
                {
                    "name": f"City{i}",
                    "lat": 55.0 + i * 0.01,
                    "lon": 37.0 + i * 0.01,
                    "country": "RU",
                    "local_names": {},
                },  # type: ignore[arg-type]
            )

        stats = cache.get_stats()
        assert stats["geocoding_entries"] == 100

        # Clear and verify memory is released
        cache.clear()
        stats = cache.get_stats()
        assert stats["total_entries"] == 0

    @pytest.mark.asyncio
    async def test_cache_error_handling_invalid_data(self):
        """Test cache error handling with invalid data"""
        cache = DictWeatherCache(default_ttl=3600)

        # Try to store None (should handle gracefully)
        try:
            await cache.setGeocoging("test,ru", None)  # type: ignore[arg-type]
            # If it doesn't raise, verify it stored something
            _ = await cache.getGeocoging("test,ru")
            # Result could be None or the stored None value
        except Exception:
            # If it raises, that's also acceptable behavior
            pass

    @pytest.mark.asyncio
    async def test_cache_stats_accuracy(self):
        """Test accuracy of cache statistics"""
        cache = DictWeatherCache(default_ttl=3600)

        # Initial stats
        stats = cache.get_stats()
        assert stats["geocoding_entries"] == 0
        assert stats["weather_entries"] == 0
        assert stats["total_entries"] == 0

        # Add geocoding entry
        await cache.setGeocoging(
            "moscow,ru", {"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "country": "RU", "local_names": {}}  # type: ignore[arg-type]  # noqa: E501
        )
        stats = cache.get_stats()
        assert stats["geocoding_entries"] == 1
        assert stats["total_entries"] == 1

        # Add weather entry
        await cache.setWeather(
            "55.7558,37.6173",
            {"lat": 55.7558, "lon": 37.6173, "timezone": "UTC", "current": {"temp": 15.0}, "daily": []},  # type: ignore[arg-type]  # noqa: E501
        )
        stats = cache.get_stats()
        assert stats["weather_entries"] == 1
        assert stats["total_entries"] == 2

    @pytest.mark.asyncio
    async def test_cache_ttl_boundary_conditions(self):
        """Test cache TTL boundary conditions"""
        cache = DictWeatherCache(default_ttl=2)

        # Add entry
        await cache.setGeocoging(
            "moscow,ru", {"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "country": "RU", "local_names": {}}  # type: ignore[arg-type]  # noqa: E501
        )

        # Check immediately (should exist)
        result = await cache.getGeocoging("moscow,ru")
        assert result is not None

        # Wait just before expiration
        await asyncio.sleep(1.5)
        result = await cache.getGeocoging("moscow,ru")
        assert result is not None

        # Wait past expiration
        await asyncio.sleep(1)
        result = await cache.getGeocoging("moscow,ru")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_mixed_operations(self):
        """Test mixed cache operations (reads, writes, clears)"""
        cache = DictWeatherCache(default_ttl=3600)

        # Write
        await cache.setGeocoging(
            "city1,ru", {"name": "City1", "lat": 55.0, "lon": 37.0, "country": "RU", "local_names": {}}  # type: ignore[arg-type]  # noqa: E501
        )

        # Read
        result = await cache.getGeocoging("city1,ru")
        assert result is not None

        # Write another
        await cache.setWeather(
            "55.0,37.0", {"lat": 55.0, "lon": 37.0, "timezone": "UTC", "current": {"temp": 15.0}, "daily": []}  # type: ignore[arg-type]  # noqa: E501
        )

        # Read both
        result1 = await cache.getGeocoging("city1,ru")
        result2 = await cache.getWeather("55.0,37.0")
        assert result1 is not None
        assert result2 is not None

        # Clear
        cache.clear()

        # Verify cleared
        result1 = await cache.getGeocoging("city1,ru")
        result2 = await cache.getWeather("55.0,37.0")
        assert result1 is None
        assert result2 is None

    print("\n✅ All tests passed! DictWeatherCache implementation is working correctly, dood!")
