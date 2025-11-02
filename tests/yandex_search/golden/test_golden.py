"""Golden data tests for Yandex Search client.

These tests use recorded HTTP traffic to test the Yandex Search client
without making actual API calls.
"""

import pytest

from lib.aurumentation import baseGoldenDataProvider
from lib.aurumentation.provider import GoldenDataProvider
from lib.yandex_search.client import YandexSearchClient


@pytest.fixture(scope="session")
def yandexSearchGoldenDataProvider() -> GoldenDataProvider:
    """Fixture that provides a GoldenDataProvider for Yandex Search tests."""
    return baseGoldenDataProvider("tests/yandex_search/golden/data")


@pytest.fixture
async def yandexSearchGoldenClient(yandexSearchGoldenDataProvider: GoldenDataProvider):
    """Fixture that provides an httpx client with Yandex Search golden data replay."""
    # Create client that replays the specified scenario
    client = yandexSearchGoldenDataProvider.createClient(None)
    yield client

    # Clean up client
    await client.aclose()


@pytest.mark.asyncio
async def testYandexSearchClientInitialization():
    """Test that YandexSearchClient can be initialized."""
    client = YandexSearchClient(apiKey="test-key", folderId="test-folder")
    assert client is not None
    assert client.apiKey == "test-key"
    assert client.folderId == "test-folder"


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "python programming",
    "программирование на Python",
    "python 3.9 tutorial",
    "python programming & \"machine learning\""
])
async def testSearchWithGoldenData(yandexSearchGoldenClient, query):
    """Test searching with different queries using golden data."""
    # Create the client with the golden data replay client
    yandex_client = YandexSearchClient(apiKey="test", folderId="test-folder")

    # Create a wrapper function that matches the expected signature
    async def makeRequestWrapper(request):
        # Convert the request to the format expected by the golden client
        # The Yandex Search API expects a POST request with JSON body
        response = await yandexSearchGoldenClient.post(
            "https://searchapi.api.cloud.yandex.net/v2/web/search",
            json=request
        )
        # Parse the JSON response and extract the rawData field
        json_response = response.json()
        # Return the parsed XML response
        from lib.yandex_search.xml_parser import parseSearchResponse
        return parseSearchResponse(json_response["rawData"])

    yandex_client._makeRequest = makeRequestWrapper

    # Make a request - this will be replayed from the golden data
    result = await yandex_client.search(query)

    # Verify the result
    assert result is not None
    assert "found" in result
    assert "groups" in result
    assert isinstance(result["found"], int)
    assert isinstance(result["groups"], list)

    # Verify groups structure
    if result["groups"]:
        group = result["groups"][0]
        assert isinstance(group, list)

        # Verify first result has required fields
        if group:
            doc = group[0]
            assert "url" in doc
            assert "title" in doc
            assert "domain" in doc
            assert isinstance(doc["url"], str)
            assert isinstance(doc["title"], str)
            assert isinstance(doc["domain"], str)