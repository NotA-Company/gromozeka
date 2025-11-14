"""Cache utilities for Yandex Search API.

This module provides specialized cache key generation for Yandex Search requests,
ensuring consistent and efficient caching of search results while excluding
client-specific parameters that don't affect the search results.
"""

from lib.cache import JsonKeyGenerator

from .models import SearchRequest


class SearchRequestKeyGenerator(JsonKeyGenerator[SearchRequest]):
    """Cache key generator for Yandex Search requests.

    Extends JsonKeyGenerator to create consistent cache keys for search requests
    by normalizing the request structure and excluding client-specific parameters
    like folderId that don't affect the search results.

    Example:
        Create a cache key generator and use it to generate keys::

            keyGen = SearchRequestKeyGenerator()
            request = {
                "query": {"searchType": "SEARCH_TYPE_RU", "queryText": "python"},
                "sortSpec": {"sortMode": "SORT_MODE_BY_RELEVANCE", "sortOrder": "SORT_ORDER_DESC"},
                "groupSpec": {"groupMode": "GROUP_MODE_DEEP"},
                "maxPassages": "2",
                "region": "225",
                "l10n": "LOCALIZATION_RU",
                "folderId": "b1g...123"  # This will be excluded from cache key
            }
            cacheKey = keyGen.generateKey(request)
    """

    def generateKey(self, obj: SearchRequest) -> str:
        """Generate a normalized cache key for a search request.

        Creates a consistent cache key by extracting only the parameters that
        affect search results, excluding client-specific values like folderId.
        This ensures that requests with the same search parameters but different
        client configurations will use the same cache entry.

        Args:
            obj (SearchRequest): The search request dictionary to generate a key for.
                Expected structure follows the Yandex Search API v2 format.

        Returns:
            str: A SHA512 hash of the normalized request parameters.
        """
        # Create a normalized representation of the request
        # Exclude folderId from cache key as it's constant per client
        cacheData = {
            "query": obj["query"],
            "sortSpec": obj.get("sortSpec", None),
            "groupSpec": obj.get("groupSpec", None),
            "maxPassages": obj.get("maxPassages", None),
            "region": obj.get("region", None),
            "l10n": obj.get("l10n", None),
        }

        return super().generateKey(cacheData)
