"""Yandex Search API v2 async client with XML parsing, caching, and rate limiting.

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

    Supports IAM token and API key authentication, with per-request HTTP sessions
    for thread-safe concurrent operations.

    Example:
        client = YandexSearchClient(
            iamToken="your_iam_token",
            folderId="your_folder_id"
        )
        results = await client.search("python programming")
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

        Args:
            iamToken: IAM token for authentication (alternative to apiKey)
            apiKey: API key for authentication (alternative to iamToken)
            folderId: Yandex Cloud folder ID (required)
            requestTimeout: HTTP request timeout in seconds (default: 30)
            cache: Cache implementation for result caching (default: None)
            cacheTTL: Default cache TTL in seconds (default: 3600)
            rateLimiterQueue: Rate limiter queue name (default: "yandex-search")

        Raises:
            ValueError: If neither iamToken nor apiKey is provided, or if folderId is empty
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

        Args:
            queryText: Search query text (required)
            searchType: Search domain (default: SEARCH_TYPE_RU)
            familyMode: Content filtering (default: FAMILY_MODE_MODERATE)
            page: Page number for pagination (default: 0)
            fixTypoMode: Typo correction mode (default: FIX_TYPO_MODE_ON)
            sortMode: Sort criteria (default: SORT_MODE_BY_RELEVANCE)
            sortOrder: Sort direction (default: SORT_ORDER_DESC)
            groupMode: Result grouping (default: GROUP_MODE_DEEP)
            groupsOnPage: Groups per page (default: API default)
            docsInGroup: Documents per group (default: API default)
            maxPassages: Max passages per document (default: 2)
            region: Region code (default: "225" for Russia)
            l10n: Interface language (default: LOCALIZATION_RU)
            cacheTTL: Override default cache TTL

        Returns:
            Search response dict or None if error occurs
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

        # Apply rate limiting
        await self._rateLimiter.applyLimit(self.rateLimiterQueue)

        # Make API request
        result = await self._makeRequest(request)

        # Cache successful results
        if result is not None:
            await self.cache.set(request, result)
            logger.debug(f"Cached result for query: {queryText}")

        return result

    async def _makeRequest(self, request: SearchRequest) -> Optional[SearchResponse]:
        """Make HTTP request to Yandex Search API with error handling.

        Creates new session per request for thread safety. Handles HTTP errors,
        network issues, and parsing failures.

        Args:
            request: Complete search request with authentication

        Returns:
            Parsed search response or None if error occurs
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
