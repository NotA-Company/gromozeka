"""Protocol and dataclasses for sandbox execution backends.

Defines the :class:`SandboxBackend` protocol that every execution backend
(Docker, gVisor, Firecracker) must implement, along with the dataclasses
used to describe container specifications and outcomes.

Classes:
    ContainerSpec: Specification for creating and running a container.
    ContainerOutcome: Result of running a container to completion.
    ManagedContainerInfo: Metadata about a managed container.
    SandboxBackend: Protocol for sandbox execution backends.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from lib.sandbox.enums import BackendName
from lib.sandbox.types import HealthcheckResult, ResourceLimits, RuntimeInfo


@dataclass(slots=True)
class ContainerSpec:
    """Specification for creating and running a container.

    Attributes:
        name: Container name.
        image: Container image tag.
        command: Command and arguments to execute inside the container.
        mounts: Volume mount specifications (hostPath, containerPath, mode).
        env: Environment variables to inject into the container.
        limits: Resource limits (CPU, memory, timeout) for the container.
        network: Network mode — ``"none"`` or ``"bridge"``.
        user: ``uid:gid`` string for the container process.
        readOnlyRoot: If True, mount the root filesystem as read-only.
        capDrop: Linux capabilities to drop.
        securityOpt: Additional Docker security options.
        labels: Key-value labels attached to the container.
    """

    name: str
    image: str
    command: list[str]
    mounts: list[dict[str, str]]
    env: dict[str, str]
    limits: ResourceLimits
    network: str
    user: str
    readOnlyRoot: bool
    capDrop: list[str]
    securityOpt: list[str]
    labels: dict[str, str]


@dataclass(slots=True)
class ContainerOutcome:
    """Result of running a container to completion.

    Attributes:
        containerId: Docker container ID.
        exitCode: Process exit code, or None if not available.
        signal: Termination signal name, or None.
        oomKilled: True if the container was killed due to out-of-memory.
        inspects: Raw Docker inspect output for the container.
    """

    containerId: str
    exitCode: int | None
    signal: str | None
    oomKilled: bool
    inspects: dict[str, Any]


@dataclass(slots=True)
class ManagedContainerInfo:
    """Metadata about a managed container.

    Attributes:
        containerId: Docker container ID.
        name: Container name.
        labels: Key-value labels attached to the container.
        status: Container status string (e.g. ``"running"``, ``"exited"``).
        createdAt: ISO-8601 timestamp when the container was created.
    """

    containerId: str
    name: str
    labels: dict[str, str]
    status: str
    createdAt: str


class SandboxBackend(Protocol):
    """Protocol for sandbox execution backends (Docker, gVisor, Firecracker).

    Every backend must implement this interface so that :class:`SandboxManager`
    can delegate container lifecycle operations without knowing the concrete
    implementation.

    Attributes:
        name: Identifies which backend this instance represents.
    """

    name: BackendName

    async def healthcheck(self) -> HealthcheckResult:
        """Check whether the backend is healthy and ready to accept work.

        Returns:
            Aggregated health status of the backend subsystem.
        """
        ...

    async def ensureImage(
        self,
        runtime: RuntimeInfo,
        *,
        rebuild: bool = False,
    ) -> None:
        """Ensure the container image for *runtime* is available locally.

        Args:
            runtime: Runtime metadata describing the image to ensure.
            rebuild: If True, force a rebuild even if the image already exists.

        Returns:
            None
        """
        ...

    async def runOneshot(self, *, spec: ContainerSpec) -> ContainerOutcome:
        """Run a container to completion and return the outcome.

        Does NOT remove the container — the caller collects artifacts first.

        Args:
            spec: Full container specification including image, command,
                mounts, and resource limits. Must be passed as keyword argument.

        Returns:
            Outcome of the container run including exit code and OOM status.
        """
        ...

    async def removeContainer(
        self,
        containerId: str,
        *,
        force: bool = True,
    ) -> None:
        """Remove a container from the backend.

        Args:
            containerId: Docker container ID to remove.
            force: If True, remove even if the container is running.

        Returns:
            None
        """
        ...

    async def killContainer(
        self,
        containerId: str,
        *,
        signal: str = "SIGKILL",
    ) -> None:
        """Send a signal to a running container.

        Args:
            containerId: Docker container ID to signal.
            signal: Signal name to send (default ``"SIGKILL"``).

        Returns:
            None
        """
        ...

    async def inspectContainer(self, containerId: str) -> dict[str, Any]:
        """Inspect a container for low-level details (e.g. OOMKilled).

        Args:
            containerId: Docker container ID to inspect.

        Returns:
            Raw inspect output as a dictionary.
        """
        ...

    async def listManagedContainers(self) -> list[ManagedContainerInfo]:
        """List all containers managed by this backend.

        Returns:
            Metadata for each managed container.
        """
        ...

    async def close(self) -> None:
        """Close the backend connection and release resources.

        Returns:
            None
        """
        ...
