"""Golden data tests for OpenWeatherMap client.

These tests use recorded HTTP traffic to test the OpenWeatherMap client
without making actual API calls.
"""

import pytest

from lib.aurumentation import baseGoldenDataProvider
from lib.aurumentation.provider import GoldenDataProvider
from lib.aurumentation.replayer import GoldenDataReplayer
from lib.openweathermap.client import OpenWeatherMapClient
from tests.lib_ratelimiter import initRateLimiter

from . import GOLDEN_DATA_PATH


@pytest.fixture(scope="session")
def owmGoldenDataProvider() -> GoldenDataProvider:
    """Fixture that provides a GoldenDataProvider for OpenWeatherMap tests."""
    return baseGoldenDataProvider(GOLDEN_DATA_PATH)


@pytest.mark.asyncio
async def testOpenweathermapClientInitialization():
    """Test that OpenWeatherMapClient can be initialized."""
    client = OpenWeatherMapClient(apiKey="test-key")
    assert client is not None
    assert client.apiKey == "test-key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "city,country_code,expected_name,expected_country",
    [
        ("London", "GB", "London", "GB"),
        ("Minsk", "BY", "Minsk", "BY"),
        ("Tokyo", "JP", "Tokyo", "JP"),
        ("São Paulo", "BR", "São Paulo", "BR"),
    ],
)
async def testGetWeatherForCity(owmGoldenDataProvider, city, country_code, expected_name, expected_country):
    """Test getting weather for different cities using golden data."""
    # Get the scenario with all golden data
    await initRateLimiter()
    scenario = owmGoldenDataProvider.getScenario(None)

    # Use GoldenDataReplayer as context manager to patch httpx globally
    async with GoldenDataReplayer(scenario):
        # Create the OpenWeatherMapClient - it will automatically use the patched httpx
        owmClient = OpenWeatherMapClient(apiKey="test")

        # Make a request - this will be replayed from the golden data
        result = await owmClient.getWeatherByCity(city, country_code)

        # Verify the result
        assert result is not None
        assert result["location"]["name"] == expected_name
        assert result["location"]["country"] == expected_country
        assert "weather" in result
        assert "current" in result["weather"]
        assert "daily" in result["weather"]

        # Verify current weather data
        current = result["weather"]["current"]
        assert "temp" in current
        assert "weather_main" in current
        assert "weather_description" in current

        # Verify daily forecast data
        daily = result["weather"]["daily"]
        assert len(daily) > 0
        assert "temp_day" in daily[0]
        assert "weather_main" in daily[0]
