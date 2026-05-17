"""Tests for SandboxManager operational methods (healthcheck, recover, shutdown).

Covers:
- healthcheck returns HealthcheckResult with backend, runtime, storage info.
- healthcheck reports storage as unhealthy when rootDir doesn't exist.
- healthcheck reports backend errors gracefully.
- shutdown returns ShutdownResult with no volumes by default.
- shutdown with cleanVolumes=True drops all sessions.
- recover returns RecoveryResult with zero counts when no containers exist.
- recover removes sessions whose workspace directories are missing.
- recover reaps managed containers.
- collectOrphanContainers delegates to the backend when available.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.sandbox.backends.base import ManagedContainerInfo
from lib.sandbox.config import (
    ConcurrencyConfig,
    GcConfig,
    SandboxConfig,
    StorageConfig,
)
from lib.sandbox.enums import RuntimeName
from lib.sandbox.gc import GarbageCollector
from lib.sandbox.manager import SandboxManager
from lib.sandbox.metadata.base import SessionRecord
from lib.sandbox.storage import sessionHash
from lib.sandbox.types import HealthcheckResult, RecoveryResult, ShutdownResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeConfig(*, rootDir: str = "/tmp/sandbox-test-ops") -> SandboxConfig:
    """Create a minimal SandboxConfig for testing.

    Args:
        rootDir: Root directory for sandbox storage.

    Returns:
        A SandboxConfig with sensible defaults.
    """
    return SandboxConfig(
        storage=StorageConfig(rootDir=rootDir),
        concurrency=ConcurrencyConfig(
            maxQueuedRunsPerSession=4,
            maxConcurrentRunsGlobal=8,
            globalQueueWaitSeconds=60,
        ),
        gc=GcConfig(enabled=True),
    )


def _makeSessionRecord(
    sessionId: str,
    workspacePath: str,
    *,
    expiresAt: datetime | None = None,
) -> SessionRecord:
    """Create a SessionRecord for testing.

    Args:
        sessionId: The session identifier.
        workspacePath: Host-side path to the workspace directory.
        expiresAt: Expiration timestamp (defaults to 30 min from now).

    Returns:
        A SessionRecord instance.
    """
    now = datetime.now(timezone.utc)
    return SessionRecord(
        sessionId=sessionId,
        sessionHash=sessionHash(sessionId),
        runtime=RuntimeName.PYTHON,
        workspacePath=workspacePath,
        createdAt=now,
        updatedAt=now,
        expiresAt=expiresAt or (now + timedelta(minutes=30)),
        metadata={},
        schemaVersion=1,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _resetSingleton():
    """Reset the SandboxManager singleton before and after each test."""
    SandboxManager._instance = None
    SandboxManager._configInstance = None
    yield
    SandboxManager._instance = None
    SandboxManager._configInstance = None


# ---------------------------------------------------------------------------
# healthcheck
# ---------------------------------------------------------------------------


class TestHealthcheck:
    """Tests for SandboxManager.healthcheck."""

    async def test_returnsHealthcheckResult(self, tmp_path: Path) -> None:
        """healthcheck returns a HealthcheckResult with storage info."""
        config = _makeConfig(rootDir=str(tmp_path / "sandbox"))
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        # Mock the backend healthcheck to return a healthy result
        mockBackendResult = HealthcheckResult(
            ok=True,
            backend={"version": "24.0.0"},
            runtimes={},
            storage={},
            errors=[],
        )
        manager._backend.healthcheck = AsyncMock(return_value=mockBackendResult)  # type: ignore[attr-defined]

        result = await manager.healthcheck()
        assert isinstance(result, HealthcheckResult)
        # Storage should be ok since tmp_path is writable
        assert result.storage.get("ok") is True

    async def test_storageUnhealthyWhenRootDirMissing(self, tmp_path: Path) -> None:
        """healthcheck reports storage as unhealthy when rootDir doesn't exist."""
        nonexistentDir = str(tmp_path / "nonexistent" / "sandbox")
        config = _makeConfig(rootDir=nonexistentDir)
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        # The manager init creates the directory via ensureDirectoryLayout,
        # so remove it after init to test the missing-directory path.
        import shutil

        shutil.rmtree(nonexistentDir, ignore_errors=True)

        mockBackendResult = HealthcheckResult(
            ok=True,
            backend={"version": "24.0.0"},
            runtimes={},
            storage={},
            errors=[],
        )
        manager._backend.healthcheck = AsyncMock(return_value=mockBackendResult)  # type: ignore[attr-defined]

        result = await manager.healthcheck()
        assert result.storage.get("ok") is False
        assert "does not exist" in result.storage.get("error", "")
        assert not result.ok  # overall should be False

    async def test_backendErrorsPropagate(self, tmp_path: Path) -> None:
        """healthcheck propagates backend errors into the result."""
        config = _makeConfig(rootDir=str(tmp_path / "sandbox"))
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        mockBackendResult = HealthcheckResult(
            ok=False,
            backend={"error": "Docker unavailable"},
            runtimes={},
            storage={},
            errors=["Docker unavailable"],
        )
        manager._backend.healthcheck = AsyncMock(return_value=mockBackendResult)  # type: ignore[attr-defined]

        result = await manager.healthcheck()
        assert not result.ok
        assert "Docker unavailable" in result.errors

    async def test_runtimeWithNoMetadata(self, tmp_path: Path) -> None:
        """healthcheck reports a runtime as unhealthy when it has no metadata record."""
        from lib.sandbox.config import PythonRuntimeConfig

        config = _makeConfig(rootDir=str(tmp_path / "sandbox"))
        config.runtimes[RuntimeName.PYTHON] = PythonRuntimeConfig()
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        mockBackendResult = HealthcheckResult(
            ok=True,
            backend={"version": "24.0.0"},
            runtimes={},
            storage={},
            errors=[],
        )
        manager._backend.healthcheck = AsyncMock(return_value=mockBackendResult)  # type: ignore[attr-defined]
        # loadRuntime returns None — no metadata record
        manager._metadata.loadRuntime = AsyncMock(return_value=None)  # type: ignore[attr-defined]

        result = await manager.healthcheck()
        assert "python" in result.runtimes
        assert result.runtimes["python"]["ok"] is False
        assert not result.ok


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    """Tests for SandboxManager.shutdown."""

    async def test_returnsShutdownResult(self, tmp_path: Path) -> None:
        """shutdown returns a ShutdownResult with zero cleaned volumes by default."""
        config = _makeConfig(rootDir=str(tmp_path / "sandbox"))
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        # Mock backend close
        manager._backend.close = AsyncMock()  # type: ignore[attr-defined]

        result = await manager.shutdown()
        assert isinstance(result, ShutdownResult)
        assert result.cleanedVolumes == 0
        assert result.errors == []

    async def test_cleanVolumesDropsAllSessions(self, tmp_path: Path) -> None:
        """shutdown with cleanVolumes=True drops all sessions."""
        config = _makeConfig(rootDir=str(tmp_path / "sandbox"))
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        # Create two sessions with workspaces
        sHash1 = sessionHash("sess-1")
        wp1 = Path(config.storage.rootDir) / "sessions" / sHash1 / "workspace"
        wp1.mkdir(parents=True, exist_ok=True)
        record1 = _makeSessionRecord("sess-1", str(wp1))
        await manager._metadata.saveSession(record1)

        sHash2 = sessionHash("sess-2")
        wp2 = Path(config.storage.rootDir) / "sessions" / sHash2 / "workspace"
        wp2.mkdir(parents=True, exist_ok=True)
        record2 = _makeSessionRecord("sess-2", str(wp2))
        await manager._metadata.saveSession(record2)

        # Mock backend close
        manager._backend.close = AsyncMock()  # type: ignore[attr-defined]

        result = await manager.shutdown(cleanVolumes=True)
        assert result.cleanedVolumes == 2
        assert result.errors == []

        # Sessions should be gone
        assert await manager._metadata.loadSession("sess-1") is None
        assert await manager._metadata.loadSession("sess-2") is None

    async def test_shutdownClosesBackend(self, tmp_path: Path) -> None:
        """shutdown calls backend.close() if available."""
        config = _makeConfig(rootDir=str(tmp_path / "sandbox"))
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        manager._backend.close = AsyncMock()  # type: ignore[attr-defined]

        result = await manager.shutdown()
        manager._backend.close.assert_awaited_once()  # type: ignore[attr-defined]
        assert result.errors == []


# ---------------------------------------------------------------------------
# recover
# ---------------------------------------------------------------------------


class TestRecover:
    """Tests for SandboxManager.recover."""

    async def test_returnsRecoveryResultWhenEmpty(self, tmp_path: Path) -> None:
        """recover returns RecoveryResult with zero counts when no containers exist."""
        config = _makeConfig(rootDir=str(tmp_path / "sandbox"))
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        # Mock backend to return no managed containers
        manager._backend.listManagedContainers = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        result = await manager.recover()
        assert isinstance(result, RecoveryResult)
        assert result.reapedContainers == 0
        assert result.releasedLocks == 0
        assert result.reconciledPools == 0
        assert result.errors == []

    async def test_removesSessionsWithMissingWorkspaces(self, tmp_path: Path) -> None:
        """recover removes sessions whose workspace directories don't exist."""
        config = _makeConfig(rootDir=str(tmp_path / "sandbox"))
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        # Mock backend to return no managed containers
        manager._backend.listManagedContainers = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        # Create a session record pointing to a nonexistent workspace
        nonexistentWorkspace = str(tmp_path / "sandbox" / "sessions" / "deadhash" / "workspace")
        record = _makeSessionRecord("dead-sess", nonexistentWorkspace)
        await manager._metadata.saveSession(record)

        result = await manager.recover()
        assert result.releasedLocks == 1

        # Session should be gone
        assert await manager._metadata.loadSession("dead-sess") is None

    async def test_reapsManagedContainers(self, tmp_path: Path) -> None:
        """recover kills and removes all managed containers."""
        config = _makeConfig(rootDir=str(tmp_path / "sandbox"))
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        containers = [
            ManagedContainerInfo(
                containerId="abc123",
                name="sandbox-run-1",
                labels={"sandbox.managed": "true"},
                status="running",
                createdAt="2025-01-01T00:00:00Z",
            ),
            ManagedContainerInfo(
                containerId="def456",
                name="sandbox-run-2",
                labels={"sandbox.managed": "true"},
                status="exited",
                createdAt="2025-01-01T00:00:00Z",
            ),
        ]
        manager._backend.listManagedContainers = AsyncMock(return_value=containers)  # type: ignore[attr-defined]
        manager._backend.killContainer = AsyncMock()  # type: ignore[attr-defined]
        manager._backend.removeContainer = AsyncMock()  # type: ignore[attr-defined]

        result = await manager.recover()
        assert result.reapedContainers == 2
        assert manager._backend.killContainer.await_count == 2  # type: ignore[attr-defined]
        assert manager._backend.removeContainer.await_count == 2  # type: ignore[attr-defined]

    async def test_handlesBackendListFailure(self, tmp_path: Path) -> None:
        """recover records an error when listing managed containers fails."""
        config = _makeConfig(rootDir=str(tmp_path / "sandbox"))
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        manager._backend.listManagedContainers = AsyncMock(  # type: ignore[attr-defined]
            side_effect=RuntimeError("Docker unavailable"),
        )

        result = await manager.recover()
        assert any("Failed to list managed containers" in e for e in result.errors)


# ---------------------------------------------------------------------------
# collectOrphanContainers (via GarbageCollector)
# ---------------------------------------------------------------------------


class TestCollectOrphanContainers:
    """Tests for GarbageCollector.collectOrphanContainers."""

    async def test_returnsZeroWithoutBackend(self, tmp_path: Path) -> None:
        """collectOrphanContainers returns 0 when no backend is provided."""
        from lib.sandbox.metadata.filesystem import FilesystemMetadataStore

        rootDir = tmp_path / "sandbox"
        rootDir.mkdir()
        (rootDir / "tmp").mkdir()
        metadataStore = FilesystemMetadataStore(rootDir=rootDir, tmpDir=rootDir / "tmp")
        gc = GarbageCollector(
            config=GcConfig(enabled=True),
            metadataStore=metadataStore,
            rootDir=rootDir,
            backend=None,
        )
        result = await gc.collectOrphanContainers()
        assert result == 0

    async def test_removesOrphanContainers(self, tmp_path: Path) -> None:
        """collectOrphanContainers removes containers older than retention."""
        from lib.sandbox.metadata.filesystem import FilesystemMetadataStore

        rootDir = tmp_path / "sandbox"
        rootDir.mkdir()
        (rootDir / "tmp").mkdir()
        metadataStore = FilesystemMetadataStore(rootDir=rootDir, tmpDir=rootDir / "tmp")

        mockBackend = MagicMock()
        containers = [
            ManagedContainerInfo(
                containerId="old-container",
                name="sandbox-old",
                labels={"sandbox.managed": "true"},
                status="exited",
                createdAt="2020-01-01T00:00:00Z",
            ),
        ]
        mockBackend.listManagedContainers = AsyncMock(return_value=containers)
        mockBackend.killContainer = AsyncMock()
        mockBackend.removeContainer = AsyncMock()

        gc = GarbageCollector(
            config=GcConfig(enabled=True, orphanContainerRetentionMinutes=10),
            metadataStore=metadataStore,
            rootDir=rootDir,
            backend=mockBackend,
        )
        result = await gc.collectOrphanContainers()
        assert result == 1
        mockBackend.killContainer.assert_awaited_once_with("old-container")
        mockBackend.removeContainer.assert_awaited_once_with("old-container", force=True)

    async def test_skipsYoungContainers(self, tmp_path: Path) -> None:
        """collectOrphanContainers skips containers younger than retention."""
        from lib.sandbox.metadata.filesystem import FilesystemMetadataStore

        rootDir = tmp_path / "sandbox"
        rootDir.mkdir()
        (rootDir / "tmp").mkdir()
        metadataStore = FilesystemMetadataStore(rootDir=rootDir, tmpDir=rootDir / "tmp")

        mockBackend = MagicMock()
        # Container created just now — within retention period
        recentTime = datetime.now(timezone.utc).isoformat()
        containers = [
            ManagedContainerInfo(
                containerId="young-container",
                name="sandbox-young",
                labels={"sandbox.managed": "true"},
                status="running",
                createdAt=recentTime,
            ),
        ]
        mockBackend.listManagedContainers = AsyncMock(return_value=containers)
        mockBackend.killContainer = AsyncMock()
        mockBackend.removeContainer = AsyncMock()

        gc = GarbageCollector(
            config=GcConfig(enabled=True, orphanContainerRetentionMinutes=10),
            metadataStore=metadataStore,
            rootDir=rootDir,
            backend=mockBackend,
        )
        result = await gc.collectOrphanContainers()
        assert result == 0
        mockBackend.killContainer.assert_not_awaited()

    async def test_handlesBackendListFailure(self, tmp_path: Path) -> None:
        """collectOrphanContainers returns 0 when listing containers fails."""
        from lib.sandbox.metadata.filesystem import FilesystemMetadataStore

        rootDir = tmp_path / "sandbox"
        rootDir.mkdir()
        (rootDir / "tmp").mkdir()
        metadataStore = FilesystemMetadataStore(rootDir=rootDir, tmpDir=rootDir / "tmp")

        mockBackend = MagicMock()
        mockBackend.listManagedContainers = AsyncMock(side_effect=RuntimeError("Docker down"))

        gc = GarbageCollector(
            config=GcConfig(enabled=True),
            metadataStore=metadataStore,
            rootDir=rootDir,
            backend=mockBackend,
        )
        result = await gc.collectOrphanContainers()
        assert result == 0
