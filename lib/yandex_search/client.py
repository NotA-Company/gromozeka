"""Yandex Search API v2 async client with XML parsing, caching, and rate limiting.

This module provides an asynchronous client for interacting with the Yandex Search API v2.
It supports both IAM token and API key authentication, automatic result caching, rate limiting,
and XML response parsing. The client is designed for thread-safe concurrent operations with
per-request HTTP sessions.

Key Features:
    - IAM token and API key authentication
    - Automatic result caching with configurable TTL
    - Built-in rate limiting to prevent API quota exhaustion
    - XML response parsing with structured data models
    - Thread-safe concurrent operations
    - Comprehensive error handling and logging

Example:
    from lib.yandex_search import SearchRequestKeyGenerator, YandexSearchClient
    from lib.cache import DictCache

    client = YandexSearchClient(
        iamToken="your_iam_token",
        folderId="your_folder_id",
        cache=DictCache(
            keyGenerator=SearchRequestKeyGenerator()
        ),
    )

    results = await client.search("python programming")
    if results:
        for item in results.get("items", []):
            print(f"{item['title']}: {item['url']}")
"""

import json
import logging
from typing import Optional

import httpx

from lib.cache import CacheInterface, NullCache
from lib.rate_limiter import RateLimiterManager

from .models import (
    FamilyMode,
    FixTypoMode,
    GroupMode,
    GroupSpec,
    Localization,
    ResponseFormat,
    SearchRequest,
    SearchResponse,
    SearchType,
    SortMode,
    SortOrder,
)
from .xml_parser import parseSearchResponse

logger = logging.getLogger(__name__)


class YandexSearchClient:
    """Async client for Yandex Search API v2 with XML parsing, caching, and rate limiting.

    This client provides a high-level interface for performing web searches using the Yandex
    Search API v2. It supports both IAM token and API key authentication, automatic result
    caching with configurable TTL, and built-in rate limiting to prevent API quota exhaustion.
    The client creates a new HTTP session for each request, ensuring thread-safe concurrent
    operations.

    Attributes:
        iamToken: IAM token for Yandex Cloud authentication (alternative to apiKey)
        apiKey: API key for Yandex Cloud authentication (alternative to iamToken)
        folderId: Yandex Cloud folder ID for resource scoping
        requestTimeout: HTTP request timeout in seconds
        cache: Cache implementation for storing search results
        cacheTTL: Default time-to-live for cached results in seconds
        rateLimiterQueue: Name of the rate limiter queue to use
        _rateLimiter: Rate limiter manager instance for API throttling
        API_ENDPOINT: Yandex Search API v2 endpoint URL

    Example:
        client = YandexSearchClient(
            iamToken="your_iam_token",
            folderId="your_folder_id"
        )
        results = await client.search("python programming")
        if results:
            for item in results.get("items", []):
                print(f"{item['title']}: {item['url']}")
    """

    __slots__ = (
        "iamToken",
        "apiKey",
        "folderId",
        "requestTimeout",
        "cache",
        "cacheTTL",
        "useCache",
        "rateLimiterQueue",
        "_rateLimiter",
    )

    API_ENDPOINT = "https://searchapi.api.cloud.yandex.net/v2/web/search"

    def __init__(
        self,
        *,
        iamToken: Optional[str] = None,
        apiKey: Optional[str] = None,
        folderId: str = "",
        requestTimeout: int = 30,
        cache: Optional[CacheInterface[SearchRequest, SearchResponse]] = None,
        cacheTTL: Optional[int] = 3600,
        rateLimiterQueue: str = "yandex-search",
    ):
        """Initialize Yandex Search client.

        Creates a new YandexSearchClient instance with the specified authentication,
        caching, and rate limiting configuration. Either an IAM token or API key must
        be provided for authentication. A folder ID is required to scope the search
        operations to a specific Yandex Cloud folder.

        Args:
            iamToken: IAM token for Yandex Cloud authentication. Alternative to apiKey.
                If provided, takes precedence over apiKey. Must be a valid IAM token
                obtained from Yandex Cloud.
            apiKey: API key for Yandex Cloud authentication. Alternative to iamToken.
                Used if iamToken is not provided. Must be a valid API key from Yandex Cloud.
            folderId: Yandex Cloud folder ID for resource scoping. Required parameter
                that identifies which folder's resources to use for the search operation.
            requestTimeout: HTTP request timeout in seconds. Default is 30 seconds.
                If a request takes longer than this timeout, a TimeoutException is raised.
            cache: Cache implementation for storing search results. If None, a NullCache
                is used which disables caching. Recommended to use DictCache with
                SearchRequestKeyGenerator for optimal performance.
            cacheTTL: Default time-to-live for cached results in seconds. Default is 3600
                (1 hour). Can be overridden per-request using the cacheTTL parameter in
                the search method. Set to None to disable caching.
            rateLimiterQueue: Name of the rate limiter queue to use for API throttling.
                Default is "yandex-search". The rate limiter helps prevent API quota
                exhaustion by limiting the number of requests per time period.

        Raises:
            ValueError: If neither iamToken nor apiKey is provided, or if folderId is empty.

        Example:
            from lib.yandex_search import YandexSearchClient
            from lib.cache import DictCache
            from lib.yandex_search.cache_utils import SearchRequestKeyGenerator

            client = YandexSearchClient(
                iamToken="your_iam_token",
                folderId="your_folder_id",
                cache=DictCache(
                    keyGenerator=SearchRequestKeyGenerator()
                ),
                cacheTTL=1800,  # 30 minutes
                requestTimeout=60
            )
        """
        if not iamToken and not apiKey:
            raise ValueError("Either iamToken or apiKey must be provided")

        if not folderId:
            raise ValueError("folderId is required")

        self.iamToken = iamToken
        self.apiKey = apiKey
        self.folderId = folderId
        self.requestTimeout = requestTimeout
        self.cache: CacheInterface[SearchRequest, SearchResponse] = cache if cache is not None else NullCache()
        self.cacheTTL = cacheTTL
        self.rateLimiterQueue = rateLimiterQueue
        self._rateLimiter = RateLimiterManager.getInstance()

    async def search(
        self,
        queryText: str,
        *,
        searchType: SearchType = SearchType.SEARCH_TYPE_RU,
        familyMode: FamilyMode = FamilyMode.FAMILY_MODE_MODERATE,
        page: int = 0,
        fixTypoMode: FixTypoMode = FixTypoMode.FIX_TYPO_MODE_ON,
        sortMode: SortMode = SortMode.SORT_MODE_BY_RELEVANCE,
        sortOrder: SortOrder = SortOrder.SORT_ORDER_DESC,
        groupMode: GroupMode = GroupMode.GROUP_MODE_DEEP,
        groupsOnPage: Optional[int] = None,
        docsInGroup: Optional[int] = None,
        maxPassages: int = 2,
        region: str = "225",  # See https://yandex.cloud/ru/docs/search-api/reference/regions for examples
        l10n: Localization = Localization.LOCALIZATION_RU,
        cacheTTL: Optional[int] = None,
    ) -> Optional[SearchResponse]:
        """Perform search with automatic caching and rate limiting.

        Executes a web search query using the Yandex Search API v2. The method automatically
        checks the cache for existing results before making an API request, applies rate
        limiting to prevent quota exhaustion, and caches successful responses for future use.

        Args:
            queryText: Search query text to search for. Required parameter. The query can
                contain any search terms and operators supported by Yandex Search.
            searchType: Search domain to use for the search. Default is SEARCH_TYPE_RU for
                Russian web search. Other options include international search domains.
            familyMode: Content filtering level for search results. Default is
                FAMILY_MODE_MODERATE which filters explicit content. Options include
                FAMILY_MODE_NONE (no filtering) and FAMILY_MODE_STRICT (strict filtering).
            page: Page number for pagination. Default is 0 (first page). Use this parameter
                to navigate through multiple pages of search results.
            fixTypoMode: Typo correction mode. Default is FIX_TYPO_MODE_ON which automatically
                corrects typos in the query. Set to FIX_TYPO_MODE_OFF to disable correction.
            sortMode: Sort criteria for search results. Default is SORT_MODE_BY_RELEVANCE
                which sorts by relevance score. Other options include SORT_MODE_BY_DATE.
            sortOrder: Sort direction for results. Default is SORT_ORDER_DESC (descending).
                Use SORT_ORDER_ASC for ascending order when applicable.
            groupMode: Result grouping mode. Default is GROUP_MODE_DEEP which groups
                similar results together. Other options include GROUP_MODE_FLAT (no grouping).
            groupsOnPage: Number of result groups per page. Default is None (API default).
                Override to control pagination granularity.
            docsInGroup: Number of documents per result group. Default is None (API default).
                Override to control how many similar results are grouped together.
            maxPassages: Maximum number of text passages per document. Default is 2.
                Passages are short text snippets showing where the query matches in the content.
            region: Region code for localized search results. Default is "225" for Russia.
                See https://yandex.cloud/ru/docs/search-api/reference/regions for available codes.
            l10n: Interface language for the search. Default is LOCALIZATION_RU for Russian.
                Controls the language of UI elements and some result metadata.
            cacheTTL: Override the default cache TTL for this specific request. Default is
                None which uses the client's default cacheTTL. Set to 0 to bypass cache,
                or a positive integer to cache for that many seconds.

        Returns:
            Search response dict containing search results and metadata, or None if an
            error occurs. The response structure includes:
                - items: List of search result items with title, url, snippet, etc.
                - totalResults: Total number of results found
                - page: Current page number
                - itemsPerPage: Number of items per page
                - query: The original query that was executed

        Raises:
            Does not raise exceptions directly. All errors are logged and None is returned.

        Example:
            results = await client.search(
                "python programming tutorial",
                page=0,
                maxPassages=3,
                region="225",
                cacheTTL=1800
            )
            if results:
                for item in results.get("items", []):
                    print(f"{item['title']}")
                    print(f"URL: {item['url']}")
                    print(f"Snippet: {item.get('snippet', '')}")
                    print("---")
        """
        # Build group specification
        groupSpec: GroupSpec = {"groupMode": groupMode}

        if groupsOnPage is not None:
            groupSpec["groupsOnPage"] = str(groupsOnPage)
        if docsInGroup is not None:
            groupSpec["docsInGroup"] = str(docsInGroup)

        # Build complete request with correct structure
        # Ensure all required fields have string values
        request: SearchRequest = {
            "query": {
                "searchType": searchType,
                "queryText": queryText,
                "familyMode": familyMode,
                "page": str(page),
                "fixTypoMode": fixTypoMode,
            },
            "sortSpec": {
                "sortMode": sortMode,
                "sortOrder": sortOrder,
            },
            "groupSpec": groupSpec,
            "maxPassages": str(maxPassages),
            "region": region,
            "l10n": l10n,
            "folderId": self.folderId,
            "responseFormat": ResponseFormat.FORMAT_XML,
        }

        # Check cache first
        cachedResult = await self.cache.get(request, cacheTTL if cacheTTL is not None else self.cacheTTL)
        if cachedResult:
            logger.debug(f"Cache hit for query: {queryText}")
            return cachedResult
        else:
            logger.debug(f"Cache miss for query: {queryText}")

        # Make API request
        result = await self._makeRequest(request)

        # Cache successful results
        if result is not None:
            await self.cache.set(request, result)
            logger.debug(f"Cached result for query: {queryText}")

        return result

    async def _makeRequest(self, request: SearchRequest) -> Optional[SearchResponse]:
        """Make HTTP request to Yandex Search API with error handling.

        Creates a new HTTP session for each request to ensure thread safety. Handles
        various error conditions including HTTP errors, network issues, timeouts,
        and parsing failures. The method applies rate limiting before making the
        request and parses the Base64-encoded XML response from the API.

        Args:
            request: Complete search request dictionary containing query parameters,
                authentication credentials, and all required fields for the API call.

        Returns:
            Parsed search response dict containing the search results and metadata,
            or None if an error occurs during the request. The response is parsed
            from the Base64-encoded XML returned by the API.

        Raises:
            Does not raise exceptions directly. All errors are caught and logged,
            with None returned to indicate failure. Error types handled include:
                - httpx.TimeoutException: Request timeout
                - httpx.RequestError: Network errors
                - json.JSONDecodeError: JSON parsing errors
                - Exception: Unexpected errors

        Note:
            This method is intended for internal use by the search method. It handles
            the low-level HTTP communication with the Yandex Search API, including
            authentication header construction and response parsing.
        """
        try:
            logger.debug(f"Making search request: {request}")
            # Apply rate limiting
            await self._rateLimiter.applyLimit(self.rateLimiterQueue)

            # Prepare headers
            headers = {
                "Content-Type": "application/json",
            }

            if self.iamToken:
                headers["Authorization"] = f"Bearer {self.iamToken}"
            elif self.apiKey:
                headers["Authorization"] = f"Api-Key {self.apiKey}"

            # Create new session for each request
            async with httpx.AsyncClient(timeout=self.requestTimeout) as session:
                response = await session.post(self.API_ENDPOINT, headers=headers, json=request)

                if response.status_code == 200:
                    # Parse JSON response
                    responseData = response.json()
                    logger.debug(f"API request successful: {response.status_code}")
                    logger.debug(f"API response: {str(responseData)[:50]}...")

                    # Extract Base64-encoded XML
                    if "rawData" not in responseData:
                        logger.error("No 'rawData' field in response")
                        return None

                    base64Xml = responseData["rawData"]

                    # Parse XML response
                    return parseSearchResponse(base64Xml)

                elif response.status_code == 400:
                    logger.error("Bad request - invalid parameters")
                    return None
                elif response.status_code == 401:
                    logger.error("Unauthorized - invalid credentials")
                    return None
                elif response.status_code == 403:
                    logger.error("Forbidden - insufficient permissions")
                    return None
                elif response.status_code == 429:
                    logger.error("Rate limit exceeded")
                    return None
                elif response.status_code >= 500:
                    logger.error(f"Server error: {response.status_code}")
                    return None
                else:
                    logger.error(f"API request failed: {response.status_code}")
                    logger.error(f"Response text: {response.text}")
                    return None

        except httpx.TimeoutException:
            logger.error("Request timeout")
            return None
        except httpx.RequestError as e:
            logger.error(f"Network error: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during API request: {e}")
            return None
