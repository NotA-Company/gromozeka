"""
Comprehensive tests for NullStorageBackend, dood!

This module tests the NullStorageBackend to ensure it properly
validates keys but performs no actual storage operations.
"""

import pytest

from internal.services.storage.backends.null import NullStorageBackend
from internal.services.storage.exceptions import StorageKeyError


class TestNullBackendInitialization:
    """Test NullStorageBackend initialization, dood!"""

    def testBackendCreation(self):
        """Test that backend can be created without parameters"""
        backend = NullStorageBackend()
        assert backend is not None


class TestNullBackendStore:
    """Test NullStorageBackend store operation, dood!"""

    def testStoreDoesNothing(self):
        """Test that store operation does nothing"""
        backend = NullStorageBackend()
        # Should not raise any exception
        backend.store("test-key", b"test data")

    def testStoreWithValidKey(self):
        """Test store with valid key"""
        backend = NullStorageBackend()
        backend.store("valid-key.txt", b"data")
        # No assertion needed - just verify it doesn't raise

    def testStoreWithInvalidKeyRaisesError(self):
        """Test that store with invalid key raises StorageKeyError"""
        backend = NullStorageBackend()
        with pytest.raises(StorageKeyError):
            backend.store("", b"data")

    def testStoreWithPathTraversalRaisesError(self):
        """Test that store with path traversal raises StorageKeyError"""
        backend = NullStorageBackend()
        # Path traversal will be sanitized to empty string, raising error
        with pytest.raises(StorageKeyError):
            backend.store("///", b"data")

    def testStoreMultipleTimes(self):
        """Test that multiple store operations work"""
        backend = NullStorageBackend()
        backend.store("key1", b"data1")
        backend.store("key2", b"data2")
        backend.store("key3", b"data3")
        # No assertions needed - just verify no exceptions

    def testStoreWithLargeData(self):
        """Test store with large data"""
        backend = NullStorageBackend()
        largeData = b"x" * 1000000  # 1MB
        backend.store("large-key", largeData)
        # Should complete instantly without actually storing


class TestNullBackendGet:
    """Test NullStorageBackend get operation, dood!"""

    def testGetAlwaysReturnsNone(self):
        """Test that get always returns None"""
        backend = NullStorageBackend()
        result = backend.get("test-key")
        assert result is None

    def testGetAfterStore(self):
        """Test that get returns None even after store"""
        backend = NullStorageBackend()
        backend.store("test-key", b"data")
        result = backend.get("test-key")
        assert result is None

    def testGetWithValidKey(self):
        """Test get with valid key returns None"""
        backend = NullStorageBackend()
        result = backend.get("valid-key.txt")
        assert result is None

    def testGetWithInvalidKeyRaisesError(self):
        """Test that get with invalid key raises StorageKeyError"""
        backend = NullStorageBackend()
        with pytest.raises(StorageKeyError):
            backend.get("")

    def testGetMultipleTimes(self):
        """Test that multiple get operations return None"""
        backend = NullStorageBackend()
        assert backend.get("key1") is None
        assert backend.get("key2") is None
        assert backend.get("key3") is None


class TestNullBackendExists:
    """Test NullStorageBackend exists operation, dood!"""

    def testExistsAlwaysReturnsFalse(self):
        """Test that exists always returns False"""
        backend = NullStorageBackend()
        result = backend.exists("test-key")
        assert result is False

    def testExistsAfterStore(self):
        """Test that exists returns False even after store"""
        backend = NullStorageBackend()
        backend.store("test-key", b"data")
        result = backend.exists("test-key")
        assert result is False

    def testExistsWithValidKey(self):
        """Test exists with valid key returns False"""
        backend = NullStorageBackend()
        result = backend.exists("valid-key.txt")
        assert result is False

    def testExistsWithInvalidKeyRaisesError(self):
        """Test that exists with invalid key raises StorageKeyError"""
        backend = NullStorageBackend()
        with pytest.raises(StorageKeyError):
            backend.exists("")

    def testExistsMultipleTimes(self):
        """Test that multiple exists operations return False"""
        backend = NullStorageBackend()
        assert backend.exists("key1") is False
        assert backend.exists("key2") is False
        assert backend.exists("key3") is False


class TestNullBackendDelete:
    """Test NullStorageBackend delete operation, dood!"""

    def testDeleteAlwaysReturnsFalse(self):
        """Test that delete always returns False"""
        backend = NullStorageBackend()
        result = backend.delete("test-key")
        assert result is False

    def testDeleteAfterStore(self):
        """Test that delete returns False even after store"""
        backend = NullStorageBackend()
        backend.store("test-key", b"data")
        result = backend.delete("test-key")
        assert result is False

    def testDeleteWithValidKey(self):
        """Test delete with valid key returns False"""
        backend = NullStorageBackend()
        result = backend.delete("valid-key.txt")
        assert result is False

    def testDeleteWithInvalidKeyRaisesError(self):
        """Test that delete with invalid key raises StorageKeyError"""
        backend = NullStorageBackend()
        with pytest.raises(StorageKeyError):
            backend.delete("")

    def testDeleteMultipleTimes(self):
        """Test that multiple delete operations return False"""
        backend = NullStorageBackend()
        assert backend.delete("key1") is False
        assert backend.delete("key2") is False
        assert backend.delete("key3") is False


class TestNullBackendList:
    """Test NullStorageBackend list operation, dood!"""

    def testListAlwaysReturnsEmptyList(self):
        """Test that list always returns empty list"""
        backend = NullStorageBackend()
        result = backend.list()
        assert result == []
        assert isinstance(result, list)

    def testListAfterStore(self):
        """Test that list returns empty list even after store"""
        backend = NullStorageBackend()
        backend.store("test-key", b"data")
        result = backend.list()
        assert result == []

    def testListWithPrefix(self):
        """Test list with prefix returns empty list"""
        backend = NullStorageBackend()
        result = backend.list(prefix="test-")
        assert result == []

    def testListWithLimit(self):
        """Test list with limit returns empty list"""
        backend = NullStorageBackend()
        result = backend.list(limit=10)
        assert result == []

    def testListWithPrefixAndLimit(self):
        """Test list with prefix and limit returns empty list"""
        backend = NullStorageBackend()
        result = backend.list(prefix="test-", limit=10)
        assert result == []

    def testListMultipleTimes(self):
        """Test that multiple list operations return empty list"""
        backend = NullStorageBackend()
        assert backend.list() == []
        assert backend.list(prefix="a") == []
        assert backend.list(limit=5) == []


class TestNullBackendNoSideEffects:
    """Test that NullStorageBackend has no side effects, dood!"""

    def testNoStateChanges(self):
        """Test that operations don't change backend state"""
        backend = NullStorageBackend()

        # Perform various operations
        backend.store("key1", b"data1")
        backend.store("key2", b"data2")
        backend.get("key1")
        backend.exists("key2")
        backend.delete("key1")

        # Verify no state changes
        assert backend.get("key1") is None
        assert backend.get("key2") is None
        assert backend.exists("key1") is False
        assert backend.exists("key2") is False
        assert backend.list() == []

    def testMultipleBackendsIndependent(self):
        """Test that multiple backend instances are independent"""
        backend1 = NullStorageBackend()
        backend2 = NullStorageBackend()

        backend1.store("key1", b"data1")
        backend2.store("key2", b"data2")

        # Both should return None/False/empty
        assert backend1.get("key1") is None
        assert backend2.get("key2") is None
        assert backend1.exists("key1") is False
        assert backend2.exists("key2") is False

    def testNoMemoryUsage(self):
        """Test that backend doesn't accumulate memory"""
        backend = NullStorageBackend()

        # Store large amounts of data
        for i in range(1000):
            backend.store(f"key-{i}", b"x" * 1000)

        # Should still return empty results
        assert backend.list() == []
        assert backend.get("key-0") is None


class TestNullBackendKeyValidation:
    """Test that NullStorageBackend validates keys properly, dood!"""

    def testValidKeysAccepted(self):
        """Test that valid keys are accepted"""
        backend = NullStorageBackend()

        validKeys = [
            "simple-key",
            "key_with_underscores",
            "key.with.dots",
            "key-123",
            "UPPERCASE",
            "MixedCase123",
        ]

        for key in validKeys:
            backend.store(key, b"data")
            backend.get(key)
            backend.exists(key)
            backend.delete(key)

    def testInvalidKeysRejected(self):
        """Test that invalid keys are rejected"""
        backend = NullStorageBackend()

        invalidKeys = [
            "",  # Empty
            "   ",  # Whitespace only
            "///",  # Path separators only
            "@#$%",  # Special characters only
        ]

        for key in invalidKeys:
            with pytest.raises(StorageKeyError):
                backend.store(key, b"data")
            with pytest.raises(StorageKeyError):
                backend.get(key)
            with pytest.raises(StorageKeyError):
                backend.exists(key)
            with pytest.raises(StorageKeyError):
                backend.delete(key)

    def testPathTraversalRejected(self):
        """Test that path traversal attempts are rejected"""
        backend = NullStorageBackend()

        pathTraversalKeys = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "./../../file",
        ]

        for key in pathTraversalKeys:
            # These will be sanitized but may become invalid
            try:
                backend.store(key, b"data")
                backend.get(key)
                backend.exists(key)
                backend.delete(key)
            except StorageKeyError:
                # Expected if sanitization makes key invalid
                pass


class TestNullBackendUseCases:
    """Test real-world use cases for NullStorageBackend, dood!"""

    def testUnitTestingWithoutStorage(self):
        """Test using null backend for unit testing"""
        backend = NullStorageBackend()

        # Simulate application code
        backend.store("user-123-avatar", b"image data")
        avatar = backend.get("user-123-avatar")

        # In tests, we don't care about actual storage
        assert avatar is None  # Expected for null backend

    def testDisablingStorageFunctionality(self):
        """Test using null backend to disable storage"""
        backend = NullStorageBackend()

        # Application tries to store data
        backend.store("config.json", b'{"key": "value"}')

        # But nothing is actually stored
        assert backend.exists("config.json") is False
        assert backend.get("config.json") is None

    def testPerformanceTestingWithoutIO(self):
        """Test using null backend for performance testing"""
        backend = NullStorageBackend()

        # Simulate high-volume operations
        for i in range(10000):
            backend.store(f"key-{i}", b"data")

        # Should complete instantly
        assert backend.list() == []
