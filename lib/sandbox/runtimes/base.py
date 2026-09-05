"""Protocol for language runtimes in the sandbox system.

Defines the :class:`Runtime` protocol that every language runtime
(Python, TypeScript, Bash) must implement so that :class:`SandboxManager`
can build commands and detect artifacts without knowing the concrete
implementation.

Classes:
    Runtime: Protocol for language runtimes.
    StagingRun: Container-side plan (command + mounts) for one staging container.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import List

from ..config import BasicRuntimeConfig
from ..enums import RuntimeName
from ..types import ContainerOutcome, PackageInfo, ResourceLimits


@dataclass(frozen=True, slots=True)
class StagingRun:
    """Container-side plan for one staging container (pre-filter or stage).

    Built and returned by the runtime — the owner of its container-side
    layout — and consumed verbatim by :class:`SandboxManager` when
    assembling the :class:`ContainerSpec`.

    Attributes:
        command: Container argv (single argv, no shell).
        mounts: Volume mount specifications, same shape as
            :attr:`ContainerSpec.mounts`.
    """

    command: list[str]
    """Container argv (single argv, no shell)."""

    mounts: list[dict[str, str]]
    """Volume mount specifications (hostPath, containerPath, mode)."""


class Runtime(ABC):
    """Protocol for language runtimes (Python, TypeScript, Bash).

    Every runtime must implement this interface so that :class:`SandboxManager`
    can construct execution commands and detect output artifacts without
    knowing the concrete runtime implementation.
    """

    name: RuntimeName

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
    def reportRun(self, hostStagingIoDir: Path, specs: Sequence[str]) -> StagingRun:
        """Build the full container plan for the dry-run pre-filter (report mode).

        The runtime owns its container-side layout: it returns the complete
        argv plus the mount list (the staging io subtree bind rw and the
        helper script bind ro), so the manager never assembles mounts itself.

        Args:
            hostStagingIoDir: Host-side per-run staging I/O directory (the
                run dir's ``io/`` subtree) to bind rw into the container.
            specs: Package specs to resolve (already validated host-side).

        Returns:
            The StagingRun plan (command + mounts) for the pre-filter container.
        """
        ...

    @abstractmethod
    def stageRun(self, hostStagingIoDir: Path, specs: Sequence[str]) -> StagingRun:
        """Build the full container plan for the staged install (install mode).

        The runtime owns its container-side layout: it returns the complete
        argv plus the mount list (the staging io subtree bind rw and the
        helper script bind ro), so the manager never assembles mounts itself.

        Args:
            hostStagingIoDir: Host-side per-run staging I/O directory (the
                run dir's ``io/`` subtree) to bind rw into the container.
            specs: Package specs to install into the staging delta.

        Returns:
            The StagingRun plan (command + mounts) for the stage container.
        """
        ...

    @abstractmethod
    def updateHelperHostPath(self) -> Path:
        """Return the host-side path of the update helper script.

        The runtime uses this path to construct the helper's read-only bind
        mount in its StagingRun plan. The manager also uses it to verify
        that the helper exists before staging.

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
