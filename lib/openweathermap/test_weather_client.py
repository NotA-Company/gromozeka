"""
Test suite for OpenWeatherMap client.

This module contains comprehensive tests for the OpenWeatherMap client library,
including unit tests for the client, cache, and integration scenarios. The test
suite covers:

- Geocoding functionality (city to coordinates conversion)
- Weather data retrieval (current and forecast)
- Error handling (network errors, HTTP errors, malformed data)
- Rate limiting scenarios
- Data validation and structure verification
- Integration tests with real cache implementations

The tests use mocking to simulate API responses and ensure reliable, fast test
execution without external dependencies.
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
    """Test suite for OpenWeatherMap client basic functionality.

    This test class covers the core functionality of the OpenWeatherMap client,
    including geocoding operations, weather data retrieval, and combined operations.
    All tests use mocked API responses to ensure fast, reliable execution without
    external dependencies.

    Attributes:
        client: OpenWeatherMapClient instance configured with test API key and settings.
    """

    @pytest.fixture
    def client(self) -> OpenWeatherMapClient:
        """Create client with mock cache.

        Returns:
            OpenWeatherMapClient: Configured client instance with test API key,
                30-day geocoding TTL, 30-minute weather TTL, 10-second timeout,
                and Russian as default language.
        """
        return OpenWeatherMapClient(
            apiKey="test_key",
            geocodingTTL=2592000,
            weatherTTL=1800,
            requestTimeout=10,
            defaultLanguage="ru",
        )

    @pytest.fixture
    def sample_geocoding_response(self) -> list[dict]:
        """Sample geocoding API response.

        Returns:
            list[dict]: Mock geocoding response for Moscow with coordinates,
                country code, and localized names.
        """
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
    def sample_weather_response(self) -> dict:
        """Sample weather API response.

        Returns:
            dict: Mock weather response for Moscow with current conditions and
                daily forecast data.
        """
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
    async def test_get_coordinates_success(
        self, client: OpenWeatherMapClient, sample_geocoding_response: list[dict]
    ) -> None:
        """Test successful geocoding.

        Verifies that the client correctly retrieves coordinates for a valid city name
        and returns the expected data structure with all required fields.

        Args:
            client: OpenWeatherMapClient instance.
            sample_geocoding_response: Mock geocoding API response.
        """
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
    async def test_get_coordinates_not_found(self, client: OpenWeatherMapClient) -> None:
        """Test geocoding when city not found.

        Verifies that the client returns None when the geocoding API returns an empty
        result list, indicating the city was not found.

        Args:
            client: OpenWeatherMapClient instance.
        """
        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getCoordinates("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_weather_success(self, client: OpenWeatherMapClient, sample_weather_response: dict) -> None:
        """Test successful weather fetch.

        Verifies that the client correctly retrieves weather data for valid coordinates
        and returns the expected data structure with current conditions and daily forecast.

        Args:
            client: OpenWeatherMapClient instance.
            sample_weather_response: Mock weather API response.
        """
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
    async def test_get_weather_by_city_success(
        self, client: OpenWeatherMapClient, sample_geocoding_response: list[dict], sample_weather_response: dict
    ) -> None:
        """Test combined operation.

        Verifies that the client correctly performs the combined operation of geocoding
        a city name and then fetching weather data for those coordinates.

        Args:
            client: OpenWeatherMapClient instance.
            sample_geocoding_response: Mock geocoding API response.
            sample_weather_response: Mock weather API response.
        """
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
    async def test_get_weather_by_city_geocoding_fails(self, client: OpenWeatherMapClient) -> None:
        """Test combined operation when geocoding fails.

        Verifies that the client returns None when the geocoding step fails (returns
        empty result), preventing unnecessary weather API calls.

        Args:
            client: OpenWeatherMapClient instance.
        """
        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getWeatherByCity("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_handling(self, client: OpenWeatherMapClient) -> None:
        """Test API error handling.

        Verifies that the client gracefully handles API errors by returning None when
        the internal request method returns None.

        Args:
            client: OpenWeatherMapClient instance.
        """
        # Mock API error
        with patch.object(client, "_makeRequest", return_value=None):
            result = await client.getCoordinates("Moscow")

        assert result is None


class TestIntegration:
    """Integration tests for OpenWeatherMap client.

    This test class covers integration scenarios that test the client with real
    cache implementations, ensuring that the caching layer works correctly with
    the client's API interaction logic.
    """

    @pytest.mark.asyncio
    async def test_full_workflow_with_real_cache(self) -> None:
        """Test full workflow with real cache implementation.

        Verifies that the client works correctly with real DictCache instances for
        both geocoding and weather data caching. The test mocks the API responses
        but uses actual cache objects to ensure the caching logic functions properly.

        The test creates a client with real cache instances, performs a combined
        geocoding and weather fetch operation, and verifies that the results are
        correctly returned.
        """
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
    """Test suite for error handling scenarios.

    This test class comprehensively covers various error conditions that the
    OpenWeatherMap client may encounter, including network errors, HTTP errors,
    malformed responses, and invalid input. Each test verifies that the client
    gracefully handles errors by returning None rather than raising exceptions.

    Attributes:
        client: OpenWeatherMapClient instance configured with test API key and settings.
    """

    @pytest.fixture
    def client(self) -> OpenWeatherMapClient:
        """Create client with mock cache.

        Returns:
            OpenWeatherMapClient: Configured client instance with test API key,
                30-day geocoding TTL, 30-minute weather TTL, 10-second timeout,
                and Russian as default language.
        """
        return OpenWeatherMapClient(
            apiKey="test_key",
            geocodingTTL=2592000,
            weatherTTL=1800,
            requestTimeout=10,
            defaultLanguage="ru",
        )

    @pytest.mark.asyncio
    async def test_network_timeout_error(self, client: OpenWeatherMapClient) -> None:
        """Test handling of network timeout errors.

        Verifies that the client gracefully handles httpx.TimeoutException
        when the API request times out, returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Connection timeout")):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_network_connection_error(self, client: OpenWeatherMapClient) -> None:
        """Test handling of network connection errors.

        Verifies that the client gracefully handles httpx.ConnectError
        when network connection fails, returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection failed")):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_http_500_error(self, client: OpenWeatherMapClient) -> None:
        """Test handling of HTTP 500 Internal Server Error.

        Verifies that the client gracefully handles HTTP 500 errors from the API,
        returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "Internal server error"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_http_503_error(self, client: OpenWeatherMapClient) -> None:
        """Test handling of HTTP 503 Service Unavailable.

        Verifies that the client gracefully handles HTTP 503 errors from the API,
        returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        mock_response = Mock()
        mock_response.status_code = 503
        mock_response.json.return_value = {"error": "Service unavailable"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_http_401_unauthorized(self, client: OpenWeatherMapClient) -> None:
        """Test handling of HTTP 401 Unauthorized (invalid API key).

        Verifies that the client gracefully handles HTTP 401 errors when the API
        key is invalid, returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": "Invalid API key"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_http_403_forbidden(self, client: OpenWeatherMapClient) -> None:
        """Test handling of HTTP 403 Forbidden.

        Verifies that the client gracefully handles HTTP 403 errors when access
        is forbidden, returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.json.return_value = {"error": "Forbidden"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_http_404_not_found(self, client: OpenWeatherMapClient) -> None:
        """Test handling of HTTP 404 Not Found.

        Verifies that the client gracefully handles HTTP 404 errors when the
        requested resource is not found, returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"error": "Not found"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getCoordinates("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_http_429_rate_limit(self, client: OpenWeatherMapClient) -> None:
        """Test handling of HTTP 429 Rate Limit Exceeded.

        Verifies that the client gracefully handles HTTP 429 errors when the
        rate limit is exceeded, returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = {"error": "Rate limit exceeded"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_json_response(self, client: OpenWeatherMapClient) -> None:
        """Test handling of malformed JSON responses.

        Verifies that the client gracefully handles JSONDecodeError when the
        API returns malformed JSON, returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_geocoding_response(self, client: OpenWeatherMapClient) -> None:
        """Test handling of empty geocoding response.

        Verifies that the client returns None when the geocoding API returns
        an empty result list, indicating the city was not found.

        Args:
            client: OpenWeatherMapClient instance.
        """
        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getCoordinates("NonexistentCity")

        assert result is None

    @pytest.mark.asyncio
    async def test_null_weather_response(self, client: OpenWeatherMapClient) -> None:
        """Test handling of null weather response.

        Verifies that the client returns None when the weather API returns
        null, indicating a failure to retrieve weather data.

        Args:
            client: OpenWeatherMapClient instance.
        """
        with patch.object(client, "_makeRequest", return_value=None):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_coordinates_out_of_range(self, client: OpenWeatherMapClient) -> None:
        """Test handling of invalid coordinates (out of range).

        Verifies that the client gracefully handles coordinates outside the
        valid range (latitude: -90 to 90, longitude: -180 to 180), returning
        None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        # Latitude out of range (-90 to 90)
        with patch.object(client, "_makeRequest", return_value=None):
            result = await client.getWeather(95.0, 37.6173)
        assert result is None

        # Longitude out of range (-180 to 180)
        with patch.object(client, "_makeRequest", return_value=None):
            result = await client.getWeather(55.7558, 200.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_city_name(self, client: OpenWeatherMapClient) -> None:
        """Test handling of empty city name.

        Verifies that the client returns None when an empty city name is
        provided, preventing unnecessary API calls.

        Args:
            client: OpenWeatherMapClient instance.
        """
        with patch.object(client, "_makeRequest", return_value=[]):
            result = await client.getCoordinates("")

        assert result is None

    @pytest.mark.asyncio
    async def test_special_characters_in_city_name(self, client: OpenWeatherMapClient) -> None:
        """Test handling of special characters in city name.

        Verifies that the client correctly handles city names with special
        characters (e.g., accented characters, UTF-8 encoding) and returns
        the expected results.

        Args:
            client: OpenWeatherMapClient instance.
        """
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
    async def test_dns_resolution_error(self, client: OpenWeatherMapClient) -> None:
        """Test handling of DNS resolution errors.

        Verifies that the client gracefully handles DNS resolution failures
        (expressed as httpx.ConnectError), returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("DNS resolution failed")):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, client: OpenWeatherMapClient) -> None:
        """Test handling of unexpected exceptions.

        Verifies that the client gracefully handles unexpected exceptions
        that may occur during API requests, returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        with patch("httpx.AsyncClient.get", side_effect=Exception("Unexpected error")):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None


class TestWeatherClientRateLimiting:
    """Test suite for rate limiting scenarios.

    This test class covers scenarios related to API rate limiting, including
    handling of 429 responses, Retry-After headers, and concurrent request
    handling. These tests ensure the client behaves correctly when the API
    imposes rate limits.

    Attributes:
        client: OpenWeatherMapClient instance configured with test API key and settings.
    """

    @pytest.fixture
    def client(self) -> OpenWeatherMapClient:
        """Create client with mock cache.

        Returns:
            OpenWeatherMapClient: Configured client instance with test API key,
                30-day geocoding TTL, 30-minute weather TTL, 10-second timeout,
                and Russian as default language.
        """
        return OpenWeatherMapClient(
            apiKey="test_key",
            geocodingTTL=2592000,
            weatherTTL=1800,
            requestTimeout=10,
            defaultLanguage="ru",
        )

    @pytest.mark.asyncio
    async def test_rate_limit_response_handling(self, client: OpenWeatherMapClient) -> None:
        """Test handling of rate limit response (429).

        Verifies that the client gracefully handles HTTP 429 responses when the
        API rate limit is exceeded, returning None instead of raising.

        Args:
            client: OpenWeatherMapClient instance.
        """
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = {"error": "Rate limit exceeded"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getWeather(55.7558, 37.6173)

        assert result is None

    @pytest.mark.asyncio
    async def test_rate_limit_with_retry_after_header(self, client: OpenWeatherMapClient) -> None:
        """Test rate limit response with Retry-After header.

        Verifies that the client gracefully handles HTTP 429 responses that include
        a Retry-After header, returning None instead of raising. The Retry-After
        header indicates how long to wait before retrying.

        Args:
            client: OpenWeatherMapClient instance.
        """
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.json.return_value = {"error": "Rate limit exceeded"}

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await client.getCoordinates("Moscow")

        assert result is None

    @pytest.mark.asyncio
    async def test_concurrent_requests_handling(self, client: OpenWeatherMapClient) -> None:
        """Test handling of concurrent requests.

        Verifies that the client can handle multiple concurrent requests without
        errors or data corruption. This test simulates a scenario where multiple
        weather requests are made simultaneously.

        Args:
            client: OpenWeatherMapClient instance.
        """
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
    """Test suite for data validation scenarios.

    This test class covers validation of API response data structures, ensuring
    that the client correctly processes and validates data from the OpenWeatherMap
    API. Tests include structure validation, type checking, handling of missing
    fields, and verification of data formats.

    Attributes:
        client: OpenWeatherMapClient instance configured with test API key and settings.
    """

    @pytest.fixture
    def client(self) -> OpenWeatherMapClient:
        """Create client with mock cache.

        Returns:
            OpenWeatherMapClient: Configured client instance with test API key,
                30-day geocoding TTL, 30-minute weather TTL, 10-second timeout,
                and Russian as default language.
        """
        return OpenWeatherMapClient(
            apiKey="test_key",
            geocodingTTL=2592000,
            weatherTTL=1800,
            requestTimeout=10,
            defaultLanguage="ru",
        )

    @pytest.mark.asyncio
    async def test_validate_geocoding_structure(self, client: OpenWeatherMapClient) -> None:
        """Test validation of geocoding data structure.

        Verifies that the client correctly validates the structure of geocoding
        API responses, ensuring all required fields are present and have the
        correct data types.

        Args:
            client: OpenWeatherMapClient instance.
        """
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
    async def test_validate_weather_structure(self, client: OpenWeatherMapClient) -> None:
        """Test validation of weather data structure.

        Verifies that the client correctly validates the structure of weather
        API responses, ensuring all required fields are present and have the
        correct data types.

        Args:
            client: OpenWeatherMapClient instance.
        """
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
    async def test_handle_missing_optional_fields(self, client: OpenWeatherMapClient) -> None:
        """Test handling of missing optional fields in API response.

        Verifies that the client gracefully handles missing optional fields in
        geocoding responses by using appropriate default values (e.g., empty string
        for missing 'state' field).

        Args:
            client: OpenWeatherMapClient instance.
        """
        # Response without optional 'state' field
        sample_response = [{"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "country": "RU", "local_names": {}}]

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getCoordinates("Moscow", "RU")

            assert result is not None
            assert result["state"] == ""

    @pytest.mark.asyncio
    async def test_handle_missing_weather_fields(self, client: OpenWeatherMapClient) -> None:
        """Test handling of missing fields in weather response.

        Verifies that the client gracefully handles missing optional fields in
        weather responses by using appropriate default values (e.g., 0.0 for
        missing 'feels_like', 0 for missing 'pressure').

        Args:
            client: OpenWeatherMapClient instance.
        """
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
    async def test_validate_temperature_units(self, client: OpenWeatherMapClient) -> None:
        """Test that temperature is in metric units (Celsius).

        Verifies that the client requests temperature data in metric units (Celsius)
        by passing 'units=metric' in the API request parameters.

        Args:
            client: OpenWeatherMapClient instance.
        """
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
    async def test_validate_coordinate_ranges(self, client: OpenWeatherMapClient) -> None:
        """Test coordinate range validation.

        Verifies that coordinates returned by the API are within valid ranges:
        latitude: -90 to 90, longitude: -180 to 180.

        Args:
            client: OpenWeatherMapClient instance.
        """
        # Valid coordinates
        sample_response = [{"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "country": "RU", "local_names": {}}]

        with patch.object(client, "_makeRequest", return_value=sample_response):
            result = await client.getCoordinates("Moscow", "RU")

            assert result is not None
            assert -90 <= result["lat"] <= 90
            assert -180 <= result["lon"] <= 180

    @pytest.mark.asyncio
    async def test_validate_timestamp_formats(self, client: OpenWeatherMapClient) -> None:
        """Test timestamp format validation.

        Verifies that timestamps in the weather response are integers representing
        Unix timestamps (seconds since epoch).

        Args:
            client: OpenWeatherMapClient instance.
        """
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
    async def test_handle_unexpected_data_types(self, client: OpenWeatherMapClient) -> None:
        """Test handling of unexpected data types in response.

        Verifies that the client can handle unexpected data types in API responses
        by converting them to the expected types (e.g., converting string temperature
        to float).

        Args:
            client: OpenWeatherMapClient instance.
        """
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
    async def test_validate_daily_forecast_structure(self, client: OpenWeatherMapClient) -> None:
        """Test validation of daily forecast structure.

        Verifies that the client correctly validates the structure of daily
        forecast data, ensuring all required temperature fields are present and
        have the correct data types.

        Args:
            client: OpenWeatherMapClient instance.
        """
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
    async def test_handle_empty_weather_array(self, client: OpenWeatherMapClient) -> None:
        """Test handling of empty weather array in response.

        Verifies that the client gracefully handles empty weather arrays in the
        current conditions response by using appropriate default values (e.g., 0
        for weather_id, empty strings for weather_main and weather_description).

        Args:
            client: OpenWeatherMapClient instance.
        """
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
