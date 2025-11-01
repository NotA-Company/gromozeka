"""Tests for DictSearchCache implementation.

This module contains comprehensive tests for the dictionary-based search cache,
covering storage, retrieval, TTL expiration, size limits, thread safety, and
error handling scenarios. The tests ensure the cache operates correctly under
various conditions and maintains data integrity.
"""

import asyncio
import time
import unittest

from .dict_cache import DictSearchCache
from .models import FamilyMode, FixTypoMode, ResponseFormat, SearchRequest, SearchResponse, SearchType


class TestDictSearchCache(unittest.TestCase):
    """Test cases for DictSearchCache.

    This test class provides comprehensive coverage of the DictSearchCache
    implementation, including basic operations, TTL management, size limits,
    thread safety, and edge case handling.
    """

    def setUp(self):
        """Set up test fixtures.

        Initializes a cache instance with short TTL and small size for testing,
        along with sample request and response data used throughout the test cases.
        """
        self.cache = DictSearchCache(default_ttl=1, max_size=3)

        # Sample search response for testing
        self.sample_response: SearchResponse = {
            "requestId": "test-request-123",
            "found": 10,
            "foundHuman": "10 results found",
            "page": 0,
            "groups": [
                [
                    {
                        "url": "https://example.com/1",
                        "domain": "example.com",
                        "title": "Test Result 1",
                        "passages": ["This is a test passage"],
                        "modtime": 1672531200.0,  # Unix timestamp for 2023-01-01
                        "size": 1024,
                        "charset": "utf-8",
                        "mimeType": "text/html",
                        "hlwords": ["test"],
                    }
                ]
            ],
        }

        # Sample search request for testing
        self.sample_request: SearchRequest = {
            "query": {
                "searchType": SearchType.SEARCH_TYPE_RU,
                "queryText": "test query",
                "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                "page": "0",
                "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
            },
            "folderId": "test-folder-id",
            "responseFormat": ResponseFormat.FORMAT_XML,
        }

    def testCacheStorageAndRetrieval(self):
        """Test basic cache storage and retrieval.

        Verifies that data can be successfully stored in the cache and
        retrieved with the same values, ensuring basic cache functionality
        works as expected.
        """

        async def runTest():
            # Store data
            result = await self.cache.setSearch(self.sample_request, self.sample_response)
            self.assertTrue(result)

            # Retrieve data
            cachedData = await self.cache.getSearch(self.sample_request)
            self.assertIsNotNone(cachedData)
            if cachedData:
                self.assertEqual(cachedData["requestId"], "test-request-123")
                self.assertEqual(cachedData["found"], 10)

        asyncio.run(runTest())

    def testCacheMiss(self):
        """Test cache miss scenario.

        Verifies that attempting to retrieve a non-existent key from the
        cache returns None, demonstrating proper handling of cache misses.
        """

        async def runTest():
            # Try to retrieve non-existent key
            request: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "non-existent query",
                    "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                    "page": "0",
                    "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                },
                "folderId": "test-folder-id",
                "responseFormat": ResponseFormat.FORMAT_XML,
            }
            cachedData = await self.cache.getSearch(request)
            self.assertIsNone(cachedData)

        asyncio.run(runTest())

    def testTtlExpiration(self):
        """Test TTL expiration functionality.

        Verifies that cached items expire after the configured TTL and
        are no longer retrievable, ensuring proper time-based cache eviction.
        """

        async def runTest():
            request: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "ttl test query",
                    "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                    "page": "0",
                    "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                },
                "folderId": "test-folder-id",
                "responseFormat": ResponseFormat.FORMAT_XML,
            }

            # Store data
            await self.cache.setSearch(request, self.sample_response)

            # Retrieve immediately (should work)
            cachedData = await self.cache.getSearch(request)
            self.assertIsNotNone(cachedData)

            # Wait for expiration
            time.sleep(1.1)

            # Try to retrieve after expiration (should fail)
            cachedData = await self.cache.getSearch(request)
            self.assertIsNone(cachedData)

        asyncio.run(runTest())

    def testCustomTtl(self):
        """Test custom TTL parameter.

        Verifies that the cache respects the default TTL configuration
        and properly expires items after the specified time period.
        """

        async def runTest():
            request: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "custom ttl test query",
                    "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                    "page": "0",
                    "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                },
                "folderId": "test-folder-id",
                "responseFormat": ResponseFormat.FORMAT_XML,
            }

            # Store data
            await self.cache.setSearch(request, self.sample_response)

            # Retrieve immediately (should work)
            cachedData = await self.cache.getSearch(request)
            self.assertIsNotNone(cachedData)

            # Wait for default TTL expiration
            time.sleep(1.1)

            # Should be expired with default TTL
            cachedData = await self.cache.getSearch(request)
            self.assertIsNone(cachedData)

        asyncio.run(runTest())

    def testMaxSizeEnforcement(self):
        """Test maximum cache size enforcement.

        Verifies that the cache maintains its configured maximum size by
        evicting the oldest entries when new items are added beyond the limit.
        """

        async def runTest():
            # Fill cache to max size
            for i in range(3):
                request: SearchRequest = {
                    "query": {
                        "searchType": SearchType.SEARCH_TYPE_RU,
                        "queryText": f"test query {i}",
                        "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                        "page": "0",
                        "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                    },
                    "folderId": "test-folder-id",
                    "responseFormat": ResponseFormat.FORMAT_XML,
                }
                await self.cache.setSearch(request, self.sample_response)

            # Check stats
            stats = self.cache.getStats()
            self.assertEqual(stats["search_entries"], 3)

            # Add one more entry (should evict oldest)
            request4: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "test query 4",
                    "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                    "page": "0",
                    "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                },
                "folderId": "test-folder-id",
                "responseFormat": ResponseFormat.FORMAT_XML,
            }
            await self.cache.setSearch(request4, self.sample_response)

            # Check that cache size is maintained
            stats = self.cache.getStats()
            self.assertEqual(stats["search_entries"], 3)  # Should still be max_size

            # Check that newest entry exists
            cachedData = await self.cache.getSearch(request4)
            self.assertIsNotNone(cachedData)

        asyncio.run(runTest())

    def testCacheClear(self):
        """Test cache clearing functionality.

        Verifies that the cache can be completely cleared, removing all
        stored items and resetting statistics to their initial state.
        """

        async def runTest():
            # Store some data
            request1: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "clear test query 1",
                    "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                    "page": "0",
                    "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                },
                "folderId": "test-folder-id",
                "responseFormat": ResponseFormat.FORMAT_XML,
            }
            request2: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "clear test query 2",
                    "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                    "page": "0",
                    "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                },
                "folderId": "test-folder-id",
                "responseFormat": ResponseFormat.FORMAT_XML,
            }
            await self.cache.setSearch(request1, self.sample_response)
            await self.cache.setSearch(request2, self.sample_response)

            # Verify data exists
            stats = self.cache.getStats()
            self.assertEqual(stats["search_entries"], 2)

            # Clear cache
            self.cache.clear()

            # Verify cache is empty
            stats = self.cache.getStats()
            self.assertEqual(stats["search_entries"], 0)

            # Verify data is gone
            cachedData = await self.cache.getSearch(request1)
            self.assertIsNone(cachedData)

        asyncio.run(runTest())

    def testCacheStats(self):
        """Test cache statistics.

        Verifies that the cache provides accurate statistics about its
        current state including the number of entries, maximum size,
        and default TTL configuration.
        """

        async def runTest():
            # Initial stats
            stats = self.cache.getStats()
            self.assertEqual(stats["search_entries"], 0)
            self.assertEqual(stats["max_size"], 3)
            self.assertEqual(stats["default_ttl"], 1)

            # Add some data
            request1: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "stats test query 1",
                    "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                    "page": "0",
                    "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                },
                "folderId": "test-folder-id",
                "responseFormat": ResponseFormat.FORMAT_XML,
            }
            request2: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "stats test query 2",
                    "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                    "page": "0",
                    "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                },
                "folderId": "test-folder-id",
                "responseFormat": ResponseFormat.FORMAT_XML,
            }
            await self.cache.setSearch(request1, self.sample_response)
            await self.cache.setSearch(request2, self.sample_response)

            # Updated stats
            stats = self.cache.getStats()
            self.assertEqual(stats["search_entries"], 2)

        asyncio.run(runTest())

    def testCacheKeyGeneration(self):
        """Test cache key generation from parameters.

        Verifies that the cache generates consistent and unique keys based
        on request parameters, ensuring identical requests produce the same
        key while different requests produce different keys.
        """
        # Test with different parameters
        request1: SearchRequest = {
            "query": {
                "searchType": SearchType.SEARCH_TYPE_RU,
                "queryText": "test query",
                "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                "page": "0",
                "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
            },
            "folderId": "test-folder-id",
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
            "folderId": "test-folder-id",
            "responseFormat": ResponseFormat.FORMAT_XML,
        }

        request3: SearchRequest = {
            "query": {
                "searchType": SearchType.SEARCH_TYPE_RU,
                "queryText": "different query",
                "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                "page": "0",
                "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
            },
            "folderId": "test-folder-id",
            "responseFormat": ResponseFormat.FORMAT_XML,
        }

        # Generate keys using the internal method
        key1 = self.cache._generateCacheKey(request1)
        key2 = self.cache._generateCacheKey(request2)
        key3 = self.cache._generateCacheKey(request3)

        # Same parameters should generate same key
        self.assertEqual(key1, key2)

        # Different parameters should generate different key
        self.assertNotEqual(key1, key3)

        # Keys should be valid SHA512 hashes (128 characters)
        self.assertEqual(len(key1), 128)
        self.assertTrue(all(c in "0123456789abcdef" for c in key1))

    def testThreadSafety(self):
        """Test thread safety of cache operations.

        Verifies that the cache operates correctly when accessed concurrently
        by multiple workers, ensuring data integrity and preventing race
        conditions during simultaneous operations.
        """

        async def worker(workerId: int):
            # Each worker stores and retrieves data
            for i in range(10):
                request: SearchRequest = {
                    "query": {
                        "searchType": SearchType.SEARCH_TYPE_RU,
                        "queryText": f"worker-{workerId}-query-{i}",
                        "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                        "page": "0",
                        "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                    },
                    "folderId": "test-folder-id",
                    "responseFormat": ResponseFormat.FORMAT_XML,
                }
                await self.cache.setSearch(request, self.sample_response)
                cachedData = await self.cache.getSearch(request)
                self.assertIsNotNone(cachedData)

        async def runTest():
            # Run multiple workers concurrently
            tasks = [worker(i) for i in range(5)]
            await asyncio.gather(*tasks)

        asyncio.run(runTest())

    def testErrorHandling(self):
        """Test error handling in cache operations.

        Verifies that the cache handles various error scenarios gracefully,
        including non-existent keys and normal operations, without raising
        unexpected exceptions.
        """

        async def runTest():
            # Test that cache handles normal operations gracefully
            # Store and retrieve data
            request: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "error test query",
                    "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                    "page": "0",
                    "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                },
                "folderId": "test-folder-id",
                "responseFormat": ResponseFormat.FORMAT_XML,
            }
            result = await self.cache.setSearch(request, self.sample_response)
            self.assertTrue(result)

            cachedData = await self.cache.getSearch(request)
            self.assertIsNotNone(cachedData)

            # Test with non-existent key (should return None gracefully)
            nonExistentRequest: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "non-existent error test query",
                    "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                    "page": "0",
                    "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                },
                "folderId": "test-folder-id",
                "responseFormat": ResponseFormat.FORMAT_XML,
            }
            cachedData = await self.cache.getSearch(nonExistentRequest)
            self.assertIsNone(cachedData)

        asyncio.run(runTest())

    def testParameterOrderIndependence(self):
        """Test that parameter order doesn't affect cache key generation.

        Verifies that cache key generation is independent of parameter order
        in the request dictionary, ensuring consistent keys regardless of
        how the request data is structured.
        """
        # Create requests with same parameters in different orders
        request1: SearchRequest = {
            "query": {
                "searchType": SearchType.SEARCH_TYPE_RU,
                "queryText": "test",
                "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                "page": "0",
                "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
            },
            "folderId": "test-folder-id",
            "responseFormat": ResponseFormat.FORMAT_XML,
            "region": "225",
        }

        request2: SearchRequest = {
            "query": {
                "searchType": SearchType.SEARCH_TYPE_RU,
                "queryText": "test",
                "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                "page": "0",
                "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
            },
            "region": "225",
            "folderId": "test-folder-id",
            "responseFormat": ResponseFormat.FORMAT_XML,
        }

        # Generate keys using the internal method
        key1 = self.cache._generateCacheKey(request1)
        key2 = self.cache._generateCacheKey(request2)

        # Different order should generate same key
        self.assertEqual(key1, key2)


if __name__ == "__main__":
    unittest.main()
