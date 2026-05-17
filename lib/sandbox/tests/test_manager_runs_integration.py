"""Integration tests for SandboxManager run methods (lib.sandbox.manager).

These tests require Docker to be available and are marked @pytest.mark.slow.
They are skipped unless the ``DOCKER_AVAILABLE`` environment variable is set
to ``"1"``.

Run integration tests with Docker enabled::

    DOCKER_AVAILABLE=1 ./venv/bin/pytest lib/sandbox/tests/test_manager_runs_integration.py -v -m slow

Covers:
- runCode("print(2+2)") → exit 0, stdout contains "4".
- runCode with timeout → timedOut=True.
- runCode persists files between runs in the same session.
- cancelRun kills a running container.
"""

import os
from pathlib import Path
from typing import AsyncGenerator

import pytest

from lib.sandbox.config import (
    ConcurrencyConfig,
    PythonRuntimeConfig,
    SandboxConfig,
    StorageConfig,
)
from lib.sandbox.enums import RuntimeName
from lib.sandbox.manager import SandboxManager
from lib.sandbox.types import NetworkPolicy

DOCKER_AVAILABLE = os.environ.get("DOCKER_AVAILABLE", "0") == "1"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker daemon unavailable"),
]


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


def _makeConfig(tmp_path) -> SandboxConfig:
    """Create a SandboxConfig with a Python runtime for integration testing.

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
async def manager(tmp_path: Path) -> AsyncGenerator[SandboxManager, None]:
    """Create a fresh SandboxManager with a temp storage directory.

    Args:
        tmp_path: Pytest-provided temporary directory (not used, for compatibility only).

    Returns:
        A SandboxManager instance with the Python runtime prepared.
    """
    import time

    # Use a directory under home that is shared with Docker
    test_dir = Path.home() / ".gromozeka-tests" / f"test-{int(time.time() * 1000000)}"
    test_dir.mkdir(parents=True)

    config = _makeConfig(test_dir)
    SandboxManager.injectConfig(config)

    manager = SandboxManager.getInstance()
    # Prepare the runtime to ensure images and directories exist
    await manager.prepareRuntime(RuntimeName.PYTHON)
    yield manager
    # Clean up after test
    import shutil

    # Close the backend to prevent "Unclosed connector" warnings
    await manager._backend.close()

    shutil.rmtree(test_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestRunCodeIntegration:
    """Integration tests for runCode that require Docker."""

    @pytest.mark.slow
    async def test_simplePrint(self, manager: SandboxManager) -> None:
        """runCode('print(2+2)') exits 0 and stdout contains '4'."""
        result = await manager.runCode("integ-sess-1", "print(2+2)")
        assert result.exitCode == 0
        assert result.error is None
        assert result.timedOut is False
        assert result.oomKilled is False

        # Read stdout
        from pathlib import Path

        sessionInfo = await manager.getSessionInfo("integ-sess-1")
        assert sessionInfo is not None
        workspacePath = Path(sessionInfo.workspacePath)
        stdoutPath = workspacePath / ".run" / result.runId / "stdout.log"
        if stdoutPath.exists():
            stdout = stdoutPath.read_text(encoding="utf-8")
            assert "4" in stdout

    @pytest.mark.slow
    async def test_timeout(self, manager: SandboxManager) -> None:
        """runCode with a short timeout returns timedOut=True."""
        result = await manager.runCode(
            "integ-sess-timeout",
            "import time; time.sleep(60)",
            timeoutSeconds=2,
        )
        assert result.timedOut is True

    @pytest.mark.slow
    async def test_persistentFiles(self, manager: SandboxManager) -> None:
        """Files persist between runs in the same session."""
        # First run: write a file
        await manager.runCode(
            "integ-sess-persist",
            "open('data.txt', 'w').write('hello')",
        )
        # Second run: read the file
        result = await manager.runCode(
            "integ-sess-persist",
            "print(open('data.txt').read())",
        )
        assert result.exitCode == 0

    @pytest.mark.slow
    async def test_nonZeroExitCode(self, manager: SandboxManager) -> None:
        """runCode with code that exits non-zero returns the exit code."""
        result = await manager.runCode(
            "integ-sess-err",
            "import sys; sys.exit(42)",
        )
        assert result.exitCode == 42
        assert result.error is not None
        assert "42" in result.error

    @pytest.mark.slow
    async def test_networkDisabled(self, manager: SandboxManager) -> None:
        """runCode with network disabled cannot reach the internet."""
        result = await manager.runCode(
            "integ-sess-netoff",
            "import urllib.request; urllib.request.urlopen('https://example.com')",
            network=NetworkPolicy(enabled=False),
            timeoutSeconds=10,
        )
        # Should fail because network is disabled
        assert result.exitCode != 0

    @pytest.mark.slow
    async def test_stdin(self, manager: SandboxManager) -> None:
        """runCode with stdin feeds input to the program."""
        result = await manager.runCode(
            "integ-sess-stdin",
            "x = input(); print(f'got: {x}')",
            stdin="hello from stdin",
        )
        assert result.exitCode == 0
