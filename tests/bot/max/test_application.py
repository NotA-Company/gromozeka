"""Tests for MaxBotApplication path resolution."""

import os
import tempfile
from pathlib import Path

from internal.bot.max import application as maxApp


class TestCertPathResolution:
    """Tests for ``max-ca-bundle`` path resolution."""

    def testResolveCaBundlePathRelative(self) -> None:
        """A relative path resolves against the current working directory.

        After ``os.chdir()``, relative paths resolve against the new cwd
        rather than a previously captured startup cwd. This matches the
        behavior of every other relative path in the project.
        """
        originalCwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmpDir:
            os.chdir(tmpDir)
            try:
                result = maxApp._resolveCaBundlePath("certs/max")
                expected = str(Path(tmpDir).resolve() / "certs" / "max")
                assert result == expected, f"Expected {expected}, got {result}"
            finally:
                os.chdir(str(originalCwd))

    def testResolveCaBundlePathAbsolute(self) -> None:
        """An absolute path passes through unchanged."""
        result = maxApp._resolveCaBundlePath("/absolute/path/to/ca.pem")
        assert result == "/absolute/path/to/ca.pem"

    def testResolveCaBundlePathEmpty(self) -> None:
        """An empty string returns an empty string (no CA bundle configured)."""
        assert maxApp._resolveCaBundlePath("") == ""
