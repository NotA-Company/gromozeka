"""
Yandex Search API Client Usage Examples

This module demonstrates various usage patterns for the Yandex Search API client,
including basic searches, advanced configurations, caching, rate limiting,
and error handling.

Run these examples with:
    ./venv/bin/python3 lib/yandex_search/examples.py

Note: You need to provide valid Yandex Cloud credentials (IAM token or API key)
and folder ID for these examples to work.
"""

import asyncio
import json
import logging
import os
import sys

# Add the project root to the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lib.yandex_search import DictSearchCache, YandexSearchClient  # noqa: E402
from lib.yandex_search.models import (  # noqa: E402
    FamilyMode,
    FixTypoMode,
    GroupMode,
    Localization,
    SearchType,
    SortMode,
    SortOrder,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# Configuration - Replace with your actual credentials
# You can get these from environment variables or hardcode for testing
IAM_TOKEN = os.getenv("YANDEX_IAM_TOKEN", "")
API_KEY = os.getenv("YANDEX_API_KEY", "")
FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")

if not FOLDER_ID:
    with open(".env", "r") as f:
        for line in f:
            splitted_line = line.split("=")
            if len(splitted_line) == 2:
                key, value = splitted_line
                if key == "YANDEX_FOLDER_ID":
                    FOLDER_ID = value.strip().strip('"')
                elif key == "YANDEX_API_KEY":
                    API_KEY = value.strip().strip('"')
                elif key == "YANDEX_IAM_TOKEN":
                    IAM_TOKEN = value.strip().strip('"')

# import lib.yandex_search.xml_parser as ys_xml_parser  # noqa: E402
# ys_xml_parser.DEBUG_PRINT_FULL = True


async def example_basic_search():
    """Example 1: Basic search with minimal configuration"""
    print("\n=== Example 1: Basic Search ===")
    # print(f"apiKey={API_KEY}, folderId={FOLDER_ID}")
    # Initialize client with IAM token
    # client = YandexSearchClient(iamToken=IAM_TOKEN, folderId=FOLDER_ID)
    client = YandexSearchClient(apiKey=API_KEY, folderId=FOLDER_ID)
    # Perform a simple search
    query = "python programming tutorials"
    print(f"Searching for: {query}")

    results = await client.search(query)

    if results:
        print(f"Found {results['found']} results")
        print(f"Page: {results['page']}")
        print(f"Request ID: {results['requestId']}")

        # Display first few results
        for i, group in enumerate(results["groups"][:3]):
            print(f"\nGroup {i + 1}:")
            for j, doc in enumerate(group):
                print(f"  {j + 1}: {json.dumps(doc, indent=2, default=str, ensure_ascii=False)}")
                # print(f"  {j + 1}. {doc['title']}")
                # print(f"     URL: {doc['url']}")
                # print(f"     Domain: {doc['domain']}")
                # if doc["passages"]:
                #    print(f"     Passage: {doc['passages'][0][:100]}...")
    else:
        print("No results found or error occurred")

    # Clean up
    await client._applyRateLimit()  # Just to show the method


async def example_search_with_api_key():
    """Example 2: Search using API key authentication"""
    print("\n=== Example 2: Search with API Key ===")

    # Initialize client with API key
    client = YandexSearchClient(apiKey=API_KEY, folderId=FOLDER_ID)

    # Search with custom parameters
    query = "machine learning algorithms"
    print(f"Searching for: {query}")

    results = await client.search(queryText=query, searchType=SearchType.SEARCH_TYPE_RU, maxPassages=3, groupsOnPage=5)

    if results:
        print(f"Found {results['foundHuman']} results")

        # Show highlighted words from first result
        if results["groups"] and results["groups"][0]:
            first_doc = results["groups"][0][0]
            hlwords = first_doc.get("hlwords")
            if hlwords:
                print(f"Highlighted words: {', '.join(hlwords)}")
    else:
        print("Search failed")


async def example_advanced_search():
    """Example 3: Advanced search with full parameter control"""
    print("\n=== Example 3: Advanced Search ===")

    client = YandexSearchClient(apiKey=API_KEY, folderId=FOLDER_ID)

    # Advanced search with all parameters
    results = await client.search(
        queryText="artificial intelligence in healthcare",
        searchType=SearchType.SEARCH_TYPE_RU,
        familyMode=FamilyMode.FAMILY_MODE_MODERATE,
        page=0,
        fixTypoMode=FixTypoMode.FIX_TYPO_MODE_ON,
        sortMode=SortMode.SORT_MODE_BY_RELEVANCE,
        sortOrder=SortOrder.SORT_ORDER_DESC,
        groupMode=GroupMode.GROUP_MODE_DEEP,
        groupsOnPage=3,
        docsInGroup=2,
        maxPassages=2,
        region="225",  # Russia
        l10n=Localization.LOCALIZATION_RU,
    )

    if results:
        print("Advanced search completed successfully")
        print(f"Results found: {results['found']}")

        # Display detailed information
        for group in results["groups"]:
            for doc in group:
                print(f"\nTitle: {doc['title']}")
                print(f"URL: {doc['url']}")
                if doc.get("size"):
                    print(f"Size: {doc.get('size', None)}")
                if doc.get("modtime"):
                    print(f"Modified: {doc.get('modtime', None)}")
                if doc.get("passages"):
                    for passage in doc["passages"]:
                        print(f"Passage: {passage}")
    else:
        print("Advanced search failed")


async def example_search_with_cache():
    """Example 4: Search with caching enabled"""
    print("\n=== Example 4: Search with Caching ===")

    # Create cache with custom settings
    cache = DictSearchCache(default_ttl=1800, max_size=100)  # 30 minutes

    client = YandexSearchClient(apiKey=API_KEY, folderId=FOLDER_ID, cache=cache, cacheTTL=1800)

    query = "data science best practices"
    print(f"First search for: {query}")

    # First search - will hit the API
    results1 = await client.search(query)
    if results1:
        print(f"First search found {results1['found']} results")

    # Check cache stats
    stats = cache.getStats()
    print(f"Cache entries after first search: {stats['search_entries']}")

    # Second search - should hit the cache
    print(f"\nSecond search for: {query} (should be cached)")
    results2 = await client.search(query)
    if results2:
        print(f"Second search found {results2['found']} results")
        print("Results retrieved from cache (faster response)")

    # Bypass cache
    print("\nThird search bypassing cache")
    results3 = await client.search(query, useCache=False)
    if results3:
        print(f"Third search found {results3['found']} results")
        print("Results retrieved fresh from API")

    # Final cache stats
    stats = cache.getStats()
    print(f"\nFinal cache stats: {stats}")


async def example_rate_limiting():
    """Example 5: Rate limiting demonstration"""
    print("\n=== Example 5: Rate Limiting ===")

    # Create client with strict rate limiting
    client = YandexSearchClient(
        apiKey=API_KEY,
        folderId=FOLDER_ID,
        rateLimitRequests=2,  # Only 2 requests per window
        rateLimitWindow=5,  # 5 second window
    )

    queries = ["python web frameworks", "javascript libraries", "rust programming", "go language features"]

    print(f"Making {len(queries)} requests with rate limit of 2 per 5 seconds")

    for i, query in enumerate(queries):
        print(f"\nRequest {i + 1}: {query}")

        # Show rate limit stats before request
        stats = client.getRateLimitStats()
        print(f"Rate limit status: {stats['requests_in_window']}/{stats['max_requests']} requests")

        # Make the request
        start_time = asyncio.get_event_loop().time()
        results = await client.search(query)
        end_time = asyncio.get_event_loop().time()

        if results:
            print(f"  Found {results['found']} results in {end_time - start_time:.2f}s")
        else:
            print("  Request failed or no results")

        # Show rate limit stats after request
        stats = client.getRateLimitStats()
        print(f"  Rate limit after: {stats['requests_in_window']}/{stats['max_requests']}")
        if stats["requests_in_window"] >= stats["max_requests"]:
            print("  Rate limit reached, next request will be delayed")


async def example_error_handling():
    """Example 6: Error handling demonstration"""
    print("\n=== Example 6: Error Handling ===")

    # Client with invalid credentials (will fail)
    client = YandexSearchClient(iamToken="invalid_token", folderId="invalid_folder")

    print("Testing with invalid credentials...")

    # This should fail gracefully
    results = await client.search("test query")

    if results is None:
        print("Search failed as expected with invalid credentials")
    elif results and results.get("error"):
        error = results.get("error", None)
        if error:
            print(f"API returned error: {error['code']} - {error['message']}")
    else:
        print("Unexpected: Search succeeded with invalid credentials")

    # Test with empty query (should fail)
    print("\nTesting with empty query...")
    client_valid = YandexSearchClient(apiKey=API_KEY, folderId=FOLDER_ID)

    results = await client_valid.search("")
    if results is None:
        print("Empty query failed as expected")
    else:
        print(f"Empty query results: {results}")


async def example_different_search_domains():
    """Example 7: Different search domains"""
    print("\n=== Example 7: Different Search Domains ===")

    client = YandexSearchClient(apiKey=API_KEY, folderId=FOLDER_ID)

    # Test different search types
    search_types = [
        (SearchType.SEARCH_TYPE_RU, "погода в москве", "Russian search"),
        (SearchType.SEARCH_TYPE_COM, "weather forecast", "International search"),
        (SearchType.SEARCH_TYPE_TR, "hava durumu", "Turkish search"),
    ]

    for search_type, query, description in search_types:
        print(f"\n{description} ({search_type}): {query}")

        results = await client.search(queryText=query, searchType=search_type)

        if results:
            print(f"  Found {results['found']} results")
            if results["groups"] and results["groups"][0]:
                first_result = results["groups"][0][0]
                print(f"  First result: {first_result['title']}")
                print(f"  Domain: {first_result['domain']}")
        else:
            print("  No results or error occurred")


async def main():
    """Run all examples"""
    print("Yandex Search API Client Examples")
    print("=" * 50)

    # Check if credentials are provided
    if IAM_TOKEN == "your_iam_token_here" and API_KEY == "your_api_key_here":
        print("\nWARNING: No valid credentials provided!")
        print("Please set YANDEX_IAM_TOKEN or YANDEX_API_KEY environment variables")
        print("Or modify the IAM_TOKEN/API_KEY variables in this file")
        print("\nSome examples will fail without valid credentials.\n")

    try:
        # Run all examples
        await example_basic_search()
        await example_search_with_api_key()
        await example_advanced_search()
        await example_search_with_cache()
        await example_rate_limiting()
        await example_error_handling()
        await example_different_search_domains()

        print("\n" + "=" * 50)
        print("All examples completed!")

    except KeyboardInterrupt:
        print("\nExamples interrupted by user")
    except Exception as e:
        logger.error(f"Error running examples: {e}", exc_info=True)


if __name__ == "__main__":
    # Run the examples
    asyncio.run(main())
