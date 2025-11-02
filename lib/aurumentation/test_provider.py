"""Tests for the GoldenDataProvider functionality.

This module demonstrates how to use the GoldenDataProvider for testing
with recorded HTTP traffic.
"""

import pytest

from lib.aurumentation import GoldenDataProvider, useGoldenData


def test_load_scenario():
    """Test loading a specific golden data scenario."""
    provider = GoldenDataProvider("tests/golden_data/openweathermap/raw")

    # Load a specific scenario
    scenario = provider.loadScenario("getWeatherByCity.London.GB.json")

    # Verify the scenario was loaded correctly
    assert scenario is not None
    assert len(scenario["recordings"]) > 0
    assert scenario["functionName"] == "getCurrentWeatherByCity"


def test_load_all_scenarios():
    """Test loading all golden data scenarios from a directory."""
    provider = GoldenDataProvider("tests/golden_data/openweathermap/raw")

    # Load all scenarios
    scenarios = provider.loadAllScenarios()

    # Verify scenarios were loaded
    assert len(scenarios) > 0
    assert "getWeatherByCity.London.GB" in scenarios


def test_get_scenario():
    """Test getting a loaded scenario by name."""
    provider = GoldenDataProvider("tests/golden_data/openweathermap/raw")

    # Load a scenario first
    provider.loadScenario("getWeatherByCity.London.GB.json")

    # Get the scenario by name
    scenario = provider.getScenario("getWeatherByCity.London.GB")

    # Verify the scenario was retrieved correctly
    assert scenario is not None
    assert len(scenario["recordings"]) > 0


def test_create_client():
    """Test creating an httpx client that replays a scenario."""
    provider = GoldenDataProvider("tests/golden_data/openweathermap/raw")

    # Load a scenario
    provider.loadScenario("getWeatherByCity.London.GB.json")

    # Create a client that replays the scenario
    client = provider.createClient("getWeatherByCity.London.GB")

    # Verify the client was created
    assert client is not None

    # Clean up
    import asyncio

    asyncio.run(client.aclose())


def test_context_manager():
    """Test using GoldenDataProvider as a context manager."""
    with GoldenDataProvider("tests/golden_data/openweathermap/raw") as provider:
        # Load and use a scenario within the context
        scenario = provider.loadScenario("getWeatherByCity.London.GB.json")
        assert scenario is not None


@pytest.mark.asyncio
async def test_async_context_manager():
    """Test using GoldenDataProvider as an async context manager."""
    async with GoldenDataProvider("tests/golden_data/openweathermap/raw") as provider:
        # Load and use a scenario within the async context
        scenario = provider.loadScenario("getWeatherByCity.London.GB.json")
        assert scenario is not None


# Test using the pytest fixtures


def test_golden_data_provider_fixture(provider: GoldenDataProvider):
    """Test the goldenDataProvider pytest fixture."""
    # The fixture should provide a GoldenDataProvider instance
    assert isinstance(provider, GoldenDataProvider)

    # Load all scenarios using the fixture
    scenarios = provider.loadAllScenarios()
    assert len(scenarios) > 0


@pytest.mark.golden("openweathermap/raw/getWeatherByCity.London.GB")
@pytest.mark.asyncio
async def test_golden_client_fixture(client):
    """Test the goldenClient pytest fixture with a marker."""
    # The fixture should provide an httpx client
    assert client is not None

    # The client should be configured to replay the specified scenario
    # (In a real test, you would make HTTP requests here)


@useGoldenData("openweathermap/raw/getWeatherByCity.London.GB.json")
@pytest.mark.asyncio
async def test_use_golden_data_decorator():
    """Test the @useGoldenData decorator."""
    # This test is marked with the decorator, which adds the golden marker
    # The actual functionality is tested through the goldenClient fixture
    pass


# Example of how to use the provider in a real test with a client that makes HTTP requests


@pytest.mark.golden("openweathermap/raw/getWeatherByCity.London.GB")
@pytest.mark.asyncio
async def test_openweathermap_client_with_golden_data(goldenClient):
    """Test OpenWeatherMap client with golden data."""
    # Import OpenWeatherMapClient here to avoid circular imports
    from lib.openweathermap.client import OpenWeatherMapClient

    # Create the client with the golden data replay client
    # We need to patch the _makeRequest method to use our golden client
    owm_client = OpenWeatherMapClient(apiKey="test")
    owm_client._makeRequest = goldenClient.get

    # Make a request - this will be replayed from the golden data
    result = await owm_client.getWeatherByCity("London", "GB")

    # Verify the result
    assert result is not None
    assert result["location"]["name"] == "London"
