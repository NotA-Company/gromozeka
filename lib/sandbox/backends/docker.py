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

from lib.sandbox.backends.base import (
    ContainerOutcome,
    ContainerSpec,
    ManagedContainerInfo,
)
from lib.sandbox.config import DockerBackendConfig
from lib.sandbox.enums import BackendName
from lib.sandbox.errors import DockerUnavailable, ImageBuildFailed, ImageNotFound
from lib.sandbox.types import HealthcheckResult, RuntimeInfo

logger = logging.getLogger(__name__)


class DockerBackend:
    """SandboxBackend implementation using Docker via aiodocker.

    Manages container lifecycle (create, run, inspect, kill, remove)
    and image management for sandbox runtimes.

    Attributes:
        name: Identifies this backend as Docker.
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
                try:
                    if hasattr(self._client, "session") and self._client.session is not None:
                        if self._client.session.connector is not None:
                            await self._client.session.connector.close()  # type: ignore[reportAttributeAccessIssue]
                except Exception:
                    pass
                try:
                    await self._client.close()
                except Exception:
                    pass
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
            HealthcheckResult with ok=True if Docker is reachable,
            along with daemon version info.
        """
        errors: list[str] = []
        backendInfo: dict[str, Any] = {}
        try:
            client = await self._getClient()
            versionInfo = await client.version()
            backendInfo = {"version": versionInfo.get("Version", "unknown")}
        except Exception as exc:
            errors.append(str(exc))
            backendInfo = {"error": str(exc)}

        return HealthcheckResult(
            ok=len(errors) == 0,
            backend=backendInfo,
            runtimes={},
            storage={},
            errors=errors,
        )

    async def ensureImage(
        self,
        runtime: RuntimeInfo,
        *,
        rebuild: bool = False,
    ) -> None:
        """Ensure both run and install Docker images are present, building if necessary.

        If an image already exists and *rebuild* is False, skips building
        that image.  Otherwise, builds the image from the Dockerfile
        referenced by the runtime configuration.

        Args:
            runtime: Runtime metadata carrying image tags and Dockerfile paths.
            rebuild: If True, force a rebuild even if the image exists.

        Raises:
            ImageBuildFailed: If the Docker build fails.
        """
        client = await self._getClient()

        # Build run image
        runTag = runtime.runImageTag
        runNeedsBuild = rebuild
        if not rebuild:
            try:
                await client.images.inspect(runTag)
                logger.info("Run image %s already exists, skipping build", runTag)
            except aiodocker.DockerError:
                logger.info("Run image %s not found, building...", runTag)
                runNeedsBuild = True

        if runNeedsBuild:
            runDockerfilePath = self._resolveDockerfilePath(runtime)
            await self._buildImage(client, runTag, runDockerfilePath)

        # Build install image
        installTag = runtime.installImageTag
        installNeedsBuild = rebuild
        if not rebuild:
            try:
                await client.images.inspect(installTag)
                logger.info("Install image %s already exists, skipping build", installTag)
            except aiodocker.DockerError:
                logger.info("Install image %s not found, building...", installTag)
                installNeedsBuild = True

        if installNeedsBuild:
            installDockerfilePath = self._resolveInstallDockerfilePath(runtime)
            await self._buildImage(client, installTag, installDockerfilePath)

    def _resolveDockerfilePath(self, runtime: RuntimeInfo) -> str:
        """Resolve the Dockerfile path for a runtime.

        Args:
            runtime: The runtime metadata.

        Returns:
            The filesystem path to the Dockerfile.

        Raises:
            ImageNotFound: If the runtime is not recognized.
        """
        if runtime.name.value == "python":
            return "lib/sandbox/runtimes/python/Dockerfile"
        raise ImageNotFound(f"No Dockerfile path configured for runtime {runtime.name.value}")

    def _resolveInstallDockerfilePath(self, runtime: RuntimeInfo) -> str:
        """Resolve the install Dockerfile path for a runtime.

        Args:
            runtime: The runtime metadata.

        Returns:
            The filesystem path to the install Dockerfile.

        Raises:
            ImageNotFound: If the runtime is not recognized.
        """
        if runtime.name.value == "python":
            return "lib/sandbox/runtimes/python/Dockerfile.install"
        raise ImageNotFound(f"No install Dockerfile path configured for runtime {runtime.name.value}")

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
            await client.images.build(
                fileobj=tarBuffer,
                tag=tag,
                path_dockerfile=dockerfileName,
                rm=True,
                pull=True,
            )
            logger.info("Successfully built image %s", tag)
        except aiodocker.DockerError as exc:
            raise ImageBuildFailed(f"Build failed for {tag}: {exc}") from exc

    async def runOneshot(self, *, spec: ContainerSpec) -> ContainerOutcome:
        """Create a container from *spec*, start it, and wait for completion.

        Does NOT remove the container — the caller collects artifacts first,
        then calls :meth:`removeContainer`.

        Args:
            spec: Container specification with image, command, mounts, env,
                limits, etc. Must be passed as keyword argument.

        Returns:
            ContainerOutcome with exit code, OOM status, and inspect data.
        """
        client = await self._getClient()
        containerConfig = self._specToContainerConfig(spec)

        container = await client.containers.create(config=containerConfig, name=spec.name)
        await container.start()

        # Wait for container to finish, respecting the timeout limit
        try:
            await asyncio.wait_for(container.wait(), timeout=spec.limits.timeoutSeconds)
        except asyncio.TimeoutError:
            # Container timed out - kill it
            await self.killContainer(container.id, signal="SIGKILL")

        inspectData = await container.show()
        exitCode = inspectData.get("State", {}).get("ExitCode")
        oomKilled = inspectData.get("State", {}).get("OOMKilled", False)

        return ContainerOutcome(
            containerId=container.id,
            exitCode=exitCode,
            signal=None,
            oomKilled=oomKilled,
            inspects=inspectData,
        )

    def _specToContainerConfig(self, spec: ContainerSpec) -> dict[str, Any]:
        """Convert a ContainerSpec to the aiodocker/Docker API container config dict.

        Args:
            spec: The container specification.

        Returns:
            Dict suitable for ``aiodocker.containers.create``.
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
            # Disable swap entirely when memorySwapMb is None
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
            Metadata for each managed container.
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
