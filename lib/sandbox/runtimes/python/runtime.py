"""Python language runtime for sandboxed execution.

Generates Docker commands for running Python code with timeout enforcement,
package installation, and artifact detection.  Implements the
:class:`lib.sandbox.runtimes.base.Runtime` protocol.

Classes:
    PythonRuntime: Concrete runtime for executing Python code inside
        sandbox containers.
"""

import json
import logging
from pathlib import Path
from typing import List, Sequence

from packaging.requirements import Requirement

from lib.sandbox.backends.base import ContainerOutcome

from ...enums import RuntimeName
from ...errors import InvalidPackageSpec
from ...types import PackageInfo, ResourceLimits
from ..base import Runtime

logger = logging.getLogger(__name__)


class PythonRuntime(Runtime):
    """Python language runtime for sandboxed execution.

    Generates Docker commands for running Python code with timeout
    enforcement, package installation, and artifact detection.

    Attributes:
        name: Identifies this runtime as Python.
    """

    name: RuntimeName = RuntimeName.PYTHON

    UPDATE_HELPER_CONTAINER_PATH = "/sandbox/pool_pip_runner.py"
    """Container-side path where the manager mounts the update helper script."""

    STAGING_CONTAINER_PATH = "/sandbox/staging"
    """Container-side mount target of the per-run staging directory.

    Both update containers mount the run dir's ``io/`` subtree
    (``<storage-root>/tmp/<runId>/io``) rw here: the dry-run report lands at
    ``<staging>/report.json`` and the pip delta at ``<staging>/delta``. The
    live pool, the pool copies (``newpool``/``oldpool``) and the rest of the
    run dir are never mounted into update containers
    (docs/plans/sandbox-update-v1.md §4.2).
    """

    def getScriptName(self) -> str:
        """Get the script file name for this runtime.

        Returns:
            The script file name.
        """
        return "main.py"

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
                f"cd /workspace/.run/{runId}/work && "
                f"python -u /workspace/.run/{runId}/{self.getScriptName()} "
                f"{stdinPart} "
                f"> /workspace/.run/{runId}/stdout.log "
                f"2> /workspace/.run/{runId}/stderr.log"
            ),
        ]
        return cmd

    def reportCommand(self, specs: Sequence[str]) -> list[str]:
        """Build the dry-run pre-filter container command (report mode).

        Single argv, no shell: the helper execs
        ``pip install --dry-run --report <staging>/report.json`` inside the
        container; the live pool is not mounted into this container.

        Args:
            specs: Package specs to resolve (already validated host-side).

        Returns:
            Command and arguments as a single argv list (no shell).
        """
        return [
            "python",
            self.UPDATE_HELPER_CONTAINER_PATH,
            "--report",
            f"{self.STAGING_CONTAINER_PATH}/report.json",
            "--",
            *specs,
        ]

    def stageInstallCommand(self, specs: Sequence[str]) -> list[str]:
        """Build the staged-install container command (install mode).

        Single argv, no shell: the helper execs
        ``pip install --target <staging>/delta`` inside the container; the
        live pool is not mounted into this container.

        Args:
            specs: Package specs to install into the staging delta.

        Returns:
            Command and arguments as a single argv list (no shell).
        """
        return [
            "python",
            self.UPDATE_HELPER_CONTAINER_PATH,
            "--install-into",
            f"{self.STAGING_CONTAINER_PATH}/delta",
            "--",
            *specs,
        ]

    def updateHelperHostPath(self) -> Path:
        """Return the host-side path of the update helper script.

        The manager mounts this file read-only into the update container.
        Derived from the install Dockerfile's directory — zero new config
        keys, same directory convention as the Dockerfiles.

        Returns:
            Path of ``pool_pip_runner.py`` next to the install Dockerfile.
        """
        return Path(self._config.installDockerfile).parent / "pool_pip_runner.py"

    def listCommand(self, stdoutPath: str, stderrPath: str) -> list[str]:
        """Build the Docker command for listing installed packages.

        Returns:
            Command list that outputs JSON to stdout.
        """
        return [
            "sh",
            "-c",
            (
                f"python -m pip list --format=json --path '{self._config.libMountPath}' "
                f"> {stdoutPath} "
                f"2> {stderrPath}"
            ),
        ]

    def parseListCommandOutput(self, outcome: ContainerOutcome, stdout: str, stderr: str) -> List[PackageInfo]:
        """Parse the output from the list command.

        Args:
            outcome: The container execution outcome (unused but part of protocol).
            stdout: The stdout content from the list command.
            stderr: The stderr content from the list command.

        Returns:
            List of installed package information.
        """
        ret: List[PackageInfo] = []
        if not stdout:
            return ret
        try:
            data = json.loads(stdout)
            if not isinstance(data, list):
                logger.error(f"Expected JSON-serialized list of objects, but got: {type(data).__name__}({data!r})")
                return ret
            for pkgInfo in data:
                if not isinstance(pkgInfo, dict):
                    logger.error(f"Each element should be dict, but got {type(pkgInfo).__name__}({pkgInfo!r})")
                    continue
                ret.append(PackageInfo(name=pkgInfo["name"], version=pkgInfo["version"]))
        except json.JSONDecodeError as exc:
            logger.exception(exc)
            logger.error(f"Can not parse pip list output: {exc}")
        return ret

    async def validatePackageSpec(self, spec: str) -> None:
        """Validate a package spec for install.

        Rejects specs containing shell metacharacters or starting with '-'.

        Args:
            spec: The package spec string.

        Raises:
            InvalidPackageSpec: If the spec is invalid.
        """
        # Basic PEP 508 validation (lightweight)
        try:
            Requirement(spec)
        except Exception as exc:
            raise InvalidPackageSpec(spec=spec, reason=str(exc)) from exc
