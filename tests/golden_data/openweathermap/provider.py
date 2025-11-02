"""
Golden Data Provider for OpenWeatherMapClient testing.

This module provides a GoldenDataProvider class that can patch the OpenWeatherMapClient
to use golden data instead of making real API calls during testing.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from lib.aurumentation import GoldenDataProvider as AurumentationProvider
from lib.openweathermap.client import OpenWeatherMapClient
from tests.golden_data.openweathermap.custom_transport import OpenWeatherMapReplayTransport

logger = logging.getLogger(__name__)


class GoldenDataProvider:
    """
    Provider for OpenWeatherMap golden data testing.

    Uses the aurumentation GoldenDataProvider to load scenarios from the golden_v2 directory
    and provides a method to patch the OpenWeatherMapClient to return golden data
    instead of making real API calls.
    """

    def __init__(self):
        """
        Initialize the GoldenDataProvider.

        Loads all golden data scenarios from the golden_v2/ directory.
        """
        self.scriptDir = Path(__file__).parent
        self.goldenV2Dir = self.scriptDir / "golden_v2"
        self.inputsDir = self.scriptDir / "inputs"
        self.missingDataLog = self.inputsDir / "missing_data.log"

        # Ensure inputs directory exists
        self.inputsDir.mkdir(parents=True, exist_ok=True)

        # Load all golden data scenarios
        self.provider = AurumentationProvider(str(self.goldenV2Dir))
        self.scenarios = self.provider.loadAllScenarios()

        # Map of city/country to scenario names
        self.cityToScenarioMap = {
            ("Minsk", "BY"): "Get weather for Minsk_ Belarus",
            ("London", "GB"): "Get weather for London_ UK",
            ("São Paulo", "BR"): "Get weather for São Paulo_ Brazil",
            ("Tokyo", "JP"): "Get weather for Tokyo_ Japan",
        }

    def _getScenarioName(self, url: str, params: Dict[str, str]) -> Optional[str]:
        """
        Get the scenario name for the given URL and parameters.

        Args:
            url: API endpoint URL
            params: Dictionary of query parameters

        Returns:
            Scenario name string or None if not found
        """
        # Handle geocoding requests
        if "q" in params:
            # Format: "City,CountryCode"
            city_country = params["q"]
            if "," in city_country:
                city, country_code = city_country.split(",", 1)
                return self.cityToScenarioMap.get((city, country_code))
        elif "lat" in params and "lon" in params:
            # For coordinates, we need to find the right scenario
            # This is a simplified approach - in reality, we'd need to match coordinates to cities
            lat = float(params["lat"])
            lon = float(params["lon"])
            if abs(lat - 53.9025) < 0.1 and abs(lon - 27.5618) < 0.1:
                return "Get weather for Minsk_ Belarus"
            elif abs(lat - 51.5073) < 0.1 and abs(lon - -0.1276) < 0.1:
                return "Get weather for London_ UK"
            elif abs(lat - -23.5505) < 0.1 and abs(lon - -46.6333) < 0.1:
                return "Get weather for São Paulo_ Brazil"
            elif abs(lat - 35.6895) < 0.1 and abs(lon - 139.6917) < 0.1:
                return "Get weather for Tokyo_ Japan"

        return None

    @asynccontextmanager
    async def patchClient(self, client: OpenWeatherMapClient):
        """
        Async context manager that patches the client's _makeRequest method.

        Args:
            client: OpenWeatherMapClient instance to patch

        Yields:
            The patched client

        Example:
            provider = GoldenDataProvider()
            client = OpenWeatherMapClient(apiKey="test", cache=cache)

            async with provider.patchClient(client):
                # Client will now return golden data instead of making real API calls
                result = await client.getWeatherByCity("Minsk", "BY")
        """
        # Store original method
        originalMakeRequest = client._makeRequest

        # Create patched method
        async def patchedMakeRequest(url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """
            Patched version of _makeRequest that returns golden data.

            Args:
                url: API endpoint URL
                params: Query parameters

            Returns:
                Parsed JSON response from golden data
            """
            try:
                # Get scenario name for this request
                scenarioName = self._getScenarioName(url, params)

                if scenarioName is None or scenarioName not in self.scenarios:
                    logger.error(f"No scenario found for URL {url} with params {params}")
                    return None

                # Get the scenario
                scenario = self.scenarios[scenarioName]

                # Create custom transport that replays the scenario
                transport = OpenWeatherMapReplayTransport(recordings=scenario["recordings"])

                # Create client with custom transport
                replayClient = httpx.AsyncClient(transport=transport)

                # Make the request using the replay client
                full_url = f"{url}?{urlencode(params)}"
                response = await replayClient.get(full_url)

                # Clean up the replay client
                await replayClient.aclose()

                # Return the JSON response
                return response.json()

            except Exception as e:
                # Log error and return None to match client behavior
                logger.error(f"Error replaying golden data for URL {url}: {e}")
                return None

        # Apply patch
        client._makeRequest = patchedMakeRequest

        try:
            # Yield control to the caller
            yield client
        finally:
            # Restore original method
            client._makeRequest = originalMakeRequest
