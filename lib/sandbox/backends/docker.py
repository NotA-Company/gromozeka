"""Docker-based sandbox backend using aiodocker.

Implements the :class:`SandboxBackend` protocol using Docker containers
managed through the ``aiodocker`` async client.  Handles container lifecycle
(create, start, wait, kill, remove), image management (inspect, build), and
health checks against the Docker daemon.

Classes:
    DockerBackend: SandboxBackend implementation backed by Docker.
"""

import asyncio
import io
import logging
import os
import tarfile
from pathlib import Path
from typing import Any

import aiodocker

from ..config import DockerBackendConfig
from ..enums import BackendName
from ..errors import DockerUnavailable, ImageBuildFailed
from ..types import ContainerOutcome, ContainerSpec, HealthcheckResult, ManagedContainerInfo
from .base import (
    SandboxBackend,
)

logger = logging.getLogger(__name__)


class DockerBackend(SandboxBackend):
    """SandboxBackend implementation using Docker via aiodocker.

    Manages container lifecycle (create, run, inspect, kill, remove)
    and image management for sandbox runtimes.

    Attributes:
        name: BackendName.DOCKER, identifies this backend as Docker.
    """

    name: BackendName = BackendName.DOCKER

    def __init__(self, config: DockerBackendConfig) -> None:
        """Initialise the Docker backend.

        Args:
            config: Docker backend configuration (baseUrl, imagePullPolicy).
        """
        self._config = config
        self._client: aiodocker.Docker | None = None

    async def _getClient(self) -> aiodocker.Docker:
        """Get or lazily create the aiodocker client.

        If an existing client is present, verifies connectivity by
        calling ``version()``.  On failure, discards the stale client
        and reconnects.

        Returns:
            A connected aiodocker Docker client.

        Raises:
            DockerUnavailable: If the Docker daemon is unreachable.
        """
        if self._client is not None:
            try:
                await self._client.version()
                return self._client
            except Exception:
                # Stale connection — close connector then client
                connectorClosed = False
                connectorAttempted = False
                clientClosed = False
                try:
                    if hasattr(self._client, "session") and self._client.session is not None:
                        if self._client.session.connector is not None:
                            connectorAttempted = True
                            await self._client.session.connector.close()  # type: ignore[reportAttributeAccessIssue]
                    connectorClosed = True
                except Exception as exc:
                    logger.warning("Failed to close connector during stale client cleanup: %s", exc)
                try:
                    await self._client.close()
                    clientClosed = True
                except Exception as exc:
                    logger.warning("Failed to close client during stale client cleanup: %s", exc)
                if connectorAttempted and not connectorClosed:
                    logger.warning("Stale client cleanup: connector close failed")
                if not clientClosed:
                    logger.warning("Stale client cleanup: client close failed")
                self._client = None

        url = os.environ.get("DOCKER_HOST", self._config.baseUrl)
        try:
            self._client = aiodocker.Docker(url=url)
            await self._client.version()
            logger.info("Connected to Docker at %s", url)
            return self._client
        except Exception as exc:
            self._client = None
            raise DockerUnavailable(f"Docker daemon unreachable at {url}: {exc}") from exc

    async def healthcheck(self) -> HealthcheckResult:
        """Check Docker daemon connectivity.

        Returns:
            HealthcheckResult with ok=True if Docker is reachable, ok=False
            otherwise. The errors list contains error details if the check fails.
        """
        errors: list[str] = []
        try:
            client = await self._getClient()
            _ = await client.version()
        except Exception as exc:
            errors.append(str(exc))

        return HealthcheckResult(
            ok=len(errors) == 0,
            errors=errors,
        )

    async def ensureImage(
        self,
        imageTag: str,
        imageFile: str,
        *,
        rebuild: bool = False,
    ) -> None:
        """Ensure both run and install Docker images are present, building if necessary.

        If an image already exists and *rebuild* is False, skips building
        that image.  Otherwise, builds the image from the Dockerfile.

        Args:
            imageTag: Docker image tag to ensure exists.
            imageFile: Path to the Dockerfile for building.
            rebuild: If True, force a rebuild even if the image exists.

        Raises:
            ImageBuildFailed: If the Docker build fails.
        """
        client = await self._getClient()

        # Build run image

        try:
            await client.images.inspect(imageTag)
            hasImage = True
        except aiodocker.DockerError:
            hasImage = False

        if rebuild or not hasImage:
            logger.info("Building image %s from Dockerfile %s", imageTag, imageFile)
            await self._buildImage(client, imageTag, imageFile)

    async def removeImage(
        self,
        imageTag: str,
    ) -> None:
        """Remove a Docker image by tag.

        Args:
            imageTag: Docker image tag to remove.
        """
        try:
            client = await self._getClient()
            await client.images.delete(imageTag)
            logger.info("Removed image %s", imageTag)
        except aiodocker.DockerError as exc:
            logger.warning("Failed to remove image %s: %s", imageTag, exc)

    async def _buildImage(
        self,
        client: aiodocker.Docker,
        tag: str,
        dockerfilePath: str,
    ) -> None:
        """Build a Docker image from a Dockerfile.

        Creates a tar archive of the Dockerfile's parent directory and
        submits it to the Docker build API.

        Args:
            client: The aiodocker client.
            tag: The image tag to apply.
            dockerfilePath: Path to the Dockerfile (relative to repo root).

        Raises:
            ImageBuildFailed: If the Dockerfile is missing or the build fails.
        """
        fullPath = Path(dockerfilePath)
        if not fullPath.exists():
            raise ImageBuildFailed(f"Dockerfile not found: {dockerfilePath}")

        contextDir = fullPath.parent
        dockerfileName = fullPath.name

        # Create an in-memory tar archive of the build context
        tarBuffer = io.BytesIO()
        with tarfile.open(fileobj=tarBuffer, mode="w") as tar:
            for filePath in contextDir.iterdir():
                tar.add(str(filePath), arcname=filePath.name)
        tarBuffer.seek(0)

        try:
            ret = await client.images.build(
                fileobj=tarBuffer,
                tag=tag,
                path_dockerfile=dockerfileName,
                rm=True,
                pull=True,
                encoding="identity",
            )
            # logger.debug(f"Build result: {json.dumps(ret, indent=2)}")
            if ret and "error" in ret[-1]:
                logger.error(f"Error during building docker image: {ret[-1]}")
                raise ImageBuildFailed(f"Error during building docker image: {ret[-1]}")

            logger.info("Successfully built image %s", tag)
        except aiodocker.DockerError as exc:
            raise ImageBuildFailed(f"Build failed for {tag}: {exc}") from exc

    async def runOneshot(self, *, spec: ContainerSpec) -> ContainerOutcome:
        """Create a container from *spec*, start it, and wait for completion.

        If the method raises before returning a :class:`ContainerOutcome`, the
        container is removed automatically so that no orphaned containers leak.

        On success the container is NOT removed — the caller collects artifacts
        first, then calls :meth:`removeContainer`.

        Args:
            spec: Container specification with image, command, mounts, env,
                limits, etc. Must be passed as keyword argument.

        Returns:
            ContainerOutcome with exit code, OOM status, and inspect data.

        Raises:
            Exception: Any error from container creation, start, wait, or
                inspect.  The container (if created) is removed before
                re-raising.
        """
        client = await self._getClient()
        containerConfig = self._specToContainerConfig(spec)

        container = None
        try:
            container = await client.containers.create(config=containerConfig, name=spec.name)
            await container.start()

            # Watchdog timeout: give the inner `timeout` wrapper its full
            # TERM → grace → KILL cycle, plus 1 s buffer.  The backend
            # wait_for is a fallback — the container's own `timeout` command
            # handles graceful termination and exits 124 on timeout.
            watchdogTimeout = spec.limits.timeoutSeconds + spec.limits.timeoutGraceSeconds + 1
            try:
                await asyncio.wait_for(container.wait(), timeout=watchdogTimeout)
            except asyncio.TimeoutError:
                # Container timed out - kill it
                await self.killContainer(container.id, signal="SIGKILL")
                # Brief delay for container state to stabilize after SIGKILL
                await asyncio.sleep(0.1)
                try:
                    inspectData = await container.show()
                except Exception as exc:
                    logger.warning("Failed to inspect container after timeout: %s", exc)
                    return ContainerOutcome(
                        containerId=container.id,
                        exitCode=-1,
                        signal="SIGKILL",
                        oomKilled=False,
                        inspects={},
                    )
                if not isinstance(inspectData, dict):
                    logger.error(f"inspectData expected to be Dict, but got {inspectData!r}")
                    inspectData = {}

                exitCode = inspectData.get("State", {}).get("ExitCode")
                return ContainerOutcome(
                    containerId=container.id,
                    exitCode=exitCode,
                    signal="SIGKILL" if exitCode is not None and exitCode != 0 else None,
                    oomKilled=inspectData.get("State", {}).get("OOMKilled", False),
                    inspects=inspectData,
                )

            inspectData = await container.show()
            if not isinstance(inspectData, dict):
                logger.error(f"inspectData expected to be Dict, but got {inspectData!r}")
                inspectData = {}

            return ContainerOutcome(
                containerId=container.id,
                exitCode=inspectData.get("State", {}).get("ExitCode"),
                signal=None,
                oomKilled=inspectData.get("State", {}).get("OOMKilled", False),
                inspects=inspectData,
            )
        except BaseException as e:
            logger.exception(e)
            if container is not None:
                try:
                    await self.removeContainer(container.id, force=True)
                except Exception as e2:
                    logger.error(f"Exception raised during container#{container.id} cleanup: {e2!r}")
            raise

    def _specToContainerConfig(self, spec: ContainerSpec) -> dict[str, Any]:
        """Convert a ContainerSpec to the aiodocker/Docker API container config dict.

        Args:
            spec: The container specification defining image, command, mounts,
                environment variables, user, limits, and other container settings.

        Returns:
            Dictionary containing the container configuration in the format
            expected by aiodocker.containers.create with keys like Image, Cmd,
            Env, HostConfig, Labels, and WorkingDir.
        """
        binds: list[str] = []
        for m in spec.mounts:
            hostPath = m["hostPath"]
            containerPath = m["containerPath"]
            mode = m.get("mode", "rw")
            binds.append(f"{hostPath}:{containerPath}:{mode}")

        hostConfig: dict[str, Any] = {
            "Binds": binds,
            "ReadonlyRootfs": spec.readOnlyRoot,
            "CapDrop": spec.capDrop,
            "SecurityOpt": spec.securityOpt,
            "Privileged": False,
            "Devices": [],
            "AutoRemove": False,
            "NetworkMode": spec.network,
            "Memory": spec.limits.memoryMb * 1024 * 1024,
            "NanoCpus": int(spec.limits.cpuCount * 1e9),
            "PidsLimit": spec.limits.pidsLimit,
        }

        if spec.limits.memorySwapMb is not None:
            hostConfig["MemorySwap"] = spec.limits.memorySwapMb * 1024 * 1024
        else:
            # Set MemorySwap equal to memory to disable swap (Docker MemorySwap == total limit)
            hostConfig["MemorySwap"] = spec.limits.memoryMb * 1024 * 1024

        labels = spec.labels.copy()

        return {
            "Image": spec.image,
            "Cmd": spec.command,
            "Env": [f"{k}={v}" for k, v in spec.env.items()],
            "User": spec.user,
            "HostConfig": hostConfig,
            "Labels": labels,
            "WorkingDir": "/workspace",
        }

    async def removeContainer(
        self,
        containerId: str,
        *,
        force: bool = True,
    ) -> None:
        """Remove a container from Docker.

        Args:
            containerId: The Docker container ID to remove.
            force: If True, remove even if the container is running.
        """
        try:
            client = await self._getClient()
            container = await client.containers.get(containerId)
            await container.delete(force=force)
        except aiodocker.DockerError as exc:
            logger.warning("Failed to remove container %s: %s", containerId, exc)

    async def killContainer(
        self,
        containerId: str,
        *,
        signal: str = "SIGKILL",
    ) -> None:
        """Send a signal to a running container.

        Args:
            containerId: The Docker container ID to signal.
            signal: Signal name to send (default ``"SIGKILL"``).
        """
        try:
            client = await self._getClient()
            container = await client.containers.get(containerId)
            await container.kill(signal=signal)
        except aiodocker.DockerError as exc:
            logger.warning("Failed to kill container %s: %s", containerId, exc)

    async def inspectContainer(self, containerId: str) -> dict[str, Any]:
        """Inspect a container for low-level details.

        Args:
            containerId: The Docker container ID to inspect.

        Returns:
            Raw Docker inspect output as a dictionary.
        """
        client = await self._getClient()
        container = await client.containers.get(containerId)
        return await container.show()

    async def listManagedContainers(self) -> list[ManagedContainerInfo]:
        """List all containers with the ``sandbox.managed=true`` label.

        Returns:
            List of ManagedContainerInfo objects, each containing containerId,
            name, labels, status, and createdAt timestamp for every container
            tagged as managed by this sandbox backend.
        """
        client = await self._getClient()
        filters = {"label": ["sandbox.managed=true"]}
        containers = await client.containers.list(all=True, filters=filters)
        result: list[ManagedContainerInfo] = []
        for c in containers:
            try:
                inspectData = await c.show()
                name = inspectData.get("Name", "").lstrip("/")
                labels = inspectData.get("Config", {}).get("Labels", {})
                status = inspectData.get("State", {}).get("Status", "")
                createdAt = inspectData.get("Created", "")
                result.append(
                    ManagedContainerInfo(
                        containerId=c.id,
                        name=name,
                        labels=labels,
                        status=status,
                        createdAt=createdAt,
                    )
                )
            except aiodocker.DockerError as exc:
                logger.warning("Failed to inspect container %s: %s", c.id, exc)
        return result

    async def close(self) -> None:
        """Close the aiodocker client connection.

        Safe to call multiple times; subsequent calls are no-ops.

        Explicitly closes the underlying aiohttp connector to prevent
        "Unclosed connector" warnings when Python exits.
        """
        if self._client is not None:
            # Close the underlying aiohttp connector BEFORE closing the
            # aiodocker client (client.close() nulls the session).
            try:
                if hasattr(self._client, "session") and self._client.session is not None:
                    if self._client.session.connector is not None:
                        await self._client.session.connector.close()  # type: ignore[reportAttributeAccessIssue]
            except Exception as exc:
                logger.warning("Failed to close aiodocker connector: %s", exc)
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
