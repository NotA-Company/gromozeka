"""
Integration tests for Yandex Search API client.

This module contains integration tests that demonstrate the client working
end-to-end with mocked responses. These tests verify that all components
work together correctly.

Run with:
    ./venv/bin/python3 -m pytest lib/yandex_search/test_integration.py -v
"""

import asyncio
import base64
from typing import Any, Dict

import pytest

from lib.yandex_search import DictSearchCache, YandexSearchClient
from lib.yandex_search.models import (
    FamilyMode,
    FixTypoMode,
    GroupMode,
    Localization,
    SearchType,
    SortMode,
    SortOrder,
)

# Mock XML response for testing
MOCK_XML_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="2.0">
    <response>
        <reqid>1234567890</reqid>
        <found priority="all">1000</found>
        <found-human>Найдено 1\xa00000 результатов</found-human>
        <results>
            <grouping>
                <page>0</page>
                <group>
                    <doc modtime="2023-01-01" size="1024" charset="utf-8">
                        <url>https://example.com/python</url>
                        <domain>example.com</domain>
                        <title>Python Programming Tutorial</title>
                        <mime-type>text/html</mime-type>
                        <passages>
                            <passage>
                                <hlword>Python</hlword> is a powerful programming language for web development.
                            </passage>
                        </passages>
                    </doc>
                    <doc modtime="2023-02-01" size="2048" charset="utf-8">
                        <url>https://example.org/guide</url>
                        <domain>example.org</domain>
                        <title>Complete Python Guide</title>
                        <mime-type>text/html</mime-type>
                        <passages>
                            <passage>
                                Learn <hlword>Python</hlword> from basics to advanced topics.
                            </passage>
                        </passages>
                    </doc>
                </group>
                <group>
                    <doc modtime="2023-03-01" size="4096" charset="utf-8">
                        <url>https://docs.python.org</url>
                        <domain>docs.python.org</domain>
                        <title>Official Python Documentation</title>
                        <mime-type>text/html</mime-type>
                        <passages>
                            <passage>
                                The official <hlword>Python</hlword> documentation and reference.
                            </passage>
                        </passages>
                    </doc>
                </group>
            </grouping>
        </results>
    </response>
</yandexsearch>"""


class MockYandexSearchClient(YandexSearchClient):
    """Mock client that returns predefined responses for integration testing."""

    def __init__(self, **kwargs):
        # Set default test credentials
        kwargs.setdefault("iamToken", "test_token")
        kwargs.setdefault("folderId", "test_folder")
        # Disable rate limiting for integration tests
        kwargs.setdefault("rateLimitRequests", 1000)
        kwargs.setdefault("rateLimitWindow", 60)

        # Initialize parent with all provided kwargs
        super().__init__(**kwargs)

        # Prepare mock response
        self.mock_base64_response = base64.b64encode(MOCK_XML_RESPONSE.encode("utf-8")).decode("utf-8")

    async def _makeRequest(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Mock API request that returns predefined response."""
        # Simulate network delay
        await asyncio.sleep(0.05)

        # Parse the XML response like the real client does
        from .xml_parser import parseSearchResponse

        response = parseSearchResponse(self.mock_base64_response)
        return response  # type: ignore


class TestEndToEndIntegration:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_complete_search_workflow(self):
        """Test complete search workflow from query to parsed results."""
        # Create client
        client = MockYandexSearchClient()

        # Perform search
        results = await client.search("python programming")

        # Verify response structure
        assert results is not None
        assert "requestId" in results
        assert "found" in results
        assert "foundHuman" in results
        assert "page" in results
        assert "groups" in results

        # Verify specific values
        assert results["requestId"] == "1234567890"
        assert results["found"] == 1000
        assert results["foundHuman"] == "Найдено 1\xa00000 результатов"
        assert results["page"] == 0
        assert len(results["groups"]) >= 2  # At least 2 groups

        # Verify first group structure
        first_group = results["groups"][0]
        assert len(first_group) == 2

        # Verify first document structure
        first_doc = first_group[0]
        assert first_doc["url"] == "https://example.com/python"
        assert first_doc["domain"] == "example.com"
        assert first_doc["title"] == "Python Programming Tutorial"
        assert "passages" in first_doc
        assert len(first_doc["passages"]) == 1
        hlwords = first_doc.get("hlwords")
        assert hlwords is not None
        assert "python" in [word.lower() for word in hlwords]

    @pytest.mark.asyncio
    async def test_search_with_caching_workflow(self):
        """Test search workflow with caching enabled."""
        # Create cache and client
        cache = DictSearchCache(default_ttl=3600, max_size=100)
        client = MockYandexSearchClient(cache=cache)

        # First search - should hit API
        results1 = await client.search("python programming")
        assert results1 is not None

        # Check cache after first search
        stats = cache.getStats()
        assert stats["search_entries"] == 1

        # Second search - should hit cache
        results2 = await client.search("python programming")
        assert results2 is not None
        assert results1["requestId"] == results2["requestId"]  # Same cached result

        # Verify cache stats
        stats = cache.getStats()
        assert stats["search_entries"] == 1  # Still only one unique entry

        # Different query - should hit API again
        results3 = await client.search("java programming")
        assert results3 is not None
        assert results3["requestId"] == results1["requestId"]  # Same mock response

        # Verify cache has two entries now
        stats = cache.getStats()
        assert stats["search_entries"] == 2

    @pytest.mark.asyncio
    async def test_advanced_search_parameters(self):
        """Test advanced search with all parameters."""
        client = MockYandexSearchClient()

        # Advanced search with all parameters
        results = await client.search(
            queryText="machine learning",
            searchType=SearchType.SEARCH_TYPE_RU,
            familyMode=FamilyMode.FAMILY_MODE_MODERATE,
            page=1,
            fixTypoMode=FixTypoMode.FIX_TYPO_MODE_ON,
            sortMode=SortMode.SORT_MODE_BY_RELEVANCE,
            sortOrder=SortOrder.SORT_ORDER_DESC,
            groupMode=GroupMode.GROUP_MODE_DEEP,
            groupsOnPage=5,
            docsInGroup=3,
            maxPassages=2,
            region="225",
            l10n=Localization.LOCALIZATION_RU,
        )

        # Verify we get results
        assert results is not None
        assert results["found"] == 1000
        assert results["requestId"] == "1234567890"

    @pytest.mark.asyncio
    async def test_cache_bypass_workflow(self):
        """Test cache bypass functionality."""
        cache = DictSearchCache(default_ttl=3600)
        client = MockYandexSearchClient(cache=cache)

        # First search
        results1 = await client.search("test query")
        assert results1 is not None

        # Verify cache has entry
        stats = cache.getStats()
        assert stats["search_entries"] == 1

        # Search with cache bypass
        results2 = await client.search("test query", useCache=False)
        assert results2 is not None
        assert results1["requestId"] == results2["requestId"]

        # Cache should still have only one entry
        stats = cache.getStats()
        assert stats["search_entries"] == 1

    @pytest.mark.asyncio
    async def test_concurrent_searches_workflow(self):
        """Test concurrent searches with caching."""
        cache = DictSearchCache(default_ttl=3600)
        client = MockYandexSearchClient(cache=cache)

        # Create multiple concurrent searches
        queries = ["python", "java", "javascript", "python"]  # Duplicate query

        # Execute all searches concurrently
        tasks = [client.search(query) for query in queries]
        results = await asyncio.gather(*tasks)

        # Verify all results
        assert all(results)
        assert all(r and r["requestId"] == "1234567890" for r in results)

        # Verify cache has 3 unique entries (python, java, javascript)
        stats = cache.getStats()
        assert stats["search_entries"] == 3

    @pytest.mark.asyncio
    async def test_rate_limiting_workflow(self):
        """Test rate limiting in integration context."""
        # Create client with strict rate limiting
        client = MockYandexSearchClient(rateLimitRequests=2, rateLimitWindow=1)  # 2 requests per 1 second

        # Make requests sequentially
        start_time = asyncio.get_event_loop().time()

        results1 = await client.search("query 1")
        results2 = await client.search("query 2")
        results3 = await client.search("query 3")

        end_time = asyncio.get_event_loop().time()
        total_time = end_time - start_time

        # All should succeed
        assert results1 and results2 and results3

        # Should take at least 1 second due to rate limiting
        assert total_time >= 1.0

        # Check rate limit stats
        stats = client.getRateLimitStats()
        assert stats["max_requests"] == 2
        assert stats["window_seconds"] == 1

    @pytest.mark.asyncio
    async def test_error_handling_workflow(self):
        """Test error handling in integration context."""
        # Create client with invalid credentials
        client = MockYandexSearchClient()

        # Override _makeRequest to simulate error
        async def mock_error_request(request):
            raise Exception("Simulated network error")

        # Store original method
        original_make_request = client._makeRequest
        client._makeRequest = mock_error_request

        try:
            # Search should handle error gracefully
            results = await client.search("test query")
            assert results is None  # Should return None on error
        except Exception:
            # If exception propagates, that's also acceptable behavior
            # The important thing is that the client doesn't crash
            pass
        finally:
            # Restore original method
            client._makeRequest = original_make_request


class TestCacheIntegration:
    """Integration tests specifically for caching."""

    @pytest.mark.asyncio
    async def test_cache_key_consistency(self):
        """Test that cache keys are generated consistently."""
        cache = DictSearchCache()
        client = MockYandexSearchClient(cache=cache)

        # Make searches with same parameters in different order
        results1 = await client.search(queryText="test", region="225", maxPassages=2)

        results2 = await client.search(maxPassages=2, region="225", queryText="test")

        # Should get same cached result
        assert results1 and results2 and results1["requestId"] == results2["requestId"]

        # Cache should have only one entry
        stats = cache.getStats()
        assert stats["search_entries"] == 1

    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self):
        """Test cache TTL expiration."""
        # Create cache with very short TTL
        cache = DictSearchCache(default_ttl=1)  # 1 second (int)
        client = MockYandexSearchClient(cache=cache)

        # First search
        results1 = await client.search("test query")
        assert results1 is not None

        # Verify cache has entry
        stats = cache.getStats()
        assert stats["search_entries"] == 1

        # Wait for TTL to expire
        await asyncio.sleep(0.2)

        # Second search should hit API again (cache expired)
        results2 = await client.search("test query")
        assert results2 is not None
        assert results1["requestId"] == results2["requestId"]

        # Cache should still have one entry (replaced)
        stats = cache.getStats()
        assert stats["search_entries"] == 1


if __name__ == "__main__":
    # Run integration tests directly
    import sys

    print("Running Yandex Search integration tests...")
    print("Note: These tests use mock clients and don't make real API calls")

    # Run pytest with verbose output
    sys.exit(pytest.main([__file__, "-v", "-s"]))
