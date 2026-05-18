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
    def installCommand(
        self,
        packages: Sequence[str],
        *,
        upgrade: bool,
    ) -> list[str]:
        """Build the command-line invocation for installing packages.

        Args:
            packages: Package names to install.
            upgrade: If True, upgrade existing packages.

        Returns:
            Command and arguments as a list of strings.
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
