"""
Tests for Yandex Search API client

This module contains unit tests for the YandexSearchClient functionality.
"""

import base64
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from .client import YandexSearchClient
from .dict_cache import DictSearchCache


class TestYandexSearchClient(unittest.IsolatedAsyncioTestCase):
    """Test cases for YandexSearchClient functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.iamToken = "test-iam-token"
        self.apiKey = "test-api-key"
        self.folderId = "test-folder-id"

        # Sample successful response XML
        self.successXml = """<?xml version="1.0" encoding="utf-8"?>
<search requestid="test-request-id" found="100" found-human="Found 100 results" page="0">
    <group>
        <doc url="https://example.com" domain="example.com" title="Example Title">
            <passage>This is a <hlword>sample</hlword> passage.</passage>
            <mime-type>text/html</mime-type>
        </doc>
    </group>
</search>"""

        # Sample error response XML
        self.errorXml = """<?xml version="1.0" encoding="utf-8"?>
<search>
    <error code="INVALID_QUERY" message="Invalid search query" details="The query contains forbidden characters"/>
</search>"""

    def testClientInitializationWithIamToken(self):
        """Test client initialization with IAM token"""
        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        self.assertEqual(client.iamToken, self.iamToken)
        self.assertIsNone(client.apiKey)
        self.assertEqual(client.folderId, self.folderId)

    def testClientInitializationWithApiKey(self):
        """Test client initialization with API key"""
        client = YandexSearchClient(apiKey=self.apiKey, folderId=self.folderId)

        self.assertEqual(client.apiKey, self.apiKey)
        self.assertIsNone(client.iamToken)
        self.assertEqual(client.folderId, self.folderId)

    def testClientInitializationWithoutCredentials(self):
        """Test client initialization fails without credentials"""
        with self.assertRaises(ValueError) as context:
            YandexSearchClient(folderId=self.folderId)

        self.assertIn("Either iamToken or apiKey must be provided", str(context.exception))

    def testClientInitializationWithoutFolderId(self):
        """Test client initialization fails without folder ID"""
        with self.assertRaises(ValueError) as context:
            YandexSearchClient(iamToken=self.iamToken)

        self.assertIn("folderId is required", str(context.exception))

    @patch("httpx.AsyncClient")
    async def testSuccessfulSearch(self, mockAsyncClient):
        """Test successful search request"""
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        # Mock HTTP client
        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Create client and make request
        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        response = await client.search("test query")

        # Verify response
        self.assertIsNotNone(response)
        if response:
            self.assertEqual(response["requestId"], "test-request-id")
            self.assertEqual(response["found"], 100)
            self.assertEqual(len(response["groups"]), 1)

        # Verify HTTP request was made correctly
        mockClient.post.assert_called_once()
        callArgs = mockClient.post.call_args

        # Check URL
        self.assertEqual(callArgs[0][0], "https://searchapi.api.cloud.yandex.net/v2/web/search")

        # Check headers
        headers = callArgs[1]["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {self.iamToken}")
        self.assertEqual(headers["Content-Type"], "application/json")

        # Check request body
        requestBody = callArgs[1]["json"]
        self.assertEqual(requestBody["query"]["queryText"], "test query")
        self.assertEqual(requestBody["query"]["searchType"], "SEARCH_TYPE_RU")
        self.assertEqual(requestBody["folderId"], self.folderId)

    @patch("httpx.AsyncClient")
    async def testErrorResponse(self, mockAsyncClient):
        """Test error response handling"""
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.errorXml.encode("utf-8")).decode("utf-8")}

        # Mock HTTP client
        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Create client and make request
        client = YandexSearchClient(apiKey=self.apiKey, folderId=self.folderId)

        response = await client.search("test query")

        # Verify error response
        self.assertIsNotNone(response)
        if response:
            self.assertEqual(response["found"], 0)
            self.assertEqual(len(response["groups"]), 0)
            self.assertIsNotNone(response["error"])
            error = response["error"]
            if error:
                self.assertEqual(error["code"], "INVALID_QUERY")

        # Verify API key was used in headers
        callArgs = mockClient.post.call_args
        headers = callArgs[1]["headers"]
        self.assertEqual(headers["Authorization"], f"Api-Key {self.apiKey}")

    @patch("httpx.AsyncClient")
    async def testHttpErrorHandling(self, mockAsyncClient):
        """Test HTTP error handling"""
        # Test 401 Unauthorized
        mockResponse = MagicMock()
        mockResponse.status_code = 401

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        response = await client.search("test query")
        self.assertIsNone(response)

        # Test 429 Rate Limit
        mockResponse.status_code = 429
        response = await client.search("test query")
        self.assertIsNone(response)

        # Test 500 Server Error
        mockResponse.status_code = 500
        response = await client.search("test query")
        self.assertIsNone(response)

    @patch("httpx.AsyncClient")
    async def testNetworkErrorHandling(self, mockAsyncClient):
        """Test network error handling"""
        # Mock network timeout
        mockClient = AsyncMock()
        mockClient.post.side_effect = httpx.TimeoutException("Request timeout")
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        response = await client.search("test query")
        self.assertIsNone(response)

        # Mock network error
        mockClient.post.side_effect = httpx.RequestError("Network error")
        response = await client.search("test query")
        self.assertIsNone(response)

    @patch("httpx.AsyncClient")
    async def testInvalidJsonResponse(self, mockAsyncClient):
        """Test handling of invalid JSON response"""
        # Mock HTTP response with invalid JSON
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        response = await client.search("test query")
        self.assertIsNone(response)

    @patch("httpx.AsyncClient")
    async def testMissingResultField(self, mockAsyncClient):
        """Test handling of response without result field"""
        # Mock HTTP response without result field
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"error": "Missing result field"}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        response = await client.search("test query")
        self.assertIsNone(response)

    @patch("httpx.AsyncClient")
    async def testAdvancedSearchParameters(self, mockAsyncClient):
        """Test search with advanced parameters"""
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        # Make advanced search request
        await client.search(
            queryText="advanced query",
            searchType="SEARCH_TYPE_COM",
            familyMode="FAMILY_MODE_STRICT",
            page=2,
            fixTypoMode="FIX_TYPO_MODE_OFF",
            sortMode="SORT_MODE_BY_TIME",
            sortOrder="SORT_ORDER_ASC",
            groupMode="GROUP_MODE_FLAT",
            groupsOnPage=5,
            docsInGroup=3,
            maxPassages=4,
            region="213",
            l10n="LOCALIZATION_EN",
        )

        # Verify request parameters
        callArgs = mockClient.post.call_args
        requestBody = callArgs[1]["json"]

        # Check query parameters
        query = requestBody["query"]
        self.assertEqual(query["queryText"], "advanced query")
        self.assertEqual(query["searchType"], "SEARCH_TYPE_COM")
        self.assertEqual(query["familyMode"], "FAMILY_MODE_STRICT")
        self.assertEqual(query["page"], "2")
        self.assertEqual(query["fixTypoMode"], "FIX_TYPO_MODE_OFF")

        # Check sort parameters
        sortSpec = requestBody["sortSpec"]
        self.assertEqual(sortSpec["sortMode"], "SORT_MODE_BY_TIME")
        self.assertEqual(sortSpec["sortOrder"], "SORT_ORDER_ASC")

        # Check group parameters
        groupSpec = requestBody["groupSpec"]
        self.assertEqual(groupSpec["groupMode"], "GROUP_MODE_FLAT")
        self.assertEqual(groupSpec["groupsOnPage"], "5")
        self.assertEqual(groupSpec["docsInGroup"], "3")

        # Check metadata fields at top level
        self.assertEqual(requestBody["maxPassages"], "4")
        self.assertEqual(requestBody["region"], "213")
        self.assertEqual(requestBody["l10n"], "LOCALIZATION_EN")
        self.assertEqual(requestBody["folderId"], self.folderId)
        self.assertEqual(requestBody["responseFormat"], "FORMAT_XML")

    @patch("httpx.AsyncClient")
    async def testSimpleSearchDefaults(self, mockAsyncClient):
        """Test simple search with default parameters"""
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        # Make simple search request
        await client.search("simple query")

        # Verify default parameters
        callArgs = mockClient.post.call_args
        requestBody = callArgs[1]["json"]

        # Check query parameters
        query = requestBody["query"]
        self.assertEqual(query["queryText"], "simple query")
        self.assertEqual(query["searchType"], "SEARCH_TYPE_RU")
        self.assertEqual(query["familyMode"], "FAMILY_MODE_MODERATE")
        self.assertEqual(query["fixTypoMode"], "FIX_TYPO_MODE_ON")

        # Check sort parameters
        sortSpec = requestBody["sortSpec"]
        self.assertEqual(sortSpec["sortMode"], "SORT_MODE_BY_RELEVANCE")
        self.assertEqual(sortSpec["sortOrder"], "SORT_ORDER_DESC")

        # Check group parameters
        groupSpec = requestBody["groupSpec"]
        self.assertEqual(groupSpec["groupMode"], "GROUP_MODE_DEEP")
        self.assertEqual(groupSpec["groupsOnPage"], "10")
        self.assertEqual(groupSpec["docsInGroup"], "2")

        # Check metadata fields at top level
        self.assertEqual(requestBody["maxPassages"], "5")
        self.assertEqual(requestBody["region"], "225")
        self.assertEqual(requestBody["l10n"], "LOCALIZATION_RU")
        self.assertEqual(requestBody["folderId"], self.folderId)
        self.assertEqual(requestBody["responseFormat"], "FORMAT_XML")

    @patch("httpx.AsyncClient")
    async def testCachingFunctionality(self, mockAsyncClient):
        """Test caching functionality"""
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Create cache and client
        cache = DictSearchCache(default_ttl=3600)
        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId, cache=cache)

        # First request - should hit API
        response1 = await client.search("cache test query")
        self.assertIsNotNone(response1)

        # Verify API was called once
        self.assertEqual(mockClient.post.call_count, 1)

        # Second request with same query - should hit cache
        response2 = await client.search("cache test query")
        self.assertIsNotNone(response2)

        # Verify API was still called only once (cache hit)
        self.assertEqual(mockClient.post.call_count, 1)

        # Verify responses are identical
        if response1 and response2:
            self.assertEqual(response1["requestId"], response2["requestId"])

        # Verify cache stats
        stats = cache.getStats()
        self.assertEqual(stats["search_entries"], 1)

    @patch("httpx.AsyncClient")
    async def testCacheBypass(self, mockAsyncClient):
        """Test cache bypass functionality"""
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Create cache and client with bypass enabled
        cache = DictSearchCache(default_ttl=3600)
        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId, cache=cache, bypassCache=True)

        # First request - should hit API
        response1 = await client.search("bypass test query")
        self.assertIsNotNone(response1)

        # Second request - should also hit API (bypass cache)
        response2 = await client.search("bypass test query")
        self.assertIsNotNone(response2)

        # Verify API was called twice (cache bypassed)
        self.assertEqual(mockClient.post.call_count, 2)

        # Verify cache is empty
        stats = cache.getStats()
        self.assertEqual(stats["search_entries"], 0)

    @patch("httpx.AsyncClient")
    async def testPerRequestCacheBypass(self, mockAsyncClient):
        """Test per-request cache bypass"""
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Create cache and client
        cache = DictSearchCache(default_ttl=3600)
        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId, cache=cache)

        # First request - should hit API and cache
        response1 = await client.search("per-request test query")
        self.assertIsNotNone(response1)

        # Second request with bypass - should hit API
        response2 = await client.search("per-request test query", bypassCache=True)
        self.assertIsNotNone(response2)

        # Third request without bypass - should hit cache
        response3 = await client.search("per-request test query")
        self.assertIsNotNone(response3)

        # Verify API was called twice (once for first, once for bypass)
        self.assertEqual(mockClient.post.call_count, 2)

    @patch("httpx.AsyncClient")
    async def testRateLimiting(self, mockAsyncClient):
        """Test rate limiting functionality"""
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Create client with strict rate limiting
        client = YandexSearchClient(
            iamToken=self.iamToken,
            folderId=self.folderId,
            rateLimitRequests=2,
            rateLimitWindow=1,  # 2 requests per 1 second
        )

        import time

        start_time = time.time()

        # Make requests up to the limit
        await client.search("rate limit test 1")
        await client.search("rate limit test 2")

        # These should be immediate
        elapsed_time = time.time() - start_time
        self.assertLess(elapsed_time, 0.5)  # Should be very fast

        # Third request should be rate limited
        await client.search("rate limit test 3")

        # Should have taken at least 1 second due to rate limiting
        elapsed_time = time.time() - start_time
        self.assertGreaterEqual(elapsed_time, 1.0)

    def testRateLimitStats(self):
        """Test rate limiting statistics"""
        client = YandexSearchClient(
            iamToken=self.iamToken, folderId=self.folderId, rateLimitRequests=5, rateLimitWindow=60
        )

        # Get initial stats
        stats = client.getRateLimitStats()
        self.assertEqual(stats["requests_in_window"], 0)
        self.assertEqual(stats["max_requests"], 5)
        self.assertEqual(stats["window_seconds"], 60)

    def testCacheKeyGeneration(self):
        """Test cache key generation in cache"""
        cache = DictSearchCache(default_ttl=3600)

        # Create sample requests
        # Create two requests with different folder IDs
        from .models import SearchRequest

        request1: SearchRequest = {
            "query": {
                "searchType": "SEARCH_TYPE_RU",
                "queryText": "test query",
                "familyMode": None,
                "page": None,
                "fixTypoMode": None,
            },
            "sortSpec": {"sortMode": "SORT_MODE_BY_RELEVANCE", "sortOrder": None},
            "groupSpec": {"groupMode": "GROUP_MODE_DEEP", "groupsOnPage": None, "docsInGroup": None},
            "maxPassages": "2",
            "region": "225",
            "l10n": "LOCALIZATION_RU",
            "folderId": self.folderId,
            "responseFormat": "FORMAT_XML",
        }
        request2: SearchRequest = {
            "query": {
                "searchType": "SEARCH_TYPE_RU",
                "queryText": "test query",
                "familyMode": None,
                "page": None,
                "fixTypoMode": None,
            },
            "sortSpec": {"sortMode": "SORT_MODE_BY_RELEVANCE", "sortOrder": None},
            "groupSpec": {"groupMode": "GROUP_MODE_DEEP", "groupsOnPage": None, "docsInGroup": None},
            "maxPassages": "2",
            "region": "225",
            "l10n": "LOCALIZATION_RU",
            "folderId": "different-folder",  # Different folder ID
            "responseFormat": "FORMAT_XML",
        }

        # Generate cache keys
        key1 = cache._generateCacheKey(request1)
        key2 = cache._generateCacheKey(request2)

        # Keys should be the same (folderId excluded from cache key)
        self.assertEqual(key1, key2)

        # Keys should be valid SHA512 hashes
        self.assertEqual(len(key1), 128)
        self.assertTrue(all(c in "0123456789abcdef" for c in key1))

    def testClientInitializationWithCache(self):
        """Test client initialization with cache"""
        cache = DictSearchCache(default_ttl=1800)

        client = YandexSearchClient(
            iamToken=self.iamToken,
            folderId=self.folderId,
            cache=cache,
            cacheTTL=1800,
            bypassCache=False,
            rateLimitRequests=20,
            rateLimitWindow=60,
        )

        self.assertEqual(client.cache, cache)
        self.assertEqual(client.cacheTTL, 1800)
        self.assertEqual(client.bypassCache, False)
        self.assertEqual(client.rateLimitRequests, 20)
        self.assertEqual(client.rateLimitWindow, 60)


if __name__ == "__main__":
    unittest.main()
