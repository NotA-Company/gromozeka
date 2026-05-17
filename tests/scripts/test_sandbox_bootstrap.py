"""Tests for the sandbox bootstrap script."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib.sandbox.enums import RuntimeName  # noqa: E402
from scripts.sandbox_bootstrap import buildConfig, parseArgs  # noqa: E402


class TestSandboxBootstrap:
    """Tests for sandbox-bootstrap.py."""

    def test_buildConfigUsesRootDir(self) -> None:
        """Verify buildConfig creates a config with the given rootDir."""
        config = buildConfig("/custom/path")
        assert config.storage.rootDir == "/custom/path"

    def test_buildConfigIncludesPythonRuntime(self) -> None:
        """Verify buildConfig sets up the Python runtime."""
        config = buildConfig("/tmp/test")
        assert RuntimeName.PYTHON in config.runtimes

    def test_parseArgsDefaults(self) -> None:
        """Verify default argument parsing."""
        with patch("sys.argv", ["sandbox-bootstrap.py"]):
            args = parseArgs()
            assert args.runtime == "python"
            assert args.upgrade is False
            assert args.init_storage is False
            assert args.root_dir == "/var/lib/gromozeka/sandbox"

    def test_parseArgsCustomRoot(self) -> None:
        """Verify custom root-dir argument."""
        with patch("sys.argv", ["sandbox-bootstrap.py", "--root-dir", "/custom"]):
            args = parseArgs()
            assert args.root_dir == "/custom"

    def test_parseArgsUpgrade(self) -> None:
        """Verify --upgrade flag."""
        with patch("sys.argv", ["sandbox-bootstrap.py", "--upgrade"]):
            args = parseArgs()
            assert args.upgrade is True

    def test_parseArgsInitStorage(self) -> None:
        """Verify --init-storage flag."""
        with patch("sys.argv", ["sandbox-bootstrap.py", "--init-storage"]):
            args = parseArgs()
            assert args.init_storage is True
