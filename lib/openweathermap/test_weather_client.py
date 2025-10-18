"""
Test suite for OpenWeatherMap client

This module contains comprehensive tests for the OpenWeatherMap client library,
including unit tests for the client, cache, and integration scenarios.
"""

import pytest
import json
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

# Add project root to path for imports
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib.openweathermap.client import OpenWeatherMapClient  # noqa: E402
from internal.database.openweathermap_cache import DatabaseWeatherCache  # noqa: E402
from lib.openweathermap.cache_interface import WeatherCacheInterface  # noqa: E402


class TestOpenWeatherMapClient:
    """Test suite for OpenWeatherMap client"""

    @pytest.fixture
    def mock_cache(self):
        """Mock cache for testing"""
        cache = Mock(spec=WeatherCacheInterface)
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock(return_value=True)
        cache.isExpired = AsyncMock(return_value=True)
        cache.clearExpired = AsyncMock(return_value=0)
        cache.clearAll = AsyncMock(return_value=True)
        return cache

    @pytest.fixture
    def client(self, mock_cache):
        """Create client with mock cache"""
        return OpenWeatherMapClient(
            apiKey="test_key",
            cache=mock_cache,
            geocodingTTL=2592000,
            weatherTTL=1800,
            requestTimeout=10,
            defaultLanguage="ru",
        )

    @pytest.fixture
    def sample_geocoding_response(self):
        """Sample geocoding API response"""
        return [
            {
                "name": "Moscow",
                "local_names": {"ru": "Москва", "en": "Moscow"},
                "lat": 55.7558,
                "lon": 37.6173,
                "country": "RU",
                "state": None,
            }
        ]

    @pytest.fixture
    def sample_weather_response(self):
        """Sample weather API response"""
        return {
            "lat": 55.7558,
            "lon": 37.6173,
            "timezone": "Europe/Moscow",
            "current": {
                "dt": 1697644800,
                "temp": 15.5,
                "feels_like": 14.2,
                "pressure": 1013,
                "humidity": 65,
                "clouds": 40,
                "wind_speed": 3.5,
                "wind_deg": 180,
                "weather": [{"id": 802, "main": "Clouds", "description": "scattered clouds"}],
            },
            "daily": [
                {
                    "dt": 1697644800,
                    "temp": {"day": 15.5, "min": 10.2, "max": 18.3},
                    "pressure": 1013,
                    "humidity": 65,
                    "wind_speed": 3.5,
                    "clouds": 40,
                    "pop": 0.2,
                    "weather": [{"id": 802, "main": "Clouds", "description": "scattered clouds"}],
                }
            ],
        }

    @pytest.mark.asyncio
    async def test_get_coordinates_success(self, client, mock_cache, sample_geocoding_response):
        """Test successful geocoding"""
        # Mock cache miss
        mock_cache.isExpired.return_value = True
        mock_cache.get.return_value = None

        # Mock API response
        with patch.object(client, "_makeRequest", return_value=sample_geocoding_response):
            result = await client.getCoordinates("Moscow", "RU")

        # Verify result
        assert result is not None
        assert result["name"] == "Moscow"
        assert result["lat"] == 55.7558
        assert result["lon"] == 37.6173
        assert result["country"] == "RU"
        assert result["local_names"]["ru"] == "Москва"

        # Verify cache operations
        mock_cache.isExpired.assert_called_once_with("moscow,RU", "geocoding", 2592000)
        mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_coordinates_from_cache(self, client, mock_cache):
        """Test geocoding from cache"""
        # Mock cache hit
        cached_result = {
            "name": "Moscow",
            "local_names": {"ru": "Москва", "en": "Moscow"},
            "lat": 55.7558,
            "lon": 37.6173,
            "country": "RU",
            "state": None,
        }
        mock_cache.isExpired.return_value = False
        mock_cache.get.return_value = json.dumps(cached_result)

        result = await client.getCoordinates("Moscow", "RU")

        # Verify result from cache
        assert result == cached_result

        # Verify no API call was made
        with patch.object(client, "_makeRequest") as mock_request:
            mock_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_coordinates_not_found(self, client, mock_cache):
        """Test geocoding when city not found"""
        # Mock cache miss and empty API response
        mock_cache.isExpired.return_value = True
        mock_cache.get.return_value = None

        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getCoordinates("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_weather_success(self, client, mock_cache, sample_weather_response):
        """Test successful weather fetch"""
        # Mock cache miss
        mock_cache.isExpired.return_value = True
        mock_cache.get.return_value = None

        # Mock API response
        with patch.object(client, "_makeRequest", return_value=sample_weather_response):
            result = await client.getWeather(55.7558, 37.6173)

        # Verify result
        assert result is not None
        assert result["lat"] == 55.7558
        assert result["lon"] == 37.6173
        assert result["timezone"] == "Europe/Moscow"
        assert result["current"]["temp"] == 15.5
        assert result["current"]["weather_description"] == "scattered clouds"
        assert len(result["daily"]) == 1

        # Verify cache operations
        mock_cache.isExpired.assert_called_once_with("55.7558,37.6173", "weather", 1800)
        mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_weather_from_cache(self, client, mock_cache):
        """Test weather from cache"""
        # Mock cache hit
        cached_result = {
            "lat": 55.7558,
            "lon": 37.6173,
            "timezone": "Europe/Moscow",
            "current": {"temp": 15.5, "weather_description": "clear sky"},
            "daily": [],
        }
        mock_cache.isExpired.return_value = False
        mock_cache.get.return_value = json.dumps(cached_result)

        result = await client.getWeather(55.7558, 37.6173)

        # Verify result from cache
        assert result == cached_result

    @pytest.mark.asyncio
    async def test_get_weather_by_city_success(
        self, client, mock_cache, sample_geocoding_response, sample_weather_response
    ):
        """Test combined operation"""
        # Mock cache misses
        mock_cache.isExpired.return_value = True
        mock_cache.get.return_value = None

        # Mock both API calls
        with patch.object(client, "_makeRequest") as mock_request:
            mock_request.side_effect = [sample_geocoding_response, sample_weather_response]

            result = await client.getWeatherByCity("Moscow", "RU")

        # Verify result
        assert result is not None
        assert "location" in result
        assert "weather" in result
        assert result["location"]["name"] == "Moscow"
        assert result["weather"]["current"]["temp"] == 15.5

        # Verify both API calls were made
        assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_get_weather_by_city_geocoding_fails(self, client, mock_cache):
        """Test combined operation when geocoding fails"""
        # Mock cache miss and empty geocoding response
        mock_cache.isExpired.return_value = True
        mock_cache.get.return_value = None

        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getWeatherByCity("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_handling(self, client, mock_cache):
        """Test API error handling"""
        # Mock cache miss
        mock_cache.isExpired.return_value = True
        mock_cache.get.return_value = None

        # Mock API error
        with patch.object(client, "_makeRequest", return_value=None):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_error_handling(self, client, mock_cache):
        """Test cache error handling"""
        # Mock cache error
        mock_cache.isExpired.side_effect = Exception("Cache error")
        mock_cache.get.side_effect = Exception("Cache error")
        mock_cache.set.side_effect = Exception("Cache error")

        # Should still work with API call
        sample_response = [{"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "country": "RU", "local_names": {}}]
        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getCoordinates("Moscow")

        assert result is not None
        assert result["name"] == "Moscow"

    # Context manager functionality removed - client now creates sessions per request


class TestDatabaseWeatherCache:
    """Test suite for database cache"""

    @pytest.fixture
    def mock_db(self):
        """Mock database wrapper"""
        db = Mock()
        db.getWeatherCache = Mock(return_value=None)
        db.setWeatherCache = Mock(return_value=True)
        db.clearExpiredWeatherCache = Mock(return_value=5)
        db.clearAllWeatherCache = Mock(return_value=True)
        return db

    @pytest.fixture
    def cache(self, mock_db):
        """Create cache with mock DB"""
        return DatabaseWeatherCache(mock_db)

    @pytest.mark.asyncio
    async def test_get_existing(self, cache, mock_db):
        """Test getting existing cache entry"""
        # Mock database return
        mock_db.getWeatherCache.return_value = {
            "cache_key": "moscow,ru",
            "cache_type": "geocoding",
            "data": '{"name": "Moscow"}',
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }

        result = await cache.get("moscow,ru", "geocoding")

        assert result == '{"name": "Moscow"}'
        mock_db.getWeatherCache.assert_called_once_with("moscow,ru", "geocoding")

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, cache, mock_db):
        """Test getting non-existent entry"""
        mock_db.getWeatherCache.return_value = None

        result = await cache.get("nonexistent", "geocoding")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_new(self, cache, mock_db):
        """Test storing new entry"""
        mock_db.setWeatherCache.return_value = True

        result = await cache.set("test_key", "geocoding", '{"test": "data"}')

        assert result is True
        mock_db.setWeatherCache.assert_called_once_with("test_key", "geocoding", '{"test": "data"}')

    @pytest.mark.asyncio
    async def test_is_expired_true(self, cache, mock_db):
        """Test expired entry detection"""
        # Mock old entry
        old_time = datetime.now() - timedelta(hours=2)
        mock_db.getWeatherCache.return_value = {
            "cache_key": "test",
            "cache_type": "weather",
            "data": "{}",
            "created_at": old_time,
            "updated_at": old_time,
        }

        result = await cache.isExpired("test", "weather", 3600)  # 1 hour TTL

        assert result is True

    @pytest.mark.asyncio
    async def test_is_expired_false(self, cache, mock_db):
        """Test valid entry detection"""
        # Mock recent entry
        recent_time = datetime.now() - timedelta(minutes=30)
        mock_db.getWeatherCache.return_value = {
            "cache_key": "test",
            "cache_type": "weather",
            "data": "{}",
            "created_at": recent_time,
            "updated_at": recent_time,
        }

        result = await cache.isExpired("test", "weather", 3600)  # 1 hour TTL

        assert result is False

    @pytest.mark.asyncio
    async def test_clear_expired(self, cache, mock_db):
        """Test clearing expired entries"""
        mock_db.clearExpiredWeatherCache.return_value = 3

        result = await cache.clearExpired("weather", 3600)

        assert result == 3
        mock_db.clearExpiredWeatherCache.assert_called_once_with("weather", 3600)

    @pytest.mark.asyncio
    async def test_clear_all(self, cache, mock_db):
        """Test clearing all entries"""
        mock_db.clearAllWeatherCache.return_value = True

        result = await cache.clearAll("geocoding")

        assert result is True
        mock_db.clearAllWeatherCache.assert_called_once_with("geocoding")


class TestIntegration:
    """Integration tests"""

    @pytest.mark.asyncio
    async def test_full_workflow_with_real_cache(self):
        """Test full workflow with real cache implementation"""
        # Mock database wrapper
        mock_db = Mock()
        mock_db.getWeatherCache = Mock(return_value=None)
        mock_db.setWeatherCache = Mock(return_value=True)
        mock_db.clearExpiredWeatherCache = Mock(return_value=0)
        mock_db.clearAllWeatherCache = Mock(return_value=True)

        # Create real cache with mock DB
        cache = DatabaseWeatherCache(mock_db)

        # Create client with real cache
        client = OpenWeatherMapClient(apiKey="test_key", cache=cache, geocodingTTL=3600, weatherTTL=1800)

        # Mock API responses
        geocoding_response = [{"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "country": "RU", "local_names": {}}]
        weather_response = {
            "lat": 55.7558,
            "lon": 37.6173,
            "timezone": "Europe/Moscow",
            "current": {
                "dt": 1697644800,
                "temp": 15.5,
                "feels_like": 14.2,
                "pressure": 1013,
                "humidity": 65,
                "clouds": 40,
                "wind_speed": 3.5,
                "wind_deg": 180,
                "weather": [{"id": 802, "main": "Clouds", "description": "scattered clouds"}],
            },
            "daily": [],
        }

        with patch.object(client, "_makeRequest") as mock_request:
            mock_request.side_effect = [geocoding_response, weather_response]

            result = await client.getWeatherByCity("Moscow", "RU")

        # Verify result
        assert result is not None
        assert result["location"]["name"] == "Moscow"
        assert result["weather"]["current"]["temp"] == 15.5

        # Verify cache operations
        assert mock_db.setWeatherCache.call_count == 2  # Both geocoding and weather cached


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
