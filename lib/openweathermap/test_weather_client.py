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
        cache.getWeather = AsyncMock(return_value=None)
        cache.setWeather = AsyncMock(return_value=True)
        cache.getGeocoging = AsyncMock(return_value=None)
        cache.setGeocoging = AsyncMock(return_value=True)
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
        mock_cache.getGeocoging.return_value = None

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
        mock_cache.getGeocoging.assert_called_once_with("moscow,RU", 2592000)
        mock_cache.setGeocoging.assert_called_once()

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
        mock_cache.getGeocoging.return_value = cached_result

        # Patch _makeRequest before calling to verify it's not called
        with patch.object(client, "_makeRequest") as mock_request:
            result = await client.getCoordinates("Moscow", "RU")
            
            # Verify result from cache
            assert result == cached_result
            
            # Verify no API call was made
            mock_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_coordinates_not_found(self, client, mock_cache):
        """Test geocoding when city not found"""
        # Mock cache miss and empty API response
        mock_cache.getGeocoging.return_value = None

        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getCoordinates("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_weather_success(self, client, mock_cache, sample_weather_response):
        """Test successful weather fetch"""
        # Mock cache miss
        mock_cache.getWeather.return_value = None

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
        mock_cache.getWeather.assert_called_once_with("55.7558,37.6173", 1800)
        mock_cache.setWeather.assert_called_once()

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
        mock_cache.getWeather.return_value = cached_result

        # Patch _makeRequest before calling to verify it's not called
        with patch.object(client, "_makeRequest") as mock_request:
            result = await client.getWeather(55.7558, 37.6173)
            
            # Verify result from cache
            assert result == cached_result
            
            # Verify no API call was made
            mock_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_weather_by_city_success(
        self, client, mock_cache, sample_geocoding_response, sample_weather_response
    ):
        """Test combined operation"""
        # Mock cache misses
        mock_cache.getGeocoging.return_value = None
        mock_cache.getWeather.return_value = None

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
        mock_cache.getGeocoging.return_value = None

        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getWeatherByCity("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_handling(self, client, mock_cache):
        """Test API error handling"""
        # Mock cache miss
        mock_cache.getGeocoging.return_value = None

        # Mock API error
        with patch.object(client, "_makeRequest", return_value=None):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_error_handling(self, client, mock_cache):
        """Test cache error handling"""
        # Mock cache error
        mock_cache.getGeocoging.side_effect = Exception("Cache error")
        mock_cache.setGeocoging.side_effect = Exception("Cache error")

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
        from internal.database.models import CacheType
        
        db = Mock()
        db.getCacheEntry = Mock(return_value=None)
        db.setCacheEntry = Mock(return_value=True)
        return db

    @pytest.fixture
    def cache(self, mock_db):
        """Create cache with mock DB"""
        return DatabaseWeatherCache(mock_db)

    @pytest.mark.asyncio
    async def test_get_weather_existing(self, cache, mock_db):
        """Test getting existing weather cache entry"""
        from internal.database.models import CacheType
        
        # Mock database return with weather data
        cached_weather = {
            "lat": 55.7558,
            "lon": 37.6173,
            "timezone": "Europe/Moscow",
            "current": {"temp": 15.5},
            "daily": [],
        }
        mock_db.getCacheEntry.return_value = {
            "data": json.dumps(cached_weather),
        }

        result = await cache.getWeather("55.7558,37.6173", 1800)

        assert result == cached_weather
        mock_db.getCacheEntry.assert_called_once_with("55.7558,37.6173", cacheType=CacheType.WEATHER, ttl=1800)

    @pytest.mark.asyncio
    async def test_get_geocoding_existing(self, cache, mock_db):
        """Test getting existing geocoding cache entry"""
        from internal.database.models import CacheType
        
        # Mock database return with geocoding data
        cached_geocoding = {
            "name": "Moscow",
            "lat": 55.7558,
            "lon": 37.6173,
            "country": "RU",
        }
        mock_db.getCacheEntry.return_value = {
            "data": json.dumps(cached_geocoding),
        }

        result = await cache.getGeocoging("moscow,ru", 2592000)

        assert result == cached_geocoding
        mock_db.getCacheEntry.assert_called_once_with("moscow,ru", cacheType=CacheType.GEOCODING, ttl=2592000)

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, cache, mock_db):
        """Test getting non-existent entry"""
        mock_db.getCacheEntry.return_value = None

        result = await cache.getWeather("nonexistent", 1800)

        assert result is None

    @pytest.mark.asyncio
    async def test_set_weather(self, cache, mock_db):
        """Test storing weather entry"""
        from internal.database.models import CacheType
        
        mock_db.setCacheEntry.return_value = True
        
        weather_data = {
            "lat": 55.7558,
            "lon": 37.6173,
            "current": {"temp": 15.5},
            "daily": [],
        }

        result = await cache.setWeather("55.7558,37.6173", weather_data)

        assert result is True
        # Verify the call was made with correct parameters
        assert mock_db.setCacheEntry.called
        call_args = mock_db.setCacheEntry.call_args
        assert call_args[0][0] == "55.7558,37.6173"
        assert call_args[1]["cacheType"] == CacheType.WEATHER

    @pytest.mark.asyncio
    async def test_set_geocoding(self, cache, mock_db):
        """Test storing geocoding entry"""
        from internal.database.models import CacheType
        
        mock_db.setCacheEntry.return_value = True
        
        geocoding_data = {
            "name": "Moscow",
            "lat": 55.7558,
            "lon": 37.6173,
            "country": "RU",
        }

        result = await cache.setGeocoging("moscow,ru", geocoding_data)

        assert result is True
        # Verify the call was made with correct parameters
        assert mock_db.setCacheEntry.called
        call_args = mock_db.setCacheEntry.call_args
        assert call_args[0][0] == "moscow,ru"
        assert call_args[1]["cacheType"] == CacheType.GEOCODING

    @pytest.mark.asyncio
    async def test_expired_entry(self, cache, mock_db):
        """Test that expired entries return None"""
        from internal.database.models import CacheType
        
        # When TTL check fails, getCacheEntry returns None
        mock_db.getCacheEntry.return_value = None

        # Request with 1 hour TTL - should return None for expired entry
        result = await cache.getWeather("test", 3600)

        assert result is None
        mock_db.getCacheEntry.assert_called_once_with("test", cacheType=CacheType.WEATHER, ttl=3600)

    @pytest.mark.asyncio
    async def test_valid_entry(self, cache, mock_db):
        """Test that valid entries are returned"""
        from internal.database.models import CacheType
        
        # Mock recent entry
        cached_data = {"temp": 15.5}
        mock_db.getCacheEntry.return_value = {
            "data": json.dumps(cached_data),
        }

        # Request with 1 hour TTL - should return data
        result = await cache.getWeather("test", 3600)

        assert result == cached_data
        mock_db.getCacheEntry.assert_called_once_with("test", cacheType=CacheType.WEATHER, ttl=3600)


class TestIntegration:
    """Integration tests"""

    @pytest.mark.asyncio
    async def test_full_workflow_with_real_cache(self):
        """Test full workflow with real cache implementation"""
        from internal.database.models import CacheType
        
        # Mock database wrapper
        mock_db = Mock()
        mock_db.getCacheEntry = Mock(return_value=None)
        mock_db.setCacheEntry = Mock(return_value=True)

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

        # Verify cache operations - both geocoding and weather should be cached
        assert mock_db.setCacheEntry.call_count == 2
        
        # Verify the cache calls were made with correct types
        calls = mock_db.setCacheEntry.call_args_list
        cache_types = [call[1]["cacheType"] for call in calls]
        assert CacheType.GEOCODING in cache_types
        assert CacheType.WEATHER in cache_types


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
