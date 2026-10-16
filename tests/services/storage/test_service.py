"""
Comprehensive tests for StorageService

This module tests the StorageService singleton to ensure proper
initialization, configuration, and operation delegation to backends.
"""

import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from internal.services.storage import StorageScope
from internal.services.storage.backends.filesystem import FSStorageBackend
from internal.services.storage.backends.null import NullStorageBackend
from internal.services.storage.backends.s3 import S3StorageBackend
from internal.services.storage.exceptions import StorageConfigError, StorageKeyError
from internal.services.storage.service import StorageService, _buildBackend


@pytest.fixture(autouse=True)
def resetStorageServiceSingleton():
    """Reset StorageService singleton before each test"""
    StorageService._instances.clear()
    yield
    StorageService._instances.clear()


@pytest.fixture
def mockConfigManager():
    """Create a mock ConfigManager"""
    mock = Mock()
    mock.getStorageConfig = Mock()
    return mock


class TestStorageServiceSingleton:
    """Test StorageService singleton behavior"""

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
    """Test StorageService initialization"""

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
    """Test StorageService configuration with null backend"""

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
    """Test StorageService configuration with filesystem backend"""

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
    """Test StorageService configuration with S3 backend"""

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
    """Test StorageService configuration error handling"""

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


class TestStorageServiceBackendType:
    """Test the read-only ``backendType`` introspection property"""

    def testBackendTypeUninitializedReturnsNone(self):
        """Test that backendType is None before initialization"""
        service = StorageService.getInstance()

        assert service.backendType is None

    def testBackendTypeNull(self, mockConfigManager):
        """Test that a configured null backend reports the "null" type"""
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}

        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        assert service.backendType == "null"

    def testBackendTypeFS(self, mockConfigManager, tmp_path):
        """Test that a configured filesystem backend reports the "fs" type"""
        mockConfigManager.getStorageConfig.return_value = {"type": "fs", "fs": {"base-dir": str(tmp_path)}}

        service = StorageService.getInstance()
        service.injectConfig(mockConfigManager)

        assert service.backendType == "fs"


class TestStorageServiceOperations:
    """Test StorageService operations"""

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
    """Test that operations fail when service is not initialized"""

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
    """Test that backend errors are properly propagated"""

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
    """Test real-world usage scenarios"""

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


class TestStorageServiceScopedInstances:
    """Test per-scope StorageService instances (scoped-storage design v1, Phase 1)"""

    def testDistinctInstancePerScope(self):
        """Test that each scope gets its own distinct instance"""
        default = StorageService.getInstance(StorageScope.DEFAULT)
        vision = StorageService.getInstance(StorageScope.VISION)

        assert default is not vision

    def testSameInstancePerScopeAcrossCalls(self):
        """Test that repeated calls for the same scope return the same instance"""
        vision1 = StorageService.getInstance(StorageScope.VISION)
        vision2 = StorageService.getInstance(StorageScope.VISION)
        default1 = StorageService.getInstance(StorageScope.DEFAULT)
        default2 = StorageService.getInstance(StorageScope.DEFAULT)

        assert vision1 is vision2
        assert default1 is default2

    def testArglessGetInstanceIsDefaultScope(self):
        """Test that argless getInstance() IS the DEFAULT-scope instance (backward-compat pin)"""
        assert StorageService.getInstance() is StorageService.getInstance(StorageScope.DEFAULT)

    def testDirectConstructionIsDefaultScope(self):
        """Test that direct StorageService() returns the registered default-scope instance"""
        assert StorageService() is StorageService.getInstance(StorageScope.DEFAULT)

    def testScopedInstanceStartsUninitialized(self, mockConfigManager):
        """Test that a new scope starts uninitialized even when the default scope is configured"""
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}
        default = StorageService.getInstance(StorageScope.DEFAULT)
        default.injectConfig(mockConfigManager)

        vision = StorageService.getInstance(StorageScope.VISION)

        assert vision.initialized is False
        assert vision.backend is None
        assert default.initialized is True

    def testPerScopeInjectConfig(self, mockConfigManager, tmp_path):
        """Test that each scope reads its own config table"""
        visionDir = tmp_path / "vision"
        visionDir.mkdir()
        mockConfigManager.getStorageConfig.return_value = {
            "type": "null",
            "storages": {
                "vision": {"type": "fs", "fs": {"base-dir": str(visionDir)}},
            },
        }

        default = StorageService.getInstance(StorageScope.DEFAULT)
        default.injectConfig(mockConfigManager)
        vision = StorageService.getInstance(StorageScope.VISION)
        vision.injectConfig(mockConfigManager)

        assert default.backendType == "null"
        assert vision.backendType == "fs"

    def testAbsentNamedStorageResolvesToNullBackend(self, mockConfigManager):
        """Test that an absent named table silently resolves to a null backend (no raise)"""
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}

        vision = StorageService.getInstance(StorageScope.VISION)

        vision.injectConfig(mockConfigManager)  # must not raise

        assert vision.initialized is True
        assert isinstance(vision.backend, NullStorageBackend)
        assert vision.backendType == "null"  # public introspection (Gate-1 fold)

    def testEmptyStoragesTableResolvesToNullBackend(self, mockConfigManager):
        """Test that an empty storages mapping also resolves to a null backend"""
        mockConfigManager.getStorageConfig.return_value = {"type": "null", "storages": {}}

        vision = StorageService.getInstance(StorageScope.VISION)

        vision.injectConfig(mockConfigManager)

        assert vision.initialized is True
        assert isinstance(vision.backend, NullStorageBackend)
        assert vision.backendType == "null"  # public introspection (Gate-1 fold)

    @pytest.mark.parametrize(
        "namedConfig, expectedMessage",
        [
            ({}, "Storage type is not specified in configuration"),
            ({"type": "unknown"}, "Unknown storage type: unknown"),
            ({"type": "fs"}, "Filesystem storage configuration is missing"),
            ({"type": "fs", "fs": {}}, "Filesystem storage configuration is missing"),
            ({"type": "fs", "fs": {"unrelated": "value"}}, "Filesystem base-dir is not specified"),
            ({"type": "s3"}, "S3 storage configuration is missing"),
            (
                {"type": "s3", "s3": {"endpoint": "https://s3.amazonaws.com"}},
                "S3 configuration missing required parameters: region, key-id, key-secret, bucket",
            ),
        ],
        ids=[
            "present-but-empty",
            "unknown-type",
            "fs-missing-fs-table",
            "fs-empty-table",
            "fs-nonempty-missing-base-dir",
            "s3-missing-s3-table",
            "s3-partial-params-missing",
        ],
    )
    def testBadNamedStorageRaisesConfigError(self, mockConfigManager, namedConfig, expectedMessage):
        """Test that a present-but-malformed named table raises StorageConfigError

        with the EXACT default-scope message (Gate-1 review fold: validation
        parity between scopes is asserted on the message text, not just the
        exception type).

        Args:
            mockConfigManager: Mock ConfigManager fixture.
            namedConfig: Malformed ``[storage.storages.vision]`` table.
            expectedMessage: The exact ``StorageConfigError`` message.
        """
        mockConfigManager.getStorageConfig.return_value = {"type": "null", "storages": {"vision": namedConfig}}

        vision = StorageService.getInstance(StorageScope.VISION)

        with pytest.raises(StorageConfigError) as excInfo:
            vision.injectConfig(mockConfigManager)

        assert str(excInfo.value) == expectedMessage

    def testReinjectIndependenceAcrossScopes(self, mockConfigManager, tmp_path):
        """Test that re-injecting one scope does not disturb another scope's backend

        Gate-1 review fold: the untouched scope must keep the SAME backend
        OBJECT (identity, not merely the same backend class), asserted from
        references saved BEFORE the other scope's re-inject.
        """
        visionDir = tmp_path / "vision"
        defaultDir = tmp_path / "default"
        visionDir.mkdir()
        defaultDir.mkdir()
        mockConfigManager.getStorageConfig.return_value = {
            "type": "fs",
            "fs": {"base-dir": str(defaultDir)},
            "storages": {"vision": {"type": "fs", "fs": {"base-dir": str(visionDir)}}},
        }

        default = StorageService.getInstance(StorageScope.DEFAULT)
        default.injectConfig(mockConfigManager)
        vision = StorageService.getInstance(StorageScope.VISION)
        vision.injectConfig(mockConfigManager)

        # Save backend references BEFORE any re-inject.
        visionBackendBefore = vision.backend
        defaultBackendBefore = default.backend

        # Re-inject the default scope as null; vision must keep its backend object
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}
        default.injectConfig(mockConfigManager)

        assert default.backend is not defaultBackendBefore  # default's backend was replaced
        assert vision.backend is visionBackendBefore  # identity: same object, untouched
        assert isinstance(vision.backend, FSStorageBackend)
        assert vision.backend.baseDir == visionDir
        assert isinstance(default.backend, NullStorageBackend)

        # And re-injecting vision must not disturb the default scope
        defaultBackendAfterDefaultReinject = default.backend
        mockConfigManager.getStorageConfig.return_value = {
            "type": "null",
            "storages": {"vision": {"type": "null"}},
        }
        vision.injectConfig(mockConfigManager)

        assert vision.backend is not visionBackendBefore  # vision's backend was replaced
        assert default.backend is defaultBackendAfterDefaultReinject  # identity: same object
        assert isinstance(vision.backend, NullStorageBackend)
        assert isinstance(default.backend, NullStorageBackend)


class TestStorageServiceScopeConfigSelection:
    """Test that each instance's injectConfig reads its OWN scope's config table

    injectConfig takes no scope argument (user decision): the config table is
    derived strictly from the instance's construction scope, so the former
    scope-mismatch ValueError is structurally impossible. These pins replace
    the obsolete mismatch-guard tests — what must hold is that each scope
    reads ITS OWN table and never another scope's.
    """

    def testConstructionScopeIsRetained(self):
        """Test that each instance retains the scope it was created for"""
        default = StorageService.getInstance(StorageScope.DEFAULT)
        vision = StorageService.getInstance(StorageScope.VISION)

        assert default.scope == StorageScope.DEFAULT
        assert vision.scope == StorageScope.VISION

    def testVisionInstanceReadsVisionConfigSection(self, mockConfigManager: Mock, tmp_path: Path) -> None:
        """Test that an arg-less injectConfig on the VISION instance reads the vision table

        Regression context (review-large finding, now pinned structurally):
        an arg-less call used to risk configuring the vision instance with the
        DEFAULT attachments config. With distinct fs base dirs in each
        section, the configured backend's baseDir pins WHICH section was read.

        Args:
            mockConfigManager: Mock ConfigManager fixture.
            tmp_path: Temporary directory holding the distinct default/vision fs base dirs.
        """
        defaultDir = tmp_path / "default"
        visionDir = tmp_path / "vision"
        defaultDir.mkdir()
        visionDir.mkdir()
        mockConfigManager.getStorageConfig.return_value = {
            "type": "fs",
            "fs": {"base-dir": str(defaultDir)},
            "storages": {"vision": {"type": "fs", "fs": {"base-dir": str(visionDir)}}},
        }

        vision = StorageService.getInstance(StorageScope.VISION)
        vision.injectConfig(mockConfigManager)  # arg-less: scope comes from the instance

        assert isinstance(vision.backend, FSStorageBackend)
        assert vision.backend.baseDir == visionDir  # the VISION section, not the default one

    def testDefaultInstanceReadsDefaultConfigSection(self, mockConfigManager: Mock, tmp_path: Path) -> None:
        """Test that an arg-less injectConfig on the DEFAULT instance reads the top-level table

        Args:
            mockConfigManager: Mock ConfigManager fixture.
            tmp_path: Temporary directory holding the distinct default/vision fs base dirs.
        """
        defaultDir = tmp_path / "default"
        visionDir = tmp_path / "vision"
        defaultDir.mkdir()
        visionDir.mkdir()
        mockConfigManager.getStorageConfig.return_value = {
            "type": "fs",
            "fs": {"base-dir": str(defaultDir)},
            "storages": {"vision": {"type": "fs", "fs": {"base-dir": str(visionDir)}}},
        }

        default = StorageService.getInstance(StorageScope.DEFAULT)
        default.injectConfig(mockConfigManager)  # arg-less: scope comes from the instance

        assert isinstance(default.backend, FSStorageBackend)
        assert default.backend.baseDir == defaultDir  # the top-level table, not the vision one

    def testAbsentVisionConfigDoesNotFallBackToDefaultStorage(self, mockConfigManager: Mock, tmp_path: Path) -> None:
        """Test that an absent vision table leaves the vision instance on the null backend

        Documented ADR-029 semantics: NO inheritance from the default
        ``[storage]`` table. With a REAL fs default store configured, the
        vision instance must not receive the default's backend — it gets the
        silent NullStorageBackend (feature off, never a fallback).

        Args:
            mockConfigManager: Mock ConfigManager fixture.
            tmp_path: Temporary directory holding the real default fs base dir.
        """
        defaultDir = tmp_path / "default"
        defaultDir.mkdir()
        mockConfigManager.getStorageConfig.return_value = {
            "type": "fs",
            "fs": {"base-dir": str(defaultDir)},
        }

        default = StorageService.getInstance(StorageScope.DEFAULT)
        default.injectConfig(mockConfigManager)
        vision = StorageService.getInstance(StorageScope.VISION)
        vision.injectConfig(mockConfigManager)  # must not raise

        assert isinstance(default.backend, FSStorageBackend)  # default store really configured
        assert isinstance(vision.backend, NullStorageBackend)  # NOT the default's fs backend
        assert vision.initialized is True
        assert vision.backendType == "null"


class TestStorageServiceInitializationConcurrency:
    """Test that first-time initialization is atomic under concurrent getInstance calls"""

    def testConcurrentFirstGetInstanceInitializesExactlyOnce(self):
        """Test N simultaneous first-time getInstance calls initialize exactly once

        Controlled concurrency: a barrier releases all threads at once on a fresh
        class state (cleared by the autouse fixture). Exactly one guard-body
        execution is counted via the module logger's "created, awaiting
        configuration" line; every thread must observe the same instance with
        its construction scope retained.
        """
        threadCount = 16
        barrier = threading.Barrier(threadCount, timeout=10)
        results: list[StorageService] = []

        with patch("internal.services.storage.service.logger") as mockLogger:

            def worker():
                barrier.wait()
                results.append(StorageService.getInstance(StorageScope.VISION))

            threads = [threading.Thread(target=worker) for _ in range(threadCount)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        initLogs = [
            callArgs
            for callArgs in mockLogger.info.call_args_list
            if "created, awaiting configuration" in str(callArgs)
        ]

        assert len(initLogs) == 1  # exactly one initialization, not one per thread
        assert len(results) == threadCount
        assert all(result is results[0] for result in results)
        assert results[0].scope == StorageScope.VISION

    def testDelayedInitializerDoesNotResetConfiguredBackend(self, mockConfigManager):
        """Test a delayed __init__ cannot reset the backend of a configured instance

        Models the inherited race: a slow first-time caller reaching the
        initializer after another thread already injected config. Re-running
        __init__ (directly, as the interpreter would on a late getInstance)
        must leave backend and initialized untouched.
        """
        mockConfigManager.getStorageConfig.return_value = {"type": "null"}

        vision = StorageService.getInstance(StorageScope.VISION)
        vision.injectConfig(mockConfigManager)
        backendBefore = vision.backend

        StorageService.__init__(vision, StorageScope.VISION)  # simulated delayed initializer

        assert vision.backend is backendBefore
        assert vision.initialized is True


class TestBuildBackend:
    """Test the shared _buildBackend validation chain (used by both scopes)"""

    @pytest.mark.parametrize(
        "config, expectedMessage",
        [
            ({}, "Storage type is not specified in configuration"),
            ({"type": "unknown"}, "Unknown storage type: unknown"),
            ({"type": "fs"}, "Filesystem storage configuration is missing"),
            ({"type": "fs", "fs": {}}, "Filesystem storage configuration is missing"),  # empty dict = missing
            ({"type": "fs", "fs": {"unrelated": "value"}}, "Filesystem base-dir is not specified"),
            ({"type": "s3"}, "S3 storage configuration is missing"),
            (
                # Non-empty table (only the optional prefix) so the required-
                # params branch (not the missing-s3 branch) produces the
                # complete ordered list.
                {"type": "s3", "s3": {"prefix": "some-prefix/"}},
                "S3 configuration missing required parameters: endpoint, region, key-id, key-secret, bucket",
            ),
            (
                {"type": "s3", "s3": {"endpoint": "https://s3.amazonaws.com"}},
                "S3 configuration missing required parameters: region, key-id, key-secret, bucket",
            ),
        ],
        ids=[
            "missing-type",
            "unknown-type",
            "fs-missing-fs-table",
            "fs-empty-table",
            "fs-nonempty-missing-base-dir",
            "s3-missing-s3-table",
            "s3-all-params-missing",
            "s3-partial-params-missing",
        ],
    )
    def testBuildBackendInvalidConfigRaises(self, config, expectedMessage):
        """Test that invalid config raises StorageConfigError with the EXACT message

        Gate-1 review fold: substring ``match=`` assertions were too loose —
        the exact ``str(exc.value)`` is pinned, including the complete
        ordered S3 missing-parameter list.

        Args:
            config: Malformed storage config table.
            expectedMessage: The exact ``StorageConfigError`` message.
        """
        with pytest.raises(StorageConfigError) as excInfo:
            _buildBackend(config)

        assert str(excInfo.value) == expectedMessage

    def testBuildBackendNull(self):
        """Test null backend construction through the shared chain"""
        assert isinstance(_buildBackend({"type": "null"}), NullStorageBackend)

    def testBuildBackendFS(self, tmp_path):
        """Test fs backend construction through the shared chain"""
        backend = _buildBackend({"type": "fs", "fs": {"base-dir": str(tmp_path)}})

        assert isinstance(backend, FSStorageBackend)
        assert backend.baseDir == tmp_path

    def testBuildBackendS3(self):
        """Test s3 backend construction through the shared chain"""
        backend = _buildBackend(
            {
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
        )

        assert isinstance(backend, S3StorageBackend)
        assert backend.bucket == "test-bucket"
        assert backend.prefix == "test-prefix/"
