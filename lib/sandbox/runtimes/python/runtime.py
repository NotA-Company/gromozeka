"""Python language runtime for sandboxed execution.

Generates Docker commands for running Python code with timeout enforcement,
package installation, and artifact detection.  Implements the
:class:`lib.sandbox.runtimes.base.Runtime` protocol.

Classes:
    PythonRuntime: Concrete runtime for executing Python code inside
        sandbox containers.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from lib.sandbox.config import PythonRuntimeConfig
from lib.sandbox.enums import RuntimeName
from lib.sandbox.types import ArtifactInfo, ResourceLimits

logger = logging.getLogger(__name__)


class PythonRuntime:
    """Python language runtime for sandboxed execution.

    Generates Docker commands for running Python code with timeout
    enforcement, package installation, and artifact detection.

    Attributes:
        name: Identifies this runtime as Python.
    """

    name: RuntimeName = RuntimeName.PYTHON

    def __init__(self, config: PythonRuntimeConfig) -> None:
        """Initialise the Python runtime.

        Args:
            config: Python runtime configuration.
        """
        self._config = config

    def runCommand(
        self,
        runId: str,
        *,
        hasStdin: bool,
        limits: ResourceLimits,
    ) -> list[str]:
        """Build the Docker command for executing Python code.

        Uses coreutils ``timeout`` for defense-in-depth: SIGTERM after
        *timeoutSeconds*, then SIGKILL after *timeoutGraceSeconds*.
        Exit code 124 indicates a timeout.

        Args:
            runId: The run identifier (for path construction).
            hasStdin: Whether a stdin file exists.
            limits: Resource limits for this run.

        Returns:
            Command list suitable for ``ContainerSpec.command``.
        """
        stdinPart = f"< /workspace/.run/{runId}/stdin" if hasStdin else ""
        cmd = [
            "timeout",
            "-s",
            "TERM",
            "-k",
            str(limits.timeoutGraceSeconds),
            str(limits.timeoutSeconds),
            "sh",
            "-c",
            (
                f"python -u /workspace/.run/{runId}/main.py "
                f"{stdinPart} "
                f"> /workspace/.run/{runId}/stdout.log "
                f"2> /workspace/.run/{runId}/stderr.log"
            ),
        ]
        return cmd

    def installCommand(
        self,
        packages: Sequence[str],
        *,
        upgrade: bool,
    ) -> list[str]:
        """Build the Docker command for installing packages into the lib pool.

        Args:
            packages: Package specs to install.
            upgrade: If True, pass ``--upgrade`` to pip.

        Returns:
            Command list for the install container.
        """
        cmd = [
            "python",
            "-m",
            "pip",
            "install",
            "--target",
            self._config.libMountPath,
            "--no-cache-dir",
            "--no-input",
        ]
        if upgrade:
            cmd.append("--upgrade")
        cmd.extend(packages)
        return cmd

    def listCommand(self) -> list[str]:
        """Build the Docker command for listing installed packages.

        Returns:
            Command list that outputs JSON to stdout.
        """
        return [
            "python",
            "-m",
            "pip",
            "list",
            "--format=json",
            "--path",
            self._config.libMountPath,
        ]

    def detectArtifacts(
        self,
        workspacePath: Path,
        *,
        sinceMtime: float,
    ) -> list[ArtifactInfo]:
        """Walk the workspace excluding ``.run/``, return files newer than *sinceMtime*.

        Args:
            workspacePath: The session workspace directory.
            sinceMtime: Timestamp (float) to compare file mtimes against.

        Returns:
            List of :class:`ArtifactInfo` for new or modified files.
        """
        results: list[ArtifactInfo] = []
        runDir = workspacePath / ".run"

        for entry in workspacePath.rglob("*"):
            # Skip .run/ directory and everything under it
            try:
                entry.relative_to(runDir)
                continue  # This is under .run/
            except ValueError:
                pass  # Not under .run/

            if entry.is_file():
                try:
                    stat = entry.stat()
                    if stat.st_mtime > sinceMtime:
                        results.append(
                            ArtifactInfo(
                                path=str(entry.relative_to(workspacePath)),
                                sizeBytes=stat.st_size,
                                modifiedAt=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                                mimeType=None,
                                sha256=None,
                            )
                        )
                except OSError:
                    continue

        return results
