"""Tests for sandbox garbage collection (lib.sandbox.gc).

Covers:
- Expired sessions are removed; non-expired sessions are kept.
- Orphan workspace directories are removed only when older than retention;
  recent orphans are kept.
- Expired run records and directories are removed; recent ones are kept.
- GC disabled returns a disabled message and removes nothing.
- Library pool directories are untouched by GC.
- Full cycle: mixed sessions, runs, orphans; GcResult counts are accurate.
- Empty GC: running on empty storage returns all zeros.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lib.sandbox.config import ConcurrencyConfig, GcConfig, SandboxConfig, StorageConfig
from lib.sandbox.enums import RuntimeName
from lib.sandbox.gc import GarbageCollector
from lib.sandbox.manager import SandboxManager
from lib.sandbox.metadata.base import RunRecord, SessionRecord
from lib.sandbox.metadata.filesystem import FilesystemMetadataStore
from lib.sandbox.storage import sessionHash
from lib.sandbox.types import GcResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeConfig(
    tmp_path: Path,
    *,
    gcEnabled: bool = True,
    runRetentionMinutes: int = 1440,
    orphanWorkspaceRetentionMinutes: int = 60,
) -> SandboxConfig:
    """Create a SandboxConfig pointing at a temp directory.

    Args:
        tmp_path: Temporary directory path for storage.
        gcEnabled: Whether GC is enabled.
        runRetentionMinutes: Retention period for completed runs.
        orphanWorkspaceRetentionMinutes: Retention period for orphan workspaces.

    Returns:
        A SandboxConfig with storage rooted at tmp_path.
    """
    return SandboxConfig(
        storage=StorageConfig(rootDir=str(tmp_path)),
        concurrency=ConcurrencyConfig(
            maxQueuedRunsPerSession=4,
            maxConcurrentRunsGlobal=8,
            globalQueueWaitSeconds=60,
        ),
        gc=GcConfig(
            enabled=gcEnabled,
            intervalSeconds=60,
            runRetentionMinutes=runRetentionMinutes,
            orphanWorkspaceRetentionMinutes=orphanWorkspaceRetentionMinutes,
        ),
    )


def _makeSessionRecord(
    sessionId: str,
    workspacePath: str,
    *,
    expiresAt: datetime | None = None,
    createdAt: datetime | None = None,
) -> SessionRecord:
    """Create a SessionRecord for testing.

    Args:
        sessionId: The session identifier.
        workspacePath: Host-side path to the workspace directory.
        expiresAt: Expiration timestamp (defaults to 30 min from now).
        createdAt: Creation timestamp (defaults to now).

    Returns:
        A SessionRecord instance.
    """
    now = datetime.now(timezone.utc)
    return SessionRecord(
        sessionId=sessionId,
        sessionHash=sessionHash(sessionId),
        runtime=RuntimeName.PYTHON,
        workspacePath=workspacePath,
        createdAt=createdAt or now,
        updatedAt=now,
        expiresAt=expiresAt or (now + timedelta(minutes=30)),
        metadata={},
        schemaVersion=1,
    )


def _makeRunRecord(
    runId: str,
    sessionId: str,
    *,
    startedAt: datetime | None = None,
    finishedAt: datetime | None = None,
    status: str = "completed",
) -> RunRecord:
    """Create a RunRecord for testing.

    Args:
        runId: The run identifier.
        sessionId: The parent session identifier.
        startedAt: When the run started (defaults to now - 2 min).
        finishedAt: When the run finished (None = still running).
        status: Run status string.

    Returns:
        A RunRecord instance.
    """
    now = datetime.now(timezone.utc)
    return RunRecord(
        runId=runId,
        sessionId=sessionId,
        runtime=RuntimeName.PYTHON,
        startedAt=startedAt or (now - timedelta(minutes=2)),
        finishedAt=finishedAt,
        status=status,
        exitCode=0 if finishedAt is not None else None,
        schemaVersion=1,
    )


def _ageDir(directory: Path, ageMinutes: float) -> None:
    """Set a directory's mtime to be ageMinutes in the past.

    Args:
        directory: The directory to age.
        ageMinutes: How many minutes in the past to set the mtime.
    """
    oldTime = time.time() - (ageMinutes * 60)
    os.utime(directory, (oldTime, oldTime))


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


@pytest.fixture
def rootDir(tmp_path: Path) -> Path:
    """Create a sandbox root directory with the standard layout.

    Args:
        tmp_path: Pytest-provided temporary directory.

    Returns:
        The root directory path.
    """
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "sessions").mkdir()
    (root / "meta" / "sessions").mkdir(parents=True)
    (root / "meta" / "runs").mkdir(parents=True)
    (root / "meta" / "runtimes").mkdir(parents=True)
    (root / "tmp").mkdir()
    return root


@pytest.fixture
def metadataStore(rootDir: Path) -> FilesystemMetadataStore:
    """Create a FilesystemMetadataStore for testing.

    Args:
        rootDir: The sandbox root directory.

    Returns:
        A FilesystemMetadataStore instance.
    """
    return FilesystemMetadataStore(rootDir=rootDir, tmpDir=rootDir / "tmp")


@pytest.fixture
def gc(rootDir: Path, metadataStore: FilesystemMetadataStore) -> GarbageCollector:
    """Create a GarbageCollector for testing.

    Args:
        rootDir: The sandbox root directory.
        metadataStore: The metadata store.

    Returns:
        A GarbageCollector instance.
    """
    config = GcConfig(enabled=True, runRetentionMinutes=1440)
    return GarbageCollector(config=config, metadataStore=metadataStore, rootDir=rootDir)


# ---------------------------------------------------------------------------
# collectExpiredSessions
# ---------------------------------------------------------------------------


class TestCollectExpiredSessions:
    """Tests for GarbageCollector.collectExpiredSessions."""

    async def test_expiredSessionIsRemoved(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
        gc: GarbageCollector,
    ) -> None:
        """An expired session is removed from metadata and its hash directory is deleted."""
        now = datetime.now(timezone.utc)
        expiredAt = now - timedelta(minutes=5)
        sHash = sessionHash("expired-sess")
        workspacePath = rootDir / "sessions" / sHash / "workspace"
        workspacePath.mkdir(parents=True)

        record = _makeSessionRecord("expired-sess", str(workspacePath), expiresAt=expiredAt)
        await metadataStore.saveSession(record)

        removed = await gc.collectExpiredSessions()
        assert removed == 1

        # Metadata should be gone
        loaded = await metadataStore.loadSession("expired-sess")
        assert loaded is None

        # The entire sessions/<hash>/ parent directory should be gone
        hashDir = rootDir / "sessions" / sHash
        assert not hashDir.exists()

    async def test_nonExpiredSessionIsKept(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
        gc: GarbageCollector,
    ) -> None:
        """A session with a future expiresAt is not removed."""
        now = datetime.now(timezone.utc)
        futureExpiry = now + timedelta(hours=1)
        sHash = sessionHash("active-sess")
        workspacePath = rootDir / "sessions" / sHash / "workspace"
        workspacePath.mkdir(parents=True)

        record = _makeSessionRecord("active-sess", str(workspacePath), expiresAt=futureExpiry)
        await metadataStore.saveSession(record)

        removed = await gc.collectExpiredSessions()
        assert removed == 0

        # Metadata should still exist
        loaded = await metadataStore.loadSession("active-sess")
        assert loaded is not None

        # Workspace should still exist
        assert workspacePath.exists()

    async def test_multipleSessionsMixedExpiry(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
        gc: GarbageCollector,
    ) -> None:
        """Only expired sessions are removed; active ones remain."""
        now = datetime.now(timezone.utc)

        # Create two expired sessions
        for sid in ("expired-1", "expired-2"):
            sHash = sessionHash(sid)
            wp = rootDir / "sessions" / sHash / "workspace"
            wp.mkdir(parents=True)
            record = _makeSessionRecord(sid, str(wp), expiresAt=now - timedelta(minutes=1))
            await metadataStore.saveSession(record)

        # Create one active session
        sHash = sessionHash("active-1")
        wp = rootDir / "sessions" / sHash / "workspace"
        wp.mkdir(parents=True)
        record = _makeSessionRecord("active-1", str(wp), expiresAt=now + timedelta(hours=1))
        await metadataStore.saveSession(record)

        removed = await gc.collectExpiredSessions()
        assert removed == 2

        # Active session should remain
        assert await metadataStore.loadSession("active-1") is not None
        # Expired sessions should be gone
        assert await metadataStore.loadSession("expired-1") is None
        assert await metadataStore.loadSession("expired-2") is None
        # Expired session hash directories should be gone
        assert not (rootDir / "sessions" / sessionHash("expired-1")).exists()
        assert not (rootDir / "sessions" / sessionHash("expired-2")).exists()


# ---------------------------------------------------------------------------
# collectOrphanWorkspaces
# ---------------------------------------------------------------------------


class TestCollectOrphanWorkspaces:
    """Tests for GarbageCollector.collectOrphanWorkspaces."""

    async def test_oldOrphanWorkspaceIsRemoved(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
        gc: GarbageCollector,
    ) -> None:
        """An orphan workspace directory older than retention is removed."""
        orphanDir = rootDir / "sessions" / "deadbeef12345678"
        orphanDir.mkdir(parents=True)
        (orphanDir / "workspace").mkdir()
        # Age the directory beyond the 60-minute retention
        _ageDir(orphanDir, ageMinutes=120)

        removed = await gc.collectOrphanWorkspaces()
        assert removed == 1
        assert not orphanDir.exists()

    async def test_recentOrphanWorkspaceIsKept(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
        gc: GarbageCollector,
    ) -> None:
        """A recently-created orphan workspace is kept until it exceeds retention."""
        orphanDir = rootDir / "sessions" / "recentbeef1234567"
        orphanDir.mkdir(parents=True)
        (orphanDir / "workspace").mkdir()
        # The orphan was just created — within the 60-minute retention period

        removed = await gc.collectOrphanWorkspaces()
        assert removed == 0
        assert orphanDir.exists()

    async def test_nonOrphanWorkspaceIsKept(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
        gc: GarbageCollector,
    ) -> None:
        """A workspace directory with a matching metadata record is kept."""
        sHash = sessionHash("known-sess")
        workspacePath = rootDir / "sessions" / sHash / "workspace"
        workspacePath.mkdir(parents=True)

        record = _makeSessionRecord("known-sess", str(workspacePath))
        await metadataStore.saveSession(record)

        removed = await gc.collectOrphanWorkspaces()
        assert removed == 0
        assert workspacePath.exists()

    async def test_dotDirectoriesAreSkipped(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
        gc: GarbageCollector,
    ) -> None:
        """Directories starting with '.' are not treated as orphans."""
        dotDir = rootDir / "sessions" / ".hidden"
        dotDir.mkdir(parents=True)

        removed = await gc.collectOrphanWorkspaces()
        assert removed == 0
        assert dotDir.exists()

    async def test_noSessionsDirReturnsZero(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
        gc: GarbageCollector,
    ) -> None:
        """If the sessions/ directory doesn't exist, return 0."""
        import shutil

        sessionsDir = rootDir / "sessions"
        if sessionsDir.exists():
            shutil.rmtree(sessionsDir)

        removed = await gc.collectOrphanWorkspaces()
        assert removed == 0


# ---------------------------------------------------------------------------
# collectExpiredRuns
# ---------------------------------------------------------------------------


class TestCollectExpiredRuns:
    """Tests for GarbageCollector.collectExpiredRuns."""

    async def test_expiredRunIsRemoved(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
    ) -> None:
        """A run that finished beyond the retention period is removed."""
        # Use a very short retention (1 minute) so old runs are expired
        config = GcConfig(enabled=True, runRetentionMinutes=1)
        gc = GarbageCollector(config=config, metadataStore=metadataStore, rootDir=rootDir)

        now = datetime.now(timezone.utc)
        sHash = sessionHash("sess-with-run")
        workspacePath = rootDir / "sessions" / sHash / "workspace"
        workspacePath.mkdir(parents=True)

        sessionRecord = _makeSessionRecord("sess-with-run", str(workspacePath))
        await metadataStore.saveSession(sessionRecord)

        # Create a run that finished 2 hours ago (well beyond 1-min retention)
        finishedAt = now - timedelta(hours=2)
        runRecord = _makeRunRecord("run-old", "sess-with-run", finishedAt=finishedAt)
        await metadataStore.saveRun(runRecord)

        # Create the .run/<runId>/ directory
        runDir = workspacePath / ".run" / "run-old"
        runDir.mkdir(parents=True)

        removed = await gc.collectExpiredRuns()
        assert removed == 1

        # Run metadata should be gone
        loaded = await metadataStore.loadRun("run-old")
        assert loaded is None

        # Run directory should be gone
        assert not runDir.exists()

    async def test_recentRunIsKept(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
    ) -> None:
        """A run that finished within the retention period is kept."""
        # Use a long retention (1440 minutes = 1 day)
        config = GcConfig(enabled=True, runRetentionMinutes=1440)
        gc = GarbageCollector(config=config, metadataStore=metadataStore, rootDir=rootDir)

        now = datetime.now(timezone.utc)
        sHash = sessionHash("sess-recent")
        workspacePath = rootDir / "sessions" / sHash / "workspace"
        workspacePath.mkdir(parents=True)

        sessionRecord = _makeSessionRecord("sess-recent", str(workspacePath))
        await metadataStore.saveSession(sessionRecord)

        # Create a run that finished 5 minutes ago (within 1-day retention)
        finishedAt = now - timedelta(minutes=5)
        runRecord = _makeRunRecord("run-recent", "sess-recent", finishedAt=finishedAt)
        await metadataStore.saveRun(runRecord)

        removed = await gc.collectExpiredRuns()
        assert removed == 0

        # Run metadata should still exist
        loaded = await metadataStore.loadRun("run-recent")
        assert loaded is not None

    async def test_runningRunIsNotTouched(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
    ) -> None:
        """A run with finishedAt=None (still running) is not removed, even if old."""
        config = GcConfig(enabled=True, runRetentionMinutes=1)
        gc = GarbageCollector(config=config, metadataStore=metadataStore, rootDir=rootDir)

        sHash = sessionHash("sess-running")
        workspacePath = rootDir / "sessions" / sHash / "workspace"
        workspacePath.mkdir(parents=True)

        sessionRecord = _makeSessionRecord("sess-running", str(workspacePath))
        await metadataStore.saveSession(sessionRecord)

        # Create a running run (finishedAt=None)
        runRecord = _makeRunRecord("run-active", "sess-running", finishedAt=None, status="running")
        await metadataStore.saveRun(runRecord)

        removed = await gc.collectExpiredRuns()
        assert removed == 0

        loaded = await metadataStore.loadRun("run-active")
        assert loaded is not None


# ---------------------------------------------------------------------------
# collectOrphanContainers (stub)
# ---------------------------------------------------------------------------


class TestCollectOrphanContainers:
    """Tests for GarbageCollector.collectOrphanContainers (stub)."""

    async def test_stubReturnsZero(self, gc: GarbageCollector) -> None:
        """The container GC stub always returns 0."""
        result = await gc.collectOrphanContainers()
        assert result == 0


# ---------------------------------------------------------------------------
# collectAll
# ---------------------------------------------------------------------------


class TestCollectAll:
    """Tests for GarbageCollector.collectAll."""

    async def test_emptyGcReturnsZeros(self, gc: GarbageCollector) -> None:
        """Running GC on empty storage returns all zeros."""
        containers, sessions, runs, orphans, errors = await gc.collectAll()
        assert containers == 0
        assert sessions == 0
        assert runs == 0
        assert orphans == 0
        assert errors == []

    async def test_fullCycle(
        self,
        rootDir: Path,
        metadataStore: FilesystemMetadataStore,
    ) -> None:
        """Mixed sessions, runs, orphans; GcResult counts are accurate."""
        config = GcConfig(enabled=True, runRetentionMinutes=1, orphanWorkspaceRetentionMinutes=1)
        gc = GarbageCollector(config=config, metadataStore=metadataStore, rootDir=rootDir)

        now = datetime.now(timezone.utc)

        # 1. Expired session
        sHash1 = sessionHash("expired-sess")
        wp1 = rootDir / "sessions" / sHash1 / "workspace"
        wp1.mkdir(parents=True)
        expiredRecord = _makeSessionRecord("expired-sess", str(wp1), expiresAt=now - timedelta(minutes=5))
        await metadataStore.saveSession(expiredRecord)

        # 2. Active session with an expired run
        sHash2 = sessionHash("active-sess")
        wp2 = rootDir / "sessions" / sHash2 / "workspace"
        wp2.mkdir(parents=True)
        activeRecord = _makeSessionRecord("active-sess", str(wp2), expiresAt=now + timedelta(hours=1))
        await metadataStore.saveSession(activeRecord)

        # Expired run under active session
        runDir = wp2 / ".run" / "run-old"
        runDir.mkdir(parents=True)
        oldRun = _makeRunRecord("run-old", "active-sess", finishedAt=now - timedelta(hours=2))
        await metadataStore.saveRun(oldRun)

        # Recent run under active session (should be kept)
        recentRun = _makeRunRecord("run-recent", "active-sess", finishedAt=now - timedelta(seconds=10))
        await metadataStore.saveRun(recentRun)

        # 3. Orphan workspace (no metadata) — age it beyond retention
        orphanDir = rootDir / "sessions" / "cafebabe12345678"
        orphanDir.mkdir(parents=True)
        _ageDir(orphanDir, ageMinutes=5)

        containers, sessions, runs, orphans, errors = await gc.collectAll()

        assert containers == 0  # stub
        assert sessions == 1  # expired-sess
        assert runs == 1  # run-old
        # Only the explicit orphan — collectExpiredSessions removes the entire
        # hash directory so no leftover parent dir remains.
        assert orphans == 1
        assert errors == []

        # Verify active session still exists
        assert await metadataStore.loadSession("active-sess") is not None
        # Verify recent run still exists
        assert await metadataStore.loadRun("run-recent") is not None
        # Verify expired session is gone
        assert await metadataStore.loadSession("expired-sess") is None
        # Verify expired run is gone
        assert await metadataStore.loadRun("run-old") is None


# ---------------------------------------------------------------------------
# SandboxManager.collectGarbage integration
# ---------------------------------------------------------------------------


class TestSandboxManagerCollectGarbage:
    """Integration tests for SandboxManager.collectGarbage."""

    async def test_gcDisabledReturnsDisabledMessage(self, tmp_path: Path) -> None:
        """When gc.enabled=False, collectGarbage returns a disabled message and removes nothing."""
        config = _makeConfig(tmp_path, gcEnabled=False)
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        # Create a session that would normally be expired
        now = datetime.now(timezone.utc)
        sHash = sessionHash("should-survive")
        wp = Path(config.storage.rootDir) / "sessions" / sHash / "workspace"
        wp.mkdir(parents=True)

        record = _makeSessionRecord("should-survive", str(wp), expiresAt=now - timedelta(minutes=5))
        await manager._metadata.saveSession(record)

        result = await manager.collectGarbage()
        assert isinstance(result, GcResult)
        assert result.removedContainers == 0
        assert result.removedSessions == 0
        assert result.removedRuns == 0
        assert result.removedOrphans == 0
        assert result.errors == ["GC disabled by configuration"]

        # The expired session should still exist because GC was disabled
        loaded = await manager._metadata.loadSession("should-survive")
        assert loaded is not None

    async def test_gcEnabledRemovesExpiredSessions(self, tmp_path: Path) -> None:
        """When gc.enabled=True, collectGarbage removes expired sessions."""
        config = _makeConfig(tmp_path, gcEnabled=True)
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        now = datetime.now(timezone.utc)
        sHash = sessionHash("expired-sess")
        wp = Path(config.storage.rootDir) / "sessions" / sHash / "workspace"
        wp.mkdir(parents=True)

        record = _makeSessionRecord("expired-sess", str(wp), expiresAt=now - timedelta(minutes=5))
        await manager._metadata.saveSession(record)

        result = await manager.collectGarbage()
        assert result.removedSessions >= 1
        assert await manager._metadata.loadSession("expired-sess") is None

    async def test_libraryPoolUntouched(self, tmp_path: Path) -> None:
        """GC does not remove the library pool directory (runtimes/python/libs)."""
        config = _makeConfig(tmp_path, gcEnabled=True, orphanWorkspaceRetentionMinutes=1)
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        # Create a library pool directory structure
        rootDir = Path(config.storage.rootDir)
        poolDir = rootDir / "runtimes" / "python" / "libs"
        poolDir.mkdir(parents=True, exist_ok=True)
        (poolDir / "some_package").mkdir()
        (poolDir / "some_package" / "__init__.py").write_text("# lib")

        # Create an orphan workspace next to it — age it beyond retention
        orphanDir = rootDir / "sessions" / "deadbeef00000000"
        orphanDir.mkdir(parents=True)
        _ageDir(orphanDir, ageMinutes=5)

        result = await manager.collectGarbage()
        # Orphan should be removed
        assert result.removedOrphans >= 1

        # Library pool should be untouched
        assert poolDir.exists()
        assert (poolDir / "some_package" / "__init__.py").exists()
        # Orphan should be gone
        assert not orphanDir.exists()

    async def test_gcOnEmptyStorage(self, tmp_path: Path) -> None:
        """Running GC on empty storage returns all zeros."""
        config = _makeConfig(tmp_path, gcEnabled=True)
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()

        result = await manager.collectGarbage()
        assert result.removedContainers == 0
        assert result.removedSessions == 0
        assert result.removedRuns == 0
        assert result.removedOrphans == 0
        assert result.errors == []
