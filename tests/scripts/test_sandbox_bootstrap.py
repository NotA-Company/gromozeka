"""Tests for the sandbox bootstrap script."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib.sandbox.enums import RuntimeName  # noqa: E402
from scripts.sandbox_bootstrap import buildConfig, main, parseArgs  # noqa: E402


class TestSandboxBootstrap:
    """Tests for sandbox-bootstrap.py."""

    @patch("scripts.sandbox_bootstrap.ConfigManager")
    def test_parseArgsDefaults(self, mockConfigManager: MagicMock) -> None:
        """Verify default argument parsing."""
        with patch("sys.argv", ["sandbox-bootstrap.py"]):
            args = parseArgs()
            assert args.runtime == "python"
            assert args.upgrade is False
            assert args.init_storage is False
            assert args.config_dir == []
            assert args.dotenv == ".env"
            assert args.packages == []

    @patch("scripts.sandbox_bootstrap.ConfigManager")
    def test_parseArgsConfigDir(self, mockConfigManager: MagicMock) -> None:
        """Verify --config-dir argument."""
        with patch("sys.argv", ["sandbox-bootstrap.py", "--config-dir", "configs/00-defaults"]):
            args = parseArgs()
            assert args.config_dir == ["configs/00-defaults"]

    @patch("scripts.sandbox_bootstrap.ConfigManager")
    def test_parseArgsPackages(self, mockConfigManager: MagicMock) -> None:
        """Verify --packages argument."""
        with patch("sys.argv", ["sandbox-bootstrap.py", "--packages", "numpy", "--packages", "pandas"]):
            args = parseArgs()
            assert args.packages == ["numpy", "pandas"]

    @patch("scripts.sandbox_bootstrap.ConfigManager")
    def test_parseArgsDotenv(self, mockConfigManager: MagicMock) -> None:
        """Verify --dotenv argument."""
        with patch("sys.argv", ["sandbox-bootstrap.py", "--dotenv", ".env.test"]):
            args = parseArgs()
            assert args.dotenv == ".env.test"

    @patch("scripts.sandbox_bootstrap.ConfigManager")
    def test_parseArgsUpgrade(self, mockConfigManager: MagicMock) -> None:
        """Verify --upgrade flag."""
        with patch("sys.argv", ["sandbox-bootstrap.py", "--upgrade"]):
            args = parseArgs()
            assert args.upgrade is True

    @patch("scripts.sandbox_bootstrap.ConfigManager")
    def test_parseArgsInitStorage(self, mockConfigManager: MagicMock) -> None:
        """Verify --init-storage flag."""
        with patch("sys.argv", ["sandbox-bootstrap.py", "--init-storage"]):
            args = parseArgs()
            assert args.init_storage is True

    @patch("scripts.sandbox_bootstrap.ConfigManager")
    def test_parseArgsRuntime(self, mockConfigManager: MagicMock) -> None:
        """Verify --runtime flag with valid runtime name."""
        with patch("sys.argv", ["sandbox-bootstrap.py", "--runtime", "python"]):
            args = parseArgs()
            assert args.runtime == "python"

    @patch("scripts.sandbox_bootstrap.ConfigManager")
    def test_parseArgsMultiplePackages(self, mockConfigManager: MagicMock) -> None:
        """Verify multiple --packages values."""
        with patch(
            "sys.argv",
            ["sandbox-bootstrap.py", "--packages", "numpy", "--packages", "pandas", "--packages", "requests"],
        ):
            args = parseArgs()
            assert args.packages == ["numpy", "pandas", "requests"]


# ============================================================================
# Mock Tests
# ============================================================================


class TestSandboxBootstrapMock:
    """Mock tests for sandbox-bootstrap.py main() function."""

    @patch("scripts.sandbox_bootstrap.SandboxManager")
    @patch("scripts.sandbox_bootstrap.ensureDirectoryLayout")
    @patch("scripts.sandbox_bootstrap.ConfigManager")
    @patch("scripts.sandbox_bootstrap.parseArgs")
    @patch("scripts.sandbox_bootstrap.buildConfig")
    @pytest.mark.asyncio
    async def test_mainCallsInjectConfigAndGetInstance(
        self,
        mockBuildConfig: MagicMock,
        mockParseArgs: MagicMock,
        mockConfigManagerClass: MagicMock,
        mockEnsureDir: MagicMock,
        mockSandboxManagerClass: MagicMock,
    ) -> None:
        """Verify main() calls SandboxManager.injectConfig() then getInstance()."""
        # Setup mocks
        mockArgs = MagicMock()
        mockArgs.config_dir = []
        mockArgs.dotenv = ".env"
        mockArgs.packages = ["numpy"]
        mockArgs.runtime = "python"
        mockArgs.upgrade = False
        mockArgs.init_storage = False
        mockParseArgs.return_value = mockArgs

        mockConfigManager = MagicMock()
        mockConfigManager.get.return_value = {}
        mockConfigManagerClass.return_value = mockConfigManager

        mockConfig = MagicMock()
        mockConfig.storage.rootDir = "/tmp/test"
        mockConfig.runtimes = {RuntimeName.PYTHON: MagicMock()}
        mockBuildConfig.return_value = mockConfig

        mockManager = AsyncMock()
        mockManager.prepareRuntime = AsyncMock(return_value=True)
        mockManager.installRuntimeLibraries = AsyncMock(return_value=True)
        mockSandboxManagerClass.getInstance.return_value = mockManager
        mockSandboxManagerClass.injectConfig = MagicMock()

        # Run main
        exitCode = await main()

        # Verify SandboxManager.injectConfig was called
        mockSandboxManagerClass.injectConfig.assert_called_once_with(mockConfig)

        # Verify SandboxManager.getInstance was called
        mockSandboxManagerClass.getInstance.assert_called_once()

        # Verify exit code
        assert exitCode == 0

    @patch("scripts.sandbox_bootstrap.SandboxManager")
    @patch("scripts.sandbox_bootstrap.ConfigManager")
    @patch("scripts.sandbox_bootstrap.parseArgs")
    @patch("scripts.sandbox_bootstrap.buildConfig")
    @pytest.mark.asyncio
    async def test_mainCallsPrepareRuntimeAndInstallLibraries(
        self,
        mockBuildConfig: MagicMock,
        mockParseArgs: MagicMock,
        mockConfigManagerClass: MagicMock,
        mockSandboxManagerClass: MagicMock,
    ) -> None:
        """Verify main() calls prepareRuntime() and installRuntimeLibraries() with correct args."""
        # Setup mocks
        mockArgs = MagicMock()
        mockArgs.config_dir = []
        mockArgs.dotenv = ".env"
        mockArgs.packages = ["numpy", "pandas"]
        mockArgs.runtime = "python"
        mockArgs.upgrade = True
        mockArgs.init_storage = False
        mockParseArgs.return_value = mockArgs

        mockConfigManager = MagicMock()
        mockConfigManager.get.return_value = {}
        mockConfigManagerClass.return_value = mockConfigManager

        mockConfig = MagicMock()
        mockConfig.storage.rootDir = "/tmp/test"
        mockRuntimeConfig = MagicMock()
        mockRuntimeConfig.runImageTag = "test:latest"
        mockRuntimeConfig.installImageTag = "test:install"
        mockConfig.runtimes = {RuntimeName.PYTHON: mockRuntimeConfig}
        mockBuildConfig.return_value = mockConfig

        mockManager = AsyncMock()
        mockManager.prepareRuntime = AsyncMock(return_value=True)
        mockManager.installRuntimeLibraries = AsyncMock(return_value=True)
        mockSandboxManagerClass.getInstance.return_value = mockManager
        mockSandboxManagerClass.injectConfig = MagicMock()

        # Run main
        exitCode = await main()

        # Verify prepareRuntime was called with correct runtime
        mockManager.prepareRuntime.assert_called_once_with(RuntimeName.PYTHON)

        # Verify installRuntimeLibraries was called with correct args
        mockManager.installRuntimeLibraries.assert_called_once_with(
            ["numpy", "pandas"], runtime=RuntimeName.PYTHON, upgrade=True
        )

        assert exitCode == 0

    @patch("scripts.sandbox_bootstrap.ensureDirectoryLayout")
    @patch("scripts.sandbox_bootstrap.SandboxManager")
    @patch("scripts.sandbox_bootstrap.ConfigManager")
    @patch("scripts.sandbox_bootstrap.parseArgs")
    @patch("scripts.sandbox_bootstrap.buildConfig")
    @pytest.mark.asyncio
    async def test_mainCallsEnsureDirectoryLayoutWhenInitStorage(
        self,
        mockBuildConfig: MagicMock,
        mockParseArgs: MagicMock,
        mockConfigManagerClass: MagicMock,
        mockSandboxManagerClass: MagicMock,
        mockEnsureDir: MagicMock,
    ) -> None:
        """Verify main() calls ensureDirectoryLayout() when --init-storage is passed."""
        # Setup mocks
        mockArgs = MagicMock()
        mockArgs.config_dir = []
        mockArgs.dotenv = ".env"
        mockArgs.packages = ["numpy"]
        mockArgs.runtime = "python"
        mockArgs.upgrade = False
        mockArgs.init_storage = True
        mockParseArgs.return_value = mockArgs

        mockConfigManager = MagicMock()
        mockConfigManager.get.return_value = {}
        mockConfigManagerClass.return_value = mockConfigManager

        mockConfig = MagicMock()
        mockConfig.storage.rootDir = "/tmp/test"
        mockConfig.storage = MagicMock()
        mockConfig.runtimes = {RuntimeName.PYTHON: MagicMock()}
        mockBuildConfig.return_value = mockConfig

        mockManager = AsyncMock()
        mockManager.prepareRuntime = AsyncMock(return_value=True)
        mockManager.installRuntimeLibraries = AsyncMock(return_value=True)
        mockSandboxManagerClass.getInstance.return_value = mockManager
        mockSandboxManagerClass.injectConfig = MagicMock()

        # Run main
        exitCode = await main()

        # Verify ensureDirectoryLayout was called
        mockEnsureDir.assert_called_once_with(mockConfig.storage)

        assert exitCode == 0

    @patch("scripts.sandbox_bootstrap.SandboxManager")
    @patch("scripts.sandbox_bootstrap.ConfigManager")
    @patch("scripts.sandbox_bootstrap.parseArgs")
    @patch("scripts.sandbox_bootstrap.buildConfig")
    @pytest.mark.asyncio
    async def test_mainReturnsExitCode1OnInstallFailure(
        self,
        mockBuildConfig: MagicMock,
        mockParseArgs: MagicMock,
        mockConfigManagerClass: MagicMock,
        mockSandboxManagerClass: MagicMock,
    ) -> None:
        """Verify main() returns exit code 1 when installRuntimeLibraries raises an exception."""
        # Setup mocks
        mockArgs = MagicMock()
        mockArgs.config_dir = []
        mockArgs.dotenv = ".env"
        mockArgs.packages = ["numpy"]
        mockArgs.runtime = "python"
        mockArgs.upgrade = False
        mockArgs.init_storage = False
        mockParseArgs.return_value = mockArgs

        mockConfigManager = MagicMock()
        mockConfigManager.get.return_value = {}
        mockConfigManagerClass.return_value = mockConfigManager

        mockConfig = MagicMock()
        mockConfig.storage.rootDir = "/tmp/test"
        mockConfig.runtimes = {RuntimeName.PYTHON: MagicMock()}
        mockBuildConfig.return_value = mockConfig

        mockManager = AsyncMock()
        mockManager.prepareRuntime = AsyncMock(return_value=True)
        mockManager.installRuntimeLibraries = AsyncMock(side_effect=Exception("Docker not available"))
        mockSandboxManagerClass.getInstance.return_value = mockManager
        mockSandboxManagerClass.injectConfig = MagicMock()

        # Run main
        exitCode = await main()

        # Verify exit code is 1 on failure
        assert exitCode == 1

    @patch("scripts.sandbox_bootstrap.SandboxManager")
    @patch("scripts.sandbox_bootstrap.ConfigManager")
    @patch("scripts.sandbox_bootstrap.parseArgs")
    @patch("scripts.sandbox_bootstrap.buildConfig")
    @pytest.mark.asyncio
    async def test_mainReturnsExitCode1WhenNoPackagesSpecified(
        self,
        mockBuildConfig: MagicMock,
        mockParseArgs: MagicMock,
        mockConfigManagerClass: MagicMock,
        mockSandboxManagerClass: MagicMock,
    ) -> None:
        """Verify main() returns exit code 1 when no packages are specified and config has none."""
        # Setup mocks
        mockArgs = MagicMock()
        mockArgs.config_dir = []
        mockArgs.dotenv = ".env"
        mockArgs.packages = []
        mockArgs.runtime = "python"
        mockArgs.upgrade = False
        mockArgs.init_storage = False
        mockParseArgs.return_value = mockArgs

        mockConfigManager = MagicMock()
        mockConfigManager.get.return_value = {"starter_packages": []}
        mockConfigManagerClass.return_value = mockConfigManager

        # Run main
        exitCode = await main()

        # Verify exit code is 1 when no packages
        assert exitCode == 1

        # Verify SandboxManager was never initialized
        mockSandboxManagerClass.injectConfig.assert_not_called()

    @patch("scripts.sandbox_bootstrap.SandboxManager")
    @patch("scripts.sandbox_bootstrap.ConfigManager")
    @patch("scripts.sandbox_bootstrap.parseArgs")
    @patch("scripts.sandbox_bootstrap.buildConfig")
    @pytest.mark.asyncio
    async def test_mainReturnsExitCode1WhenInstallFails(
        self,
        mockBuildConfig: MagicMock,
        mockParseArgs: MagicMock,
        mockConfigManagerClass: MagicMock,
        mockSandboxManagerClass: MagicMock,
    ) -> None:
        """Verify main() returns exit code 1 when installRuntimeLibraries returns False."""
        # Setup mocks
        mockArgs = MagicMock()
        mockArgs.config_dir = []
        mockArgs.dotenv = ".env"
        mockArgs.packages = ["numpy"]
        mockArgs.runtime = "python"
        mockArgs.upgrade = False
        mockArgs.init_storage = False
        mockParseArgs.return_value = mockArgs

        mockConfigManager = MagicMock()
        mockConfigManager.get.return_value = {}
        mockConfigManagerClass.return_value = mockConfigManager

        mockConfig = MagicMock()
        mockConfig.storage.rootDir = "/tmp/test"
        mockConfig.runtimes = {RuntimeName.PYTHON: MagicMock()}
        mockBuildConfig.return_value = mockConfig

        mockManager = AsyncMock()
        mockManager.prepareRuntime = AsyncMock(return_value=True)
        mockManager.installRuntimeLibraries = AsyncMock(return_value=False)
        mockSandboxManagerClass.getInstance.return_value = mockManager
        mockSandboxManagerClass.injectConfig = MagicMock()

        # Run main
        exitCode = await main()

        # Verify exit code is 1 when install fails
        assert exitCode == 1


# ============================================================================
# Integration Tests (Docker)
# ============================================================================


@pytest.mark.slow
class TestSandboxBootstrapIntegration:
    """Integration tests with real Docker backend."""

    @pytest.mark.skipif(
        os.environ.get("DOCKER_AVAILABLE") != "1",
        reason="Docker not available (set DOCKER_AVAILABLE=1 to run)",
    )
    @patch("scripts.sandbox_bootstrap.parseArgs")
    @pytest.mark.asyncio
    async def test_realDockerBootstrapWithSmallPackage(self, mockParseArgs: MagicMock) -> None:
        """Test bootstrap with real Docker backend using a small package."""
        # Create temporary config directory
        testWorkspace = Path.home() / ".gromozeka-tests" / "sandbox-bootstrap"
        testWorkspace.mkdir(parents=True, exist_ok=True)

        testConfigDir = testWorkspace / "config"
        testConfigDir.mkdir(exist_ok=True)

        # Create minimal config
        configContent = """
[sandbox]
storage.root_dir = "{workspace}"

[sandbox.runtimes.python]
run_image_tag = "python:3.12-slim"
install_image_tag = "python:3.12-slim"

[sandbox.bootstrap]
starter_packages = ["six"]
""".format(workspace=str(testWorkspace))

        configPath = testConfigDir / "config.toml"
        configPath.write_text(configContent)

        # Setup mock args
        mockArgs = MagicMock()
        mockArgs.config_dir = [str(testConfigDir)]
        mockArgs.dotenv = ".env.test"
        mockArgs.packages = []  # Use config default
        mockArgs.runtime = "python"
        mockArgs.upgrade = False
        mockArgs.init_storage = True
        mockParseArgs.return_value = mockArgs

        # Create .env.test file
        envPath = testWorkspace / ".env.test"
        envPath.write_text("")

        try:
            # Run main
            exitCode = await main()

            # Verify success
            assert exitCode == 0, f"Bootstrap failed with exit code {exitCode}"

            # Verify package was installed
            libsDir = testWorkspace / "runtimes" / "python" / "libs"
            assert libsDir.exists(), "Libraries directory not created"
            assert (libsDir / "six").exists() or any(
                file.name.startswith("six") for file in libsDir.iterdir()
            ), "Package 'six' not found in libs directory"

        finally:
            # Cleanup
            import shutil

            if testWorkspace.exists():
                shutil.rmtree(testWorkspace, ignore_errors=True)


# ============================================================================
# Config Tests
# ============================================================================


class TestSandboxBootstrapConfig:
    """Tests for buildConfig function."""

    @pytest.fixture
    def mockConfigManager(self) -> MagicMock:
        """Create mock ConfigManager."""
        return MagicMock()

    def test_buildConfigLoadsSandboxSettings(self, mockConfigManager: MagicMock) -> None:
        """Verify buildConfig loads sandbox settings from ConfigManager."""
        mockConfigManager.get.return_value = {
            "storage": {"root-dir": "/tmp/sandbox", "dir-mode": "0o700", "file-mode": "0o600"},
            "runtimes": {"python": {}},
        }

        config = buildConfig(mockConfigManager)

        # Verify ConfigManager.get was called with correct key
        mockConfigManager.get.assert_called_once_with("sandbox", {})

        # Verify config was built
        assert config is not None
