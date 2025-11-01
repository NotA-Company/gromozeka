"""Yandex Search API async client library.

This module provides a comprehensive async client library for interacting with the
Yandex Search API v2, featuring XML response parsing, caching capabilities, and
rate limiting support.

The library offers a clean, type-safe interface for performing text searches with
various parameters including region targeting, search type specification, and
result filtering. Built-in caching and rate limiting help optimize performance
and prevent API abuse.

Example:
    Basic search usage with API key authentication::

        from lib.yandex_search import YandexSearchClient

        # Initialize client with credentials
        client = YandexSearchClient(
            apiKey="your_api_key",
            folderId="your_folder_id"
        )

        # Perform simple search
        results = await client.search("python programming")
        if results:
            print(f"Found {results['found']} results")
            for group in results['groups']:
                for doc in group:
                    print(f"Title: {doc['title']}")
                    print(f"URL: {doc['url']}")

    Advanced search with custom parameters::

        from lib.yandex_search.models import SearchType

        results = await client.search(
            queryText="machine learning",
            searchType=SearchType.SEARCH_TYPE_RU,
            region="225",
            maxPassages=3
        )

    Search with caching enabled::

        from lib.yandex_search import DictSearchCache

        cache = DictSearchCache(maxSize=100, defaultTtl=300)
        client = YandexSearchClient(
            apiKey="your_api_key",
            folderId="your_folder_id",
            cache=cache
        )

        # This request will be cached
        results = await client.search("artificial intelligence")

Components:
    YandexSearchClient: Main async client for API interactions
    SearchCacheInterface: Abstract interface for cache implementations
    DictSearchCache: In-memory cache implementation with TTL support
    parseSearchResponse: XML response parser utility
    Various TypedDict models for type-safe API interactions

Note:
    This library requires proper Yandex Cloud credentials (IAM token or API key)
    and a valid folder ID to function correctly.
"""

from .cache_interface import SearchCacheInterface
from .client import YandexSearchClient
from .dict_cache import DictSearchCache
from .models import (
    ErrorResponse,
    GroupSpec,
    SearchGroup,
    SearchQuery,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SortSpec,
)
from .xml_parser import parseSearchResponse

__all__ = [
    # Client
    "YandexSearchClient",
    # Models
    "ErrorResponse",
    "GroupSpec",
    "SearchQuery",
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    "SearchGroup",
    "SortSpec",
    # XML Parser
    "parseSearchResponse",
    # Cache
    "SearchCacheInterface",
    "DictSearchCache",
]