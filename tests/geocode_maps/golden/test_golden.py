"""Golden data tests for Geocode Maps client.

These tests use recorded HTTP traffic to test the Geocode Maps client
without making actual API calls.
"""

import pytest

from lib.aurumentation import GoldenDataProvider, GoldenDataReplayer, baseGoldenDataProvider
from lib.geocode_maps.client import GeocodeMapsClient
from tests.geocode_maps.golden import GOLDEN_DATA_PATH
from tests.lib_ratelimiter import initRateLimiter


@pytest.fixture(scope="session")
def goldenDataProvider() -> GoldenDataProvider:
    """Fixture that provides a GoldenDataProvider for Geocode Maps tests."""
    return baseGoldenDataProvider(str(GOLDEN_DATA_PATH))


@pytest.mark.asyncio
async def test_geocode_maps_golden(goldenDataProvider):
    """Test Geocode Maps client methods using golden data.

    This test uses recorded HTTP traffic to verify that the Geocode Maps client
    correctly handles different API methods (search, reverse, lookup) without
    making actual API calls.

    Args:
        goldenDataProvider: Provider for golden data scenarios
    """
    # Initialize rate limiter
    await initRateLimiter()

    # Get the scenario with all golden data
    scenario = goldenDataProvider.getScenario(None)

    # Use GoldenDataReplayer as context manager to patch httpx globally
    async with GoldenDataReplayer(scenario):
        # Create client with test API key
        client = GeocodeMapsClient(apiKey="test_key")

        # Test search method
        searchResult = await client.search("Angarsk, Russia")
        assert searchResult is not None
        assert isinstance(searchResult, list)
        assert len(searchResult) > 0
        firstSearchResult = searchResult[0]
        assert "lat" in firstSearchResult
        assert "lon" in firstSearchResult
        assert "display_name" in firstSearchResult
        assert "place_id" in firstSearchResult
        assert "osm_type" in firstSearchResult
        assert "osm_id" in firstSearchResult

        # Test reverse method
        reverseResult = await client.reverse(52.5443, 103.8882)
        assert reverseResult is not None
        assert isinstance(reverseResult, dict)
        assert "lat" in reverseResult
        assert "lon" in reverseResult
        assert "display_name" in reverseResult
        assert "place_id" in reverseResult
        assert "osm_type" in reverseResult
        assert "osm_id" in reverseResult

        # Test lookup method
        lookupResult = await client.lookup(["R2623018"])
        assert lookupResult is not None
        assert isinstance(lookupResult, list)
        assert len(lookupResult) > 0
        firstLookupResult = lookupResult[0]
        assert "osm_id" in firstLookupResult
        assert "display_name" in firstLookupResult
        assert "place_id" in firstLookupResult
        assert "osm_type" in firstLookupResult
        assert "lat" in firstLookupResult
        assert "lon" in firstLookupResult
