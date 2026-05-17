"""Tests for :class:`PythonRuntime` command generation and artifact detection.

Covers:
- ``runCommand`` shape with and without stdin redirection.
- ``runCommand`` timeout value placement.
- ``installCommand`` base shape, ``--upgrade`` flag, and package ordering.
- ``listCommand`` exact output.
- ``detectArtifacts`` mtime filtering, ``.run/`` exclusion, and
  :class:`ArtifactInfo` field population.
- ``name`` class attribute.
"""

import os
import time
from pathlib import Path

import pytest

from lib.sandbox.config import PythonRuntimeConfig
from lib.sandbox.enums import RuntimeName
from lib.sandbox.runtimes.python.runtime import PythonRuntime
from lib.sandbox.types import ArtifactInfo, ResourceLimits

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> PythonRuntimeConfig:
    """Return a default :class:`PythonRuntimeConfig`."""
    return PythonRuntimeConfig()


@pytest.fixture
def runtime(config: PythonRuntimeConfig) -> PythonRuntime:
    """Return a :class:`PythonRuntime` initialised with the default config."""
    return PythonRuntime(config)


@pytest.fixture
def defaultLimits() -> ResourceLimits:
    """Return default resource limits (30s timeout, 5s grace)."""
    return ResourceLimits(timeoutSeconds=30, timeoutGraceSeconds=5)


# ---------------------------------------------------------------------------
# runCommand
# ---------------------------------------------------------------------------


class TestRunCommand:
    """Tests for :meth:`PythonRuntime.runCommand`."""

    def testCommandShapeNoStdin(self, runtime: PythonRuntime, defaultLimits: ResourceLimits) -> None:
        """Verify command list structure without stdin redirection."""
        cmd = runtime.runCommand("abc123", hasStdin=False, limits=defaultLimits)

        assert isinstance(cmd, list)
        assert all(isinstance(part, str) for part in cmd)

        # timeout wrapper arguments
        assert "timeout" in cmd
        assert "-s" in cmd
        assert "TERM" in cmd
        assert "-k" in cmd
        assert "5" in cmd  # timeoutGraceSeconds
        assert "30" in cmd  # timeoutSeconds

        # Shell command references main.py
        shellCmd = cmd[-1]
        assert "main.py" in shellCmd
        # No stdin redirection
        assert "< /workspace/.run/abc123/stdin" not in shellCmd

    def testCommandWithStdin(self, runtime: PythonRuntime, defaultLimits: ResourceLimits) -> None:
        """Verify stdin redirection appears when hasStdin is True."""
        cmd = runtime.runCommand("abc123", hasStdin=True, limits=defaultLimits)
        shellCmd = cmd[-1]
        assert "< /workspace/.run/abc123/stdin" in shellCmd

    def testTimeoutValues(self, runtime: PythonRuntime) -> None:
        """Verify custom timeout values appear in the command."""
        limits = ResourceLimits(timeoutSeconds=60, timeoutGraceSeconds=10)
        cmd = runtime.runCommand("run42", hasStdin=False, limits=limits)

        # timeoutSeconds and timeoutGraceSeconds should appear as strings
        assert "60" in cmd
        assert "10" in cmd

    def testRunIdInPath(self, runtime: PythonRuntime, defaultLimits: ResourceLimits) -> None:
        """Verify the runId appears in the constructed paths."""
        cmd = runtime.runCommand("xyz789", hasStdin=False, limits=defaultLimits)
        shellCmd = cmd[-1]
        assert "/workspace/.run/xyz789/main.py" in shellCmd
        assert "/workspace/.run/xyz789/stdout.log" in shellCmd
        assert "/workspace/.run/xyz789/stderr.log" in shellCmd


# ---------------------------------------------------------------------------
# installCommand
# ---------------------------------------------------------------------------


class TestInstallCommand:
    """Tests for :meth:`PythonRuntime.installCommand`."""

    def testBaseShape(self, runtime: PythonRuntime) -> None:
        """Verify base install command prefix without --upgrade."""
        cmd = runtime.installCommand(["numpy"], upgrade=False)

        assert cmd[:6] == [
            "python",
            "-m",
            "pip",
            "install",
            "--target",
            "/sandbox/libs",
        ]
        assert "--no-cache-dir" in cmd
        assert "--no-input" in cmd
        assert "--upgrade" not in cmd

    def testUpgradeFlag(self, runtime: PythonRuntime) -> None:
        """Verify --upgrade flag is present when upgrade=True."""
        cmd = runtime.installCommand(["numpy"], upgrade=True)
        assert "--upgrade" in cmd

    def testPackages(self, runtime: PythonRuntime) -> None:
        """Verify package names appear at the end of the command."""
        cmd = runtime.installCommand(["numpy", "pandas"], upgrade=False)
        assert cmd[-2:] == ["numpy", "pandas"]

    def testUpgradeAndPackages(self, runtime: PythonRuntime) -> None:
        """Verify --upgrade appears before packages."""
        cmd = runtime.installCommand(["requests"], upgrade=True)
        upgradeIdx = cmd.index("--upgrade")
        requestsIdx = cmd.index("requests")
        assert upgradeIdx < requestsIdx


# ---------------------------------------------------------------------------
# listCommand
# ---------------------------------------------------------------------------


class TestListCommand:
    """Tests for :meth:`PythonRuntime.listCommand`."""

    def testExactCommand(self, runtime: PythonRuntime) -> None:
        """Verify listCommand returns the exact expected command."""
        assert runtime.listCommand() == [
            "python",
            "-m",
            "pip",
            "list",
            "--format=json",
            "--path",
            "/sandbox/libs",
        ]


# ---------------------------------------------------------------------------
# detectArtifacts
# ---------------------------------------------------------------------------


class TestDetectArtifacts:
    """Tests for :meth:`PythonRuntime.detectArtifacts`."""

    def testDetectsNewFile(self, runtime: PythonRuntime, tmp_path: Path) -> None:
        """Files modified after sinceMtime are detected."""
        # Create a file with a known mtime
        testFile = tmp_path / "output.txt"
        testFile.write_text("hello")

        # Use a sinceMtime slightly in the past
        sinceMtime = time.time() - 10
        # Ensure the file mtime is newer than sinceMtime
        os.utime(testFile, (sinceMtime + 100, sinceMtime + 100))

        artifacts = runtime.detectArtifacts(tmp_path, sinceMtime=sinceMtime)
        assert len(artifacts) == 1
        assert artifacts[0].path == "output.txt"
        assert artifacts[0].sizeBytes == 5  # "hello"

    def testExcludesOldFile(self, runtime: PythonRuntime, tmp_path: Path) -> None:
        """Files modified before sinceMtime are excluded."""
        testFile = tmp_path / "old.txt"
        testFile.write_text("old content")

        # Set mtime well in the past
        oldTime = time.time() - 1000
        os.utime(testFile, (oldTime, oldTime))

        sinceMtime = time.time()
        artifacts = runtime.detectArtifacts(tmp_path, sinceMtime=sinceMtime)
        assert len(artifacts) == 0

    def testExcludesRunDir(self, runtime: PythonRuntime, tmp_path: Path) -> None:
        """Files under .run/ are excluded from detection."""
        runDir = tmp_path / ".run"
        runDir.mkdir()
        runFile = runDir / "main.py"
        runFile.write_text("print('hi')")

        # Also create a real artifact
        realFile = tmp_path / "result.txt"
        realFile.write_text("data")
        recentTime = time.time() + 100
        os.utime(realFile, (recentTime, recentTime))

        artifacts = runtime.detectArtifacts(tmp_path, sinceMtime=0.0)
        paths = [a.path for a in artifacts]
        assert ".run/main.py" not in paths
        assert "result.txt" in paths

    def testSubdirectoryFiles(self, runtime: PythonRuntime, tmp_path: Path) -> None:
        """Files in subdirectories are detected with correct relative paths."""
        subDir = tmp_path / "subdir"
        subDir.mkdir()
        subFile = subDir / "nested.csv"
        subFile.write_text("a,b,c")

        recentTime = time.time() + 100
        os.utime(subFile, (recentTime, recentTime))

        artifacts = runtime.detectArtifacts(tmp_path, sinceMtime=0.0)
        assert len(artifacts) == 1
        assert artifacts[0].path == str(Path("subdir") / "nested.csv")

    def testArtifactInfoFields(self, runtime: PythonRuntime, tmp_path: Path) -> None:
        """Verify all ArtifactInfo fields are populated correctly."""
        testFile = tmp_path / "data.bin"
        content = b"\x00\x01\x02\x03"
        testFile.write_bytes(content)

        recentTime = time.time() + 100
        os.utime(testFile, (recentTime, recentTime))

        artifacts = runtime.detectArtifacts(tmp_path, sinceMtime=0.0)
        assert len(artifacts) == 1

        art = artifacts[0]
        assert isinstance(art, ArtifactInfo)
        assert art.path == "data.bin"
        assert art.sizeBytes == len(content)
        assert art.modifiedAt is not None
        assert art.mimeType is None
        assert art.sha256 is None


# ---------------------------------------------------------------------------
# name attribute
# ---------------------------------------------------------------------------


class TestNameAttribute:
    """Tests for the :attr:`PythonRuntime.name` class attribute."""

    def testNameIsPython(self) -> None:
        """Verify the name attribute equals RuntimeName.PYTHON."""
        assert PythonRuntime.name == RuntimeName.PYTHON

    def testInstanceNameMatchesClass(self, runtime: PythonRuntime) -> None:
        """Verify instance name matches the class attribute."""
        assert runtime.name == PythonRuntime.name
