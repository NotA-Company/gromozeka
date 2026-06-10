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
