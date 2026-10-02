"""Tests for the in-container thin pip runner (pool_pip_runner.py).

Covers the ratified contract (docs/plans/sandbox-update-v1.md §12): argv
shape for both modes (dry-run + report + scratch ``--target``; install-into
``--target``), the mandatory ``--`` separator before the specs, no shell
involvement, pip exit-code passthrough, report-mode non-mutation
(``--dry-run``, temp scratch target, no ``--upgrade``), and the
exactly-one-mode requirement (mutually exclusive, one required). Pip never
runs: subprocess.run is monkeypatched.
"""

import sys
from types import SimpleNamespace

import pytest

from lib.sandbox.runtimes.python import pool_pip_runner

REPORT_PATH = "/sandbox/staging/report.json"
"""Report-mode container path used across the tests."""

DELTA_DIR = "/sandbox/staging/delta"
"""Install-mode container path used across the tests."""


class _FakePip:
    """Monkeypatch replacement for subprocess.run representing pip.

    Records every invocation and reports a configured exit code.

    Attributes:
        calls: Recorded argv lists.
        exitCode: Exit code reported for every invocation.
    """

    def __init__(self, exitCode: int) -> None:
        """Initialize the fake pip.

        Args:
            exitCode: Exit code to report via ``returncode``.
        """
        self.calls: list[list[str]] = []
        self.exitCode: int = exitCode

    def __call__(self, cmd: list[str], **kwargs: object) -> SimpleNamespace:
        """Record the invocation and report the configured exit code.

        Args:
            cmd: The argv of the attempted subprocess call.
            **kwargs: Keyword arguments from the caller (ignored).

        Returns:
            An object mimicking CompletedProcess with the configured returncode.
        """
        self.calls.append(list(cmd))
        return SimpleNamespace(returncode=self.exitCode)


def _patchPip(monkeypatch: pytest.MonkeyPatch, fakePip: _FakePip) -> None:
    """Replace subprocess.run used by the helper with the given fake.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        fakePip: The fake pip callable to install.

    Returns:
        None
    """
    monkeypatch.setattr(pool_pip_runner.subprocess, "run", fakePip)


# ============================================================================
# Report mode (--report)
# ============================================================================


class TestReportMode:
    """Tests for the --report dry-run pre-filter mode."""

    def testArgvShape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report mode execs pip dry-run with the report file, scratch target, and specs.

        Args:
            monkeypatch: The pytest monkeypatch fixture.

        Returns:
            None
        """
        fakePip = _FakePip(exitCode=0)
        _patchPip(monkeypatch, fakePip)

        exitCode = pool_pip_runner.main(["--report", REPORT_PATH, "--", "numpy>=2.0", "requests"])

        assert exitCode == 0
        assert len(fakePip.calls) == 1
        assert fakePip.calls[0] == [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--report",
            REPORT_PATH,
            "--target",
            pool_pip_runner.DRY_RUN_SCRATCH_TARGET,
            "--no-cache-dir",
            "--no-input",
            "--",
            "numpy>=2.0",
            "requests",
        ]

    def testMutatesNothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report mode pins --dry-run, no --upgrade, and an ephemeral scratch target.

        Args:
            monkeypatch: The pytest monkeypatch fixture.

        Returns:
            None
        """
        fakePip = _FakePip(exitCode=0)
        _patchPip(monkeypatch, fakePip)

        pool_pip_runner.main(["--report", REPORT_PATH, "--", "numpy"])

        argv = fakePip.calls[0]
        assert "--dry-run" in argv, "report mode must be a dry run — it may not install anything"
        assert "--upgrade" not in argv
        scratchTarget = argv[argv.index("--target") + 1]
        assert scratchTarget.startswith("/tmp/"), "the scratch --target must stay in container temp space"

    def testExitCodePassthrough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A pip failure exit code propagates unchanged.

        Args:
            monkeypatch: The pytest monkeypatch fixture.

        Returns:
            None
        """
        fakePip = _FakePip(exitCode=1)
        _patchPip(monkeypatch, fakePip)

        exitCode = pool_pip_runner.main(["--report", REPORT_PATH, "--", "broken-pkg"])

        assert exitCode == 1

    def testNoShell(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The pip invocation is a single argv list — no shell, no string command.

        Args:
            monkeypatch: The pytest monkeypatch fixture.

        Returns:
            None
        """
        fakePip = _FakePip(exitCode=0)
        _patchPip(monkeypatch, fakePip)

        pool_pip_runner.main(["--report", REPORT_PATH, "--", "numpy"])

        argv = fakePip.calls[0]
        assert isinstance(argv, list)
        assert all(isinstance(part, str) for part in argv)
        assert "sh" not in argv
        assert "-c" not in argv


# ============================================================================
# Install mode (--install-into)
# ============================================================================


class TestInstallMode:
    """Tests for the --install-into staging mode."""

    def testArgvShape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Install mode execs pip install --target <delta> followed by the specs.

        Args:
            monkeypatch: The pytest monkeypatch fixture.

        Returns:
            None
        """
        fakePip = _FakePip(exitCode=0)
        _patchPip(monkeypatch, fakePip)

        exitCode = pool_pip_runner.main(["--install-into", DELTA_DIR, "--", "numpy>=2.0", "requests"])

        assert exitCode == 0
        assert len(fakePip.calls) == 1
        assert fakePip.calls[0] == [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            DELTA_DIR,
            "--no-cache-dir",
            "--no-input",
            "--",
            "numpy>=2.0",
            "requests",
        ]

    def testNoDryRunFlag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The install mode is a real install — --dry-run must be absent.

        Args:
            monkeypatch: The pytest monkeypatch fixture.

        Returns:
            None
        """
        fakePip = _FakePip(exitCode=0)
        _patchPip(monkeypatch, fakePip)

        pool_pip_runner.main(["--install-into", DELTA_DIR, "--", "numpy"])

        assert "--dry-run" not in fakePip.calls[0]

    def testExitCodePassthrough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A pip failure exit code propagates unchanged in install mode.

        Args:
            monkeypatch: The pytest monkeypatch fixture.

        Returns:
            None
        """
        fakePip = _FakePip(exitCode=3)
        _patchPip(monkeypatch, fakePip)

        exitCode = pool_pip_runner.main(["--install-into", DELTA_DIR, "--", "broken-pkg"])

        assert exitCode == 3


# ============================================================================
# Mode guards (exactly one mode required)
# ============================================================================


class TestModeGuards:
    """Exactly one mode flag is required; the flags are mutually exclusive."""

    def testBothModesRejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Passing both --report and --install-into is a usage error before pip runs.

        Args:
            monkeypatch: The pytest monkeypatch fixture.

        Returns:
            None
        """
        fakePip = _FakePip(exitCode=0)
        _patchPip(monkeypatch, fakePip)

        with pytest.raises(SystemExit) as excInfo:
            pool_pip_runner.main(["--report", REPORT_PATH, "--install-into", DELTA_DIR, "--", "numpy"])

        assert excInfo.value.code == 2
        assert fakePip.calls == []

    def testNoModeRejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Passing neither mode flag is a usage error before pip runs.

        Args:
            monkeypatch: The pytest monkeypatch fixture.

        Returns:
            None
        """
        fakePip = _FakePip(exitCode=0)
        _patchPip(monkeypatch, fakePip)

        with pytest.raises(SystemExit) as excInfo:
            pool_pip_runner.main(["--", "numpy"])

        assert excInfo.value.code == 2
        assert fakePip.calls == []


# ============================================================================
# Argv builders (-- separator invariant, pinned at the builder level too)
# ============================================================================


class TestBuilders:
    """The argv builders main() delegates to."""

    def testReportCommandSeparatorBeforeSpecs(self) -> None:
        """buildReportCommand places -- before the specs and after all pip flags.

        Args:
            None

        Returns:
            None
        """
        cmd = pool_pip_runner.buildReportCommand(REPORT_PATH, ["numpy>=2.0", "requests"])
        separatorIdx = cmd.index("--")
        assert separatorIdx < len(cmd) - 1, "-- must precede the specs"
        assert cmd[separatorIdx + 1 :] == ["numpy>=2.0", "requests"]

    def testInstallCommandSeparatorBeforeSpecs(self) -> None:
        """buildInstallCommand places -- before the specs and after all pip flags.

        Args:
            None

        Returns:
            None
        """
        cmd = pool_pip_runner.buildInstallCommand(DELTA_DIR, ["numpy"])
        separatorIdx = cmd.index("--")
        assert separatorIdx < len(cmd) - 1, "-- must precede the specs"
        assert cmd[separatorIdx + 1 :] == ["numpy"]
