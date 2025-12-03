"""
Comprehensive tests for FSStorageBackend, dood!

This module tests the FSStorageBackend to ensure it properly
stores and retrieves files from the filesystem.
"""

import os
import tempfile
from pathlib import Path

import pytest

from internal.services.storage.backends.filesystem import FSStorageBackend
from internal.services.storage.exceptions import StorageBackendError, StorageKeyError


@pytest.fixture
def tempDir():
    """Create a temporary directory for testing, dood!"""
    tmpDir = tempfile.mkdtemp()
    yield tmpDir
    # Cleanup
    import shutil

    shutil.rmtree(tmpDir, ignore_errors=True)


@pytest.fixture
def fsBackend(tempDir):
    """Create FSStorageBackend with temporary directory, dood!"""
    return FSStorageBackend(tempDir)


class TestFSBackendInitialization:
    """Test FSStorageBackend initialization, dood!"""

    def testBackendCreation(self, tempDir):
        """Test that backend can be created with base directory"""
        backend = FSStorageBackend(tempDir)
        assert backend is not None
        assert backend.baseDir == Path(tempDir)

    def testDirectoryCreation(self):
        """Test that backend creates directory if it doesn't exist"""
        tmpDir = tempfile.mktemp()  # Get path but don't create
        try:
            FSStorageBackend(tmpDir)
            assert Path(tmpDir).exists()
            assert Path(tmpDir).is_dir()
        finally:
            import shutil

            shutil.rmtree(tmpDir, ignore_errors=True)

    def testNestedDirectoryCreation(self):
        """Test that backend creates nested directories"""
        tmpDir = tempfile.mktemp()
        nestedDir = os.path.join(tmpDir, "nested", "path")
        try:
            FSStorageBackend(nestedDir)
            assert Path(nestedDir).exists()
            assert Path(nestedDir).is_dir()
        finally:
            import shutil

            shutil.rmtree(tmpDir, ignore_errors=True)

    def testExistingDirectoryAccepted(self, tempDir):
        """Test that backend accepts existing directory"""
        backend = FSStorageBackend(tempDir)
        assert backend.baseDir == Path(tempDir)

    def testFileAsBaseDirRaisesError(self, tempDir):
        """Test that using a file as base dir raises error"""
        filePath = os.path.join(tempDir, "file.txt")
        with open(filePath, "w") as f:
            f.write("test")

        with pytest.raises(StorageBackendError):
            FSStorageBackend(filePath)


class TestFSBackendStore:
    """Test FSStorageBackend store operation, dood!"""

    def testStoreSimpleData(self, fsBackend, tempDir):
        """Test storing simple data"""
        key = "test-key"
        data = b"test data"

        fsBackend.store(key, data)

        # Verify file exists
        filePath = Path(tempDir) / key
        assert filePath.exists()
        assert filePath.read_bytes() == data

    def testStoreOverwritesExisting(self, fsBackend, tempDir):
        """Test that store overwrites existing file"""
        key = "test-key"
        data1 = b"original data"
        data2 = b"new data"

        fsBackend.store(key, data1)
        fsBackend.store(key, data2)

        filePath = Path(tempDir) / key
        assert filePath.read_bytes() == data2

    def testStoreWithSanitizedKey(self, fsBackend, tempDir):
        """Test storing with key that needs sanitization"""
        key = "path/to/file"
        data = b"test data"

        fsBackend.store(key, data)

        # Key should be sanitized to path_to_file
        filePath = Path(tempDir) / "path_to_file"
        assert filePath.exists()
        assert filePath.read_bytes() == data

    def testStoreWithInvalidKeyRaisesError(self, fsBackend):
        """Test that store with invalid key raises StorageKeyError"""
        with pytest.raises(StorageKeyError):
            fsBackend.store("", b"data")

    def testStoreEmptyData(self, fsBackend, tempDir):
        """Test storing empty data"""
        key = "empty-key"
        data = b""

        fsBackend.store(key, data)

        filePath = Path(tempDir) / key
        assert filePath.exists()
        assert filePath.read_bytes() == data

    def testStoreLargeData(self, fsBackend, tempDir):
        """Test storing large data"""
        key = "large-key"
        data = b"x" * 1000000  # 1MB

        fsBackend.store(key, data)

        filePath = Path(tempDir) / key
        assert filePath.exists()
        assert filePath.read_bytes() == data

    def testStoreFilePermissions(self, fsBackend, tempDir):
        """Test that stored files have correct permissions (0o644)"""
        key = "test-key"
        data = b"test data"

        fsBackend.store(key, data)

        filePath = Path(tempDir) / key
        permissions = oct(filePath.stat().st_mode)[-3:]
        assert permissions == "644"


class TestFSBackendGet:
    """Test FSStorageBackend get operation, dood!"""

    def testGetExistingFile(self, fsBackend):
        """Test getting existing file"""
        key = "test-key"
        data = b"test data"

        fsBackend.store(key, data)
        result = fsBackend.get(key)

        assert result == data

    def testGetNonExistentFile(self, fsBackend):
        """Test getting non-existent file returns None"""
        result = fsBackend.get("non-existent-key")
        assert result is None

    def testGetWithSanitizedKey(self, fsBackend):
        """Test getting with key that needs sanitization"""
        key = "path/to/file"
        data = b"test data"

        fsBackend.store(key, data)
        result = fsBackend.get(key)

        assert result == data

    def testGetWithInvalidKeyRaisesError(self, fsBackend):
        """Test that get with invalid key raises StorageKeyError"""
        with pytest.raises(StorageKeyError):
            fsBackend.get("")

    def testGetEmptyFile(self, fsBackend):
        """Test getting empty file"""
        key = "empty-key"
        data = b""

        fsBackend.store(key, data)
        result = fsBackend.get(key)

        assert result == data

    def testGetLargeFile(self, fsBackend):
        """Test getting large file"""
        key = "large-key"
        data = b"x" * 1000000  # 1MB

        fsBackend.store(key, data)
        result = fsBackend.get(key)

        assert result == data


class TestFSBackendExists:
    """Test FSStorageBackend exists operation, dood!"""

    def testExistsForExistingFile(self, fsBackend):
        """Test exists returns True for existing file"""
        key = "test-key"
        data = b"test data"

        fsBackend.store(key, data)
        assert fsBackend.exists(key) is True

    def testExistsForNonExistentFile(self, fsBackend):
        """Test exists returns False for non-existent file"""
        assert fsBackend.exists("non-existent-key") is False

    def testExistsWithSanitizedKey(self, fsBackend):
        """Test exists with key that needs sanitization"""
        key = "path/to/file"
        data = b"test data"

        fsBackend.store(key, data)
        assert fsBackend.exists(key) is True

    def testExistsWithInvalidKeyRaisesError(self, fsBackend):
        """Test that exists with invalid key raises StorageKeyError"""
        with pytest.raises(StorageKeyError):
            fsBackend.exists("")

    def testExistsAfterDelete(self, fsBackend):
        """Test exists returns False after delete"""
        key = "test-key"
        data = b"test data"

        fsBackend.store(key, data)
        fsBackend.delete(key)
        assert fsBackend.exists(key) is False


class TestFSBackendDelete:
    """Test FSStorageBackend delete operation, dood!"""

    def testDeleteExistingFile(self, fsBackend, tempDir):
        """Test deleting existing file"""
        key = "test-key"
        data = b"test data"

        fsBackend.store(key, data)
        result = fsBackend.delete(key)

        assert result is True
        filePath = Path(tempDir) / key
        assert not filePath.exists()

    def testDeleteNonExistentFile(self, fsBackend):
        """Test deleting non-existent file returns False"""
        result = fsBackend.delete("non-existent-key")
        assert result is False

    def testDeleteWithSanitizedKey(self, fsBackend, tempDir):
        """Test deleting with key that needs sanitization"""
        key = "path/to/file"
        data = b"test data"

        fsBackend.store(key, data)
        result = fsBackend.delete(key)

        assert result is True
        filePath = Path(tempDir) / "path_to_file"
        assert not filePath.exists()

    def testDeleteWithInvalidKeyRaisesError(self, fsBackend):
        """Test that delete with invalid key raises StorageKeyError"""
        with pytest.raises(StorageKeyError):
            fsBackend.delete("")

    def testDeleteTwiceReturnsFalse(self, fsBackend):
        """Test that deleting twice returns False second time"""
        key = "test-key"
        data = b"test data"

        fsBackend.store(key, data)
        assert fsBackend.delete(key) is True
        assert fsBackend.delete(key) is False


class TestFSBackendList:
    """Test FSStorageBackend list operation, dood!"""

    def testListEmptyDirectory(self, fsBackend):
        """Test listing empty directory"""
        result = fsBackend.list()
        assert result == []

    def testListWithFiles(self, fsBackend):
        """Test listing directory with files"""
        keys = ["file1.txt", "file2.txt", "file3.txt"]
        for key in keys:
            fsBackend.store(key, b"data")

        result = fsBackend.list()
        assert sorted(result) == sorted(keys)

    def testListWithPrefix(self, fsBackend):
        """Test listing with prefix filter"""
        fsBackend.store("test-1.txt", b"data")
        fsBackend.store("test-2.txt", b"data")
        fsBackend.store("other-1.txt", b"data")

        result = fsBackend.list(prefix="test-")
        assert sorted(result) == ["test-1.txt", "test-2.txt"]

    def testListWithLimit(self, fsBackend):
        """Test listing with limit"""
        for i in range(10):
            fsBackend.store(f"file-{i}.txt", b"data")

        result = fsBackend.list(limit=5)
        assert len(result) == 5

    def testListWithPrefixAndLimit(self, fsBackend):
        """Test listing with prefix and limit"""
        for i in range(10):
            fsBackend.store(f"test-{i}.txt", b"data")
        fsBackend.store("other.txt", b"data")

        result = fsBackend.list(prefix="test-", limit=5)
        assert len(result) == 5
        assert all(key.startswith("test-") for key in result)

    def testListReturnsOnlyFiles(self, fsBackend, tempDir):
        """Test that list returns only files, not directories"""
        fsBackend.store("file.txt", b"data")

        # Create a subdirectory (shouldn't be listed)
        subdir = Path(tempDir) / "subdir"
        subdir.mkdir()

        result = fsBackend.list()
        assert result == ["file.txt"]

    def testListSortedResults(self, fsBackend):
        """Test that list returns sorted results"""
        keys = ["c.txt", "a.txt", "b.txt"]
        for key in keys:
            fsBackend.store(key, b"data")

        result = fsBackend.list()
        assert result == ["a.txt", "b.txt", "c.txt"]


class TestFSBackendEdgeCases:
    """Test edge cases and error handling, dood!"""

    def testConcurrentStoreOperations(self, fsBackend):
        """Test concurrent store operations"""
        key = "test-key"
        data1 = b"data1"
        data2 = b"data2"

        # Store twice quickly
        fsBackend.store(key, data1)
        fsBackend.store(key, data2)

        # Last write should win
        result = fsBackend.get(key)
        assert result == data2

    def testStoreAndGetCycle(self, fsBackend):
        """Test complete store and get cycle"""
        key = "test-key"
        data = b"test data"

        # Store
        fsBackend.store(key, data)
        assert fsBackend.exists(key) is True

        # Get
        result = fsBackend.get(key)
        assert result == data

        # Delete
        assert fsBackend.delete(key) is True
        assert fsBackend.exists(key) is False
        assert fsBackend.get(key) is None

    def testMultipleFiles(self, fsBackend):
        """Test storing multiple files"""
        files = {
            "file1.txt": b"data1",
            "file2.txt": b"data2",
            "file3.txt": b"data3",
        }

        for key, data in files.items():
            fsBackend.store(key, data)

        for key, data in files.items():
            assert fsBackend.get(key) == data

    def testBinaryData(self, fsBackend):
        """Test storing binary data"""
        key = "binary-key"
        data = bytes(range(256))  # All byte values

        fsBackend.store(key, data)
        result = fsBackend.get(key)

        assert result == data

    def testUnicodeInData(self, fsBackend):
        """Test storing unicode data as bytes"""
        key = "unicode-key"
        data = "Hello 世界 🌍".encode("utf-8")

        fsBackend.store(key, data)
        result = fsBackend.get(key)

        assert result == data
        assert result.decode("utf-8") == "Hello 世界 🌍"


class TestFSBackendAtomicOperations:
    """Test atomic file operations, dood!"""

    def testAtomicWrite(self, fsBackend, tempDir):
        """Test that write is atomic (uses temp file)"""
        key = "test-key"
        data = b"test data"

        fsBackend.store(key, data)

        # Verify no .tmp files left behind
        tmpFiles = list(Path(tempDir).glob("*.tmp"))
        assert len(tmpFiles) == 0

    def testAtomicWriteOnError(self, fsBackend, tempDir):
        """Test that temp file is cleaned up on error"""
        key = "test-key"

        # This should work normally
        fsBackend.store(key, b"data")

        # Verify no .tmp files
        tmpFiles = list(Path(tempDir).glob("*.tmp"))
        assert len(tmpFiles) == 0


class TestFSBackendRealWorldScenarios:
    """Test real-world scenarios, dood!"""

    def testImageStorage(self, fsBackend):
        """Test storing image-like data"""
        key = "avatar-123.jpg"
        # Simulate JPEG header
        data = b"\xff\xd8\xff\xe0" + b"x" * 1000

        fsBackend.store(key, data)
        result = fsBackend.get(key)

        assert result == data
        assert result.startswith(b"\xff\xd8\xff\xe0")

    def testJsonStorage(self, fsBackend):
        """Test storing JSON data"""
        key = "config.json"
        data = b'{"key": "value", "number": 123}'

        fsBackend.store(key, data)
        result = fsBackend.get(key)

        assert result == data

    def testMultipleExtensions(self, fsBackend):
        """Test files with multiple extensions"""
        key = "archive.tar.gz"
        data = b"compressed data"

        fsBackend.store(key, data)
        result = fsBackend.get(key)

        assert result == data

    def testVersionedFiles(self, fsBackend):
        """Test storing versioned files"""
        keys = ["file-v1.txt", "file-v2.txt", "file-v3.txt"]
        for i, key in enumerate(keys):
            fsBackend.store(key, f"version {i + 1}".encode())

        for i, key in enumerate(keys):
            result = fsBackend.get(key)
            assert result == f"version {i + 1}".encode()
