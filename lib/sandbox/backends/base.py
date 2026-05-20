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

from abc import ABC, abstractmethod
from typing import Any

from ..enums import BackendName
from ..types import ContainerOutcome, ContainerSpec, HealthcheckResult, ManagedContainerInfo


class SandboxBackend(ABC):
    """Protocol for sandbox execution backends (Docker, gVisor, Firecracker).

    Every backend must implement this interface so that :class:`SandboxManager`
    can delegate container lifecycle operations without knowing the concrete
    implementation.

    Attributes:
        name: Identifies which backend this instance represents.
    """

    name: BackendName

    @abstractmethod
    async def healthcheck(self) -> HealthcheckResult:
        """Check whether the backend is healthy and ready to accept work.

        Returns:
            Aggregated health status of the backend subsystem.
        """
        ...

    @abstractmethod
    async def ensureImage(
        self,
        imageTag: str,
        imageFile: str,
        *,
        rebuild: bool = False,
    ) -> None:
        """Ensure the container image is available locally.

        Builds the image from Dockerfile if missing or rebuild=True.

        Args:
            imageTag: Docker image tag to ensure exists.
            imageFile: Path to the Dockerfile for building.
            rebuild: If True, force a rebuild even if the image already exists.

        Returns:
            None
        """
        ...

    @abstractmethod
    async def removeImage(
        self,
        imageTag: str,
    ) -> None:
        """Remove a container image from the backend.

        Args:
            imageTag: Docker image tag to remove.

        Returns:
            None
        """
        ...

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
    async def inspectContainer(self, containerId: str) -> dict[str, Any]:
        """Inspect a container for low-level details (e.g. OOMKilled).

        Args:
            containerId: Docker container ID to inspect.

        Returns:
            Raw inspect output as a dictionary.
        """
        ...

    @abstractmethod
    async def listManagedContainers(self) -> list[ManagedContainerInfo]:
        """List all containers managed by this backend.

        Returns:
            Metadata for each managed container.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the backend connection and release resources.

        Returns:
            None
        """
        ...
