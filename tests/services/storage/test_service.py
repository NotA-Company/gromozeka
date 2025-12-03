"""
Comprehensive tests for StorageService, dood!

This module tests the StorageService singleton to ensure proper
initialization, configuration, and operation delegation to backends.
"""

from unittest.mock import Mock, patch

import pytest

from internal.services.storage.backends.filesystem import FSStorageBackend
from internal.services.storage.backends.null import NullStorageBackend
from internal.services.storage.exceptions import StorageConfigError, StorageKeyError
from internal.services.storage.service import StorageService


@pytest.fixture(autouse=True)
def resetStorageServiceSingleton():
    """Reset StorageService singleton before each test, dood!"""
    StorageService._instance = None
    yield
    StorageService._instance = None


@pytest.fixture
def mockConfigManager():
    """Create a mock ConfigManager, dood!"""
    mock = Mock()
    mock.getStorageConfig = Mock()
    return mock


class TestStorageServiceSingleton:
    """Test StorageService singleton behavior, dood!"""

    def testGetInstanceReturnsSameInstance(self):
        """Test that getInstance returns same instance"""
        service1 = StorageService.getInstance()
        service2 = StorageService.getInstance()

        assert service1 is service2

    def testMultipleCallsReturnSameInstance(self):
        """Test that multiple calls return same instance"""
        instances = [StorageService.getInstance() for _ in range(10)]
        assert all(inst is instances[0] for inst in instances)

    def testNewReturnsSingleton(self):
        """Test that __new__ returns singleton"""
        service1 = StorageService()
        service2 = StorageService()

        assert service1 is service2


class TestStorageServiceInitialization:
    """Test StorageService initialization, dood!"""

    def testInitialState(self):
        """Test that service initializes with correct state"""
        service = StorageService.getInstance()

        assert service.backend is None
        assert service.initialized is False

    def testInitializationOnlyRunsOnce(self):
        """Test that __init__ only runs once"""
        service1 = StorageService.getInstance()
        setattr(service1, "testAttribute", "test")

        service2 = StorageService.getInstance()
        assert hasattr(service2, "testAttribute")
        assert getattr(service2, "testAttribute") == "test"


class TestStorageServiceInjectConfigNull:
    """Test StorageService configuration with null backend, dood!"""

    def testInjectConfigNull(self, mockConfigManager):
        """Test injecting config for null backend"""
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}

        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        assert service.initialized is True
        assert isinstance(service.backend, NullStorageBackend)

    def testInjectConfigNullMultipleTimes(self, mockConfigManager):
        """Test that injecting config multiple times works"""
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}

        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)
        service.injectConfig(mockConfigManager)

        assert service.initialized is True


class TestStorageServiceInjectConfigFS:
    """Test StorageService configuration with filesystem backend, dood!"""

    def testInjectConfigFS(self, mockConfigManager, tmp_path):
        """Test injecting config for filesystem backend"""
        mockConfigManager.getStorageConfig.return_value = {"type": "fs", "fs": {"base-dir": str(tmp_path)}}

        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        assert service.initialized is True
        assert isinstance(service.backend, FSStorageBackend)
        assert service.backend.baseDir == tmp_path

    def testInjectConfigFSMissingConfig(self, mockConfigManager):
        """Test that missing fs config raises error"""
        mockConfigManager.getStorageConfig.return_value = {"type": "fs"}

        service = StorageService.getInstance()
        with pytest.raises(StorageConfigError, match="Filesystem storage configuration is missing"):
            service.injectConfig(mockConfigManager)

    def testInjectConfigFSMissingBaseDir(self, mockConfigManager):
        """Test that missing base-dir raises error"""
        mockConfigManager.getStorageConfig.return_value = {"type": "fs", "fs": {}}

        service = StorageService.getInstance()
        with pytest.raises(StorageConfigError):
            service.injectConfig(mockConfigManager)


class TestStorageServiceInjectConfigS3:
    """Test StorageService configuration with S3 backend, dood!"""

    def testInjectConfigS3(self, mockConfigManager):
        """Test injecting config for S3 backend"""
        mockConfigManager.getStorageConfig.return_value = {
            "type": "s3",
            "s3": {
                "endpoint": "https://s3.amazonaws.com",
                "region": "us-east-1",
                "key-id": "test-key-id",
                "key-secret": "test-key-secret",
                "bucket": "test-bucket",
                "prefix": "test-prefix/",
            },
        }

        service = StorageService.getInstance()

        with patch("internal.services.storage.service.S3StorageBackend") as mockS3Backend:
            mockBackendInstance = Mock()
            mockS3Backend.return_value = mockBackendInstance

            service.injectConfig(mockConfigManager)

            assert service.initialized is True
            mockS3Backend.assert_called_once_with(
                endpoint="https://s3.amazonaws.com",
                region="us-east-1",
                keyId="test-key-id",
                keySecret="test-key-secret",
                bucket="test-bucket",
                prefix="test-prefix/",
            )

    def testInjectConfigS3WithoutPrefix(self, mockConfigManager):
        """Test injecting S3 config without prefix"""
        mockConfigManager.getStorageConfig.return_value = {
            "type": "s3",
            "s3": {
                "endpoint": "https://s3.amazonaws.com",
                "region": "us-east-1",
                "key-id": "test-key-id",
                "key-secret": "test-key-secret",
                "bucket": "test-bucket",
            },
        }

        service = StorageService.getInstance()

        with patch("internal.services.storage.service.S3StorageBackend") as mockS3Backend:
            mockBackendInstance = Mock()
            mockS3Backend.return_value = mockBackendInstance

            service.injectConfig(mockConfigManager)

            call_args = mockS3Backend.call_args
            assert call_args[1]["prefix"] == ""

    def testInjectConfigS3MissingConfig(self, mockConfigManager):
        """Test that missing s3 config raises error"""
        mockConfigManager.getStorageConfig.return_value = {"type": "s3"}

        service = StorageService.getInstance()
        with pytest.raises(StorageConfigError, match="S3 storage configuration is missing"):
            service.injectConfig(mockConfigManager)

    def testInjectConfigS3MissingRequiredParams(self, mockConfigManager):
        """Test that missing required S3 params raises error"""
        mockConfigManager.getStorageConfig.return_value = {
            "type": "s3",
            "s3": {
                "endpoint": "https://s3.amazonaws.com",
                "region": "us-east-1",
                # Missing key-id, key-secret, bucket
            },
        }

        service = StorageService.getInstance()
        with pytest.raises(StorageConfigError, match="missing required parameters"):
            service.injectConfig(mockConfigManager)


class TestStorageServiceInjectConfigErrors:
    """Test StorageService configuration error handling, dood!"""

    def testInjectConfigMissingConfig(self, mockConfigManager):
        """Test that missing config raises error"""
        mockConfigManager.getStorageConfig.return_value = None

        service = StorageService.getInstance()
        with pytest.raises(StorageConfigError, match="Storage configuration is missing"):
            service.injectConfig(mockConfigManager)

    def testInjectConfigMissingType(self, mockConfigManager):
        """Test that missing type raises error"""
        mockConfigManager.getStorageConfig.return_value = {}

        service = StorageService.getInstance()
        with pytest.raises(StorageConfigError):
            service.injectConfig(mockConfigManager)

    def testInjectConfigUnknownType(self, mockConfigManager):
        """Test that unknown type raises error"""
        mockConfigManager.getStorageConfig.return_value = {"type": "unknown"}

        service = StorageService.getInstance()
        with pytest.raises(StorageConfigError, match="Unknown storage type"):
            service.injectConfig(mockConfigManager)

    def testInjectConfigBackendCreationFailure(self, mockConfigManager):
        """Test that backend creation failure raises error"""
        mockConfigManager.getStorageConfig.return_value = {"type": "fs", "fs": {"base-dir": "/invalid/path"}}

        service = StorageService.getInstance()

        with patch("internal.services.storage.service.FSStorageBackend", side_effect=Exception("Creation failed")):
            with pytest.raises(StorageConfigError, match="Failed to initialize storage service"):
                service.injectConfig(mockConfigManager)


class TestStorageServiceOperations:
    """Test StorageService operations, dood!"""

    @pytest.fixture
    def configuredService(self, mockConfigManager):
        """Create a configured service with null backend"""
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)
        return service

    def testStoreOperation(self, configuredService):
        """Test store operation delegates to backend"""
        configuredService.backend = Mock()
        configuredService.backend.store = Mock()

        configuredService.store("test-key", b"data")

        configuredService.backend.store.assert_called_once_with("test-key", b"data")

    def testGetOperation(self, configuredService):
        """Test get operation delegates to backend"""
        configuredService.backend = Mock()
        configuredService.backend.get = Mock(return_value=b"data")

        result = configuredService.get("test-key")

        assert result == b"data"
        configuredService.backend.get.assert_called_once_with("test-key")

    def testExistsOperation(self, configuredService):
        """Test exists operation delegates to backend"""
        configuredService.backend = Mock()
        configuredService.backend.exists = Mock(return_value=True)

        result = configuredService.exists("test-key")

        assert result is True
        configuredService.backend.exists.assert_called_once_with("test-key")

    def testDeleteOperation(self, configuredService):
        """Test delete operation delegates to backend"""
        configuredService.backend = Mock()
        configuredService.backend.delete = Mock(return_value=True)

        result = configuredService.delete("test-key")

        assert result is True
        configuredService.backend.delete.assert_called_once_with("test-key")

    def testListOperation(self, configuredService):
        """Test list operation delegates to backend"""
        configuredService.backend = Mock()
        configuredService.backend.list = Mock(return_value=["key1", "key2"])

        result = configuredService.list(prefix="test-", limit=10)

        assert result == ["key1", "key2"]
        configuredService.backend.list.assert_called_once_with(prefix="test-", limit=10)


class TestStorageServiceUninitializedErrors:
    """Test that operations fail when service is not initialized, dood!"""

    def testStoreWithoutInitRaisesError(self):
        """Test that store without init raises error"""
        service = StorageService.getInstance()

        with pytest.raises(StorageConfigError, match="not initialized"):
            service.store("test-key", b"data")

    def testGetWithoutInitRaisesError(self):
        """Test that get without init raises error"""
        service = StorageService.getInstance()

        with pytest.raises(StorageConfigError, match="not initialized"):
            service.get("test-key")

    def testExistsWithoutInitRaisesError(self):
        """Test that exists without init raises error"""
        service = StorageService.getInstance()

        with pytest.raises(StorageConfigError, match="not initialized"):
            service.exists("test-key")

    def testDeleteWithoutInitRaisesError(self):
        """Test that delete without init raises error"""
        service = StorageService.getInstance()

        with pytest.raises(StorageConfigError, match="not initialized"):
            service.delete("test-key")

    def testListWithoutInitRaisesError(self):
        """Test that list without init raises error"""
        service = StorageService.getInstance()

        with pytest.raises(StorageConfigError, match="not initialized"):
            service.list()


class TestStorageServiceErrorPropagation:
    """Test that backend errors are properly propagated, dood!"""

    @pytest.fixture
    def configuredService(self, mockConfigManager):
        """Create a configured service with mock backend"""
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)
        service.backend = Mock()
        return service

    def testStoreKeyErrorPropagated(self, configuredService):
        """Test that StorageKeyError is propagated"""
        configuredService.backend.store = Mock(side_effect=StorageKeyError("Invalid key"))

        with pytest.raises(StorageKeyError, match="Invalid key"):
            configuredService.store("", b"data")

    def testGetKeyErrorPropagated(self, configuredService):
        """Test that StorageKeyError from get is propagated"""
        configuredService.backend.get = Mock(side_effect=StorageKeyError("Invalid key"))

        with pytest.raises(StorageKeyError, match="Invalid key"):
            configuredService.get("")

    def testExistsKeyErrorPropagated(self, configuredService):
        """Test that StorageKeyError from exists is propagated"""
        configuredService.backend.exists = Mock(side_effect=StorageKeyError("Invalid key"))

        with pytest.raises(StorageKeyError, match="Invalid key"):
            configuredService.exists("")

    def testDeleteKeyErrorPropagated(self, configuredService):
        """Test that StorageKeyError from delete is propagated"""
        configuredService.backend.delete = Mock(side_effect=StorageKeyError("Invalid key"))

        with pytest.raises(StorageKeyError, match="Invalid key"):
            configuredService.delete("")


class TestStorageServiceRealWorldScenarios:
    """Test real-world usage scenarios, dood!"""

    def testCompleteWorkflow(self, mockConfigManager, tmp_path):
        """Test complete workflow from config to operations"""
        mockConfigManager.getStorageConfig.return_value = {"type": "fs", "fs": {"base-dir": str(tmp_path)}}

        # Get singleton and configure
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        # Store data
        service.store("test-key", b"test data")

        # Verify exists
        assert service.exists("test-key") is True

        # Retrieve data
        data = service.get("test-key")
        assert data == b"test data"

        # List files
        keys = service.list()
        assert "test-key" in keys

        # Delete
        assert service.delete("test-key") is True
        assert service.exists("test-key") is False

    def testMultipleFiles(self, mockConfigManager, tmp_path):
        """Test storing multiple files"""
        mockConfigManager.getStorageConfig.return_value = {"type": "fs", "fs": {"base-dir": str(tmp_path)}}

        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        # Store multiple files
        files = {"file1.txt": b"data1", "file2.txt": b"data2", "file3.txt": b"data3"}

        for key, data in files.items():
            service.store(key, data)

        # Verify all exist
        for key in files.keys():
            assert service.exists(key) is True

        # List all
        keys = service.list()
        assert len(keys) == 3

    def testSwitchingBackends(self, mockConfigManager, tmp_path):
        """Test that service can be reconfigured with different backend"""
        # First configure with null
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}
        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)
        assert isinstance(service.backend, NullStorageBackend)

        # Reconfigure with filesystem
        mockConfigManager.getStorageConfig.return_value = {"type": "fs", "fs": {"base-dir": str(tmp_path)}}
        service.injectConfig(mockConfigManager)
        assert isinstance(service.backend, FSStorageBackend)
