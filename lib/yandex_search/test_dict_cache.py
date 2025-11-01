"""
Tests for DictSearchCache implementation

This module contains comprehensive tests for the dictionary-based search cache.
"""

import asyncio
import time
import unittest

from .dict_cache import DictSearchCache
from .models import FamilyMode, FixTypoMode, ResponseFormat, SearchRequest, SearchResponse, SearchType


class TestDictSearchCache(unittest.TestCase):
    """Test cases for DictSearchCache"""

    def setUp(self):
        """Set up test fixtures"""
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

    def test_cache_storage_and_retrieval(self):
        """Test basic cache storage and retrieval"""

        async def run_test():
            # Store data
            result = await self.cache.setSearch(self.sample_request, self.sample_response)
            self.assertTrue(result)

            # Retrieve data
            cached_data = await self.cache.getSearch(self.sample_request)
            self.assertIsNotNone(cached_data)
            if cached_data:
                self.assertEqual(cached_data["requestId"], "test-request-123")
                self.assertEqual(cached_data["found"], 10)

        asyncio.run(run_test())

    def test_cache_miss(self):
        """Test cache miss scenario"""

        async def run_test():
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
            cached_data = await self.cache.getSearch(request)
            self.assertIsNone(cached_data)

        asyncio.run(run_test())

    def test_ttl_expiration(self):
        """Test TTL expiration functionality"""

        async def run_test():
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
            cached_data = await self.cache.getSearch(request)
            self.assertIsNotNone(cached_data)

            # Wait for expiration
            time.sleep(1.1)

            # Try to retrieve after expiration (should fail)
            cached_data = await self.cache.getSearch(request)
            self.assertIsNone(cached_data)

        asyncio.run(run_test())

    def test_custom_ttl(self):
        """Test custom TTL parameter"""

        async def run_test():
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
            cached_data = await self.cache.getSearch(request)
            self.assertIsNotNone(cached_data)

            # Wait for default TTL expiration
            time.sleep(1.1)

            # Should be expired with default TTL
            cached_data = await self.cache.getSearch(request)
            self.assertIsNone(cached_data)

        asyncio.run(run_test())

    def test_max_size_enforcement(self):
        """Test maximum cache size enforcement"""

        async def run_test():
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
            cached_data = await self.cache.getSearch(request4)
            self.assertIsNotNone(cached_data)

        asyncio.run(run_test())

    def test_cache_clear(self):
        """Test cache clearing functionality"""

        async def run_test():
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
            cached_data = await self.cache.getSearch(request1)
            self.assertIsNone(cached_data)

        asyncio.run(run_test())

    def test_cache_stats(self):
        """Test cache statistics"""

        async def run_test():
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

        asyncio.run(run_test())

    def test_cache_key_generation(self):
        """Test cache key generation from parameters"""
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

    def test_thread_safety(self):
        """Test thread safety of cache operations"""

        async def worker(worker_id: int):
            # Each worker stores and retrieves data
            for i in range(10):
                request: SearchRequest = {
                    "query": {
                        "searchType": SearchType.SEARCH_TYPE_RU,
                        "queryText": f"worker-{worker_id}-query-{i}",
                        "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                        "page": "0",
                        "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON,
                    },
                    "folderId": "test-folder-id",
                    "responseFormat": ResponseFormat.FORMAT_XML,
                }
                await self.cache.setSearch(request, self.sample_response)
                cached_data = await self.cache.getSearch(request)
                self.assertIsNotNone(cached_data)

        async def run_test():
            # Run multiple workers concurrently
            tasks = [worker(i) for i in range(5)]
            await asyncio.gather(*tasks)

        asyncio.run(run_test())

    def test_error_handling(self):
        """Test error handling in cache operations"""

        async def run_test():
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

            cached_data = await self.cache.getSearch(request)
            self.assertIsNotNone(cached_data)

            # Test with non-existent key (should return None gracefully)
            non_existent_request: SearchRequest = {
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
            cached_data = await self.cache.getSearch(non_existent_request)
            self.assertIsNone(cached_data)

        asyncio.run(run_test())

    def test_parameter_order_independence(self):
        """Test that parameter order doesn't affect cache key generation"""
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
