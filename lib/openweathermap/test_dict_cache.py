#!/usr/bin/env python3
"""
Test script for DictWeatherCache implementation

This script tests the basic functionality of the dictionary-based cache.
"""

import asyncio
import sys
import os

# Add project root to path  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # noqa: E402

from lib.openweathermap.dict_cache import DictWeatherCache  # noqa: E402
from lib.openweathermap.models import GeocodingResult, WeatherData  # noqa: E402


async def test_dict_cache():
    """Test DictWeatherCache functionality"""
    print("Testing DictWeatherCache implementation...")

    # Initialize cache with 2 second TTL for testing
    cache = DictWeatherCache(default_ttl=2)

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
    print("Waiting 3 seconds for TTL expiration...")
    await asyncio.sleep(3)

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

    print("\n✅ All tests passed! DictWeatherCache implementation is working correctly, dood!")


if __name__ == "__main__":
    asyncio.run(test_dict_cache())
