"""Yandex Search API async client implementation.

This module provides the main YandexSearchClient class for interacting with the
Yandex Search API v2, featuring XML response format parsing, comprehensive caching,
and built-in rate limiting capabilities.

API References:
    - https://yandex.cloud/ru/docs/search-api/api-ref/WebSearch/search
    - https://yandex.cloud/ru/docs/search-api/concepts/response

Key Features:
    - Dual authentication support (IAM token and API key)
    - Configurable caching with TTL and size limits
    - Sliding window rate limiting to prevent API abuse
    - Comprehensive error handling and logging
    - Support for multiple search domains and languages
    - Thread-safe async operations with per-request sessions

Example:
    Basic usage with caching enabled::

        from lib.yandex_search import YandexSearchClient, DictSearchCache

        # Initialize cache and client
        cache = DictSearchCache(maxSize=1000, defaultTtl=3600)
        client = YandexSearchClient(
            iamToken="your_iam_token",
            folderId="your_folder_id",
            cache=cache
        )

        # Perform search
        results = await client.search("python programming")
        if results:
            print(f"Found {results['found']} results")
            for group in results['groups']:
                for doc in group['group']:
                    print(f"Title: {doc['title']}")
                    print(f"URL: {doc['url']}")
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from .cache_interface import SearchCacheInterface
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
    """Async client for Yandex Search API v2 with XML response format.

    This client provides a comprehensive, high-level interface to the Yandex Search API,
    supporting extensive search parameters, intelligent caching, and robust rate limiting.
    The implementation creates a new HTTP session for each request to ensure proper
    concurrent request handling without session conflicts.

    Core Capabilities:
        - Dual authentication methods (IAM token and API key)
        - Configurable caching with TTL and size management
        - Sliding window rate limiting for API abuse prevention
        - Comprehensive error handling with detailed logging
        - Multi-domain and multi-language search support
        - Thread-safe async operations

    Example:
        Basic client initialization and usage::

            # Simple client with IAM token
            client = YandexSearchClient(
                iamToken="your_iam_token",
                folderId="your_folder_id"
            )

            # Perform basic search
            results = await client.search("python programming")

        Advanced configuration with caching::

            from lib.yandex_search import DictSearchCache

            cache = DictSearchCache(maxSize=1000, defaultTtl=3600)
            client = YandexSearchClient(
                apiKey="your_api_key",
                folderId="your_folder_id",
                cache=cache,
                rateLimitRequests=20,
                rateLimitWindow=60
            )

            # Advanced search with custom parameters
            results = await client.search(
                queryText="machine learning",
                searchType=SearchType.SEARCH_TYPE_RU,
                region="225",
                maxPassages=3,
                groupsOnPage=5
            )
    """

    API_ENDPOINT = "https://searchapi.api.cloud.yandex.net/v2/web/search"

    def __init__(
        self,
        *,
        iamToken: Optional[str] = None,
        apiKey: Optional[str] = None,
        folderId: str = "",
        requestTimeout: int = 30,
        cache: Optional[SearchCacheInterface] = None,
        cacheTTL: Optional[int] = 3600,
        useCache: bool = True,
        rateLimitRequests: int = 10,
        rateLimitWindow: int = 60,
    ):
        """Initialize Yandex Search client with authentication and configuration.

        The client requires either an IAM token or API key for authentication.
        IAM tokens are recommended for production environments as they support
        automatic refresh, while API keys are static and suitable for simple
        applications or testing scenarios.

        Args:
            iamToken (Optional[str]): IAM token for authentication as alternative to apiKey.
                Obtain from Yandex Cloud IAM service. Recommended for production use.
            apiKey (Optional[str]): API key for authentication as alternative to iamToken.
                Create in Yandex Cloud console. Suitable for simple applications.
            folderId (str): Yandex Cloud folder ID (required). Find in Yandex Cloud console.
            requestTimeout (int): HTTP request timeout in seconds (default: 30).
            cache (Optional[SearchCacheInterface]): Cache implementation for result caching.
                If None, caching is disabled regardless of other cache settings.
            cacheTTL (Optional[int]): Default cache TTL in seconds (default: 3600 = 1 hour).
                Can be overridden per request. Ignored if cache is None.
            useCache (bool): Enable/disable caching for all requests by default.
                Can be overridden per request. Ignored if cache is None.
            rateLimitRequests (int): Maximum requests allowed within rate limit window
                (default: 10 requests). Must be positive integer.
            rateLimitWindow (int): Rate limit time window in seconds (default: 60 seconds).
                Uses sliding window algorithm. Must be positive integer.

        Raises:
            ValueError: If neither iamToken nor apiKey is provided, or if folderId is empty.
            ValueError: If rateLimitRequests or rateLimitWindow are not positive.

        Example:
            Production-ready client with caching and rate limiting::

                from lib.yandex_search import DictSearchCache

                cache = DictSearchCache(maxSize=1000, defaultTtl=3600)
                client = YandexSearchClient(
                    iamToken="your_iam_token",
                    folderId="your_folder_id",
                    cache=cache,
                    rateLimitRequests=20,
                    rateLimitWindow=60
                )

            Simple client for testing::

                client = YandexSearchClient(
                    apiKey="your_api_key",
                    folderId="your_folder_id"
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
        self.cache = cache
        self.cacheTTL = cacheTTL
        self.useCache = useCache

        # Rate limiting
        self.rateLimitRequests = rateLimitRequests
        self.rateLimitWindow = rateLimitWindow
        self._requestTimes: List[float] = []
        self._rateLimitLock = asyncio.Lock()

        # No persistent session - create new session for each request

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
        useCache: Optional[bool] = None,
    ) -> Optional[SearchResponse]:
        """Perform search with comprehensive parameter control.

        This method provides access to all Yandex Search API parameters with sensible
        defaults. It automatically handles caching (if enabled), rate limiting,
        and error recovery. A new HTTP session is created for each request to ensure
        thread safety in concurrent environments.

        Args:
            queryText (str): Search query text (required). Can contain any characters
                supported by the search engine. Empty strings will return no results.
            searchType (SearchType): Search domain identifier (default: SEARCH_TYPE_RU).
                Determines which Yandex search domain to use:
                - SEARCH_TYPE_RU: Russian search (yandex.ru)
                - SEARCH_TYPE_TR: Turkish search (yandex.com.tr)
                - SEARCH_TYPE_COM: International search (yandex.com)
                - SEARCH_TYPE_KK: Kazakh search (yandex.kz)
                - SEARCH_TYPE_BE: Belarusian search (yandex.by)
                - SEARCH_TYPE_UZ: Uzbek search (yandex.uz)
            familyMode (FamilyMode): Content filtering mode (default: FAMILY_MODE_MODERATE).
                Controls family-safe content filtering:
                - FAMILY_MODE_MODERATE: Moderate filtering
                - FAMILY_MODE_STRICT: Strict filtering
                - FAMILY_MODE_NONE: No filtering
            page (int): Page number for pagination (0-based, default: 0).
                Must be non-negative integer.
            fixTypoMode (FixTypoMode): Typo correction mode (default: FIX_TYPO_MODE_ON).
                Controls automatic typo correction:
                - FIX_TYPO_MODE_ON: Enable typo correction
                - FIX_TYPO_MODE_OFF: Disable typo correction
            sortMode (SortMode): Results sorting mode (default: SORT_MODE_BY_RELEVANCE).
                Determines primary sort criteria:
                - SORT_MODE_BY_RELEVANCE: Sort by relevance
                - SORT_MODE_BY_TIME: Sort by date
            sortOrder (SortOrder): Sort direction (default: SORT_ORDER_DESC).
                Controls sort order direction:
                - SORT_ORDER_DESC: Descending order
                - SORT_ORDER_ASC: Ascending order
            groupMode (GroupMode): Result grouping mode (default: GROUP_MODE_DEEP).
                Controls how results are grouped:
                - GROUP_MODE_DEEP: Deep grouping with hierarchy
                - GROUP_MODE_FLAT: Flat results without grouping
            groupsOnPage (Optional[int]): Number of result groups per page (default: 10).
                Valid range: 1-100. If None, uses API default.
            docsInGroup (Optional[int]): Number of documents per group (default: 2).
                Valid range: 1-10. If None, uses API default.
            maxPassages (int): Maximum text passages per document (default: 2).
                Valid range: 1-5. Controls snippet length.
            region (str): Region code for localized results (default: "225" for Russia).
                See Yandex Search API documentation for complete region codes list.
            l10n (Localization): Interface language (default: LOCALIZATION_RU).
                Controls response language and formatting:
                - LOCALIZATION_RU: Russian
                - LOCALIZATION_EN: English
                - LOCALIZATION_TR: Turkish
                - Additional languages available
            useCache (Optional[bool]): Cache override for this request.
                If False, bypass cache for this request only.
                If True, force cache usage (if available).
                If None, uses client's default useCache setting.

        Returns:
            Optional[SearchResponse]: Search response dictionary with structure:
                {
                    'requestId': str,           # Unique request identifier
                    'found': int,               # Total results found
                    'foundHuman': str,          # Human-readable result count
                    'page': int,                # Current page number
                    'groups': List[SearchGroup], # Result groups with documents
                    'error': Optional[Dict]     # Error information if any
                }
                Returns None if an error occurs and no cached result is available.

        Example:
            Advanced search with custom parameters::

                results = await client.search(
                    queryText="machine learning tutorials",
                    searchType=SearchType.SEARCH_TYPE_RU,
                    familyMode=FamilyMode.FAMILY_MODE_MODERATE,
                    fixTypoMode=FixTypoMode.FIX_TYPO_MODE_ON,
                    sortMode=SortMode.SORT_MODE_BY_RELEVANCE,
                    groupMode=GroupMode.GROUP_MODE_DEEP,
                    groupsOnPage=5,
                    docsInGroup=3,
                    maxPassages=2,
                    region="225",
                    l10n=Localization.LOCALIZATION_RU
                )

                if results:
                    print(f"Found {results['found']} results")
                    for group in results['groups']:
                        for doc in group['group']:
                            print(f"Title: {doc['title']}")
                            print(f"URL: {doc['url']}")
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

        # Check cache first (if enabled and not bypassed)
        effectiveUseCache = useCache if useCache is not None else self.useCache
        if self.cache and effectiveUseCache:
            cachedResult = await self.cache.getSearch(request, self.cacheTTL)
            if cachedResult:
                logger.debug(f"Cache hit for query: {queryText}")
                return cachedResult
            else:
                logger.debug(f"Cache miss for query: {queryText}")

        # Apply rate limiting
        await self._applyRateLimit()

        # Make API request
        result = await self._makeRequest(request)

        # Cache successful results
        if result and self.cache and effectiveUseCache:
            await self.cache.setSearch(request, result)
            logger.debug(f"Cached result for query: {queryText}")

        return result

    async def _makeRequest(self, request: SearchRequest) -> Optional[SearchResponse]:
        """Make HTTP request to Yandex Search API with proper error handling.

        This method creates a new HTTP session for each request to ensure proper
        concurrent request handling without session conflicts. It handles all
        HTTP status codes and network errors gracefully.

        Args:
            request (SearchRequest): Complete search request structure with all
                required parameters and authentication information.

        Returns:
            Optional[SearchResponse]: Parsed search response if successful,
                None if any error occurs during the request.

        Note:
            The method handles various error conditions:
            - HTTP 4xx errors (authentication, authorization, rate limiting)
            - HTTP 5xx errors (server issues)
            - Network timeouts and connection errors
            - JSON parsing errors
            - XML parsing errors (delegated to parseSearchResponse)
        """
        try:
            logger.debug(f"Making search request: {request}")

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

    async def _applyRateLimit(self) -> None:
        """Apply rate limiting using sliding window algorithm to prevent API abuse.

        This method implements a sophisticated sliding window rate limiter that
        tracks request timestamps and ensures the request count doesn't exceed the
        configured limit within the specified time window. When the limit is reached,
        the method automatically sleeps until the oldest request falls outside
        the window.

        Algorithm Implementation:
            1. Remove request timestamps outside the current time window
            2. Check if remaining requests exceed the configured limit
            3. If limit exceeded, calculate required wait time and sleep
            4. Clean up old requests after waiting period
            5. Add current request timestamp to tracking list

        Thread Safety:
            This method is thread-safe due to asyncio.Lock() usage, ensuring
            atomic operations on the request tracking list in concurrent environments.

        Note:
            Rate limiting is applied per client instance. For global rate limiting
            across multiple processes or servers, consider implementing an external
            distributed rate limiter (e.g., Redis-based or database-backed).

        Performance Considerations:
            - The sliding window provides smooth request distribution
            - Memory usage scales with request rate, not total requests
            - Lock contention is minimal due to short critical sections
        """
        async with self._rateLimitLock:
            currentTime = time.time()

            # Remove old request times outside the window
            self._requestTimes = [
                reqTime for reqTime in self._requestTimes if currentTime - reqTime < self.rateLimitWindow
            ]

            # Check if we've exceeded the rate limit
            if len(self._requestTimes) >= self.rateLimitRequests:
                # Calculate how long to wait
                oldestRequest = min(self._requestTimes)
                waitTime = self.rateLimitWindow - (currentTime - oldestRequest)

                if waitTime > 0:
                    logger.debug(f"Rate limit reached, waiting {waitTime:.2f} seconds")
                    await asyncio.sleep(waitTime)

                    # Clean up old requests after waiting
                    currentTime = time.time()
                    self._requestTimes = [
                        req_time for req_time in self._requestTimes if currentTime - req_time < self.rateLimitWindow
                    ]

            # Add current request time
            self._requestTimes.append(currentTime)

    def getRateLimitStats(self) -> Dict[str, Any]:
        """Get current rate limiting statistics for monitoring and debugging.

        This method provides real-time insights into the rate limiting status,
        useful for monitoring API usage patterns, debugging rate limiting issues,
        or implementing adaptive request strategies.

        Returns:
            Dict[str, Any]: Rate limiting statistics dictionary containing:
                - requestsInWindow (int): Current requests in the active time window
                - maxRequests (int): Maximum allowed requests per window
                - windowSeconds (int): Time window duration in seconds
                - resetTime (float): Unix timestamp when window will reset
                    (oldest request time + window duration)

        Example:
            Monitoring rate limit usage::

                stats = client.getRateLimitStats()
                print(f"Used {stats['requestsInWindow']}/{stats['maxRequests']} requests")
                print(f"Window resets at: {stats['resetTime']}")

                # Calculate remaining requests
                remaining = stats['maxRequests'] - stats['requestsInWindow']
                print(f"Remaining requests: {remaining}")

            Implementing adaptive delays::

                stats = client.getRateLimitStats()
                if stats['requestsInWindow'] >= stats['maxRequests'] * 0.8:
                    # Approaching limit, add extra delay
                    await asyncio.sleep(1.0)
        """
        currentTime = time.time()
        recent_requests = [reqTime for reqTime in self._requestTimes if currentTime - reqTime < self.rateLimitWindow]

        return {
            "requests_in_window": len(recent_requests),
            "max_requests": self.rateLimitRequests,
            "window_seconds": self.rateLimitWindow,
            "reset_time": max(recent_requests) + self.rateLimitWindow if recent_requests else currentTime,
        }
