"""
Yandex Search API Async Client Library

This module provides an async client for the Yandex Search API v2 with XML response format.
Supports text search with various parameters and response parsing.

Example usage:
    from lib.yandex_search import YandexSearchClient

    # Initialize with IAM token
    client = YandexSearchClient(
        iam_token="your_iam_token",
        folder_id="your_folder_id"
    )

    # Simple search
    results = await client.searchSimple("python programming")
    if results:
        print(f"Found {results['found']} results")
        for group in results['groups']:
            for doc in group['group']:
                print(f"Title: {doc['title']}")
                print(f"URL: {doc['url']}")

    # Advanced search
    results = await client.search(
        query_text="machine learning",
        search_type="SEARCH_TYPE_RU",
        region="225",
        max_passages=3
    )
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
