"""
Unit tests for Geocode Maps API Client

This module contains comprehensive unit tests for the GeocodeMapsClient class,
testing caching, error handling, rate limiting, and coordinate processing.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from lib.cache import DictCache
from lib.cache.key_generator import JsonKeyGenerator
from lib.geocode_maps import GeocodeMapsClient


@pytest.mark.asyncio
async def test_error_handling_401():
    """Test handling of authentication error, dood!"""
    client = GeocodeMapsClient(apiKey="invalid_key")

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        result = await client.search("Test")

        assert result is None


@pytest.mark.asyncio
async def test_rate_limiting():
    """Test rate limiter integration, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")

    with patch.object(client._rateLimiter, "applyLimit") as mock_limit:
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = []
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            await client.search("Test")

            mock_limit.assert_called_once_with("geocode-maps")


@pytest.mark.asyncio
async def test_cache_error_handling():
    """Test cache error handling doesn't break API calls, dood!"""
    cache = MagicMock()
    cache.get = AsyncMock(side_effect=Exception("Cache error"))
    cache.set = AsyncMock(side_effect=Exception("Cache error"))

    client = GeocodeMapsClient(apiKey="test_key", searchCache=cache)

    mockResponse = [{"place_id": 123, "name": "Test", "lat": "52.5", "lon": "103.8"}]

    with patch.object(client._rateLimiter, "applyLimit", new_callable=AsyncMock):
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mockResponse
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            result = await client.search("Test Query")

            # Should still get result despite cache errors
            assert result == mockResponse


@pytest.mark.asyncio
async def test_error_handling_404():
    """Test handling of not found error, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        result = await client.search("Nonexistent Location")

        assert result is None


@pytest.mark.asyncio
async def test_error_handling_429():
    """Test handling of rate limit error, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        result = await client.search("Test")

        assert result is None


@pytest.mark.asyncio
async def test_error_handling_500():
    """Test handling of server error, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        result = await client.search("Test")

        assert result is None


@pytest.mark.asyncio
async def test_timeout_exception():
    """Test handling of timeout exception, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.TimeoutException("Timeout")

        result = await client.search("Test")

        assert result is None


@pytest.mark.asyncio
async def test_network_error():
    """Test handling of network error, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.RequestError("Network error")

        result = await client.search("Test")

        assert result is None


@pytest.mark.asyncio
async def test_json_decode_error():
    """Test handling of JSON decode error, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = Exception("JSON decode error")
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        result = await client.search("Test")

        assert result is None


@pytest.mark.asyncio
async def test_search_parameter_validation():
    """Test search method with various parameters, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")

    mockResponse = [{"place_id": 123, "name": "Test", "lat": "52.5", "lon": "103.8"}]

    with patch.object(client._rateLimiter, "applyLimit", new_callable=AsyncMock):
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mockResponse
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            # Test with all parameters
            await client.search(
                query="Test Query",
                limit=5,
                countrycodes="ru,us",
                viewbox="103.0,52.0,104.0,53.0",
                bounded=True,
                addressdetails=False,
                extratags=False,
                namedetails=False,
                dedupe=False,
            )

            # Verify HTTP client was called with correct params
            mock_client.return_value.__aenter__.return_value.get.assert_called_once()
            call_args = mock_client.return_value.__aenter__.return_value.get.call_args[1]["params"]  # Get params dict

            assert call_args["q"] == "Test Query"
            assert call_args["limit"] == 5
            assert call_args["countrycodes"] == "ru,us"
            assert call_args["viewbox"] == "103.0,52.0,104.0,53.0"
            assert call_args["bounded"] == 1
            assert call_args["addressdetails"] == 0
            assert call_args["extratags"] == 0
            assert call_args["namedetails"] == 0
            assert call_args["dedupe"] == 0
            assert call_args["format"] == "jsonv2"


@pytest.mark.asyncio
async def test_reverse_parameter_validation():
    """Test reverse method with various parameters, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")

    mockResponse = {"place_id": 123, "name": "Test", "lat": "52.5", "lon": "103.8"}

    with patch.object(client._rateLimiter, "applyLimit", new_callable=AsyncMock):
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mockResponse
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            # Test with all parameters
            await client.reverse(
                lat=52.5443, lon=103.8882, zoom=15, addressdetails=False, extratags=False, namedetails=False
            )

            # Verify HTTP client was called with correct params
            mock_client.return_value.__aenter__.return_value.get.assert_called_once()
            call_args = mock_client.return_value.__aenter__.return_value.get.call_args[1]["params"]  # Get params dict

            assert call_args["lat"] == 52.5443
            assert call_args["lon"] == 103.8882
            assert call_args["zoom"] == 15
            assert call_args["addressdetails"] == 0
            assert call_args["extratags"] == 0
            assert call_args["namedetails"] == 0
            assert call_args["format"] == "jsonv2"


@pytest.mark.asyncio
async def test_lookup_parameter_validation():
    """Test lookup method with various parameters, dood!"""
    client = GeocodeMapsClient(apiKey="test_key")

    mockResponse = [{"place_id": 123, "name": "Test", "lat": "52.5", "lon": "103.8"}]

    with patch.object(client._rateLimiter, "applyLimit", new_callable=AsyncMock):
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mockResponse
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            # Test with all parameters
            await client.lookup(
                osmIds=["R2623018", "N107775"],
                addressdetails=False,
                extratags=False,
                namedetails=False,
                polygonGeojson=True,
                polygonKml=True,
                polygonSvg=True,
                polygonText=True,
            )

            # Verify HTTP client was called with correct params
            mock_client.return_value.__aenter__.return_value.get.assert_called_once()
            call_args = mock_client.return_value.__aenter__.return_value.get.call_args[1]["params"]  # Get params dict

            assert call_args["osm_ids"] == "N107775,R2623018"  # Sorted
            assert call_args["addressdetails"] == 0
            assert call_args["extratags"] == 0
            assert call_args["namedetails"] == 0
            assert call_args["polygon_geojson"] == 1
            assert call_args["polygon_kml"] == 1
            assert call_args["polygon_svg"] == 1
            assert call_args["polygon_text"] == 1
            assert call_args["format"] == "jsonv2"


@pytest.mark.asyncio
async def test_lookup_cache_behavior():
    """Test lookup cache behavior, dood!"""
    cache = DictCache(keyGenerator=JsonKeyGenerator())
    client = GeocodeMapsClient(apiKey="test_key", lookupCache=cache)

    mockResponse = [{"place_id": 123, "name": "Test", "lat": "52.5", "lon": "103.8"}]

    with patch.object(client._rateLimiter, "applyLimit", new_callable=AsyncMock):
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mockResponse
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            # First call - should hit API
            result1 = await client.lookup(["R2623018", "N107775"])

            # Second call with IDs in different order - should hit cache
            result2 = await client.lookup(["N107775", "R2623018"])

            assert result1 == result2 == mockResponse

            # Verify only one API call was made
            mock_client.return_value.__aenter__.return_value.get.assert_called_once()


@pytest.mark.asyncio
async def test_client_initialization():
    """Test client initialization with various parameters, dood!"""
    # Test with minimal parameters
    client1 = GeocodeMapsClient(apiKey="test_key")
    assert client1.apiKey == "test_key"
    assert client1.acceptLanguage is None  # Default is None
    assert client1.requestTimeout == 10
    assert client1.rateLimiterQueue == "geocode-maps"

    # Test with all parameters
    cache = DictCache(keyGenerator=JsonKeyGenerator())
    client2 = GeocodeMapsClient(
        apiKey="test_key",
        searchCache=cache,
        reverseCache=cache,
        lookupCache=cache,
        searchTTL=1000,
        reverseTTL=2000,
        lookupTTL=3000,
        requestTimeout=15,
        acceptLanguage="ru",
        rateLimiterQueue="custom-queue",
    )

    assert client2.apiKey == "test_key"
    assert client2.acceptLanguage == "ru"
    assert client2.requestTimeout == 15
    assert client2.rateLimiterQueue == "custom-queue"
    assert client2.searchTTL == 1000
    assert client2.reverseTTL == 2000
    assert client2.lookupTTL == 3000
