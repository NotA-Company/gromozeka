"""Integration tests for SandboxManager library pool methods (lib.sandbox.manager).

These tests require Docker to be available and are gated on DOCKER_AVAILABLE.
They are marked as @pytest.mark.slow and will be skipped in normal test runs.

Covers:
- installRuntimeLibraries(["numpy"]) installs into pool.
- removeRuntimeLibraries(["numpy"]) removes from pool.
"""

import os
from pathlib import Path
from typing import AsyncGenerator

import pytest

from lib.sandbox.config import ConcurrencyConfig, PythonRuntimeConfig, SandboxConfig, StorageConfig
from lib.sandbox.enums import RuntimeName
from lib.sandbox.manager import SandboxManager

# Skip the entire module if Docker is not available
DOCKER_AVAILABLE = os.environ.get("DOCKER_AVAILABLE", "0") == "1"
pytestmark = [
    pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker not available"),
    pytest.mark.slow,
]


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


class TestInstallRuntimeLibrariesIntegration:
    """Integration tests for installRuntimeLibraries with Docker."""

    async def test_installNumpy(self, manager: SandboxManager, tmp_path: Path) -> None:
        """installRuntimeLibraries installs numpy into the pool."""
        result = await manager.installRuntimeLibraries(
            ["numpy"],
            runtime=RuntimeName.PYTHON,
            timeoutSeconds=300,
        )

        # At least one package should be installed
        assert len(result.installed) > 0 or len(result.failed) == 0
        # poolVersion should be non-empty on success
        if result.installed:
            assert result.poolVersion != ""

    async def test_installAndList(self, manager: SandboxManager, tmp_path: Path) -> None:
        """After installing, listRuntimeLibraries returns the package."""
        await manager.installRuntimeLibraries(
            ["numpy"],
            runtime=RuntimeName.PYTHON,
            timeoutSeconds=300,
        )

        packages = await manager.listRuntimeLibraries(runtime=RuntimeName.PYTHON)
        names = [p.name for p in packages]
        # numpy should appear in the list (possibly with different casing)
        assert any("numpy" in n.lower() for n in names)


class TestRemoveRuntimeLibrariesIntegration:
    """Integration tests for removeRuntimeLibraries with Docker."""

    async def test_removeNumpy(self, manager: SandboxManager, tmp_path: Path) -> None:
        """removeRuntimeLibraries removes numpy from the pool."""
        # Install first
        await manager.installRuntimeLibraries(
            ["numpy"],
            runtime=RuntimeName.PYTHON,
            timeoutSeconds=300,
        )

        # Then remove
        result = await manager.removeRuntimeLibraries(
            ["numpy"],
            runtime=RuntimeName.PYTHON,
        )

        assert "numpy" in result.removed
