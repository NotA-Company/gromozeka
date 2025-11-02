"""Pytest fixtures and helper functions for golden data testing.

This module provides pytest fixtures and decorators for easily using
golden data in tests.
"""

import pytest

from .provider import GoldenDataProvider


@pytest.fixture
def goldenDataProvider():
    """Fixture that provides a GoldenDataProvider for tests."""
    provider = GoldenDataProvider("tests/golden_data")
    yield provider


@pytest.fixture
async def goldenClient(goldenDataProvider, request):
    """Fixture that provides an httpx client with golden data replay.

    Usage:
        @pytest.mark.golden("openweathermap/golden/getWeatherByCity.London.GB")
        async def test_weather(goldenClient):
            # goldenClient will replay the specified scenario
            pass
    """
    # Get the golden marker to determine which scenario to use
    marker = request.node.get_closest_marker("golden")
    if marker is None:
        raise ValueError("goldenClient fixture requires @pytest.mark.golden decorator")

    scenario_path = marker.args[0] if marker.args else None
    if scenario_path is None:
        raise ValueError("goldenClient fixture requires a scenario path in @pytest.mark.golden")

    # Create client that replays the specified scenario
    client = goldenDataProvider.createClient(scenario_path)
    yield client

    # Clean up client
    await client.aclose()


def useGoldenData(scenarioPath: str):
    """Decorator that can be used to mark test functions to use specific golden data.

    Args:
        scenarioPath: Path to the golden data scenario to use

    Usage:
        @useGoldenData("openweathermap/golden/getWeatherByCity.London.GB.json")
        async def test_weather_london():
            # Test implementation
            pass
    """

    def decorator(func):
        # Add the golden marker to the function
        marker = pytest.mark.golden(scenarioPath)
        func = marker(func)
        return func

    return decorator
