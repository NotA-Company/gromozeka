"""
Test suite for OpenWeatherMap client

This module contains comprehensive tests for the OpenWeatherMap client library,
including unit tests for the client, cache, and integration scenarios.
"""

import asyncio
import json
import os

# Add project root to path for imports
import sys
from unittest.mock import Mock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib.cache import DictCache, StringKeyGenerator  # noqa: E402
from lib.openweathermap.client import OpenWeatherMapClient  # noqa: E402


class TestOpenWeatherMapClient:
    """Test suite for OpenWeatherMap client"""

    @pytest.fixture
    def client(self):
        """Create client with mock cache"""
        return OpenWeatherMapClient(
            apiKey="test_key",
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
    async def test_get_coordinates_success(self, client, sample_geocoding_response):
        """Test successful geocoding"""

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

    @pytest.mark.asyncio
    async def test_get_coordinates_not_found(self, client):
        """Test geocoding when city not found"""

        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getCoordinates("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_weather_success(self, client, sample_weather_response):
        """Test successful weather fetch"""

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

    @pytest.mark.asyncio
    async def test_get_weather_by_city_success(self, client, sample_geocoding_response, sample_weather_response):
        """Test combined operation"""

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
    async def test_get_weather_by_city_geocoding_fails(self, client):
        """Test combined operation when geocoding fails"""

        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getWeatherByCity("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_handling(self, client):
        """Test API error handling"""

        # Mock API error
        with patch.object(client, "_makeRequest", return_value=None):
            result = await client.getCoordinates("Moscow")

        assert result is None


class TestIntegration:
    """Integration tests"""

    @pytest.mark.asyncio
    async def test_full_workflow_with_real_cache(self):
        """Test full workflow with real cache implementation"""

        # Create client with real cache
        client = OpenWeatherMapClient(
            apiKey="test_key",
            weatherCache=DictCache(keyGenerator=StringKeyGenerator()),
            geocodingCache=DictCache(keyGenerator=StringKeyGenerator()),
            geocodingTTL=3600,
            weatherTTL=1800,
        )

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


class TestWeatherClientErrorHandling:
    """Test suite for error handling scenarios"""

    @pytest.fixture
    def client(self):
        """Create client with mock cache"""
        return OpenWeatherMapClient(
            apiKey="test_key",
            geocodingTTL=2592000,
            weatherTTL=1800,
            requestTimeout=10,
            defaultLanguage="ru",
        )

    @pytest.mark.asyncio
    async def test_network_timeout_error(self, client):
        """Test handling of network timeout errors"""
        with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Connection timeout")):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_network_connection_error(self, client):
        """Test handling of network connection errors"""

        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection failed")):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_http_500_error(self, client):
        """Test handling of HTTP 500 Internal Server Error"""

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "Internal server error"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_http_503_error(self, client):
        """Test handling of HTTP 503 Service Unavailable"""

        mock_response = Mock()
        mock_response.status_code = 503
        mock_response.json.return_value = {"error": "Service unavailable"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_http_401_unauthorized(self, client):
        """Test handling of HTTP 401 Unauthorized (invalid API key)"""

        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": "Invalid API key"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_http_403_forbidden(self, client):
        """Test handling of HTTP 403 Forbidden"""

        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.json.return_value = {"error": "Forbidden"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_http_404_not_found(self, client):
        """Test handling of HTTP 404 Not Found"""

        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"error": "Not found"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getCoordinates("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_http_429_rate_limit(self, client):
        """Test handling of HTTP 429 Rate Limit Exceeded"""

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = {"error": "Rate limit exceeded"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_json_response(self, client):
        """Test handling of malformed JSON responses"""

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_geocoding_response(self, client):
        """Test handling of empty geocoding response"""

        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getCoordinates("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_null_weather_response(self, client):
        """Test handling of null weather response"""

        with patch.object(client, "_makeRequest", return_value=None):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_coordinates_out_of_range(self, client):
        """Test handling of invalid coordinates (out of range)"""

        # Latitude out of range (-90 to 90)
        with patch.object(client, "_makeRequest", return_value=None):
            result = await client.getWeather(95.0, 37.6173)
        assert result is None

        # Longitude out of range (-180 to 180)
        with patch.object(client, "_makeRequest", return_value=None):
            result = await client.getWeather(55.7558, 200.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_city_name(self, client):
        """Test handling of empty city name"""

        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getCoordinates("")

        assert result is None

    @pytest.mark.asyncio
    async def test_special_characters_in_city_name(self, client):
        """Test handling of special characters in city name"""

        sample_response = [
            {
                "name": "São Paulo",
                "lat": -23.5505,
                "lon": -46.6333,
                "country": "BR",
                "local_names": {},
            }
        ]

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getCoordinates("São Paulo", "BR")

        assert result is not None
        assert result["name"] == "São Paulo"

    @pytest.mark.asyncio
    async def test_dns_resolution_error(self, client):
        """Test handling of DNS resolution errors"""

        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("DNS resolution failed")):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, client):
        """Test handling of unexpected exceptions"""

        with patch("httpx.AsyncClient.get", side_effect=Exception("Unexpected error")):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None


class TestWeatherClientRateLimiting:
    """Test suite for rate limiting scenarios"""

    @pytest.fixture
    def client(self):
        """Create client with mock cache"""
        return OpenWeatherMapClient(
            apiKey="test_key",
            geocodingTTL=2592000,
            weatherTTL=1800,
            requestTimeout=10,
            defaultLanguage="ru",
        )

    @pytest.mark.asyncio
    async def test_rate_limit_response_handling(self, client):
        """Test handling of rate limit response (429)"""

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = {"error": "Rate limit exceeded"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_rate_limit_with_retry_after_header(self, client):
        """Test rate limit response with Retry-After header"""

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.json.return_value = {"error": "Rate limit exceeded"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_concurrent_requests_handling(self, client):
        """Test handling of concurrent requests"""

        sample_weather = {
            "lat": 55.7558,
            "lon": 37.6173,
            "timezone": "Europe/Moscow",
            "current": {"temp": 15.5},
            "daily": [],
        }

        with patch.object(client, "_makeRequest", return_value=sample_weather):
            # Make multiple concurrent requests
            tasks = [client.getWeather(55.7558 + i * 0.1, 37.6173) for i in range(5)]
            results = await asyncio.gather(*tasks)

            assert len(results) == 5
            assert all(r is not None for r in results)


class TestWeatherClientDataValidation:
    """Test suite for data validation scenarios"""

    @pytest.fixture
    def client(self):
        """Create client with mock cache"""
        return OpenWeatherMapClient(
            apiKey="test_key",
            geocodingTTL=2592000,
            weatherTTL=1800,
            requestTimeout=10,
            defaultLanguage="ru",
        )

    @pytest.mark.asyncio
    async def test_validate_geocoding_structure(self, client):
        """Test validation of geocoding data structure"""

        sample_response = [
            {
                "name": "Moscow",
                "lat": 55.7558,
                "lon": 37.6173,
                "country": "RU",
                "local_names": {"en": "Moscow", "ru": "Москва"},
            }
        ]

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getCoordinates("Moscow", "RU")

            assert result is not None
            assert "name" in result
            assert "lat" in result
            assert "lon" in result
            assert "country" in result
            assert "local_names" in result
            assert isinstance(result["lat"], float)
            assert isinstance(result["lon"], float)

    @pytest.mark.asyncio
    async def test_validate_weather_structure(self, client):
        """Test validation of weather data structure"""

        sample_response = {
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

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getWeather(55.7558, 37.6173)

            assert result is not None
            assert "lat" in result
            assert "lon" in result
            assert "timezone" in result
            assert "current" in result
            assert "daily" in result
            assert isinstance(result["current"]["temp"], float)
            assert isinstance(result["current"]["humidity"], int)

    @pytest.mark.asyncio
    async def test_handle_missing_optional_fields(self, client):
        """Test handling of missing optional fields in API response"""

        # Response without optional 'state' field
        sample_response = [{"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "country": "RU", "local_names": {}}]

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getCoordinates("Moscow", "RU")

            assert result is not None
            assert result["state"] == ""

    @pytest.mark.asyncio
    async def test_handle_missing_weather_fields(self, client):
        """Test handling of missing fields in weather response"""

        # Minimal weather response
        sample_response = {
            "lat": 55.7558,
            "lon": 37.6173,
            "timezone": "Europe/Moscow",
            "current": {"dt": 1697644800, "temp": 15.5, "weather": [{"id": 800, "main": "Clear"}]},
            "daily": [],
        }

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getWeather(55.7558, 37.6173)

            assert result is not None
            # Verify default values are used for missing fields
            assert result["current"]["feels_like"] == 0.0
            assert result["current"]["pressure"] == 0

    @pytest.mark.asyncio
    async def test_validate_temperature_units(self, client):
        """Test that temperature is in metric units (Celsius)"""

        sample_response = {
            "lat": 55.7558,
            "lon": 37.6173,
            "timezone": "Europe/Moscow",
            "current": {"dt": 1697644800, "temp": 15.5, "feels_like": 14.2, "weather": [{"id": 800}]},
            "daily": [],
        }

        with patch.object(client, "_makeRequest", return_value=sample_response) as mock_request:
            await client.getWeather(55.7558, 37.6173)

            # Verify units=metric is passed in request
            call_args = mock_request.call_args
            assert call_args[0][1]["units"] == "metric"

    @pytest.mark.asyncio
    async def test_validate_coordinate_ranges(self, client):
        """Test coordinate range validation"""

        # Valid coordinates
        sample_response = [{"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "country": "RU", "local_names": {}}]

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getCoordinates("Moscow", "RU")

            assert result is not None
            assert -90 <= result["lat"] <= 90
            assert -180 <= result["lon"] <= 180

    @pytest.mark.asyncio
    async def test_validate_timestamp_formats(self, client):
        """Test timestamp format validation"""

        sample_response = {
            "lat": 55.7558,
            "lon": 37.6173,
            "timezone": "Europe/Moscow",
            "current": {
                "dt": 1697644800,
                "temp": 15.5,
                "sunrise": 1697600000,
                "sunset": 1697640000,
                "weather": [{"id": 800}],
            },
            "daily": [],
        }

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getWeather(55.7558, 37.6173)

            assert result is not None
            # Verify timestamps are integers (Unix timestamps)
            assert isinstance(result["current"]["dt"], int)
            assert isinstance(result["current"]["sunrise"], int)
            assert isinstance(result["current"]["sunset"], int)

    @pytest.mark.asyncio
    async def test_handle_unexpected_data_types(self, client):
        """Test handling of unexpected data types in response"""

        # Response with string instead of number for temperature
        sample_response = {
            "lat": 55.7558,
            "lon": 37.6173,
            "timezone": "Europe/Moscow",
            "current": {"dt": 1697644800, "temp": "15.5", "weather": [{"id": 800}]},
            "daily": [],
        }

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getWeather(55.7558, 37.6173)

            assert result is not None
            # Verify conversion to float
            assert isinstance(result["current"]["temp"], float)
            assert result["current"]["temp"] == 15.5

    @pytest.mark.asyncio
    async def test_validate_daily_forecast_structure(self, client):
        """Test validation of daily forecast structure"""

        sample_response = {
            "lat": 55.7558,
            "lon": 37.6173,
            "timezone": "Europe/Moscow",
            "current": {"dt": 1697644800, "temp": 15.5, "weather": [{"id": 800}]},
            "daily": [
                {
                    "dt": 1697644800,
                    "temp": {"day": 15.5, "night": 10.0, "min": 8.0, "max": 18.0},
                    "weather": [{"id": 800, "main": "Clear", "description": "clear sky"}],
                }
            ],
        }

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getWeather(55.7558, 37.6173)

            assert result is not None
            assert len(result["daily"]) == 1
            daily = result["daily"][0]
            assert "temp_day" in daily
            assert "temp_night" in daily
            assert "temp_min" in daily
            assert "temp_max" in daily
            assert isinstance(daily["temp_day"], float)

    @pytest.mark.asyncio
    async def test_handle_empty_weather_array(self, client):
        """Test handling of empty weather array in response"""

        sample_response = {
            "lat": 55.7558,
            "lon": 37.6173,
            "timezone": "Europe/Moscow",
            "current": {"dt": 1697644800, "temp": 15.5, "weather": []},
            "daily": [],
        }

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getWeather(55.7558, 37.6173)

            assert result is not None
            # Verify default values are used when weather array is empty
            assert result["current"]["weather_id"] == 0
            assert result["current"]["weather_main"] == ""
            assert result["current"]["weather_description"] == ""


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
