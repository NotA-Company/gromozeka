"""Protocol for language runtimes in the sandbox system.

Defines the :class:`Runtime` protocol that every language runtime
(Python, TypeScript, Bash) must implement so that :class:`SandboxManager`
can build commands and detect artifacts without knowing the concrete
implementation.

Classes:
    Runtime: Protocol for language runtimes.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import List

from ..config import BasicRuntimeConfig
from ..enums import RuntimeName
from ..types import ContainerOutcome, PackageInfo, ResourceLimits


class Runtime(ABC):
    """Protocol for language runtimes (Python, TypeScript, Bash).

    Every runtime must implement this interface so that :class:`SandboxManager`
    can construct execution commands and detect output artifacts without
    knowing the concrete runtime implementation.
    """

    name: RuntimeName

    UPDATE_HELPER_CONTAINER_PATH: str
    """Container-side path where the update helper script is mounted.

    Set by concrete runtimes; the manager mounts the file returned by
    ``updateHelperHostPath()`` at this path, read-only.
    """

    STAGING_CONTAINER_PATH: str
    """Container-side mount target of the per-run staging directory.

    Set by concrete runtimes; the manager mounts the per-run staging
    directory's container I/O subtree (``io/``) read-write at this path for
    the update containers (dry-run report, staged pip delta). The live pool,
    the pool copies (``newpool``/``oldpool``) and the rest of the run dir are
    never mounted into staging containers
    (docs/plans/sandbox-update-v1.md §4.2).
    """

    def __init__(self, config: BasicRuntimeConfig) -> None:
        """Initialize the runtime with configuration.

        Args:
            config: Basic runtime configuration settings.
        """
        super().__init__()
        self._config = config
        self._prepared: bool = False

    def markPrepared(self) -> None:
        """Mark the runtime as prepared for execution.

        This should be called after the runtime has been set up
        (e.g., after base container creation or package installation).
        """
        self._prepared = True

    def isPrepared(self) -> bool:
        """Check if the runtime has been marked as prepared.

        Returns:
            True if the runtime is prepared, False otherwise.
        """
        return self._prepared

    @abstractmethod
    def getScriptName(self) -> str:
        """Return the filename of the script to execute.

        Returns:
            The script filename (e.g., "main.py" for Python).
        """

    @abstractmethod
    def runCommand(
        self,
        runId: str,
        *,
        hasStdin: bool,
        limits: ResourceLimits,
    ) -> list[str]:
        """Build the command-line invocation for executing code.

        Args:
            runId: Unique identifier for this run (used in container naming).
            hasStdin: Whether the run expects stdin input.
            limits: Resource limits to apply to the execution.

        Returns:
            Command and arguments as a list of strings.
        """
        ...

    @abstractmethod
    def reportCommand(self, specs: Sequence[str]) -> list[str]:
        """Build the dry-run pre-filter container command (report mode).

        Args:
            specs: Package specs to resolve (already validated host-side).

        Returns:
            Command and arguments as a single argv list (no shell).
        """
        ...

    @abstractmethod
    def stageInstallCommand(self, specs: Sequence[str]) -> list[str]:
        """Build the staged-install container command (install mode).

        Args:
            specs: Package specs to install into the staging delta.

        Returns:
            Command and arguments as a single argv list (no shell).
        """
        ...

    @abstractmethod
    def updateHelperHostPath(self) -> Path:
        """Return the host-side path of the update helper script.

        The manager mounts this file read-only into the update container.

        Returns:
            Path derived from the install Dockerfile's directory.
        """
        ...

    @abstractmethod
    def listCommand(self, stdoutPath: str, stderrPath: str) -> list[str]:
        """Build the command-line invocation for listing installed packages.

        Returns:
            Command and arguments as a list of strings.
        """
        ...

    @abstractmethod
    def parseListCommandOutput(self, outcome: ContainerOutcome, stdout: str, stderr: str) -> List[PackageInfo]:
        """Parse the output from the list packages command.

        Args:
            outcome: Container outcome from the list command.
            stdout: Standard output from the list command.
            stderr: Standard error from the list command.

        Returns:
            List of PackageInfo for installed packages.
        """
        ...

    async def validatePackageSpec(self, spec: str) -> None:
        """Validate a package spec for install.

        Rejects specs containing shell metacharacters or starting with '-'.
        Base implementation is a no-op; concrete runtimes may override with
        actual validation.

        Args:
            spec: The package spec string.
        """
        # By default - no extra validation needed
        return
