"""
Yandex Search API Async Client

API References:
- https://yandex.cloud/ru/docs/search-api/api-ref/WebSearch/search
- https://yandex.cloud/ru/docs/search-api/concepts/response

This module provides the main YandexSearchClient class for interacting with
the Yandex Search API v2 with XML response format.

The client supports:
- IAM token and API key authentication
- Configurable caching with TTL
- Rate limiting to prevent API abuse
- Comprehensive error handling
- Multiple search domains and languages

Example:
    ```python
    from lib.yandex_search import YandexSearchClient, DictSearchCache

    # Initialize with cache
    cache = DictSearchCache(max_size=1000, default_ttl=3600)
    client = YandexSearchClient(
        iam_token="your_iam_token",
        folder_id="your_folder_id",
        cache=cache
    )

    # Simple search
    results = await client.search("python programming")
    if results:
        print(f"Found {results['found']} results")
        for group in results['groups']:
            for doc in group['group']:
                print(f"Title: {doc['title']}")
                print(f"URL: {doc['url']}")
    ```
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
    """
    Async client for Yandex Search API v2 with XML response format.

    This client provides a high-level interface to the Yandex Search API, supporting
    various search parameters, caching, and rate limiting. It creates a new HTTP session
    for each request to support proper concurrent requests without session conflicts.

    Features:
    - Support for both IAM token and API key authentication
    - Configurable caching with TTL support
    - Built-in rate limiting to prevent API abuse
    - Comprehensive error handling and logging
    - Support for multiple search domains and languages

    Example usage:
        ```python
        # Basic usage with IAM token
        client = YandexSearchClient(
            iam_token="your_iam_token",
            folder_id="your_folder_id"
        )

        # Simple search with defaults
        results = await client.search("python programming")

        # Advanced search with custom parameters
        results = await client.search(
            query_text="machine learning",
            search_type="SEARCH_TYPE_RU",
            region="225",
            max_passages=3,
            groups_on_page=5
        )

        # With caching
        from lib.yandex_search import DictSearchCache
        cache = DictSearchCache(max_size=1000, default_ttl=3600)
        client = YandexSearchClient(
            api_key="your_api_key",
            folder_id="your_folder_id",
            cache=cache
        )
        ```
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
        """
        Initialize Yandex Search client with authentication and configuration options.

        The client requires either an IAM token or API key for authentication.
        IAM tokens are recommended for production use as they can be automatically
        refreshed, while API keys are static and suitable for simple applications.

        Args:
            iamToken: IAM token for authentication (alternative to apiKey).
                     Obtain from Yandex Cloud IAM service.
            apiKey: API key for authentication (alternative to iamToken).
                   Create in Yandex Cloud console.
            folderId: Yandex Cloud folder ID (required). Find in Yandex Cloud console.
            requestTimeout: HTTP request timeout in seconds (default: 30).
            cache: Optional cache implementation for caching search results.
                  If None, caching is disabled.
            cacheTTL: Default cache TTL in seconds (default: 3600 = 1 hour).
                     Can be overridden per request.
            useCache: If False, do not use cache for all requests by default.
                        Can be overridden per request.
            rateLimitRequests: Maximum requests allowed within the rate limit window
                              (default: 10 requests).
            rateLimitWindow: Rate limit time window in seconds (default: 60 seconds).
                            Uses sliding window algorithm.

        Raises:
            ValueError: If neither iamToken nor apiKey is provided, or if folderId is empty.

        Example:
            ```python
            # With IAM token and caching
            cache = DictSearchCache(max_size=1000, default_ttl=3600)
            client = YandexSearchClient(
                iam_token="your_iam_token",
                folder_id="your_folder_id",
                cache=cache,
                rate_limit_requests=20,
                rate_limit_window=60
            )
            ```
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
        """
        Perform search with full parameter control.

        This method provides access to all Yandex Search API parameters.
         It provides sensible defaults.

        The method automatically handles caching (if enabled), rate limiting, and
        error recovery. It creates a new HTTP session for each request to ensure
        thread safety in concurrent environments.

        Args:
            queryText: Search query text (required). Can contain any characters
                      supported by the search engine.
            searchType: Search domain identifier (default: "SEARCH_TYPE_RU").
                       Valid values:
                       - SEARCH_TYPE_RU: Russian search (yandex.ru)
                       - SEARCH_TYPE_TR: Turkish search (yandex.com.tr)
                       - SEARCH_TYPE_COM: International search (yandex.com)
                       - SEARCH_TYPE_KK: Kazakh search (yandex.kz)
                       - SEARCH_TYPE_BE: Belarusian search (yandex.by)
                       - SEARCH_TYPE_UZ: Uzbek search (yandex.uz)
            familyMode: Family filter mode for content filtering.
                       Valid values:
                       - FAMILY_MODE_MODERATE: Moderate filtering
                       - FAMILY_MODE_STRICT: Strict filtering
                       - FAMILY_MODE_OFF: No filtering
            page: Page number for pagination (0-based, default: 0).
            fixTypoMode: Typo correction mode.
                        Valid values:
                        - FIX_TYPO_MODE_ON: Enable typo correction
                        - FIX_TYPO_MODE_OFF: Disable typo correction
            sortMode: Sort mode for results.
                     Valid values:
                     - SORT_MODE_BY_RELEVANCE: Sort by relevance (default)
                     - SORT_MODE_BY_TIME: Sort by date
            sortOrder: Sort order direction.
                      Valid values:
                      - SORT_ORDER_DESC: Descending order (default)
                      - SORT_ORDER_ASC: Ascending order
            groupMode: Result grouping mode.
                      Valid values:
                      - GROUP_MODE_DEEP: Deep grouping (default)
                      - GROUP_MODE_FLAT: Flat results
            groupsOnPage: Number of result groups per page (default: 10).
                          Valid range: 1-100.
            docsInGroup: Number of documents in each group (default: 2).
                         Valid range: 1-10.
            maxPassages: Maximum number of text passages per document (default: 2).
                        Valid range: 1-5.
            region: Region code for localized results (default: "225" for Russia).
                    See Yandex Search API documentation for region codes.
            l10n: Localization language (default: "LOCALIZATION_RU").
                  Valid values:
                  - LOCALIZATION_RU: Russian
                  - LOCALIZATION_EN: English
                  - LOCALIZATION_TR: Turkish
                  - etc.
            useCache: If False, do not use cache for this request (overrides client default).
                        If None, uses client's default useCache setting.

        Returns:
            SearchResponse: Dictionary containing search results with the following structure:
                {
                    'requestId': str,      # Unique request identifier
                    'found': int,          # Total number of results found
                    'foundHuman': str,     # Human-readable result count
                    'page': int,           # Current page number
                    'groups': List[SearchGroup],  # List of result groups
                    'error': Optional[Dict]       # Error information if any
                }
            Returns None if an error occurs and no cached result is available.

        Example:
            ```python
            # Advanced search with custom parameters
            results = await client.search(
                query_text="machine learning tutorials",
                search_type="SEARCH_TYPE_RU",
                family_mode="FAMILY_MODE_MODERATE",
                fix_typo_mode="FIX_TYPO_MODE_ON",
                sort_mode="SORT_MODE_BY_RELEVANCE",
                group_mode="GROUP_MODE_DEEP",
                groups_on_page=5,
                docs_in_group=3,
                max_passages=2,
                region="225",
                l10n="LOCALIZATION_RU"
            )

            if results:
                print(f"Found {results['found']} results")
                for group in results['groups']:
                    for doc in group['group']:
                        print(f"Title: {doc['title']}")
                        print(f"URL: {doc['url']}")
            ```
        """
        # Build group specification
        groupSpec: Optional[GroupSpec] = {"groupMode": groupMode}

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
        """
        Make HTTP request to Yandex Search API

        Creates a new session for each request to support proper concurrent requests.

        Args:
            request: Search request structure

        Returns:
            Parsed SearchResponse or None on error
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
                    logger.debug(f"API response: {responseData}")

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
        """
        Apply rate limiting to prevent API abuse using sliding window algorithm.

        This method implements a sliding window rate limiter that tracks request
        timestamps and ensures the number of requests doesn't exceed the configured
        limit within the time window. If the limit is reached, the method will
        sleep until the oldest request falls outside the window.

        The algorithm works as follows:
        1. Remove request timestamps that are outside the current time window
        2. If the number of remaining requests exceeds the limit, calculate wait time
        3. Sleep if necessary, then clean up old requests again
        4. Add the current request timestamp to the tracking list

        This method is thread-safe due to the use of asyncio.Lock().

        Note:
            The rate limiting is applied per client instance. If you need global
            rate limiting across multiple processes, consider implementing an
            external rate limiter (e.g., Redis-based).
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
        """
        Get current rate limiting statistics for monitoring and debugging.

        This method provides real-time information about the rate limiting
        status, which can be useful for monitoring API usage or debugging
        rate limiting issues.

        Returns:
            Dict[str, any]: Dictionary containing the following fields:
                - requests_in_window (int): Number of requests made in the current window
                - max_requests (int): Maximum allowed requests per window
                - window_seconds (int): Time window duration in seconds
                - reset_time (float): Unix timestamp when the window will reset
                                    (oldest request time + window duration)

        Example:
            ```python
            stats = client.get_rate_limit_stats()
            print(f"Used {stats['requests_in_window']}/{stats['max_requests']} requests")
            print(f"Window resets at: {stats['reset_time']}")
            ```
        """
        currentTime = time.time()
        recent_requests = [reqTime for reqTime in self._requestTimes if currentTime - reqTime < self.rateLimitWindow]

        return {
            "requests_in_window": len(recent_requests),
            "max_requests": self.rateLimitRequests,
            "window_seconds": self.rateLimitWindow,
            "reset_time": max(recent_requests) + self.rateLimitWindow if recent_requests else currentTime,
        }
