"""Tests for SandboxManager session lifecycle methods (lib.sandbox.manager).

Covers:
- createSession creates a session; getSessionInfo returns it.
- createSession is idempotent (calling twice returns the same session).
- createSession with forceRecreate=True drops and recreates.
- getSessionInfo for unknown ID returns None.
- getSessionUsage returns file count and size.
- getSessionUsage for unknown ID raises SessionNotFound.
- touchSession bumps updatedAt and expiresAt.
- touchSession for unknown ID raises SessionNotFound.
- listSessions returns created sessions.
- dropSession deletes session and workspace.
- Drop + recreate cycle works.
"""

import asyncio
from pathlib import Path

import pytest

from lib.sandbox.config import ConcurrencyConfig, SandboxConfig, StorageConfig
from lib.sandbox.enums import RuntimeName
from lib.sandbox.errors import SessionNotFound
from lib.sandbox.manager import SandboxManager
from lib.sandbox.types import DropSessionResult, SessionInfo, SessionUsage

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


def _makeConfig(tmp_path: Path) -> SandboxConfig:
    """Create a SandboxConfig pointing at a temp directory.

    Args:
        tmp_path: Temporary directory path for storage.

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
    )


@pytest.fixture
def manager(tmp_path: Path) -> SandboxManager:
    """Create a fresh SandboxManager with a temp storage directory.

    Args:
        tmp_path: Pytest-provided temporary directory.

    Returns:
        A SandboxManager instance.
    """
    config = _makeConfig(tmp_path)
    SandboxManager.injectConfig(config)
    return SandboxManager.getInstance()


# ---------------------------------------------------------------------------
# createSession tests
# ---------------------------------------------------------------------------


class TestCreateSession:
    """Tests for SandboxManager.createSession."""

    async def test_createSessionReturnsSessionInfo(self, manager: SandboxManager) -> None:
        """Creating a session returns a valid SessionInfo."""
        info = await manager.createSession("sess-1")
        assert isinstance(info, SessionInfo)
        assert info.sessionId == "sess-1"
        assert info.runtime == RuntimeName.PYTHON
        assert info.workspacePath != ""
        assert info.createdAt is not None
        assert info.updatedAt is not None
        assert info.expiresAt is not None

    async def test_createSessionCreatesWorkspaceDir(self, manager: SandboxManager) -> None:
        """Creating a session creates the workspace directory on disk."""
        info = await manager.createSession("sess-1")
        workspacePath = Path(info.workspacePath)
        assert workspacePath.exists()
        assert workspacePath.is_dir()

    async def test_createSessionIsIdempotent(self, manager: SandboxManager) -> None:
        """Calling createSession twice with the same ID returns the same session."""
        first = await manager.createSession("sess-1")
        second = await manager.createSession("sess-1")
        assert first.sessionId == second.sessionId
        assert first.workspacePath == second.workspacePath
        assert first.createdAt == second.createdAt

    async def test_createSessionWithForceRecreate(self, manager: SandboxManager) -> None:
        """createSession with forceRecreate=True drops and recreates the session."""
        first = await manager.createSession("sess-1")
        second = await manager.createSession("sess-1", forceRecreate=True)
        assert first.sessionId == second.sessionId
        # The workspace path changes because the hash is the same but the
        # timestamps differ — verify the session was actually recreated.
        assert second.createdAt > first.createdAt

    async def test_createSessionWithMetadata(self, manager: SandboxManager) -> None:
        """Creating a session with metadata stores it on the SessionInfo."""
        info = await manager.createSession("sess-1", metadata={"env": "test", "owner": "alice"})
        assert info.metadata == {"env": "test", "owner": "alice"}

    async def test_createSessionWithCustomTtl(self, manager: SandboxManager) -> None:
        """Creating a session with a custom TTL sets expiresAt accordingly."""
        info = await manager.createSession("sess-1", ttlMinutes=60)
        # expiresAt should be roughly createdAt + 60 minutes
        delta = info.expiresAt - info.createdAt
        # Allow a small tolerance for test execution time
        assert 59 * 60 <= delta.total_seconds() <= 61 * 60

    async def test_createSessionPersistsMetadata(self, manager: SandboxManager) -> None:
        """Creating a session persists it so getSessionInfo can retrieve it."""
        await manager.createSession("sess-1")
        loaded = await manager.getSessionInfo("sess-1")
        assert loaded is not None
        assert loaded.sessionId == "sess-1"


# ---------------------------------------------------------------------------
# getSessionInfo tests
# ---------------------------------------------------------------------------


class TestGetSessionInfo:
    """Tests for SandboxManager.getSessionInfo."""

    async def test_getSessionInfoReturnsSession(self, manager: SandboxManager) -> None:
        """getSessionInfo returns the SessionInfo for an existing session."""
        created = await manager.createSession("sess-1")
        loaded = await manager.getSessionInfo("sess-1")
        assert loaded is not None
        assert loaded.sessionId == created.sessionId
        assert loaded.workspacePath == created.workspacePath

    async def test_getSessionInfoReturnsNoneForUnknown(self, manager: SandboxManager) -> None:
        """getSessionInfo returns None for a non-existent session."""
        result = await manager.getSessionInfo("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# getSessionUsage tests
# ---------------------------------------------------------------------------


class TestGetSessionUsage:
    """Tests for SandboxManager.getSessionUsage."""

    async def test_getSessionUsageEmptyWorkspace(self, manager: SandboxManager) -> None:
        """getSessionUsage returns zero counts for an empty workspace."""
        await manager.createSession("sess-1")
        usage = await manager.getSessionUsage("sess-1")
        assert isinstance(usage, SessionUsage)
        assert usage.sessionId == "sess-1"
        assert usage.fileCount == 0
        assert usage.totalBytes == 0
        assert usage.runCount == 0

    async def test_getSessionUsageWithFiles(self, manager: SandboxManager) -> None:
        """getSessionUsage counts files and sizes in the workspace."""
        info = await manager.createSession("sess-1")
        workspacePath = Path(info.workspacePath)

        # Write some files into the workspace
        (workspacePath / "file1.txt").write_text("hello world")
        (workspacePath / "file2.txt").write_text("foo")

        usage = await manager.getSessionUsage("sess-1")
        assert usage.fileCount == 2
        assert usage.totalBytes > 0

    async def test_getSessionUsageRaisesForUnknown(self, manager: SandboxManager) -> None:
        """getSessionUsage raises SessionNotFound for a non-existent session."""
        with pytest.raises(SessionNotFound):
            await manager.getSessionUsage("nonexistent")


# ---------------------------------------------------------------------------
# listSessions tests
# ---------------------------------------------------------------------------


class TestListSessions:
    """Tests for SandboxManager.listSessions."""

    async def test_listSessionsEmpty(self, manager: SandboxManager) -> None:
        """listSessions returns an empty list when no sessions exist."""
        sessions = await manager.listSessions()
        assert sessions == []

    async def test_listSessionsReturnsCreated(self, manager: SandboxManager) -> None:
        """listSessions returns all created sessions."""
        await manager.createSession("sess-1")
        await manager.createSession("sess-2")
        sessions = await manager.listSessions()
        ids = {s.sessionId for s in sessions}
        assert ids == {"sess-1", "sess-2"}

    async def test_listSessionsFilterByRuntime(self, manager: SandboxManager) -> None:
        """listSessions filters by runtime when provided."""
        await manager.createSession("sess-1", runtime=RuntimeName.PYTHON)
        sessions = await manager.listSessions(runtime=RuntimeName.PYTHON)
        assert len(sessions) == 1
        assert sessions[0].sessionId == "sess-1"

        sessions = await manager.listSessions(runtime=RuntimeName.PYTHON)
        assert len(sessions) >= 1


# ---------------------------------------------------------------------------
# touchSession tests
# ---------------------------------------------------------------------------


class TestTouchSession:
    """Tests for SandboxManager.touchSession."""

    async def test_touchSessionBumpsTimestamps(self, manager: SandboxManager) -> None:
        """touchSession updates updatedAt and extends expiresAt."""
        info = await manager.createSession("sess-1")
        originalUpdatedAt = info.updatedAt
        originalExpiresAt = info.expiresAt

        # Small delay to ensure timestamps differ
        await asyncio.sleep(0.01)

        touched = await manager.touchSession("sess-1")
        assert touched.updatedAt > originalUpdatedAt
        assert touched.expiresAt > originalExpiresAt

    async def test_touchSessionWithCustomTtl(self, manager: SandboxManager) -> None:
        """touchSession with ttlMinutes extends expiresAt by that amount."""
        await manager.createSession("sess-1")
        touched = await manager.touchSession("sess-1", ttlMinutes=120)
        delta = touched.expiresAt - touched.updatedAt
        # Allow small tolerance
        assert 119 * 60 <= delta.total_seconds() <= 121 * 60

    async def test_touchSessionRaisesForUnknown(self, manager: SandboxManager) -> None:
        """touchSession raises SessionNotFound for a non-existent session."""
        with pytest.raises(SessionNotFound):
            await manager.touchSession("nonexistent")


# ---------------------------------------------------------------------------
# dropSession tests
# ---------------------------------------------------------------------------


class TestDropSession:
    """Tests for SandboxManager.dropSession."""

    async def test_dropSessionDeletesSession(self, manager: SandboxManager) -> None:
        """dropSession removes the session so getSessionInfo returns None."""
        await manager.createSession("sess-1")
        result = await manager.dropSession("sess-1")
        assert isinstance(result, DropSessionResult)
        assert result.existed is True
        assert result.sessionId == "sess-1"

        # Session should no longer exist
        info = await manager.getSessionInfo("sess-1")
        assert info is None

    async def test_dropSessionDeletesWorkspace(self, manager: SandboxManager) -> None:
        """dropSession removes the workspace directory from disk."""
        info = await manager.createSession("sess-1")
        workspacePath = Path(info.workspacePath)
        assert workspacePath.exists()

        await manager.dropSession("sess-1")
        assert not workspacePath.exists()

    async def test_dropSessionNonExistent(self, manager: SandboxManager) -> None:
        """dropSession for a non-existent session returns existed=False."""
        result = await manager.dropSession("nonexistent")
        assert result.existed is False
        assert result.sessionId == "nonexistent"

    async def test_dropAndRecreateCycle(self, manager: SandboxManager) -> None:
        """A session can be recreated after being dropped."""
        first = await manager.createSession("sess-1")
        await manager.dropSession("sess-1")
        second = await manager.createSession("sess-1")
        assert second.sessionId == "sess-1"
        # The recreated session should have a different createdAt
        assert second.createdAt > first.createdAt

    async def test_dropSessionForce(self, manager: SandboxManager) -> None:
        """dropSession with force=True force-cancels waiters."""
        await manager.createSession("sess-1")
        result = await manager.dropSession("sess-1", force=True)
        assert result.existed is True

        # Session should no longer exist
        info = await manager.getSessionInfo("sess-1")
        assert info is None
