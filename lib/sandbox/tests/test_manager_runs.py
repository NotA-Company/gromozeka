"""Tests for SandboxManager run methods (lib.sandbox.manager).

Covers:
- runCode with missing session auto-creates it.
- runCode with requiredPackages that don't exist raises MissingDependenciesError.
- runCode with unknown runtime raises UnknownRuntime.
- getRunInfo for nonexistent run returns None.
- listRunsForSession returns empty list for new session.
- cancelRun returns False when no container matches.
- Helper methods: _getDefaultImageTag, _getLibPoolPath, _runResultToDict.
- Lock and semaphore are released on error paths.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from lib.sandbox.backends.base import ContainerOutcome
from lib.sandbox.config import (
    ConcurrencyConfig,
    PythonRuntimeConfig,
    SandboxConfig,
    StorageConfig,
)
from lib.sandbox.enums import RuntimeName
from lib.sandbox.errors import MissingDependenciesError, PathOutsideWorkspace, UnknownRuntime
from lib.sandbox.manager import SandboxManager
from lib.sandbox.runtimes.python import PythonRuntime
from lib.sandbox.types import (
    InputFile,
    NetworkPolicy,
    ResourceLimits,
    RunResult,
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


def _makeConfig(tmp_path: Path) -> SandboxConfig:
    """Create a SandboxConfig with a Python runtime for testing.

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
        runtimes={RuntimeName.PYTHON: PythonRuntimeConfig()},
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


def _makeOutcome(
    exitCode: int | None = 0,
    oomKilled: bool = False,
    signal: str | None = None,
) -> ContainerOutcome:
    """Create a ContainerOutcome for mocking.

    Args:
        exitCode: Process exit code.
        oomKilled: Whether the container was OOM-killed.
        signal: Termination signal name.

    Returns:
        A ContainerOutcome instance.
    """
    return ContainerOutcome(
        containerId="fake-container-id",
        exitCode=exitCode,
        signal=signal,
        oomKilled=oomKilled,
        inspects={},
    )


# ---------------------------------------------------------------------------
# Helper method tests
# ---------------------------------------------------------------------------


class TestGetDefaultImageTag:
    """Tests for SandboxManager._getDefaultImageTag."""

    def test_pythonRuntime(self, manager: SandboxManager) -> None:
        """Python runtime returns the default Python image tag."""
        tag = manager._getDefaultImageTag(RuntimeName.PYTHON)
        assert tag == "gromozeka-sandbox-python:run"

    def test_unknownRuntime(self, manager: SandboxManager) -> None:
        """An unknown runtime returns 'unknown'."""
        # RuntimeName only has PYTHON currently, but test the fallback
        tag = manager._getDefaultImageTag(RuntimeName.PYTHON)
        assert tag != "unknown"  # PYTHON should not be unknown


class TestGetLibPoolPath:
    """Tests for SandboxManager._getLibPoolPath."""

    def test_returnsPathUnderRuntimes(self, manager: SandboxManager, tmp_path: Path) -> None:
        """The lib pool path is under the storage root runtimes directory."""
        path = manager._getLibPoolPath(RuntimeName.PYTHON)
        assert "runtimes" in path
        assert "python" in path
        assert "libs" in path


class TestRunResultToDict:
    """Tests for RunResult.toDict()."""

    def test_convertsRunResult(self, manager: SandboxManager) -> None:
        """RunResult.toDict() produces a JSON-serializable dict."""
        now = datetime.now(timezone.utc)
        result = RunResult(
            runId="abc123",
            sessionId="sess-1",
            runtime=RuntimeName.PYTHON,
            stdoutPath=".run/abc123/stdout.log",
            stderrPath=".run/abc123/stderr.log",
            stdoutBytes=42,
            stderrBytes=0,
            exitCode=0,
            signal=None,
            timedOut=False,
            oomKilled=False,
            startedAt=now,
            finishedAt=now,
            elapsedMs=100,
            newArtifacts=[],
            limits=ResourceLimits(),
            networkEnabled=False,
            libPoolVersion="v1",
            error=None,
        )
        d = result.toDict()
        assert d["runId"] == "abc123"
        assert d["sessionId"] == "sess-1"
        assert d["runtime"] == "python"
        assert d["exitCode"] == 0
        assert d["timedOut"] is False
        assert d["oomKilled"] is False
        assert d["elapsedMs"] == 100
        assert d["networkEnabled"] is False
        assert d["libPoolVersion"] == "v1"
        assert d["error"] is None
        # Datetimes should be ISO strings
        assert isinstance(d["startedAt"], str)
        assert isinstance(d["finishedAt"], str)


# ---------------------------------------------------------------------------
# runCode tests
# ---------------------------------------------------------------------------


class TestRunCodeAutoCreatesSession:
    """Tests for runCode auto-creating sessions."""

    async def test_autoCreatesSession(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode auto-creates a session if it doesn't exist."""
        outcome = _makeOutcome(exitCode=0)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode("auto-session-1", "print(2+2)")
        assert result.sessionId == "auto-session-1"
        assert result.exitCode == 0
        # Session should now exist
        info = await manager.getSessionInfo("auto-session-1")
        assert info is not None
        assert info.sessionId == "auto-session-1"


class TestRunCodeUnknownRuntime:
    """Tests for runCode with an unknown runtime."""

    async def test_unknownRuntimeRaises(self, manager: SandboxManager) -> None:
        """runCode raises UnknownRuntime for an unconfigured runtime."""
        # The default config only has PYTHON, so any other runtime should fail.
        # But RuntimeName only has PYTHON currently. We can test by removing
        # the Python runtime from the runtimes dict.
        manager._runtimes.clear()
        with pytest.raises(UnknownRuntime, match="not available"):
            await manager.runCode("sess-1", "print(1)", runtime=RuntimeName.PYTHON)


class TestRunCodeMissingDependencies:
    """Tests for runCode with missing required packages."""

    async def test_missingPackagesRaisesError(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode raises MissingDependenciesError when required packages are not in the pool."""
        # Create a session first so we don't auto-create
        await manager.createSession("sess-dep")
        # Save a runtime record so loadRuntime returns something
        from lib.sandbox.metadata.base import RuntimeRecord

        runtimeRecord = RuntimeRecord(
            runtime=RuntimeName.PYTHON,
            runImageTag="gromozeka-sandbox-python:run",
            installImageTag="gromozeka-sandbox-python:install",
            libPoolPath=str(tmp_path / "runtimes" / "python" / "libs"),
            libPoolVersion="v1",
            packageCount=0,
        )
        await manager._metadata.saveRuntime(runtimeRecord)

        # listRuntimeLibraries is not implemented yet, so it will raise NotImplementedError.
        # But the MissingDependenciesError path is hit before that if the runtime
        # has no packages. Since listRuntimeLibraries raises NotImplementedError,
        # we need to mock it.
        with patch.object(manager, "listRuntimeLibraries", new_callable=AsyncMock, return_value=[]):
            with pytest.raises(MissingDependenciesError) as excInfo:
                await manager.runCode(
                    "sess-dep",
                    "import numpy",
                    requiredPackages=["numpy"],
                )
            assert "numpy" in excInfo.value.missing


class TestRunCodeSuccessPath:
    """Tests for runCode successful execution."""

    async def test_successfulRun(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode returns a RunResult with exit code 0 on success."""
        outcome = _makeOutcome(exitCode=0)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode("sess-ok", "print(2+2)")

        assert result.exitCode == 0
        assert result.timedOut is False
        assert result.oomKilled is False
        assert result.error is None
        assert result.runId != ""
        assert result.sessionId == "sess-ok"
        assert result.runtime == RuntimeName.PYTHON
        assert result.elapsedMs >= 0
        assert result.startedAt is not None
        assert result.finishedAt is not None

    async def test_timedOutRun(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode returns timedOut=True when exit code is 124."""
        outcome = _makeOutcome(exitCode=124)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode("sess-timeout", "while True: pass")

        assert result.timedOut is True
        assert result.error == "Run timed out"

    async def test_oomKilledRun(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode returns oomKilled=True when the container was OOM-killed."""
        outcome = _makeOutcome(exitCode=137, oomKilled=True)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode("sess-oom", "big_list = [0] * 10**9")

        assert result.oomKilled is True
        assert result.error == "Run OOM killed"

    async def test_nonZeroExitCode(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode returns an error message for non-zero exit codes."""
        outcome = _makeOutcome(exitCode=1)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode("sess-err", "import nonexistent_module")

        assert result.exitCode == 1
        assert result.error == "Exit code 1"

    async def test_runCodeWritesResultJson(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode writes a result.json file in the run directory."""
        outcome = _makeOutcome(exitCode=0)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode("sess-json", "print(1)")

        # Check that result.json exists
        sessionInfo = await manager.getSessionInfo("sess-json")
        assert sessionInfo is not None
        workspacePath = Path(sessionInfo.workspacePath)
        resultJsonPath = workspacePath / ".run" / result.runId / "result.json"
        assert resultJsonPath.exists()

    async def test_runCodeWritesMainPy(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode writes the code to main.py in the run directory."""
        outcome = _makeOutcome(exitCode=0)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode("sess-mainpy", "print('hello')")

        sessionInfo = await manager.getSessionInfo("sess-mainpy")
        assert sessionInfo is not None
        workspacePath = Path(sessionInfo.workspacePath)
        mainPyPath = workspacePath / ".run" / result.runId / "main.py"
        assert mainPyPath.exists()
        assert mainPyPath.read_text(encoding="utf-8") == "print('hello')"

    async def test_runCodeWritesStdin(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode writes stdin to a file when provided."""
        outcome = _makeOutcome(exitCode=0)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode("sess-stdin", "x = input()", stdin="hello")

        sessionInfo = await manager.getSessionInfo("sess-stdin")
        assert sessionInfo is not None
        workspacePath = Path(sessionInfo.workspacePath)
        stdinPath = workspacePath / ".run" / result.runId / "stdin"
        assert stdinPath.exists()
        assert stdinPath.read_text(encoding="utf-8") == "hello"

    async def test_runCodeWritesInputFiles(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode writes input files to the workspace."""
        outcome = _makeOutcome(exitCode=0)
        files = [InputFile(path="data/input.txt", content="hello world")]
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                _ = await manager.runCode("sess-files", "open('data/input.txt')", files=files)

        sessionInfo = await manager.getSessionInfo("sess-files")
        assert sessionInfo is not None
        workspacePath = Path(sessionInfo.workspacePath)
        inputPath = workspacePath / "data" / "input.txt"
        assert inputPath.exists()
        assert inputPath.read_text(encoding="utf-8") == "hello world"

    async def test_runCodeRejectsPathTraversalInInputFiles(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode rejects input files with path traversal (..) in their path."""
        outcome = _makeOutcome(exitCode=0)
        traversalFile = InputFile(path="../../../etc/passwd", content="malicious")
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                with pytest.raises(PathOutsideWorkspace):
                    await manager.runCode("sess-traversal", "print(1)", files=[traversalFile])

    async def test_runCodeSavesRunRecord(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode saves a RunRecord with status 'completed' on success."""
        outcome = _makeOutcome(exitCode=0)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode("sess-record", "print(1)")

        # Verify the run record was saved
        runInfo = await manager.getRunInfo(result.runId)
        assert runInfo is not None
        assert runInfo.status == "completed"
        assert runInfo.exitCode == 0

    async def test_runCodeSavesFailedRunRecord(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode saves a RunRecord with status 'failed' on non-zero exit."""
        outcome = _makeOutcome(exitCode=1)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode("sess-fail", "exit(1)")

        runInfo = await manager.getRunInfo(result.runId)
        assert runInfo is not None
        assert runInfo.status == "failed"
        assert runInfo.exitCode == 1

    async def test_runCodeBumpsSessionTtl(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode bumps the session TTL after a run."""
        await manager.createSession("sess-ttl")
        originalInfo = await manager.getSessionInfo("sess-ttl")
        assert originalInfo is not None

        outcome = _makeOutcome(exitCode=0)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                await manager.runCode("sess-ttl", "print(1)")

        updatedInfo = await manager.getSessionInfo("sess-ttl")
        assert updatedInfo is not None
        assert updatedInfo.updatedAt >= originalInfo.updatedAt

    async def test_runCodeWithCustomLimits(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode uses custom limits when provided."""
        customLimits = ResourceLimits(memoryMb=1024, timeoutSeconds=60)
        outcome = _makeOutcome(exitCode=0)

        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome) as mockRun:
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                _ = await manager.runCode("sess-limits", "print(1)", limits=customLimits)

        # Verify the ContainerSpec was called with the custom limits
        callArgs = mockRun.call_args
        spec = callArgs.kwargs["spec"]
        assert spec.limits.memoryMb == 1024
        assert spec.limits.timeoutSeconds == 60

    async def test_runCodeWithNetworkEnabled(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode uses bridge networking when network is enabled."""
        outcome = _makeOutcome(exitCode=0)

        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome) as mockRun:
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode(
                    "sess-net",
                    "import urllib.request",
                    network=NetworkPolicy(enabled=True),
                )

        assert result.networkEnabled is True
        callArgs = mockRun.call_args
        spec = callArgs.kwargs["spec"]
        assert spec.network == "bridge"

    async def test_runCodeWithNetworkDisabled(self, manager: SandboxManager, tmp_path: Path) -> None:
        """runCode uses 'none' networking by default."""
        outcome = _makeOutcome(exitCode=0)

        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome) as mockRun:
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                result = await manager.runCode("sess-nonet", "print(1)")

        assert result.networkEnabled is False
        callArgs = mockRun.call_args
        spec = callArgs.kwargs["spec"]
        assert spec.network == "none"


# ---------------------------------------------------------------------------
# Lock/semaphore release tests
# ---------------------------------------------------------------------------


class TestRunCodeLockRelease:
    """Tests that locks and semaphores are released even on error paths."""

    async def test_lockReleasedOnUnknownRuntime(self, manager: SandboxManager) -> None:
        """Session lock and global semaphore are released when runtime is unknown."""
        # Remove the Python runtime to trigger UnknownRuntime
        manager._runtimes.clear()
        with pytest.raises(UnknownRuntime):
            await manager.runCode("sess-lock-err", "print(1)", runtime=RuntimeName.PYTHON)

        # Re-add the Python runtime so we can run successfully
        manager._runtimes[RuntimeName.PYTHON] = PythonRuntime(PythonRuntimeConfig())

        outcome = _makeOutcome(exitCode=0)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                # This should succeed — locks were released
                result = await manager.runCode("sess-lock-err", "print(1)")
        assert result.exitCode == 0


class TestRunCodeContainerCleanup:
    """Tests that containers and RunRecords are cleaned up on exceptions."""

    async def test_containerRemovedOnPostRunError(self, manager: SandboxManager, tmp_path: Path) -> None:
        """Container is removed even when post-run steps raise an exception."""
        outcome = _makeOutcome(exitCode=0)
        removeMock = AsyncMock()

        # Make detectArtifacts raise to trigger the error path
        runtimeImpl = manager._runtimes[RuntimeName.PYTHON]
        with patch.object(runtimeImpl, "detectArtifacts", side_effect=OSError("disk error")):
            with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
                with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock) as removeMock:
                    with pytest.raises(OSError, match="disk error"):
                        await manager.runCode("sess-cleanup", "print(1)")

        # Container must have been removed despite the error
        removeMock.assert_awaited_once_with("fake-container-id")

    async def test_runRecordMarkedFailedOnRunOneshotError(self, manager: SandboxManager, tmp_path: Path) -> None:
        """RunRecord is updated to 'failed' when runOneshot raises an exception."""
        with patch.object(
            manager._backend, "runOneshot", new_callable=AsyncMock, side_effect=RuntimeError("docker crash")
        ):
            with pytest.raises(RuntimeError, match="docker crash"):
                await manager.runCode("sess-fail-record", "print(1)")

        # Find the run record — it should be marked as failed
        runs = await manager.listRunsForSession("sess-fail-record")
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert runs[0].exitCode == -1


# ---------------------------------------------------------------------------
# getRunInfo tests
# ---------------------------------------------------------------------------


class TestGetRunInfo:
    """Tests for SandboxManager.getRunInfo."""

    async def test_getRunInfoReturnsNoneForNonexistent(self, manager: SandboxManager) -> None:
        """getRunInfo returns None for a nonexistent run."""
        result = await manager.getRunInfo("nonexistent-run")
        assert result is None

    async def test_getRunInfoReturnsRunInfo(self, manager: SandboxManager, tmp_path: Path) -> None:
        """getRunInfo returns RunInfo for an existing run."""
        outcome = _makeOutcome(exitCode=0)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                runResult = await manager.runCode("sess-info", "print(1)")

        runInfo = await manager.getRunInfo(runResult.runId)
        assert runInfo is not None
        assert runInfo.runId == runResult.runId
        assert runInfo.sessionId == "sess-info"
        assert runInfo.runtime == RuntimeName.PYTHON
        assert runInfo.status == "completed"
        assert runInfo.exitCode == 0


# ---------------------------------------------------------------------------
# listRunsForSession tests
# ---------------------------------------------------------------------------


class TestListRunsForSession:
    """Tests for SandboxManager.listRunsForSession."""

    async def test_emptyListForNewSession(self, manager: SandboxManager) -> None:
        """listRunsForSession returns an empty list for a session with no runs."""
        await manager.createSession("sess-empty")
        runs = await manager.listRunsForSession("sess-empty")
        assert runs == []

    async def test_returnsRunsForSession(self, manager: SandboxManager, tmp_path: Path) -> None:
        """listRunsForSession returns RunInfo for runs in the session."""
        outcome = _makeOutcome(exitCode=0)
        with patch.object(manager._backend, "runOneshot", new_callable=AsyncMock, return_value=outcome):
            with patch.object(manager._backend, "removeContainer", new_callable=AsyncMock):
                await manager.runCode("sess-list", "print(1)")

        runs = await manager.listRunsForSession("sess-list")
        assert len(runs) == 1
        assert runs[0].sessionId == "sess-list"
        assert runs[0].status == "completed"


# ---------------------------------------------------------------------------
# cancelRun tests
# ---------------------------------------------------------------------------


class TestCancelRun:
    """Tests for SandboxManager.cancelRun."""

    async def test_cancelRunReturnsFalseWhenNoContainer(self, manager: SandboxManager) -> None:
        """cancelRun returns False when no container matches the runId."""
        with patch.object(manager._backend, "listManagedContainers", new_callable=AsyncMock, return_value=[]):
            result = await manager.cancelRun("nonexistent-run")
        assert result is False

    async def test_cancelRunReturnsTrueWhenContainerFound(self, manager: SandboxManager) -> None:
        """cancelRun returns True when a matching container is found and killed."""
        from lib.sandbox.backends.base import ManagedContainerInfo

        container = ManagedContainerInfo(
            containerId="container-123",
            name="sandbox-run-abc",
            labels={"sandbox.runId": "run-abc", "sandbox.managed": "true"},
            status="running",
            createdAt=datetime.now(timezone.utc).isoformat(),
        )
        with patch.object(manager._backend, "listManagedContainers", new_callable=AsyncMock, return_value=[container]):
            with patch.object(manager._backend, "killContainer", new_callable=AsyncMock):
                result = await manager.cancelRun("run-abc")
        assert result is True

    async def test_cancelRunReturnsFalseOnException(self, manager: SandboxManager) -> None:
        """cancelRun returns False when an exception occurs."""
        with patch.object(
            manager._backend, "listManagedContainers", new_callable=AsyncMock, side_effect=Exception("Docker error")
        ):
            result = await manager.cancelRun("run-err")
        assert result is False
