"""Golden Data Provider for OpenWeatherMap tests.

This module provides a provider for loading and replaying OpenWeatherMap golden data scenarios.
"""

from lib.aurumentation import GoldenDataProvider


class OpenWeatherMapGoldenDataProvider(GoldenDataProvider):
    """Provider for loading and replaying OpenWeatherMap golden data scenarios."""

    def __init__(self):
        """Initialize the OpenWeatherMapGoldenDataProvider."""
        super().__init__("tests/openweathermap/golden/data")
