"""
Golden data integration tests for YandexSearchClient

This module contains integration tests that use real golden data collected
from the Yandex Search API to test the YandexSearchClient functionality.
"""

import pytest

from lib.yandex_search.client import YandexSearchClient
from lib.yandex_search.dict_cache import DictSearchCache
from tests.golden_data.yandex_search import GoldenDataProvider


@pytest.mark.asyncio
async def testSearchPythonProgramming():
    """Test searching for 'python programming' using golden data."""
    provider = GoldenDataProvider()
    cache = DictSearchCache()

    async with provider.patchClient(
        YandexSearchClient(apiKey="test_key", folderId="test_folder", cache=cache)
    ) as client:
        result = await client.search("python programming")

        assert result is not None
        assert "found" in result
        assert result["found"] > 0
        assert "groups" in result
        assert isinstance(result["groups"], list)
        assert len(result["groups"]) > 0

        # Validate first group structure
        firstGroup = result["groups"][0]
        assert isinstance(firstGroup, list)
        assert len(firstGroup) > 0

        # Validate first result structure
        firstResult = firstGroup[0]
        assert "url" in firstResult
        assert "title" in firstResult
        assert "passages" in firstResult
        assert isinstance(firstResult["url"], str)
        assert len(firstResult["url"]) > 0
        assert isinstance(firstResult["title"], str)
        assert len(firstResult["title"]) > 0
        assert isinstance(firstResult["passages"], list)


@pytest.mark.asyncio
async def testSearchPythonProgrammingWithSpecialCharacters():
    """Test searching for 'python programming !@#$%^&*()' using golden data."""
    provider = GoldenDataProvider()
    cache = DictSearchCache()

    async with provider.patchClient(
        YandexSearchClient(apiKey="test_key", folderId="test_folder", cache=cache)
    ) as client:
        result = await client.search("python programming !@#$%^&*()")

        assert result is not None
        assert "found" in result
        assert result["found"] > 0
        assert "groups" in result
        assert isinstance(result["groups"], list)
        assert len(result["groups"]) > 0

        # Validate first group structure
        firstGroup = result["groups"][0]
        assert isinstance(firstGroup, list)
        assert len(firstGroup) > 0

        # Validate first result structure
        firstResult = firstGroup[0]
        assert "url" in firstResult
        assert "title" in firstResult
        assert "passages" in firstResult
        assert isinstance(firstResult["url"], str)
        assert len(firstResult["url"]) > 0
        assert isinstance(firstResult["title"], str)
        assert len(firstResult["title"]) > 0
        assert isinstance(firstResult["passages"], list)


@pytest.mark.asyncio
async def testSearchRussianQuery():
    """Test searching for 'программирование на Python' using golden data."""
    provider = GoldenDataProvider()
    cache = DictSearchCache()

    async with provider.patchClient(
        YandexSearchClient(apiKey="test_key", folderId="test_folder", cache=cache)
    ) as client:
        result = await client.search("программирование на Python")

        assert result is not None
        assert "found" in result
        assert result["found"] > 0
        assert "groups" in result
        assert isinstance(result["groups"], list)
        assert len(result["groups"]) > 0

        # Validate first group structure
        firstGroup = result["groups"][0]
        assert isinstance(firstGroup, list)
        assert len(firstGroup) > 0

        # Validate first result structure
        firstResult = firstGroup[0]
        assert "url" in firstResult
        assert "title" in firstResult
        assert "passages" in firstResult
        assert isinstance(firstResult["url"], str)
        assert len(firstResult["url"]) > 0
        assert isinstance(firstResult["title"], str)
        assert len(firstResult["title"]) > 0
        assert isinstance(firstResult["passages"], list)


@pytest.mark.asyncio
async def testSearchPythonTutorial():
    """Test searching for 'python 3.9 tutorial' using golden data."""
    provider = GoldenDataProvider()
    cache = DictSearchCache()

    async with provider.patchClient(
        YandexSearchClient(apiKey="test_key", folderId="test_folder", cache=cache)
    ) as client:
        result = await client.search("python 3.9 tutorial")

        assert result is not None
        assert "found" in result
        assert result["found"] > 0
        assert "groups" in result
        assert isinstance(result["groups"], list)
        assert len(result["groups"]) > 0

        # Validate first group structure
        firstGroup = result["groups"][0]
        assert isinstance(firstGroup, list)
        assert len(firstGroup) > 0

        # Validate first result structure
        firstResult = firstGroup[0]
        assert "url" in firstResult
        assert "title" in firstResult
        assert "passages" in firstResult
        assert isinstance(firstResult["url"], str)
        assert len(firstResult["url"]) > 0
        assert isinstance(firstResult["title"], str)
        assert len(firstResult["title"]) > 0
        assert isinstance(firstResult["passages"], list)


@pytest.mark.asyncio
async def testClientWithMissingData():
    """Test that missing data returns None."""
    provider = GoldenDataProvider()
    cache = DictSearchCache()

    async with provider.patchClient(
        YandexSearchClient(apiKey="test_key", folderId="test_folder", cache=cache)
    ) as client:
        # Test with a query that's not in our golden data
        result = await client.search("machine learning 2024")
        # Should return None when data is not found
        assert result is None

        # Test another query that's not in our golden data
        result = await client.search("weather forecast")
        # Should return None when data is not found
        assert result is None
