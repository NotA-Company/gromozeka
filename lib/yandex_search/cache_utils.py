"""Cache utilities for Yandex Search API.

This module provides specialized cache key generation for Yandex Search requests,
ensuring consistent and efficient caching of search results while excluding
client-specific parameters that don't affect the search results.

The primary component is SearchRequestKeyGenerator, which extends JsonKeyGenerator
to create normalized cache keys that exclude client-specific fields like folderId.
This allows multiple clients with different folder IDs to share cached results
when searching for the same content.

Key Features:
    - Normalized cache key generation for search requests
    - Exclusion of client-specific parameters (folderId, metadata)
    - Consistent hashing regardless of parameter order
    - Support for all Yandex Search API v2 request parameters

Example:
    Basic usage with a cache implementation::

        from lib.cache import DictCache
        from lib.yandex_search.cache_utils import SearchRequestKeyGenerator
        from lib.yandex_search.models import SearchRequest, SearchType

        # Create cache with custom key generator
        cache = DictCache(keyGenerator=SearchRequestKeyGenerator())

        # Search request that will be cached
        request: SearchRequest = {
            "query": {
                "searchType": SearchType.SEARCH_TYPE_RU,
                "queryText": "python programming"
            },
            "folderId": "your_folder_id"
        }

        # Cache key will be the same regardless of folderId
        cacheKey = cache.keyGenerator.generateKey(request)
"""

from lib.cache import JsonKeyGenerator

from .models import SearchRequest


class SearchRequestKeyGenerator(JsonKeyGenerator[SearchRequest]):
    """Cache key generator for Yandex Search requests.

    Extends JsonKeyGenerator to create consistent cache keys for search requests
    by normalizing the request structure and excluding client-specific parameters
    like folderId and metadata that don't affect the search results.

    This generator ensures that requests with identical search parameters but
    different client configurations (e.g., different folder IDs) will generate
    the same cache key, enabling efficient cache sharing across multiple clients.

    Attributes:
        sort_keys (bool): Whether to sort JSON keys for consistent serialization.
            Inherited from JsonKeyGenerator. Defaults to True.
        hash (bool): Whether to create SHA512 hash of the JSON string.
            Inherited from JsonKeyGenerator. Defaults to True.

    Example:
        Create a cache key generator and use it to generate keys::

            from lib.yandex_search.cache_utils import SearchRequestKeyGenerator
            from lib.yandex_search.models import SearchRequest, SearchType

            keyGen = SearchRequestKeyGenerator()
            request: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "python"
                },
                "sortSpec": {
                    "sortMode": "SORT_MODE_BY_RELEVANCE",
                    "sortOrder": "SORT_ORDER_DESC"
                },
                "groupSpec": {"groupMode": "GROUP_MODE_DEEP"},
                "maxPassages": "2",
                "region": "225",
                "l10n": "LOCALIZATION_RU",
                "folderId": "b1g...123"  # This will be excluded from cache key
            }
            cacheKey = keyGen.generateKey(request)

        The same search with a different folderId produces the same key::

            request2: SearchRequest = request.copy()
            request2["folderId"] = "different_folder_id"
            cacheKey2 = keyGen.generateKey(request2)
            assert cacheKey == cacheKey2  # True - same cache key
    """

    def generateKey(self, obj: SearchRequest) -> str:
        """Generate a normalized cache key for a search request.

        Creates a consistent cache key by extracting only the parameters that
        affect search results, excluding client-specific values like folderId
        and metadata. This ensures that requests with the same search parameters
        but different client configurations will use the same cache entry.

        The method extracts the following fields from the request:
            - query: Core search query parameters (required)
            - sortSpec: Sorting configuration (optional)
            - groupSpec: Grouping configuration (optional)
            - maxPassages: Maximum passages per document (optional)
            - region: Region code for localized results (optional)
            - l10n: Interface language (optional)

        Excluded fields (not affecting search results):
            - folderId: Client-specific identifier
            - metadata: Search flags and metadata
            - responseFormat: Response format (client-side concern)

        Args:
            obj: The search request dictionary to generate a key for.
                Expected structure follows the Yandex Search API v2 format
                as defined in SearchRequest TypedDict.

        Returns:
            str: A 128-character SHA512 hash of the normalized request parameters.
                The hash is deterministic - the same request will always produce
                the same hash, regardless of parameter order in the original request.

        Raises:
            KeyError: If the required 'query' field is missing from the request.
            TypeError: If the request structure is invalid or cannot be serialized.

        Example:
            Generate cache keys for identical searches with different clients::

                from lib.yandex_search.cache_utils import SearchRequestKeyGenerator
                from lib.yandex_search.models import SearchRequest, SearchType

                keyGen = SearchRequestKeyGenerator()

                # Client A's request
                requestA: SearchRequest = {
                    "query": {
                        "searchType": SearchType.SEARCH_TYPE_RU,
                        "queryText": "python tutorial"
                    },
                    "folderId": "client_a_folder"
                }

                # Client B's request (same search, different folder)
                requestB: SearchRequest = {
                    "query": {
                        "searchType": SearchType.SEARCH_TYPE_RU,
                        "queryText": "python tutorial"
                    },
                    "folderId": "client_b_folder"
                }

                # Both generate the same cache key
                keyA = keyGen.generateKey(requestA)
                keyB = keyGen.generateKey(requestB)
                assert keyA == keyB  # True - shared cache entry
        """
        # Create a normalized representation of the request
        # Exclude folderId from cache key as it's constant per client
        # Also exclude metadata and responseFormat as they don't affect results
        cacheData = {
            "query": obj["query"],
            "sortSpec": obj.get("sortSpec", None),
            "groupSpec": obj.get("groupSpec", None),
            "maxPassages": obj.get("maxPassages", None),
            "region": obj.get("region", None),
            "l10n": obj.get("l10n", None),
        }

        return super().generateKey(cacheData)
