"""
Golden data integration tests for OpenWeatherMapClient

This module contains integration tests that use real golden data collected
from the OpenWeatherMap API to test the OpenWeatherMapClient functionality.
"""

import pytest

from lib.openweathermap.client import OpenWeatherMapClient
from lib.openweathermap.dict_cache import DictWeatherCache
from tests.golden_data.openweathermap.provider import GoldenDataProvider


@pytest.mark.asyncio
async def testGetWeatherByCity():
    """Test getting weather by city using golden data."""
    provider = GoldenDataProvider()
    cache = DictWeatherCache()

    async with provider.patchClient(OpenWeatherMapClient(apiKey="test_key", cache=cache)) as client:
        # Test Minsk
        result = await client.getWeatherByCity("Minsk", "BY")
        assert result is not None
        assert "location" in result
        assert "weather" in result
        assert result["location"]["name"] == "Minsk"
        assert result["location"]["country"] == "BY"
        assert isinstance(result["location"]["lat"], float)
        assert isinstance(result["location"]["lon"], float)
        assert result["weather"]["current"]["temp"] is not None
        assert isinstance(result["weather"]["current"]["temp"], float)
        assert result["weather"]["current"]["weather_description"] is not None
        assert isinstance(result["weather"]["daily"], list)

        # Test London
        result = await client.getWeatherByCity("London", "GB")
        assert result is not None
        assert "location" in result
        assert "weather" in result
        assert result["location"]["name"] == "London"
        assert result["location"]["country"] == "GB"
        assert isinstance(result["location"]["lat"], float)
        assert isinstance(result["location"]["lon"], float)
        assert result["weather"]["current"]["temp"] is not None
        assert isinstance(result["weather"]["current"]["temp"], float)
        assert result["weather"]["current"]["weather_description"] is not None
        assert isinstance(result["weather"]["daily"], list)

        # Test São Paulo
        result = await client.getWeatherByCity("São Paulo", "BR")
        assert result is not None
        assert "location" in result
        assert "weather" in result
        assert result["location"]["name"] == "São Paulo"
        assert result["location"]["country"] == "BR"
        assert isinstance(result["location"]["lat"], float)
        assert isinstance(result["location"]["lon"], float)
        assert result["weather"]["current"]["temp"] is not None
        assert isinstance(result["weather"]["current"]["temp"], float)
        assert result["weather"]["current"]["weather_description"] is not None
        assert isinstance(result["weather"]["daily"], list)

        # Test Tokyo
        result = await client.getWeatherByCity("Tokyo", "JP")
        assert result is not None
        assert "location" in result
        assert "weather" in result
        assert result["location"]["name"] == "Tokyo"
        assert result["location"]["country"] == "JP"
        assert isinstance(result["location"]["lat"], float)
        assert isinstance(result["location"]["lon"], float)
        assert result["weather"]["current"]["temp"] is not None
        assert isinstance(result["weather"]["current"]["temp"], float)
        assert result["weather"]["current"]["weather_description"] is not None
        assert isinstance(result["weather"]["daily"], list)


@pytest.mark.asyncio
async def testGetCoordinates():
    """Test getting coordinates by city name using golden data."""
    provider = GoldenDataProvider()
    cache = DictWeatherCache()

    async with provider.patchClient(OpenWeatherMapClient(apiKey="test_key", cache=cache)) as client:
        # Test Minsk
        result = await client.getCoordinates("Minsk", "BY")
        assert result is not None
        assert result["name"] == "Minsk"
        assert result["country"] == "BY"
        assert isinstance(result["lat"], float)
        assert isinstance(result["lon"], float)
        assert "local_names" in result
        assert isinstance(result["local_names"], dict)

        # Test London
        result = await client.getCoordinates("London", "GB")
        assert result is not None
        assert result["name"] == "London"
        assert result["country"] == "GB"
        assert isinstance(result["lat"], float)
        assert isinstance(result["lon"], float)
        assert "local_names" in result
        assert isinstance(result["local_names"], dict)

        # Test São Paulo
        result = await client.getCoordinates("São Paulo", "BR")
        assert result is not None
        assert result["name"] == "São Paulo"
        assert result["country"] == "BR"
        assert isinstance(result["lat"], float)
        assert isinstance(result["lon"], float)
        assert "local_names" in result
        assert isinstance(result["local_names"], dict)

        # Test Tokyo
        result = await client.getCoordinates("Tokyo", "JP")
        assert result is not None
        assert result["name"] == "Tokyo"
        assert result["country"] == "JP"
        assert isinstance(result["lat"], float)
        assert isinstance(result["lon"], float)
        assert "local_names" in result
        assert isinstance(result["local_names"], dict)


@pytest.mark.asyncio
async def testGetWeatherByCoordinates():
    """Test getting weather by coordinates using golden data."""
    provider = GoldenDataProvider()
    cache = DictWeatherCache()

    async with provider.patchClient(OpenWeatherMapClient(apiKey="test_key", cache=cache)) as client:
        # Test Minsk coordinates from golden data
        result = await client.getWeather(53.9024716, 27.5618225)
        assert result is not None
        assert isinstance(result["lat"], float)
        assert isinstance(result["lon"], float)
        assert result["timezone"] == "Europe/Minsk"
        assert isinstance(result["current"]["temp"], float)
        assert isinstance(result["current"]["humidity"], int)
        assert result["current"]["weather_description"] is not None
        assert isinstance(result["daily"], list)
        assert len(result["daily"]) > 0

        # Test London coordinates
        result = await client.getWeather(51.5073219, -0.1276474)
        assert result is not None
        assert isinstance(result["lat"], float)
        assert isinstance(result["lon"], float)
        assert "London" in result["timezone"]
        assert isinstance(result["current"]["temp"], float)
        assert isinstance(result["current"]["humidity"], int)
        assert result["current"]["weather_description"] is not None
        assert isinstance(result["daily"], list)
        assert len(result["daily"]) > 0

        # Test São Paulo coordinates
        result = await client.getWeather(-23.5505199, -46.6333094)
        assert result is not None
        assert isinstance(result["lat"], float)
        assert isinstance(result["lon"], float)
        assert "America/Sao_Paulo" == result["timezone"]
        assert isinstance(result["current"]["temp"], float)
        assert isinstance(result["current"]["humidity"], int)
        assert result["current"]["weather_description"] is not None
        assert isinstance(result["daily"], list)
        assert len(result["daily"]) > 0

        # Test Tokyo coordinates
        result = await client.getWeather(35.689487, 139.691711)
        assert result is not None
        assert isinstance(result["lat"], float)
        assert isinstance(result["lon"], float)
        assert "Asia/Tokyo" == result["timezone"]
        assert isinstance(result["current"]["temp"], float)
        assert isinstance(result["current"]["humidity"], int)
        assert result["current"]["weather_description"] is not None
        assert isinstance(result["daily"], list)
        assert len(result["daily"]) > 0


@pytest.mark.asyncio
async def testClientWithMissingData():
    """Test that missing data raises appropriate exception."""
    provider = GoldenDataProvider()
    cache = DictWeatherCache()

    async with provider.patchClient(OpenWeatherMapClient(apiKey="test_key", cache=cache)) as client:
        # Test with a city that's not in our golden data
        result = await client.getWeatherByCity("NonExistentCity", "XX")
        # Should return None when data is not found
        assert result is None

        # Test coordinates that are not in our golden data
        result = await client.getWeather(0.0, 0.0)
        # Should return None when data is not found
        assert result is None

        # Test geocoding for a city not in our golden data
        result = await client.getCoordinates("NonExistentCity", "XX")
        # Should return None when data is not found
        assert result is None
