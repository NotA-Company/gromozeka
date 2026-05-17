"""Tests for SandboxManager library pool methods (lib.sandbox.manager).

Covers:
- listRuntimeLibraries returns empty list for uninitialized runtime.
- listRuntimeLibraries reads packages.json correctly.
- installRuntimeLibraries validates package specs (rejects shell metacharacters,
  flag prefixes, accepts valid PEP 508 specs).
- removeRuntimeLibraries with empty packages returns empty result.
- prepareRuntime creates libs dir and initializes metadata record.
- listRuntimes returns runtimes with metadata.
- Package spec validation edge cases.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lib.sandbox.backends.base import ContainerOutcome
from lib.sandbox.config import ConcurrencyConfig, PythonRuntimeConfig, SandboxConfig, StorageConfig
from lib.sandbox.enums import RuntimeName
from lib.sandbox.errors import InvalidPackageSpec, UnknownRuntime
from lib.sandbox.manager import SandboxManager
from lib.sandbox.metadata.base import RuntimeRecord
from lib.sandbox.types import LibraryInstallResult, PackageInfo, RuntimeInfo

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


# ---------------------------------------------------------------------------
# listRuntimeLibraries tests
# ---------------------------------------------------------------------------


class TestListRuntimeLibraries:
    """Tests for SandboxManager.listRuntimeLibraries."""

    async def test_returnsEmptyForUninitializedRuntime(self, manager: SandboxManager) -> None:
        """listRuntimeLibraries returns an empty list when no packages.json exists."""
        result = await manager.listRuntimeLibraries(runtime=RuntimeName.PYTHON)
        assert result == []

    async def test_readsPackagesJson(self, manager: SandboxManager, tmp_path: Path) -> None:
        """listRuntimeLibraries reads and parses packages.json correctly."""
        packagesDir = Path(tmp_path) / "runtimes" / "python"
        packagesDir.mkdir(parents=True, exist_ok=True)
        packagesData = [
            {"name": "numpy", "version": "1.24.0"},
            {"name": "requests", "version": "2.28.1"},
        ]
        (packagesDir / "packages.json").write_text(json.dumps(packagesData))

        result = await manager.listRuntimeLibraries(runtime=RuntimeName.PYTHON)
        assert len(result) == 2
        assert result[0] == PackageInfo(name="numpy", version="1.24.0")
        assert result[1] == PackageInfo(name="requests", version="2.28.1")

    async def test_handlesMalformedJson(self, manager: SandboxManager, tmp_path: Path) -> None:
        """listRuntimeLibraries returns empty list for malformed packages.json."""
        packagesDir = Path(tmp_path) / "runtimes" / "python"
        packagesDir.mkdir(parents=True, exist_ok=True)
        (packagesDir / "packages.json").write_text("not json")

        result = await manager.listRuntimeLibraries(runtime=RuntimeName.PYTHON)
        assert result == []


# ---------------------------------------------------------------------------
# _validatePackageSpec tests
# ---------------------------------------------------------------------------


class TestValidatePackageSpec:
    """Tests for SandboxManager._validatePackageSpec."""

    def test_acceptsSimpleName(self, manager: SandboxManager) -> None:
        """Valid simple package name passes validation."""
        manager._validatePackageSpec("numpy")

    def test_acceptsSpecWithVersion(self, manager: SandboxManager) -> None:
        """Valid PEP 508 spec with version constraint passes validation."""
        manager._validatePackageSpec("numpy>=1.0")

    def test_acceptsSpecWithExtras(self, manager: SandboxManager) -> None:
        """Valid PEP 508 spec with extras passes validation."""
        manager._validatePackageSpec("requests[security]>=2.0")

    def test_rejectsShellMetacharacterAmpersand(self, manager: SandboxManager) -> None:
        """Spec containing '&' is rejected."""
        with pytest.raises(InvalidPackageSpec, match="shell metacharacter"):
            manager._validatePackageSpec("numpy; rm -rf /")

    def test_rejectsShellMetacharacterPipe(self, manager: SandboxManager) -> None:
        """Spec containing '|' is rejected."""
        with pytest.raises(InvalidPackageSpec, match="shell metacharacter"):
            manager._validatePackageSpec("numpy | echo pwned")

    def test_rejectsShellMetacharacterSemicolon(self, manager: SandboxManager) -> None:
        """Spec containing ';' is rejected."""
        with pytest.raises(InvalidPackageSpec, match="shell metacharacter"):
            manager._validatePackageSpec("numpy;echo")

    def test_rejectsShellMetacharacterBacktick(self, manager: SandboxManager) -> None:
        """Spec containing '`' is rejected."""
        with pytest.raises(InvalidPackageSpec, match="shell metacharacter"):
            manager._validatePackageSpec("numpy`whoami`")

    def test_rejectsShellMetacharacterDollarParen(self, manager: SandboxManager) -> None:
        """Spec containing '$(' is rejected."""
        with pytest.raises(InvalidPackageSpec, match="shell metacharacter"):
            manager._validatePackageSpec("$(whoami)")

    def test_rejectsShellMetacharacterNewline(self, manager: SandboxManager) -> None:
        """Spec containing newline is rejected."""
        with pytest.raises(InvalidPackageSpec, match="shell metacharacter"):
            manager._validatePackageSpec("numpy\nrm")

    def test_rejectsShellMetacharacterCarriageReturn(self, manager: SandboxManager) -> None:
        """Spec containing carriage return is rejected."""
        with pytest.raises(InvalidPackageSpec, match="shell metacharacter"):
            manager._validatePackageSpec("numpy\rrm")

    def test_rejectsFlagPrefix(self, manager: SandboxManager) -> None:
        """Spec starting with '-' is rejected."""
        with pytest.raises(InvalidPackageSpec, match="starts with '-'"):
            manager._validatePackageSpec("--flag")

    def test_rejectsDashDashFlag(self, manager: SandboxManager) -> None:
        """Spec starting with '--' is rejected."""
        with pytest.raises(InvalidPackageSpec, match="starts with '-'"):
            manager._validatePackageSpec("--no-cache-dir")


# ---------------------------------------------------------------------------
# installRuntimeLibraries tests (unit — no Docker)
# ---------------------------------------------------------------------------


class TestInstallRuntimeLibraries:
    """Tests for SandboxManager.installRuntimeLibraries (unit, no Docker)."""

    async def test_emptyPackagesReturnsEmptyResult(self, manager: SandboxManager) -> None:
        """installRuntimeLibraries with empty packages returns empty result."""
        result = await manager.installRuntimeLibraries([], runtime=RuntimeName.PYTHON)
        assert result == LibraryInstallResult(
            runtime=RuntimeName.PYTHON,
            installed=[],
            skipped=[],
            failed=[],
            poolVersion="",
        )

    async def test_allWhitespacePackagesReturnsEmptyResult(self, manager: SandboxManager) -> None:
        """installRuntimeLibraries with only whitespace packages returns empty result."""
        result = await manager.installRuntimeLibraries(["  ", ""], runtime=RuntimeName.PYTHON)
        assert result.installed == []
        assert result.skipped == []
        assert result.failed == []

    async def test_raisesUnknownRuntimeForMissingRuntime(self, manager: SandboxManager) -> None:
        """installRuntimeLibraries raises UnknownRuntime for an unavailable runtime."""
        # Remove the Python runtime from the manager
        manager._runtimes.clear()
        with pytest.raises(UnknownRuntime):
            await manager.installRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

    async def test_raisesInvalidPackageSpec(self, manager: SandboxManager) -> None:
        """installRuntimeLibraries raises InvalidPackageSpec for malicious specs."""
        with pytest.raises(InvalidPackageSpec):
            await manager.installRuntimeLibraries(["numpy; rm -rf /"], runtime=RuntimeName.PYTHON)

    async def test_raisesInvalidPackageSpecForFlag(self, manager: SandboxManager) -> None:
        """installRuntimeLibraries raises InvalidPackageSpec for flag-like specs."""
        with pytest.raises(InvalidPackageSpec):
            await manager.installRuntimeLibraries(["--no-cache-dir"], runtime=RuntimeName.PYTHON)

    async def test_validatesAllSpecsBeforeRunning(self, manager: SandboxManager) -> None:
        """installRuntimeLibraries validates all specs before running any container."""
        with pytest.raises(InvalidPackageSpec):
            await manager.installRuntimeLibraries(["numpy", "--evil"], runtime=RuntimeName.PYTHON)


# ---------------------------------------------------------------------------
# removeRuntimeLibraries tests (unit — no Docker)
# ---------------------------------------------------------------------------


class TestRemoveRuntimeLibraries:
    """Tests for SandboxManager.removeRuntimeLibraries (unit, no Docker)."""

    async def test_emptyPackagesReturnsEmptyResult(self, manager: SandboxManager, tmp_path: Path) -> None:
        """removeRuntimeLibraries with empty packages returns empty result."""
        # Need a runtime record so the method doesn't fail on metadata
        poolDir = Path(tmp_path) / "runtimes" / "python"
        poolDir.mkdir(parents=True, exist_ok=True)
        (poolDir / "libs").mkdir(parents=True, exist_ok=True)

        record = RuntimeRecord(
            runtime=RuntimeName.PYTHON,
            runImageTag="gromozeka-sandbox-python:run",
            installImageTag="gromozeka-sandbox-python:install",
            libPoolPath=str(poolDir / "libs"),
            libPoolVersion="",
            packageCount=0,
        )
        await manager._metadata.saveRuntime(record)

        result = await manager.removeRuntimeLibraries([], runtime=RuntimeName.PYTHON)
        assert result.removed == []
        assert result.notFound == []

    async def test_raisesUnknownRuntimeForMissingRuntime(self, manager: SandboxManager) -> None:
        """removeRuntimeLibraries raises UnknownRuntime for an unavailable runtime."""
        manager._runtimes.clear()
        with pytest.raises(UnknownRuntime):
            await manager.removeRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

    async def test_removesPackageDirectory(self, manager: SandboxManager, tmp_path: Path) -> None:
        """removeRuntimeLibraries removes the package directory from libs."""
        poolDir = Path(tmp_path) / "runtimes" / "python"
        libsDir = poolDir / "libs"
        libsDir.mkdir(parents=True, exist_ok=True)

        # Create a fake package directory
        (libsDir / "numpy").mkdir()
        (libsDir / "numpy-1.24.0.dist-info").mkdir()

        record = RuntimeRecord(
            runtime=RuntimeName.PYTHON,
            runImageTag="gromozeka-sandbox-python:run",
            installImageTag="gromozeka-sandbox-python:install",
            libPoolPath=str(libsDir),
            libPoolVersion="abc123",
            packageCount=1,
        )
        await manager._metadata.saveRuntime(record)

        result = await manager.removeRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)
        assert "numpy" in result.removed
        assert not (libsDir / "numpy").exists()

    async def test_reportsNotFoundForMissingPackage(self, manager: SandboxManager, tmp_path: Path) -> None:
        """removeRuntimeLibraries reports notFound for packages not in the pool."""
        poolDir = Path(tmp_path) / "runtimes" / "python"
        libsDir = poolDir / "libs"
        libsDir.mkdir(parents=True, exist_ok=True)

        record = RuntimeRecord(
            runtime=RuntimeName.PYTHON,
            runImageTag="gromozeka-sandbox-python:run",
            installImageTag="gromozeka-sandbox-python:install",
            libPoolPath=str(libsDir),
            libPoolVersion="",
            packageCount=0,
        )
        await manager._metadata.saveRuntime(record)

        result = await manager.removeRuntimeLibraries(["nonexistent"], runtime=RuntimeName.PYTHON)
        assert "nonexistent" in result.notFound

    async def test_noLibsDirReturnsAllNotFound(self, manager: SandboxManager, tmp_path: Path) -> None:
        """removeRuntimeLibraries returns all packages as notFound when libs dir doesn't exist."""
        poolDir = Path(tmp_path) / "runtimes" / "python"
        poolDir.mkdir(parents=True, exist_ok=True)
        # No libs dir

        record = RuntimeRecord(
            runtime=RuntimeName.PYTHON,
            runImageTag="gromozeka-sandbox-python:run",
            installImageTag="gromozeka-sandbox-python:install",
            libPoolPath=str(poolDir / "libs"),
            libPoolVersion="",
            packageCount=0,
        )
        await manager._metadata.saveRuntime(record)

        result = await manager.removeRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)
        assert "numpy" in result.notFound


# ---------------------------------------------------------------------------
# prepareRuntime tests (unit — no Docker)
# ---------------------------------------------------------------------------


class TestPrepareRuntime:
    """Tests for SandboxManager.prepareRuntime (unit, no Docker)."""

    async def test_createsLibsDirAndMetadata(self, manager: SandboxManager, tmp_path: Path) -> None:
        """prepareRuntime creates the libs directory and initializes metadata."""
        # Mock ensureImage to avoid needing Docker
        manager._backend.ensureImage = AsyncMock()  # type: ignore[assignment]

        result = await manager.prepareRuntime(RuntimeName.PYTHON)

        assert isinstance(result, RuntimeInfo)
        assert result.name == RuntimeName.PYTHON
        assert result.runImageTag == "gromozeka-sandbox-python:run"
        assert result.installImageTag == "gromozeka-sandbox-python:install"

        # Check libs dir was created
        libsDir = Path(tmp_path) / "runtimes" / "python" / "libs"
        assert libsDir.exists()

        # Check metadata was saved
        record = await manager._metadata.loadRuntime(RuntimeName.PYTHON)
        assert record is not None
        assert record.runImageTag == "gromozeka-sandbox-python:run"

    async def test_idempotentPrepare(self, manager: SandboxManager, tmp_path: Path) -> None:
        """prepareRuntime called twice does not fail and preserves metadata."""
        manager._backend.ensureImage = AsyncMock()  # type: ignore[assignment]

        result1 = await manager.prepareRuntime(RuntimeName.PYTHON)
        result2 = await manager.prepareRuntime(RuntimeName.PYTHON)

        assert result1.name == result2.name
        assert result1.runImageTag == result2.runImageTag


# ---------------------------------------------------------------------------
# listRuntimes tests (unit — no Docker)
# ---------------------------------------------------------------------------


class TestListRuntimes:
    """Tests for SandboxManager.listRuntimes."""

    async def test_returnsEmptyWhenNoRuntimesPrepared(self, manager: SandboxManager) -> None:
        """listRuntimes returns empty list when no runtimes have been prepared."""
        result = await manager.listRuntimes()
        assert result == []

    async def test_returnsRuntimeAfterPrepare(self, manager: SandboxManager, tmp_path: Path) -> None:
        """listRuntimes returns the prepared runtime."""
        manager._backend.ensureImage = AsyncMock()  # type: ignore[assignment]
        await manager.prepareRuntime(RuntimeName.PYTHON)

        result = await manager.listRuntimes()
        assert len(result) == 1
        assert result[0].name == RuntimeName.PYTHON


# ---------------------------------------------------------------------------
# _refreshPackageList tests
# ---------------------------------------------------------------------------


class TestRefreshPackageList:
    """Tests for SandboxManager._refreshPackageList."""

    async def test_writesPackagesJson(self, manager: SandboxManager, tmp_path: Path) -> None:
        """_refreshPackageList writes packages.json from dist-info directories."""
        # Set up runtime record
        poolDir = Path(tmp_path) / "runtimes" / "python"
        libsDir = poolDir / "libs"
        libsDir.mkdir(parents=True, exist_ok=True)

        # Create fake dist-info directories
        (libsDir / "numpy-1.24.0.dist-info").mkdir()
        (libsDir / "requests-2.28.1.dist-info").mkdir()

        record = RuntimeRecord(
            runtime=RuntimeName.PYTHON,
            runImageTag="gromozeka-sandbox-python:run",
            installImageTag="gromozeka-sandbox-python:install",
            libPoolPath=str(libsDir),
            libPoolVersion="",
            packageCount=0,
        )
        await manager._metadata.saveRuntime(record)

        poolVersion = await manager._refreshPackageList(RuntimeName.PYTHON, libsDir)

        # Check packages.json was written
        packagesPath = poolDir / "packages.json"
        assert packagesPath.exists()
        data = json.loads(packagesPath.read_text())
        assert len(data) == 2

        # Check poolVersion is non-empty
        assert poolVersion != ""

        # Check runtime record was updated
        updated = await manager._metadata.loadRuntime(RuntimeName.PYTHON)
        assert updated is not None
        assert updated.packageCount == 2
        assert updated.libPoolVersion == poolVersion

    async def test_emptyLibsDir(self, manager: SandboxManager, tmp_path: Path) -> None:
        """_refreshPackageList handles empty libs directory."""
        poolDir = Path(tmp_path) / "runtimes" / "python"
        libsDir = poolDir / "libs"
        libsDir.mkdir(parents=True, exist_ok=True)

        record = RuntimeRecord(
            runtime=RuntimeName.PYTHON,
            runImageTag="gromozeka-sandbox-python:run",
            installImageTag="gromozeka-sandbox-python:install",
            libPoolPath=str(libsDir),
            libPoolVersion="",
            packageCount=0,
        )
        await manager._metadata.saveRuntime(record)

        poolVersion = await manager._refreshPackageList(RuntimeName.PYTHON, libsDir)

        # Empty pool should have a deterministic hash
        assert poolVersion != ""
        assert len(poolVersion) == 64  # SHA-256 hex digest

        packagesPath = poolDir / "packages.json"
        data = json.loads(packagesPath.read_text())
        assert data == []


# ---------------------------------------------------------------------------
# _parseInstallOutput tests
# ---------------------------------------------------------------------------


class TestParseInstallOutput:
    """Tests for SandboxManager._parseInstallOutput."""

    def test_successExitCode(self, manager: SandboxManager) -> None:
        """Successful exit code returns a placeholder installed entry."""
        outcome = ContainerOutcome(
            containerId="abc123",
            exitCode=0,
            signal=None,
            oomKilled=False,
            inspects={},
        )
        installed, skipped, failed = manager._parseInstallOutput(outcome)
        assert len(installed) == 1
        assert installed[0].name == "packages"
        assert skipped == []
        assert failed == []

    def test_failureExitCode(self, manager: SandboxManager) -> None:
        """Non-zero exit code returns a failed entry."""
        outcome = ContainerOutcome(
            containerId="abc123",
            exitCode=1,
            signal=None,
            oomKilled=False,
            inspects={},
        )
        installed, skipped, failed = manager._parseInstallOutput(outcome)
        assert installed == []
        assert skipped == []
        assert len(failed) == 1
        assert failed[0][0] == "install"
