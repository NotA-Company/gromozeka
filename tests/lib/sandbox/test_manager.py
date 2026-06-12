"""Tests for SandboxManager (lib.sandbox.manager).

Covers:
- runCode() workDir behaviour: RunResult.workDir is set to the expected
  workspace-relative path format and the work/ directory is created on disk.
- RunResult.workDir default: the field defaults to empty string when not
  provided.

The DockerBackend is replaced with a mock so that no real Docker daemon is
required.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.sandbox.config import (
    BasicRuntimeConfig,
    InstallContainerConfig,
    SandboxConfig,
    StorageConfig,
)
from lib.sandbox.enums import RuntimeName
from lib.sandbox.manager import SandboxManager
from lib.sandbox.types import ContainerOutcome, RunResult

# ============================================================================
# Helpers
# ============================================================================


def _makeSandboxConfig(rootDir: str) -> SandboxConfig:
    """Create a minimal SandboxConfig for testing.

    Args:
        rootDir: Host-side root directory for sandbox storage.

    Returns:
        A SandboxConfig with a Python runtime and test-friendly defaults.
    """
    return SandboxConfig(
        storage=StorageConfig(rootDir=rootDir),
        runtimes={
            RuntimeName.PYTHON: BasicRuntimeConfig(
                runImageTag="test-python:run",
                installImageTag="test-python:install",
                runDockerfile="lib/sandbox/runtimes/python/Dockerfile",
                installDockerfile="lib/sandbox/runtimes/python/Dockerfile.install",
                libMountPath="/sandbox/libs/python",
                env={},
                installContainer=InstallContainerConfig(),
            )
        },
    )


def _makeContainerOutcome(*, exitCode: int = 0) -> ContainerOutcome:
    """Create a minimal ContainerOutcome for testing.

    Args:
        exitCode: Process exit code to return.

    Returns:
        A ContainerOutcome with the specified exit code.
    """
    return ContainerOutcome(
        containerId="fake-container-id",
        exitCode=exitCode,
        signal=None,
        oomKilled=False,
        inspects={},
    )


def _makeMockBackend(outcome: ContainerOutcome) -> MagicMock:
    """Create a mock backend that returns the given outcome from runOneshot.

    Args:
        outcome: The ContainerOutcome to return from runOneshot.

    Returns:
        A MagicMock configured as a DockerBackend replacement.
    """
    backend = MagicMock()
    backend.runOneshot = AsyncMock(return_value=outcome)
    backend.removeContainer = AsyncMock(return_value=None)
    backend.listManagedContainers = AsyncMock(return_value=[])
    backend.close = AsyncMock(return_value=None)
    backend.ensureImage = AsyncMock(return_value=None)
    backend.healthcheck = AsyncMock(return_value=MagicMock(ok=True, errors=[]))
    return backend


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _resetSandboxManagerSingleton():
    """Reset SandboxManager singleton before and after each test.

    Ensures each test gets a fresh SandboxManager instance.

    Yields:
        None
    """
    SandboxManager._instance = None
    SandboxManager._configInstance = None
    yield
    SandboxManager._instance = None
    SandboxManager._configInstance = None


# ============================================================================
# Tests — RunResult.workDir default
# ============================================================================


def testRunResultWorkDirDefaultsToEmptyString() -> None:
    """Verify that RunResult.workDir defaults to empty string.

    When a RunResult is constructed without explicitly providing workDir,
    the field must default to an empty string so that legacy serialisations
    (which lack the key) remain compatible.

    Returns:
        None
    """
    started = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2025, 6, 1, 12, 0, 1, tzinfo=timezone.utc)
    rr = RunResult(
        runId="run-default-workdir",
        sessionId="sess-001",
        runtime=RuntimeName.PYTHON,
        stdoutPath=".run/run-default-workdir/stdout.log",
        stderrPath=".run/run-default-workdir/stderr.log",
        stdoutBytes=0,
        stderrBytes=0,
        exitCode=0,
        signal=None,
        timedOut=False,
        oomKilled=False,
        startedAt=started,
        finishedAt=finished,
        elapsedMs=1000,
        networkEnabled=False,
        error=None,
    )
    assert rr.workDir == ""


# ============================================================================
# Tests — RunResult.workDir format
# ============================================================================


def testRunResultWorkDirFormatMatchesManagerOutput() -> None:
    """Verify that the workDir format matches what SandboxManager.runCode() produces.

    The manager constructs workDir as ``.run/{runId}/work``.  This test
    verifies that a RunResult with that format is well-formed and
    round-trips correctly through toDict/fromDict.

    Returns:
        None
    """
    runId = "abc-123-def"
    started = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2025, 6, 1, 12, 0, 2, tzinfo=timezone.utc)
    workDir = f".run/{runId}/work"
    rr = RunResult(
        runId=runId,
        sessionId="sess-001",
        workDir=workDir,
        runtime=RuntimeName.PYTHON,
        stdoutPath=f".run/{runId}/stdout.log",
        stderrPath=f".run/{runId}/stderr.log",
        stdoutBytes=10,
        stderrBytes=0,
        exitCode=0,
        signal=None,
        timedOut=False,
        oomKilled=False,
        startedAt=started,
        finishedAt=finished,
        elapsedMs=2000,
        networkEnabled=False,
        error=None,
    )
    assert rr.workDir == f".run/{runId}/work"
    # Round-trip through serialisation
    restored = RunResult.fromDict(rr.toDict())
    assert restored.workDir == f".run/{runId}/work"


# ============================================================================
# Tests — runCode() workDir integration (mocked backend)
# ============================================================================


async def testRunCodeSetsWorkDirAndCreatesDirectory(tmp_path: Path) -> None:
    """Verify that runCode() sets RunResult.workDir and creates the work/ directory.

    Replaces the DockerBackend with a mock so no real Docker daemon is
    needed.  After runCode() completes successfully, result.workDir must
    equal ``.run/{runId}/work`` and the directory must exist on disk inside
    the session workspace.

    Args:
        tmp_path: pytest-provided temporary directory.

    Returns:
        None
    """
    rootDir = str(tmp_path / "sandbox")
    config = _makeSandboxConfig(rootDir)
    SandboxManager.injectConfig(config)

    manager = SandboxManager.getInstance()

    # Replace the backend with a mock so no Docker calls are made.
    mockOutcome = _makeContainerOutcome(exitCode=0)
    manager._backend = _makeMockBackend(mockOutcome)

    # Mark the Python runtime as prepared so prepareRuntime() is skipped.
    manager._runtimes[RuntimeName.PYTHON].markPrepared()

    result = await manager.runCode(
        sessionId="test-session",
        code="print('hello')",
        runtime=RuntimeName.PYTHON,
    )

    # workDir must follow the expected format
    assert result.workDir == f".run/{result.runId}/work"

    # The work/ directory must actually exist on disk
    workspacePath = tmp_path / "sandbox" / "sessions"
    # Find the session workspace (there should be exactly one)
    sessionDirs = list(workspacePath.iterdir())
    assert len(sessionDirs) == 1
    workDirOnDisk = sessionDirs[0] / "workspace" / ".run" / result.runId / "work"
    assert workDirOnDisk.is_dir(), f"Expected work directory {workDirOnDisk} to exist"


async def testRunCodeWorkDirIsWorkspaceRelative(tmp_path: Path) -> None:
    """Verify that workDir is a workspace-relative path, not absolute.

    The workDir field must be relative to the session workspace root
    (e.g. ``.run/<runId>/work``), never an absolute filesystem path.

    Args:
        tmp_path: pytest-provided temporary directory.

    Returns:
        None
    """
    rootDir = str(tmp_path / "sandbox")
    config = _makeSandboxConfig(rootDir)
    SandboxManager.injectConfig(config)

    manager = SandboxManager.getInstance()
    mockOutcome = _makeContainerOutcome(exitCode=0)
    manager._backend = _makeMockBackend(mockOutcome)
    manager._runtimes[RuntimeName.PYTHON].markPrepared()

    result = await manager.runCode(
        sessionId="test-session-rel",
        code="pass",
        runtime=RuntimeName.PYTHON,
    )

    # workDir must not start with '/' (it's workspace-relative)
    assert not result.workDir.startswith("/"), f"workDir must be relative, got: {result.workDir}"
    # workDir must start with '.run/'
    assert result.workDir.startswith(".run/"), f"workDir must start with '.run/', got: {result.workDir}"
    # workDir must end with '/work'
    assert result.workDir.endswith("/work"), f"workDir must end with '/work', got: {result.workDir}"
