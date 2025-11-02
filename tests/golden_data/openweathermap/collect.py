#!/usr/bin/env python3
"""
Golden Data Collection Script for OpenWeatherMap API

This script collects real API responses from OpenWeatherMap and saves them
as golden data for testing. It uses the actual OpenWeatherMapClient methods
but patches HTTP calls to capture raw responses.

Usage:
    ./venv/bin/python3 tests/golden_data/openweathermap/collect.py

Requirements:
    - .env file with OPENWEATHERMAP_API_KEY
    - inputs/locations.json with test locations
"""
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from lib import utils  # noqa: E402
from lib.openweathermap.client import OpenWeatherMapClient  # noqa: E402
from lib.openweathermap.dict_cache import DictWeatherCache  # noqa: E402
from tests.golden_data.openweathermap.types import GoldenDataEntry  # noqa: E402

REDACTED_API_KEY = "REDACTED_API_KEY"


class GoldenDataCollector:
    """Collects golden data from OpenWeatherMap API using actual client methods."""

    def __init__(self, apiKey: str, outputDir: Path):
        """
        Initialize collector.

        Args:
            apiKey: OpenWeatherMap API key
            outputDir: Directory to save golden data
        """
        self.apiKey = apiKey
        self.outputDir = outputDir
        self.outputDir.mkdir(parents=True, exist_ok=True)

    async def collectCurrentWeather(self, cityName: str, countryCode: str = "") -> None:
        """
        Collect current weather data for a city using actual client method.

        Args:
            cityName: Name of the city
            countryCode: Optional country code (e.g., "BY")
        """
        print(f"Collecting current weather for {cityName}...")

        client = OpenWeatherMapClient(
            apiKey=self.apiKey,
            cache=DictWeatherCache(),
            geocodingTTL=0,  # Disable caching for collection
            weatherTTL=0,  # Disable caching for collection
        )

        requests: List[GoldenDataEntry] = []

        # Patch the _makeRequest method to capture raw responses
        # original_make_request = client._makeRequest

        async def patched_make_request(url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Patched version of _makeRequest that captures raw responses."""
            import httpx

            data: GoldenDataEntry = {
                "call": {
                    "method": "getCurrentWeatherByCity",
                    "params": {
                        "city": cityName,
                        "countryCode": countryCode,
                    },
                    "date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
                "request": {
                    "url": url.replace(self.apiKey, REDACTED_API_KEY),
                    "params": {k: str(v).replace(self.apiKey, REDACTED_API_KEY) for k, v in params.items()},
                },
                "response": {
                    "raw": "",
                    "status_code": 0,
                },
            }

            # Make the actual request
            async with httpx.AsyncClient(timeout=client.requestTimeout) as session:
                response = await session.get(url, params=params)
                raw_response = response.text
                data["response"]["raw"] = raw_response
                data["response"]["status_code"] = response.status_code
                try:
                    data["response"]["json"] = response.json()
                except Exception as e:
                    print(f"Error: can't get JSON response: {e}")
                requests.append(data)

                # Return parsed response for normal client operation
                if response.status_code == 200:
                    return response.json()
                else:
                    return None

        # Apply the patch
        client._makeRequest = patched_make_request

        try:
            # Call the client method - this will use our patched _makeRequest
            _ = await client.getWeatherByCity(cityName, countryCode if countryCode else None)

            filename = f"getWeatherByCity.{cityName}.{countryCode}.json"
            filepath = self.outputDir / filename
            with open(filepath, "w") as f:
                f.write(utils.jsonDumps(requests, indent=2))

        except Exception as e:
            print(f" Error collecting current weather for {cityName}: {e}")

    async def collectGeocoding(self, cityName: str, countryCode: str = "") -> None:
        """
        Collect geocoding data for a city.

        Args:
            cityName: Name of the city
            countryCode: Optional country code
        """
        print(f"Collecting geocoding for {cityName}...")

        client = OpenWeatherMapClient(
            apiKey=self.apiKey,
            cache=DictWeatherCache(),
            geocodingTTL=0,  # Disable caching for collection
            weatherTTL=0,  # Disable caching for collection
        )

        requests: List[GoldenDataEntry] = []

        # Patch the _makeRequest method to capture raw responses
        async def patched_make_request(url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Patched version of _makeRequest that captures raw responses."""
            import httpx

            # Set request info for capture
            data: GoldenDataEntry = {
                "call": {
                    "method": "getCoordinates",
                    "params": {
                        "city": cityName,
                        "countryCode": countryCode,
                    },
                    "date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
                "request": {
                    "url": url.replace(self.apiKey, REDACTED_API_KEY),
                    "params": {k: str(v).replace(self.apiKey, REDACTED_API_KEY) for k, v in params.items()},
                },
                "response": {
                    "raw": "",
                    "status_code": 0,
                },
            }

            # Make the actual request
            async with httpx.AsyncClient(timeout=client.requestTimeout) as session:
                response = await session.get(url, params=params)
                raw_response = response.text

                data["response"]["raw"] = raw_response
                data["response"]["status_code"] = response.status_code
                try:
                    data["response"]["json"] = response.json()
                except Exception as e:
                    print(f"Error: can't get JSON response: {e}")
                requests.append(data)

                # Return parsed response for normal client operation
                if response.status_code == 200:
                    return response.json()
                else:
                    return None

        # Apply the patch
        client._makeRequest = patched_make_request

        try:
            # Call the client method - this will use our patched _makeRequest
            _ = await client.getCoordinates(cityName, countryCode if countryCode else None)

            filename = f"getCoordinates.{cityName}.{countryCode}.json"
            filepath = self.outputDir / filename
            with open(filepath, "w") as f:
                f.write(utils.jsonDumps(requests, indent=2))

        except Exception as e:
            print(f" Error collecting geocoding for {cityName}: {e}")

    async def collectWeatherByCoordinates(self, lat: float, lon: float, description: str = "") -> None:
        """
        Collect weather data for specific coordinates.

        Args:
            lat: Latitude
            lon: Longitude
            description: Optional description for the file name
        """
        print(f"Collecting weather for coordinates {lat}, {lon}...")

        client = OpenWeatherMapClient(
            apiKey=self.apiKey,
            cache=DictWeatherCache(),
            geocodingTTL=0,  # Disable caching for collection
            weatherTTL=0,  # Disable caching for collection
        )

        requests: List[GoldenDataEntry] = []

        # Patch the _makeRequest method to capture raw responses
        async def patched_make_request(url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Patched version of _makeRequest that captures raw responses."""
            import httpx

            # Set request info for capture
            data: GoldenDataEntry = {
                "call": {
                    "method": "getWeatherByCoordinates",
                    "params": {
                        "lat": lat,
                        "lon": lon,
                    },
                    "date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
                "request": {
                    "url": url.replace(self.apiKey, REDACTED_API_KEY),
                    "params": {k: str(v).replace(self.apiKey, REDACTED_API_KEY) for k, v in params.items()},
                },
                "response": {
                    "raw": "",
                    "status_code": 0,
                },
            }

            # Make the actual request
            async with httpx.AsyncClient(timeout=client.requestTimeout) as session:
                response = await session.get(url, params=params)
                raw_response = response.text

                data["response"]["raw"] = raw_response
                data["response"]["status_code"] = response.status_code
                try:
                    data["response"]["json"] = response.json()
                except Exception as e:
                    print(f"Error: can't get JSON response: {e}")
                requests.append(data)

                # Return parsed response for normal client operation
                if response.status_code == 200:
                    return response.json()
                else:
                    return None

        # Apply the patch
        client._makeRequest = patched_make_request

        try:
            # Call the client method - this will use our patched _makeRequest
            _ = await client.getWeather(lat, lon)

            # Create filename with coordinates
            latStr = f"{lat:.7f}".rstrip("0").rstrip(".")
            lonStr = f"{lon:.7f}".rstrip("0").rstrip(".")
            filename = f"getWeatherByCoordinates.{latStr}.{lonStr}.json"
            if description:
                filename = f"getWeatherByCoordinates.{description}.{latStr}.{lonStr}.json"
            filepath = self.outputDir / filename
            with open(filepath, "w") as f:
                f.write(utils.jsonDumps(requests, indent=2))

        except Exception as e:
            print(f" Error collecting weather for coordinates {lat}, {lon}: {e}")


async def main():
    """Main collection workflow."""
    # Load environment variables (try .env.test first for testing)
    utils.load_dotenv()
    apiKey = os.getenv("OPENWEATHERMAP_API_KEY")
    if not apiKey:
        print("Error: OPENWEATHERMAP_API_KEY not found in .env or .env.test file")
        return

    # Setup paths
    scriptDir = Path(__file__).parent
    inputsDir = scriptDir / "inputs"
    outputsDir = scriptDir / "raw"  # Save to raw directory as specified

    # Load input data
    locationsFile = inputsDir / "locations.json"
    if not locationsFile.exists():
        print(f"Error: {locationsFile} not found")
        return

    with open(locationsFile, "r", encoding="utf-8") as f:
        locations = json.load(f)

    # Initialize collector
    collector = GoldenDataCollector(apiKey=apiKey, outputDir=outputsDir)

    # Collect data for each location
    print(f"\n  Collecting golden data for {len(locations)} locations...\n")

    for location in locations:
        cityName = location["city"]
        countryCode = location.get("country_code", "")

        try:
            # Collect current weather
            await collector.collectCurrentWeather(cityName, countryCode)

            # Collect geocoding
            await collector.collectGeocoding(cityName, countryCode)

            print()  # Empty line between locations

        except Exception as e:
            print(f"Error collecting data for {cityName}: {e}\n")
            continue

    print("\nGolden data collection complete!")
    print(f" Data saved to: {outputsDir}")

    # Collect data for specific coordinates that are used in tests
    print("\n  Collecting golden data for specific coordinates...\n")

    # São Paulo coordinates from the test
    await collector.collectWeatherByCoordinates(-23.5505199, -46.6333094, "SaoPaulo")

    # Other coordinates from the test
    await collector.collectWeatherByCoordinates(53.9024716, 27.5618225, "Minsk")
    await collector.collectWeatherByCoordinates(51.5073219, -0.1276474, "London")
    await collector.collectWeatherByCoordinates(35.689487, 139.691711, "Tokyo")

    print("\nAdditional golden data collection complete!")


if __name__ == "__main__":
    asyncio.run(main())
