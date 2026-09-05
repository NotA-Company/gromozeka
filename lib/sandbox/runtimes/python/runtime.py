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
from ..base import Runtime, StagingRun

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
    """Container-side path where this runtime's update helper is mounted (ro)."""

    STAGING_CONTAINER_PATH = "/sandbox/staging"
    """Container-side mount target of the staging run dir's ``io/`` subtree (rw)."""

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

    def _buildStagingMounts(self, hostStagingIoDir: Path) -> list[dict[str, str]]:
        """Build the mounts shared by both staging containers (plan §4.2).

        Only the run dir's container I/O subtree is mounted read-write, plus
        the helper script read-only. The rest of the run dir — ``newpool``
        and ``oldpool`` in particular — is never visible to a container:
        package build code must not be able to modify the future live pool
        copy and bypass the controlled merge. The live pool itself is NEVER
        mounted into a networked container — pip (the attack surface touching
        PyPI) only ever sees a scratch delta.

        Args:
            hostStagingIoDir: Host-side per-run staging I/O directory (the
                run dir's ``io/`` subtree; must already exist).

        Returns:
            Mount list for the StagingRun.
        """
        return [
            {
                "hostPath": str(hostStagingIoDir.absolute()),
                "containerPath": self.STAGING_CONTAINER_PATH,
                "mode": "rw",
            },
            {
                "hostPath": str(self.updateHelperHostPath().absolute()),
                "containerPath": self.UPDATE_HELPER_CONTAINER_PATH,
                "mode": "ro",
            },
        ]

    def reportRun(self, hostStagingIoDir: Path, specs: Sequence[str]) -> StagingRun:
        """Build the full container plan for the dry-run pre-filter (report mode).

        Single argv, no shell: the helper execs
        ``pip install --dry-run --report <staging>/report.json`` inside the
        container; the live pool is not mounted into this container.

        Args:
            hostStagingIoDir: Host-side per-run staging I/O directory to bind
                rw at :attr:`STAGING_CONTAINER_PATH`.
            specs: Package specs to resolve (already validated host-side).

        Returns:
            The StagingRun plan (command + mounts) for the pre-filter container.
        """
        return StagingRun(
            command=[
                "python",
                self.UPDATE_HELPER_CONTAINER_PATH,
                "--report",
                f"{self.STAGING_CONTAINER_PATH}/report.json",
                "--",
                *specs,
            ],
            mounts=self._buildStagingMounts(hostStagingIoDir),
        )

    def stageRun(self, hostStagingIoDir: Path, specs: Sequence[str]) -> StagingRun:
        """Build the full container plan for the staged install (install mode).

        Single argv, no shell: the helper execs
        ``pip install --target <staging>/delta`` inside the container; the
        live pool is not mounted into this container.

        Args:
            hostStagingIoDir: Host-side per-run staging I/O directory to bind
                rw at :attr:`STAGING_CONTAINER_PATH`.
            specs: Package specs to install into the staging delta.

        Returns:
            The StagingRun plan (command + mounts) for the stage container.
        """
        return StagingRun(
            command=[
                "python",
                self.UPDATE_HELPER_CONTAINER_PATH,
                "--install-into",
                f"{self.STAGING_CONTAINER_PATH}/delta",
                "--",
                *specs,
            ],
            mounts=self._buildStagingMounts(hostStagingIoDir),
        )

    def updateHelperHostPath(self) -> Path:
        """Return the host-side path of the update helper script.

        The runtime uses this path to construct the helper's read-only bind
        mount in its StagingRun plan. The manager also uses it to verify
        that the helper exists before staging. Derived from the install
        Dockerfile's directory — zero new config keys, same directory
        convention as the Dockerfiles.

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
