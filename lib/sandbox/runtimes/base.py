"""Protocol for language runtimes in the sandbox system.

Defines the :class:`Runtime` protocol that every language runtime
(Python, TypeScript, Bash) must implement so that :class:`SandboxManager`
can build commands and detect artifacts without knowing the concrete
implementation.

Classes:
    Runtime: Protocol for language runtimes.
"""

from pathlib import Path
from typing import Protocol, Sequence

from lib.sandbox.enums import RuntimeName
from lib.sandbox.types import ArtifactInfo, ResourceLimits


class Runtime(Protocol):
    """Protocol for language runtimes (Python, TypeScript, Bash).

    Every runtime must implement this interface so that :class:`SandboxManager`
    can construct execution commands and detect output artifacts without
    knowing the concrete runtime implementation.

    Attributes:
        name: Identifies which runtime this instance represents.
    """

    name: RuntimeName

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

    def listCommand(self) -> list[str]:
        """Build the command-line invocation for listing installed packages.

        Returns:
            Command and arguments as a list of strings.
        """
        ...

    def detectArtifacts(
        self,
        workspacePath: Path,
        *,
        sinceMtime: float,
    ) -> list[ArtifactInfo]:
        """Walk the workspace and return files newer than *sinceMtime*.

        Excludes the ``.run/`` directory from the walk.

        Args:
            workspacePath: Host-side path to the workspace directory.
            sinceMtime: Modification-time threshold (epoch seconds); only
                files modified after this time are returned.

        Returns:
            List of artifact metadata for new or changed files.
        """
        ...
