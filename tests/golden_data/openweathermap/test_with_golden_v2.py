"""
Tests for OpenWeatherMap client using Golden Data System v2

This file demonstrates how to use the new golden data system v2
to test OpenWeatherMap client methods with replayed HTTP calls.
"""

import pytest
from lib.openweathermap.client import OpenWeatherMapClient
from lib.openweathermap.null_cache import NullWeatherCache
from tests.golden_data.openweathermap.provider import GoldenDataProvider


@pytest.mark.asyncio
async def test_get_weather_by_city_minsk():
    """Test getting weather for Minsk using golden data."""
    provider = GoldenDataProvider()
    owm = OpenWeatherMapClient(apiKey="dummy_key", cache=NullWeatherCache())
    
    async with provider.patchClient(owm) as client:
        # Call the method - it will use golden data
        result = await client.getWeatherByCity("Minsk", "BY")
        
        # Verify results
        assert result is not None
        assert result["location"]["name"] == "Minsk"
        assert result["location"]["country"] == "BY"
        assert "weather" in result
        assert "current" in result["weather"]
        assert "daily" in result["weather"]


@pytest.mark.asyncio
async def test_get_weather_by_city_london():
    """Test getting weather for London using golden data."""
    provider = GoldenDataProvider()
    owm = OpenWeatherMapClient(apiKey="dummy_key", cache=NullWeatherCache())
    
    async with provider.patchClient(owm) as client:
        # Call the method - it will use golden data
        result = await client.getWeatherByCity("London", "GB")
        
        # Verify results
        assert result is not None
        assert result["location"]["name"] == "London"
        assert result["location"]["country"] == "GB"
        assert "weather" in result
        assert "current" in result["weather"]
        assert "daily" in result["weather"]


@pytest.mark.asyncio
async def test_get_weather_by_city_sao_paulo():
    """Test getting weather for São Paulo using golden data."""
    provider = GoldenDataProvider()
    owm = OpenWeatherMapClient(apiKey="dummy_key", cache=NullWeatherCache())
    
    async with provider.patchClient(owm) as client:
        # Call the method - it will use golden data
        result = await client.getWeatherByCity("São Paulo", "BR")
        
        # Verify results
        assert result is not None
        assert result["location"]["name"] == "São Paulo"
        assert result["location"]["country"] == "BR"
        assert "weather" in result
        assert "current" in result["weather"]
        assert "daily" in result["weather"]


@pytest.mark.asyncio
async def test_get_weather_by_coordinates_minsk():
    """Test getting weather by coordinates for Minsk using golden data."""
    provider = GoldenDataProvider()
    owm = OpenWeatherMapClient(apiKey="dummy_key", cache=NullWeatherCache())
    
    async with provider.patchClient(owm) as client:
        # Call the method with Minsk coordinates - it will use golden data
        # Minsk coordinates from the golden data: lat=53.9024716, lon=27.5618225
        result = await client.getWeather(53.9024716, 27.5618225)
        
        # Verify results
        assert result is not None
        assert "current" in result
        assert "daily" in result
        # Check that the coordinates are approximately correct
        assert abs(result["lat"] - 53.9025) < 0.01
        assert abs(result["lon"] - 27.5618) < 0.01


@pytest.mark.asyncio
async def test_get_coordinates_minsk():
    """Test getting coordinates for Minsk using golden data."""
    provider = GoldenDataProvider()
    owm = OpenWeatherMapClient(apiKey="dummy_key", cache=NullWeatherCache())
    
    async with provider.patchClient(owm) as client:
        # Call the method - it will use golden data
        result = await client.getCoordinates("Minsk", "BY")
        
        # Verify results
        assert result is not None
        assert result["name"] == "Minsk"
        assert result["country"] == "BY"
        # Check that the coordinates are approximately correct
        assert abs(result["lat"] - 53.9025) < 0.01
        assert abs(result["lon"] - 27.5618) < 0.01