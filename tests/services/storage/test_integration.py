"""
Integration tests for Storage Service, dood!

This module provides end-to-end integration tests for the storage service
with real filesystem backend and ConfigManager integration.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from internal.services.storage.service import StorageService


@pytest.fixture(autouse=True)
def resetStorageServiceSingleton():
    """Reset StorageService singleton before each test, dood!"""
    StorageService._instance = None
    yield
    StorageService._instance = None


@pytest.fixture
def tempDir():
    """Create a temporary directory for testing, dood!"""
    tmpDir = tempfile.mkdtemp()
    yield tmpDir
    import shutil

    shutil.rmtree(tmpDir, ignore_errors=True)


@pytest.fixture
def mockConfigManager(tempDir):
    """Create a mock ConfigManager with filesystem config, dood!"""
    mock = Mock()
    mock.getStorageConfig = Mock(return_value={"type": "fs", "fs": {"base-dir": tempDir}})
    return mock


class TestStorageServiceIntegration:
    """Integration tests for StorageService with real backend, dood!"""

    def testCompleteStoreRetrieveCycle(self, mockConfigManager):
        """Test complete store and retrieve cycle"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        key = "test-document.txt"
        data = b"This is test data"

        service.store(key, data)
        assert service.exists(key) is True

        retrieved = service.get(key)
        assert retrieved == data

        assert service.delete(key) is True
        assert service.exists(key) is False

    def testMultipleFilesIntegration(self, mockConfigManager):
        """Test storing and managing multiple files"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        files = {
            "document1.txt": b"Content of document 1",
            "document2.txt": b"Content of document 2",
            "image.jpg": b"\xff\xd8\xff\xe0" + b"x" * 100,
            "data.json": b'{"key": "value"}',
        }

        for key, data in files.items():
            service.store(key, data)

        for key in files.keys():
            assert service.exists(key) is True

        allKeys = service.list()
        assert len(allKeys) == 4
        for key in files.keys():
            assert key in allKeys

        for key, expectedData in files.items():
            retrieved = service.get(key)
            assert retrieved == expectedData

        for key in files.keys():
            assert service.delete(key) is True

        assert service.list() == []

    def testListWithPrefixIntegration(self, mockConfigManager):
        """Test list operation with prefix filtering"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        service.store("docs-file1.txt", b"data1")
        service.store("docs-file2.txt", b"data2")
        service.store("images-photo1.jpg", b"data3")
        service.store("images-photo2.jpg", b"data4")
        service.store("other.txt", b"data5")

        docsFiles = service.list(prefix="docs-")
        assert len(docsFiles) == 2
        assert all(key.startswith("docs-") for key in docsFiles)

        imagesFiles = service.list(prefix="images-")
        assert len(imagesFiles) == 2
        assert all(key.startswith("images-") for key in imagesFiles)

        allFiles = service.list()
        assert len(allFiles) == 5

    def testListWithLimitIntegration(self, mockConfigManager):
        """Test list operation with limit"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        for i in range(20):
            service.store(f"file-{i:02d}.txt", f"data{i}".encode())

        limitedList = service.list(limit=10)
        assert len(limitedList) == 10

        allList = service.list()
        assert len(allList) == 20

    def testOverwriteExistingFile(self, mockConfigManager):
        """Test overwriting existing file"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        key = "test-file.txt"

        service.store(key, b"original data")
        assert service.get(key) == b"original data"

        service.store(key, b"new data")
        assert service.get(key) == b"new data"

        allFiles = service.list()
        assert allFiles.count(key) == 1

    def testLargeFileIntegration(self, mockConfigManager):
        """Test storing and retrieving large file"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        key = "large-file.bin"
        largeData = b"x" * (5 * 1024 * 1024)

        service.store(key, largeData)
        retrieved = service.get(key)

        assert retrieved is not None
        assert retrieved == largeData
        assert len(retrieved) == 5 * 1024 * 1024

    def testBinaryDataIntegration(self, mockConfigManager):
        """Test storing various binary data types"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        testCases = {
            "all-bytes.bin": bytes(range(256)),
            "zeros.bin": b"\x00" * 1000,
            "random.bin": bytes([i % 256 for i in range(1000)]),
        }

        for key, data in testCases.items():
            service.store(key, data)
            retrieved = service.get(key)
            assert retrieved == data

    def testUnicodeDataIntegration(self, mockConfigManager):
        """Test storing unicode text as bytes"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        key = "unicode-text.txt"
        text = "Hello world"
        data = text.encode("utf-8")

        service.store(key, data)
        retrieved = service.get(key)

        assert retrieved is not None
        assert retrieved == data
        assert retrieved.decode("utf-8") == text

    def testEmptyFileIntegration(self, mockConfigManager):
        """Test storing and retrieving empty file"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        key = "empty-file.txt"
        data = b""

        service.store(key, data)
        assert service.exists(key) is True

        retrieved = service.get(key)
        assert retrieved == data
        assert len(retrieved) == 0


class TestStorageServicePersistence:
    """Test persistence across service instances, dood!"""

    def testPersistenceAcrossInstances(self, mockConfigManager, tempDir):
        """Test that data persists across service instances"""
        service1 = StorageService.getInstance()
        service1.injectConfig(mockConfigManager)
        service1.store("persistent-key", b"persistent data")

        StorageService._instance = None

        service2 = StorageService.getInstance()
        service2.injectConfig(mockConfigManager)

        assert service2.exists("persistent-key") is True
        assert service2.get("persistent-key") == b"persistent data"

    def testPersistenceAfterReconfiguration(self, mockConfigManager, tempDir):
        """Test that data persists after reconfiguration"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        service.store("test-key", b"test data")

        service.injectConfig(mockConfigManager)

        assert service.exists("test-key") is True
        assert service.get("test-key") == b"test data"


class TestStorageServiceErrorHandling:
    """Test error handling in integration scenarios, dood!"""

    def testGetNonExistentFile(self, mockConfigManager):
        """Test getting non-existent file returns None"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        result = service.get("non-existent-file.txt")
        assert result is None

    def testExistsNonExistentFile(self, mockConfigManager):
        """Test exists returns False for non-existent file"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        result = service.exists("non-existent-file.txt")
        assert result is False

    def testDeleteNonExistentFile(self, mockConfigManager):
        """Test delete returns False for non-existent file"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        result = service.delete("non-existent-file.txt")
        assert result is False

    def testListEmptyDirectory(self, mockConfigManager):
        """Test list returns empty list for empty directory"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        result = service.list()
        assert result == []


class TestStorageServiceKeySanitization:
    """Test key sanitization in integration scenarios, dood!"""

    def testPathTraversalPrevention(self, mockConfigManager, tempDir):
        """Test that path traversal is prevented"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        key = "../../../etc/passwd"
        data = b"malicious data"

        service.store(key, data)

        sanitizedKey = "etc_passwd"

        files = list(Path(tempDir).iterdir())
        assert len(files) == 1
        assert files[0].name == sanitizedKey

        retrieved = service.get(key)
        assert retrieved == data

    def testSpecialCharactersInKey(self, mockConfigManager):
        """Test that special characters are handled"""
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        testKeys = [
            "file with spaces.txt",
            "file@with#special$chars.txt",
            "file/with/slashes.txt",
        ]

        for originalKey in testKeys:
            data = f"data for {originalKey}".encode()
            service.store(originalKey, data)

            retrieved = service.get(originalKey)
            assert retrieved == data
