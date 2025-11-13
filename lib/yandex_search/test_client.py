"""Tests for Yandex Search API client.

This module contains comprehensive unit tests for the YandexSearchClient
functionality, covering authentication, request handling, error scenarios,
caching, rate limiting, and advanced search parameters.

The test suite uses mocking to simulate HTTP responses and network conditions,
ensuring reliable and fast test execution without external dependencies.
"""

import base64
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from .client import YandexSearchClient
from .dict_cache import DictSearchCache
from .models import (
    FamilyMode,
    FixTypoMode,
    GroupMode,
    Localization,
    SearchType,
    SortMode,
    SortOrder,
)


class TestYandexSearchClient(unittest.IsolatedAsyncioTestCase):
    """Test cases for YandexSearchClient functionality.

    This test class provides comprehensive coverage of the YandexSearchClient
    including initialization, authentication, search requests, error handling,
    caching mechanisms, and rate limiting functionality.
    """

    def setUp(self):
        """Set up test fixtures.

        Initializes common test data including sample XML responses for both
        successful and error scenarios, along with authentication credentials
        used throughout the test cases.
        """
        self.iamToken = "test-iam-token"
        self.apiKey = "test-api-key"
        self.folderId = "test-folder-id"

        # Sample successful response XML
        self.successXml = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
    <response>
        <reqid>test-request-id</reqid>
        <found priority="all">100</found>
        <found-human>Found 100 results</found-human>
        <results>
            <grouping>
                <page>0</page>
                <group>
                    <doc url="https://example.com" domain="example.com">
                        <title>Example Title</title>
                        <passage>This is a <hlword>sample</hlword> passage.</passage>
                        <mime-type>text/html</mime-type>
                        <charset>utf-8</charset>
                        <modtime>20090213T233130</modtime>
                        <size>1024</size>
                    </doc>
                </group>
            </grouping>
        </results>
    </response>
</yandexsearch>"""

        # Sample error response XML
        self.errorXml = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
    <response>
        <error code="INVALID_QUERY">Invalid search query</error>
    </response>
</yandexsearch>"""

    def testClientInitializationWithIamToken(self):
        """Test client initialization with IAM token.

        Verifies that the client correctly stores IAM token credentials
        and sets other authentication fields to None when initialized
        with an IAM token.
        """
        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        self.assertEqual(client.iamToken, self.iamToken)
        self.assertIsNone(client.apiKey)
        self.assertEqual(client.folderId, self.folderId)

    def testClientInitializationWithApiKey(self):
        """Test client initialization with API key.

        Verifies that the client correctly stores API key credentials
        and sets other authentication fields to None when initialized
        with an API key.
        """
        client = YandexSearchClient(apiKey=self.apiKey, folderId=self.folderId)

        self.assertEqual(client.apiKey, self.apiKey)
        self.assertIsNone(client.iamToken)
        self.assertEqual(client.folderId, self.folderId)

    def testClientInitializationWithoutCredentials(self):
        """Test client initialization fails without credentials.

        Verifies that the client raises a ValueError when neither IAM token
        nor API key is provided, ensuring proper authentication validation.
        """
        with self.assertRaises(ValueError) as context:
            YandexSearchClient(folderId=self.folderId)

        self.assertIn("Either iamToken or apiKey must be provided", str(context.exception))

    def testClientInitializationWithoutFolderId(self):
        """Test client initialization fails without folder ID.

        Verifies that the client raises a ValueError when folder ID is not
        provided, as this is a required parameter for API requests.
        """
        with self.assertRaises(ValueError) as context:
            YandexSearchClient(iamToken=self.iamToken)

        self.assertIn("folderId is required", str(context.exception))

    @patch("httpx.AsyncClient")
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testSuccessfulSearch(self, mockManagerGetInstance, mockAsyncClient):
        """Test successful search request.

        Verifies that the client correctly formats and sends search requests,
        handles successful responses, and properly parses the returned data.
        Also validates that HTTP headers and request body are correctly formatted.
        """
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        # Mock HTTP client
        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

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
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testErrorResponse(self, mockManagerGetInstance, mockAsyncClient):
        """Test error response handling.

        Verifies that the client correctly handles API error responses,
        properly extracts error information from the XML response, and
        uses the correct authentication method (API key in this case).
        """
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.errorXml.encode("utf-8")).decode("utf-8")}

        # Mock HTTP client
        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

        # Create client and make request
        client = YandexSearchClient(apiKey=self.apiKey, folderId=self.folderId)

        response = await client.search("test query")

        # Verify error response
        self.assertIsNotNone(response)
        if response:
            self.assertEqual(response["found"], 0)
            self.assertEqual(len(response["groups"]), 0)
            self.assertIn("error", response)
            if "error" in response and response["error"] is not None:
                error = response["error"]
                self.assertEqual(error["code"], "INVALID_QUERY")

        # Verify API key was used in headers
        callArgs = mockClient.post.call_args
        headers = callArgs[1]["headers"]
        self.assertEqual(headers["Authorization"], f"Api-Key {self.apiKey}")

    @patch("httpx.AsyncClient")
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testHttpErrorHandling(self, mockManagerGetInstance, mockAsyncClient):
        """Test HTTP error handling.

        Verifies that the client gracefully handles various HTTP error
        status codes including 401 Unauthorized, 429 Rate Limit, and
        500 Server Error, returning None for failed requests.
        """
        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

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
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testNetworkErrorHandling(self, mockManagerGetInstance, mockAsyncClient):
        """Test network error handling.

        Verifies that the client handles network-related errors such as
        timeouts and connection failures gracefully, returning None for
        failed requests without raising exceptions.
        """
        # Mock network timeout
        mockClient = AsyncMock()
        mockClient.post.side_effect = httpx.TimeoutException("Request timeout")
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        response = await client.search("test query")
        self.assertIsNone(response)

        # Mock network error
        mockClient.post.side_effect = httpx.RequestError("Network error")
        response = await client.search("test query")
        self.assertIsNone(response)

    @patch("httpx.AsyncClient")
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testInvalidJsonResponse(self, mockManagerGetInstance, mockAsyncClient):
        """Test handling of invalid JSON response.

        Verifies that the client handles cases where the API returns
        invalid JSON data, ensuring graceful error handling without
        crashing or raising exceptions.
        """
        # Mock HTTP response with invalid JSON
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        response = await client.search("test query")
        self.assertIsNone(response)

    @patch("httpx.AsyncClient")
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testMissingResultField(self, mockManagerGetInstance, mockAsyncClient):
        """Test handling of response without result field.

        Verifies that the client handles cases where the API response
        is missing the expected 'rawData' field, ensuring graceful
        error handling without crashing.
        """
        # Mock HTTP response without result field
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"error": "Missing result field"}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        response = await client.search("test query")
        self.assertIsNone(response)

    @patch("httpx.AsyncClient")
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testAdvancedSearchParameters(self, mockManagerGetInstance, mockAsyncClient):
        """Test search with advanced parameters.

        Verifies that the client correctly formats and sends requests
        with all available search parameters including search type,
        family mode, sorting, grouping, and localization options.
        """
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        # Make advanced search request
        await client.search(
            queryText="advanced query",
            searchType=SearchType.SEARCH_TYPE_COM,
            familyMode=FamilyMode.FAMILY_MODE_STRICT,
            page=2,
            fixTypoMode=FixTypoMode.FIX_TYPO_MODE_OFF,
            sortMode=SortMode.SORT_MODE_BY_TIME,
            sortOrder=SortOrder.SORT_ORDER_ASC,
            groupMode=GroupMode.GROUP_MODE_FLAT,
            groupsOnPage=5,
            docsInGroup=3,
            maxPassages=4,
            region="213",
            l10n=Localization.LOCALIZATION_EN,
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
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testSimpleSearchDefaults(self, mockManagerGetInstance, mockAsyncClient):
        """Test simple search with default parameters.

        Verifies that the client uses appropriate default values when
        making simple search requests without explicitly specifying
        advanced parameters.
        """
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

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

        # Check group parameters - groupSpec may be None if no grouping params were set
        groupSpec = requestBody.get("groupSpec")
        if groupSpec:
            self.assertEqual(groupSpec["groupMode"], "GROUP_MODE_DEEP")
            if "groupsOnPage" in groupSpec:
                self.assertEqual(groupSpec["groupsOnPage"], "10")
            if "docsInGroup" in groupSpec:
                self.assertEqual(groupSpec["docsInGroup"], "2")

        # Check metadata fields at top level
        self.assertEqual(requestBody["maxPassages"], "2")
        self.assertEqual(requestBody["region"], "225")
        self.assertEqual(requestBody["l10n"], "LOCALIZATION_RU")
        self.assertEqual(requestBody["folderId"], self.folderId)
        self.assertEqual(requestBody["responseFormat"], "FORMAT_XML")

    @patch("httpx.AsyncClient")
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testCachingFunctionality(self, mockManagerGetInstance, mockAsyncClient):
        """Test caching functionality.

        Verifies that the client properly caches search responses and
        serves subsequent identical requests from cache, reducing API
        calls and improving performance.
        """
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

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
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testCacheBypass(self, mockManagerGetInstance, mockAsyncClient):
        """Test cache bypass functionality.

        Verifies that the client can completely disable caching when
        useCache is set to False, ensuring all requests hit the API
        regardless of previous identical queries.
        """
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

        # Create cache and client with cache disabled
        cache = DictSearchCache(default_ttl=3600)
        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId, cache=cache, useCache=False)

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
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testPerRequestCacheBypass(self, mockManagerGetInstance, mockAsyncClient):
        """Test per-request cache bypass.

        Verifies that the client can bypass cache on a per-request basis
        using the useCache parameter, allowing selective cache control
        while maintaining caching for other requests.
        """
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

        # Create cache and client
        cache = DictSearchCache(default_ttl=3600)
        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId, cache=cache)

        # First request - should hit API and cache
        response1 = await client.search("per-request test query")
        self.assertIsNotNone(response1)

        # Second request with cache disabled - should hit API
        response2 = await client.search("per-request test query", useCache=False)
        self.assertIsNotNone(response2)

        # Third request without bypass - should hit cache
        response3 = await client.search("per-request test query")
        self.assertIsNotNone(response3)

        # Verify API was called twice (once for first, once for bypass)
        self.assertEqual(mockClient.post.call_count, 2)

    @patch("httpx.AsyncClient")
    @patch("lib.rate_limiter.manager.RateLimiterManager.getInstance")
    async def testRateLimiting(self, mockManagerGetInstance, mockAsyncClient):
        """Test rate limiting functionality.

        Verifies that the client uses the global rate limiter manager
        to apply rate limiting for the "yandex_search" queue.
        """
        # Mock HTTP response
        mockResponse = MagicMock()
        mockResponse.status_code = 200
        mockResponse.json.return_value = {"rawData": base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")}

        mockClient = AsyncMock()
        mockClient.post.return_value = mockResponse
        mockAsyncClient.return_value.__aenter__.return_value = mockClient

        # Mock rate limiter manager
        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()
        mockManagerGetInstance.return_value = mockManager

        # Create client
        client = YandexSearchClient(iamToken=self.iamToken, folderId=self.folderId)

        # Make a search request
        await client.search("rate limit test")

        # Verify that the rate limiter manager was called with the correct queue
        mockManager.applyLimit.assert_called_once_with("yandex-search")

    def testCacheKeyGeneration(self):
        """Test cache key generation in cache.

        Verifies that the cache generates consistent and unique keys
        for search requests, properly handling different request
        parameters while excluding folderId from the key generation.
        """
        cache = DictSearchCache(default_ttl=3600)

        # Create sample requests
        # Create two requests with different folder IDs
        from .models import (
            FamilyMode,
            FixTypoMode,
            GroupMode,
            Localization,
            ResponseFormat,
            SearchRequest,
            SearchType,
            SortMode,
            SortOrder,
        )

        request1: SearchRequest = {
            "query": {
                "searchType": SearchType.SEARCH_TYPE_RU,
                "queryText": "test query",
                "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                "page": "0",
                "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
            },
            "sortSpec": {"sortMode": SortMode.SORT_MODE_BY_RELEVANCE, "sortOrder": SortOrder.SORT_ORDER_DESC},
            "groupSpec": {"groupMode": GroupMode.GROUP_MODE_DEEP},
            "maxPassages": "2",
            "region": "225",
            "l10n": Localization.LOCALIZATION_RU,
            "folderId": self.folderId,
            "responseFormat": ResponseFormat.FORMAT_XML,
        }
        request2: SearchRequest = {
            "query": {
                "searchType": SearchType.SEARCH_TYPE_RU,
                "queryText": "test query",
                "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                "page": "0",
                "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
            },
            "sortSpec": {"sortMode": SortMode.SORT_MODE_BY_RELEVANCE, "sortOrder": SortOrder.SORT_ORDER_DESC},
            "groupSpec": {"groupMode": GroupMode.GROUP_MODE_DEEP},
            "maxPassages": "2",
            "region": "225",
            "l10n": Localization.LOCALIZATION_RU,
            "folderId": "different-folder",  # Different folder ID
            "responseFormat": ResponseFormat.FORMAT_XML,
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
        """Test client initialization with cache.

        Verifies that the client correctly initializes with cache
        configuration including TTL, usage flags, and rate limiting
        parameters.
        """
        cache = DictSearchCache(default_ttl=1800)

        client = YandexSearchClient(
            iamToken=self.iamToken,
            folderId=self.folderId,
            cache=cache,
            cacheTTL=1800,
            useCache=True,
        )

        self.assertEqual(client.cache, cache)
        self.assertEqual(client.cacheTTL, 1800)
        self.assertEqual(client.useCache, True)


if __name__ == "__main__":
    unittest.main()
