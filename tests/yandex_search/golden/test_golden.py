"""Golden data tests for Yandex Search client.

These tests use recorded HTTP traffic to test the Yandex Search client
without making actual API calls.
"""

import pytest

from lib.aurumentation import baseGoldenDataProvider
from lib.aurumentation.provider import GoldenDataProvider
from lib.aurumentation.replayer import GoldenDataReplayer
from lib.yandex_search.client import YandexSearchClient

from . import GOLDEN_DATA_PATH


@pytest.fixture(scope="session")
def yandexSearchGoldenDataProvider() -> GoldenDataProvider:
    """Fixture that provides a GoldenDataProvider for Yandex Search tests."""
    return baseGoldenDataProvider(GOLDEN_DATA_PATH)


@pytest.mark.asyncio
async def testYandexSearchClientInitialization():
    """Test that YandexSearchClient can be initialized."""
    client = YandexSearchClient(apiKey="test-key", folderId="test-folder")
    assert client is not None
    assert client.apiKey == "test-key"
    assert client.folderId == "test-folder"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "python programming",
        "программирование на Python",
        "python 3.9 tutorial",
        'python programming & "machine learning"',
    ],
)
async def testSearchWithGoldenData(yandexSearchGoldenDataProvider, query):
    """Test searching with different queries using golden data."""
    # Get the scenario with all golden data
    scenario = yandexSearchGoldenDataProvider.getScenario(None)

    # Use GoldenDataReplayer as context manager to patch httpx globally
    async with GoldenDataReplayer(scenario):
        # Create the YandexSearchClient - it will automatically use the patched httpx
        yandexClient = YandexSearchClient(apiKey="test", folderId="test-folder")

        # Make a request - this will be replayed from the golden data
        result = await yandexClient.search(query)

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
