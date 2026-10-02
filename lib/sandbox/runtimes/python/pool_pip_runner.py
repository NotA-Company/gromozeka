"""In-container thin pip runner for the staged sandbox library-pool update flow.

Runs inside the one-shot update containers (the ``gromozeka-sandbox-python:install``
image). Stdlib only. It is a pure argv adaptor: it translates one of two
mutually exclusive CLI modes into a single ``pip install`` invocation executed
via ``subprocess.run`` (argv list, no shell) and exits with pip's exit code.
All pool-structural logic (enumeration, merge, swap) lives host-side in
``pool_staging.py`` — pip never touches the live pool
(docs/plans/sandbox-update-v1.md §4.2).

Modes:

- ``--report <file>``: dry-run resolution report for the given specs —
  ``pip install --dry-run --report <file> --target /tmp/pip-dryrun-scratch
  --no-cache-dir --no-input -- <specs>``. Non-mutating: under ``--dry-run``
  the scratch target stays empty.
- ``--install-into <dir>``: real install of the given specs into the staging
  delta directory — ``pip install --target <dir> --no-cache-dir --no-input --
  <specs>``. The live pool is never passed to this helper.

The ``--`` separator before the specs blocks pip option injection; pool-derived
names are additionally grammar-validated host-side (plan §6).

Functions:
    buildReportCommand: Build the report-mode pip argv.
    buildInstallCommand: Build the install-mode pip argv.
    main: CLI entry point (exactly one mode; exit code equals pip's).
"""

import argparse
import subprocess
import sys
from typing import Sequence

DRY_RUN_SCRATCH_TARGET = "/tmp/pip-dryrun-scratch"
"""Report-mode ``--target`` scratch directory.

In-container temp; under ``--dry-run`` pip never populates it (plan §1.2
fact 5), so report mode mutates nothing.
"""

PIP_SHARED_FLAGS: list[str] = ["--no-cache-dir", "--no-input"]
"""Pip flags shared by both modes (no cache: the containers are one-shot and ephemeral)."""


def buildReportCommand(reportPath: str, specs: Sequence[str]) -> list[str]:
    """Build the report-mode pip argv (dry-run resolution report).

    Args:
        reportPath: Container-side path where pip writes the JSON report.
        specs: Package specs to resolve (already validated host-side).

    Returns:
        Complete argv for subprocess.run (no shell); ``--`` precedes the
        specs so they cannot parse as pip options.
    """
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--dry-run",
        "--report",
        reportPath,
        "--target",
        DRY_RUN_SCRATCH_TARGET,
        *PIP_SHARED_FLAGS,
        "--",
    ]
    cmd.extend(specs)
    return cmd


def buildInstallCommand(targetDir: str, specs: Sequence[str]) -> list[str]:
    """Build the install-mode pip argv (staged delta install).

    Args:
        targetDir: Container-side directory pip installs into (the staging
            delta; never the live pool).
        specs: Package specs to install (already validated host-side).

    Returns:
        Complete argv for subprocess.run (no shell); ``--`` precedes the
        specs so they cannot parse as pip options.
    """
    cmd = [sys.executable, "-m", "pip", "install", "--target", targetDir, *PIP_SHARED_FLAGS, "--"]
    cmd.extend(specs)
    return cmd


def main(argv: Sequence[str] | None = None) -> int:
    """Run exactly one pip mode and propagate its exit code.

    Args:
        argv: Command-line arguments (defaults to sys.argv). Exactly one of
            ``--report <file>`` / ``--install-into <dir>`` is required; the
            positional specs follow the ``--`` separator.

    Returns:
        Pip's exit code. Usage errors (zero or both mode flags) exit with
        argparse's code 2 before pip runs.
    """
    parser = argparse.ArgumentParser(description="Thin pip runner for the sandbox pool update flow.")
    modeGroup = parser.add_mutually_exclusive_group(required=True)
    modeGroup.add_argument(
        "--report",
        dest="reportPath",
        metavar="file",
        help="Dry-run resolve the specs and write the pip JSON report to <file> (mutates nothing).",
    )
    modeGroup.add_argument(
        "--install-into",
        dest="installInto",
        metavar="dir",
        help="Install the specs into <dir> (the staging delta).",
    )
    parser.add_argument("specs", nargs="*", metavar="spec", help="PEP 508 specs; must follow a ``--`` separator.")
    args = parser.parse_args(argv)

    reportPath = args.reportPath
    installInto = args.installInto
    if reportPath is not None:
        cmd = buildReportCommand(reportPath, args.specs)
    elif installInto is not None:
        cmd = buildInstallCommand(installInto, args.specs)
    else:
        # Unreachable: the mutually exclusive group is required, so argparse
        # exits before this point. Kept as a typed defensive fallback.
        parser.error("Exactly one of --report / --install-into is required")
    pipResult = subprocess.run(cmd, check=False)
    return pipResult.returncode


if __name__ == "__main__":
    sys.exit(main())
