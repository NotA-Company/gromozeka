"""Tests for :class:`PythonRuntime` command generation.

Covers:
- ``runCommand`` shape with and without stdin redirection.
- ``runCommand`` timeout value placement.
- ``installCommand`` base shape, ``--upgrade`` flag, and package ordering.
- ``listCommand`` exact output.
- ``validatePackageSpec`` acceptance and rejection of package specs.
"""

import pytest

from lib.sandbox.config import BasicRuntimeConfig, InstallContainerConfig
from lib.sandbox.enums import RuntimeName
from lib.sandbox.errors import InvalidPackageSpec
from lib.sandbox.runtimes.python.runtime import PythonRuntime
from lib.sandbox.types import ResourceLimits

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> BasicRuntimeConfig:
    """Return a default :class:`BasicRuntimeConfig`."""
    return BasicRuntimeConfig(
        runImageTag="gromozeka-sandbox-python:run",
        installImageTag="gromozeka-sandbox-python:install",
        runDockerfile="lib/sandbox/runtimes/python/Dockerfile",
        installDockerfile="lib/sandbox/runtimes/python/Dockerfile.install",
        libMountPath="/sandbox/libs/python",
        env={},
        installContainer=InstallContainerConfig(),
    )


@pytest.fixture
def runtime(config: BasicRuntimeConfig) -> PythonRuntime:
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

    def testCdIntoWorkDir(self, runtime: PythonRuntime, defaultLimits: ResourceLimits) -> None:
        """Verify the command cd's into the per-run work directory."""
        cmd = runtime.runCommand("run99", hasStdin=False, limits=defaultLimits)
        shellCmd = cmd[-1]
        assert shellCmd.startswith("cd /workspace/.run/run99/work &&")


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
            runtime._config.libMountPath,
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
        stdoutPath = "/tmp/stdout.json"
        stderrPath = "/tmp/stderr.log"
        cmd = runtime.listCommand(stdoutPath, stderrPath)
        assert cmd == [
            "sh",
            "-c",
            f"python -m pip list --format=json --path '{runtime._config.libMountPath}' > {stdoutPath} 2> {stderrPath}",
        ]


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


# ---------------------------------------------------------------------------
# validatePackageSpec
# ---------------------------------------------------------------------------


class TestValidatePackageSpec:
    """Tests for :meth:`PythonRuntime.validatePackageSpec`.

    Exercises the import path from ``packaging.requirements`` — a
    regression guard against environments where the ``packaging`` library
    is missing from the venv (e.g. Alpine CI with ``--system-site-packages``
    where the system package shadows the PyPI install).
    """

    async def testValidSimpleName(self, runtime: PythonRuntime) -> None:
        """Verify a plain package name passes validation."""
        await runtime.validatePackageSpec("numpy")

    async def testValidWithVersionPin(self, runtime: PythonRuntime) -> None:
        """Verify a package name with a version pin passes validation."""
        await runtime.validatePackageSpec("requests>=2.32.0")

    async def testValidWithExtras(self, runtime: PythonRuntime) -> None:
        """Verify a package name with extras passes validation."""
        await runtime.validatePackageSpec("httpx[http2]")

    async def testValidWithMultipleExtras(self, runtime: PythonRuntime) -> None:
        """Verify a package name with multiple extras passes validation."""
        await runtime.validatePackageSpec("httpx[http2,socks]")

    async def testInvalidStartsWithDash(self, runtime: PythonRuntime) -> None:
        """Verify a spec starting with '-' raises InvalidPackageSpec."""
        with pytest.raises(InvalidPackageSpec):
            await runtime.validatePackageSpec("--upgrade")

    async def testInvalidEmpty(self, runtime: PythonRuntime) -> None:
        """Verify an empty spec raises InvalidPackageSpec."""
        with pytest.raises(InvalidPackageSpec):
            await runtime.validatePackageSpec("")

    async def testInvalidBareEquals(self, runtime: PythonRuntime) -> None:
        """Verify a malformed spec raises InvalidPackageSpec."""
        with pytest.raises(InvalidPackageSpec):
            await runtime.validatePackageSpec("=1.0")
