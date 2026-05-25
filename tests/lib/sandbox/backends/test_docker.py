"""Tests for DockerBackend (lib.sandbox.backends.docker).

Unit tests run unconditionally.  Integration tests that require a running
Docker daemon are gated behind the ``DOCKER_AVAILABLE`` environment variable
(set to ``"1"`` to enable) and marked ``@pytest.mark.slow``.

Run integration tests with Docker enabled::

    DOCKER_AVAILABLE=1 ./venv/bin/pytest tests/lib/sandbox/backends/test_docker.py -v -m slow
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.sandbox.backends.base import ContainerOutcome, ContainerSpec, ManagedContainerInfo
from lib.sandbox.backends.docker import DockerBackend
from lib.sandbox.config import DockerBackendConfig
from lib.sandbox.enums import BackendName
from lib.sandbox.errors import DockerUnavailable
from lib.sandbox.types import HealthcheckResult, ResourceLimits

DOCKER_AVAILABLE = os.environ.get("DOCKER_AVAILABLE", "0") == "1"

# Skip marker for integration tests that need a Docker daemon
skipUnlessDocker = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="Docker not available (set DOCKER_AVAILABLE=1)",
)


def _makeConfig() -> DockerBackendConfig:
    """Create a default DockerBackendConfig for testing.

    Returns:
        A DockerBackendConfig with default settings.
    """
    return DockerBackendConfig()


def _makeSpec(
    *,
    name: str = "test-container",
    image: str = "alpine:latest",
    command: list[str] | None = None,
) -> ContainerSpec:
    """Create a minimal ContainerSpec for testing.

    Args:
        name: Container name.
        image: Container image tag.
        command: Command to run inside the container.

    Returns:
        A ContainerSpec with sensible defaults.
    """
    return ContainerSpec(
        name=name,
        image=image,
        command=command or ["echo", "hello"],
        mounts=[],
        env={},
        limits=ResourceLimits(),
        network="none",
        user="1000:1000",
        readOnlyRoot=True,
        capDrop=["ALL"],
        securityOpt=["no-new-privileges"],
        labels={"sandbox.managed": "true"},
    )


# ============================================================================
# Unit tests (no Docker required)
# ============================================================================


class TestDockerBackendUnit:
    """Unit tests that do not require a running Docker daemon."""

    def testNameAttribute(self) -> None:
        """Verify DockerBackend exposes name=BackendName.DOCKER.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        assert backend.name is BackendName.DOCKER

    def testConfigStored(self) -> None:
        """Verify DockerBackend stores the provided config.

        Returns:
            None
        """
        config = DockerBackendConfig(baseUrl="tcp://localhost:2375")
        backend = DockerBackend(config)
        assert backend._config is config
        assert backend._config.baseUrl == "tcp://localhost:2375"

    def testClientInitiallyNone(self) -> None:
        """Verify DockerBackend starts with no client connection.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        assert backend._client is None

    def testSpecToContainerConfig(self) -> None:
        """Verify _specToContainerConfig produces a valid Docker API dict.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec()
        config = backend._specToContainerConfig(spec)

        assert config["Image"] == "alpine:latest"
        assert config["Cmd"] == ["echo", "hello"]
        assert config["User"] == "1000:1000"
        assert config["WorkingDir"] == "/workspace"
        assert "HostConfig" in config
        assert config["HostConfig"]["NetworkMode"] == "none"
        assert config["HostConfig"]["ReadonlyRootfs"] is True
        assert config["HostConfig"]["CapDrop"] == ["ALL"]
        assert config["HostConfig"]["SecurityOpt"] == ["no-new-privileges"]
        assert config["HostConfig"]["Privileged"] is False
        assert config["HostConfig"]["AutoRemove"] is False
        assert config["HostConfig"]["Memory"] == ResourceLimits().memoryMb * 1024 * 1024
        assert config["Labels"] == {"sandbox.managed": "true"}

    def testSpecToContainerConfigWithMounts(self) -> None:
        """Verify _specToContainerConfig handles bind mounts correctly.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = ContainerSpec(
            name="test-mounts",
            image="alpine:latest",
            command=["echo", "hello"],
            mounts=[
                {"hostPath": "/tmp/host", "containerPath": "/workspace", "mode": "rw"},
                {"hostPath": "/tmp/ro", "containerPath": "/data", "mode": "ro"},
            ],
            env={"FOO": "bar"},
            limits=ResourceLimits(),
            network="bridge",
            user="1000:1000",
            readOnlyRoot=False,
            capDrop=["ALL"],
            securityOpt=[],
            labels={},
        )
        config = backend._specToContainerConfig(spec)

        assert len(config["HostConfig"]["Binds"]) == 2
        assert "/tmp/host:/workspace:rw" in config["HostConfig"]["Binds"]
        assert "/tmp/ro:/data:ro" in config["HostConfig"]["Binds"]
        assert config["Env"] == ["FOO=bar"]
        assert config["HostConfig"]["NetworkMode"] == "bridge"

    def testSpecToContainerConfigMemorySwap(self) -> None:
        """Verify _specToContainerConfig handles memory swap limits.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())

        # With memorySwapMb set
        limits = ResourceLimits(memoryMb=512, memorySwapMb=1024)
        spec = ContainerSpec(
            name="test-swap",
            image="alpine:latest",
            command=["echo"],
            mounts=[],
            env={},
            limits=limits,
            network="none",
            user="1000:1000",
            readOnlyRoot=True,
            capDrop=["ALL"],
            securityOpt=[],
            labels={},
        )
        config = backend._specToContainerConfig(spec)
        assert config["HostConfig"]["MemorySwap"] == 1024 * 1024 * 1024

        # With memorySwapMb=None (swap disabled)
        limits2 = ResourceLimits(memoryMb=512, memorySwapMb=None)
        spec2 = ContainerSpec(
            name="test-no-swap",
            image="alpine:latest",
            command=["echo"],
            mounts=[],
            env={},
            limits=limits2,
            network="none",
            user="1000:1000",
            readOnlyRoot=True,
            capDrop=["ALL"],
            securityOpt=[],
            labels={},
        )
        config2 = backend._specToContainerConfig(spec2)
        # When swap is None, MemorySwap equals Memory (disables swap)
        assert config2["HostConfig"]["MemorySwap"] == 512 * 1024 * 1024


# ============================================================================
# Integration tests (require Docker daemon)
# ============================================================================


@pytest.fixture
async def _ensureAlpineImage():
    """Pull alpine:latest image before tests that need it.

    Yields:
        None
    """
    if not DOCKER_AVAILABLE:
        yield
        return

    import aiodocker

    client = aiodocker.Docker()
    try:
        await client.images.pull("alpine:latest")
    except aiodocker.DockerError as exc:
        pytest.skip(f"Failed to pull alpine:latest: {exc}")
    finally:
        await client.close()

    yield


@skipUnlessDocker
@pytest.mark.slow
class TestDockerBackendIntegration:
    """Integration tests that require a running Docker daemon."""

    @pytest.mark.asyncio
    async def testHealthcheckOk(self) -> None:
        """Verify healthcheck returns ok=True when Docker is available.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        result = await backend.healthcheck()
        assert isinstance(result, HealthcheckResult)
        assert result.ok is True
        await backend.close()

    @pytest.mark.asyncio
    async def testHealthcheckBackendInfo(self) -> None:
        """Verify healthcheck returns successful result when Docker is available.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        result = await backend.healthcheck()
        assert result.ok is True
        await backend.close()

    @pytest.mark.asyncio
    async def testListManagedContainersEmpty(self) -> None:
        """Verify listManagedContainers returns a list (may be empty).

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        containers = await backend.listManagedContainers()
        assert isinstance(containers, list)
        await backend.close()

    @pytest.mark.asyncio
    async def testRunOneshotEcho(self, _ensureAlpineImage) -> None:
        """Verify runOneshot can run a simple echo command.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec(
            name="test-echo-container",
            image="alpine:latest",
            command=["echo", "hello from docker"],
        )
        outcome = await backend.runOneshot(spec=spec)
        assert isinstance(outcome, ContainerOutcome)
        assert outcome.exitCode == 0
        assert outcome.oomKilled is False
        assert outcome.containerId != ""

        # Clean up
        await backend.removeContainer(outcome.containerId, force=True)
        await backend.close()

    @pytest.mark.asyncio
    async def testInspectContainer(self, _ensureAlpineImage) -> None:
        """Verify inspectContainer returns container details.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec(
            name="test-inspect-container",
            image="alpine:latest",
            command=["echo", "inspect test"],
        )
        outcome = await backend.runOneshot(spec=spec)
        inspectData = await backend.inspectContainer(outcome.containerId)
        assert "State" in inspectData
        assert "ExitCode" in inspectData["State"]

        # Clean up
        await backend.removeContainer(outcome.containerId, force=True)
        await backend.close()

    @pytest.mark.asyncio
    async def testKillContainer(self, _ensureAlpineImage) -> None:
        """Verify killContainer can kill a running container.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec(
            name="test-kill-container",
            image="alpine:latest",
            command=["sleep", "300"],
        )
        outcome = await backend.runOneshot(spec=spec)

        # Kill the sleeping container
        await backend.killContainer(outcome.containerId, signal="SIGKILL")

        # Clean up
        await backend.removeContainer(outcome.containerId, force=True)
        await backend.close()

    @pytest.mark.asyncio
    async def testRemoveContainer(self, _ensureAlpineImage) -> None:
        """Verify removeContainer cleans up a stopped container.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec(
            name="test-remove-container",
            image="alpine:latest",
            command=["echo", "remove test"],
        )
        outcome = await backend.runOneshot(spec=spec)
        containerId = outcome.containerId

        # Remove the container
        await backend.removeContainer(containerId, force=True)

        # Verify it's gone by trying to inspect (should fail)
        with pytest.raises(Exception):
            await backend.inspectContainer(containerId)

        await backend.close()

    @pytest.mark.asyncio
    async def testListManagedContainersAfterCreate(self, _ensureAlpineImage) -> None:
        """Verify listManagedContainers finds containers with sandbox.managed=true.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec(
            name="test-list-container",
            image="alpine:latest",
            command=["echo", "list test"],
        )
        outcome = await backend.runOneshot(spec=spec)

        containers = await backend.listManagedContainers()
        containerIds = [c.containerId for c in containers]
        assert outcome.containerId in containerIds

        # Find our container in the list
        ourContainer = next(c for c in containers if c.containerId == outcome.containerId)
        assert isinstance(ourContainer, ManagedContainerInfo)
        assert ourContainer.labels.get("sandbox.managed") == "true"

        # Clean up
        await backend.removeContainer(outcome.containerId, force=True)
        await backend.close()

    @pytest.mark.asyncio
    async def testCloseIdempotent(self) -> None:
        """Verify close() can be called multiple times safely.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        await backend.healthcheck()  # Force client creation
        await backend.close()
        await backend.close()  # Second call should be a no-op

    @pytest.mark.asyncio
    async def testGetClientReconnectsAfterFailure(self) -> None:
        """Verify _getClient raises DockerUnavailable when daemon is unreachable.

        Returns:
            None
        """
        import os

        # Temporarily clear DOCKER_HOST to test error handling
        originalDockerHost = os.environ.pop("DOCKER_HOST", None)
        try:
            config = DockerBackendConfig(baseUrl="tcp://nonexistent-host:2375")
            backend = DockerBackend(config)
            with pytest.raises(DockerUnavailable):
                await backend._getClient()
        finally:
            if originalDockerHost is not None:
                os.environ["DOCKER_HOST"] = originalDockerHost


# ============================================================================
# Regression tests for container leak fix (no Docker required)
# ============================================================================


class TestRunOneshotContainerCleanup:
    """Verify runOneshot cleans up containers when exceptions occur.

    Regression tests for the container leak: if start(), wait(), or show()
    raises after the container has been created, the container must be
    removed before re-raising so it is not orphaned.
    """

    @pytest.mark.asyncio
    async def testCleanupOnStartFailure(self) -> None:
        """Container is removed when start() raises after create().

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec()

        mockContainer = AsyncMock()
        mockContainer.id = "fake-container-id"
        mockContainer.start = AsyncMock(side_effect=RuntimeError("start failed"))

        mockClient = MagicMock()
        mockClient.containers.create = AsyncMock(return_value=mockContainer)

        removeContainerCalls: list[str] = []

        async def fakeRemoveContainer(containerId: str, *, force: bool = True) -> None:
            removeContainerCalls.append(containerId)

        with patch.object(backend, "_getClient", new=AsyncMock(return_value=mockClient)):
            with patch.object(backend, "removeContainer", side_effect=fakeRemoveContainer):
                with pytest.raises(RuntimeError, match="start failed"):
                    await backend.runOneshot(spec=spec)

        assert removeContainerCalls == ["fake-container-id"]

    @pytest.mark.asyncio
    async def testCleanupOnWaitFailure(self) -> None:
        """Container is removed when wait() raises after start().

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec()

        mockContainer = AsyncMock()
        mockContainer.id = "fake-container-id"
        mockContainer.start = AsyncMock()
        mockContainer.wait = AsyncMock(side_effect=RuntimeError("wait crashed"))

        mockClient = MagicMock()
        mockClient.containers.create = AsyncMock(return_value=mockContainer)

        removeContainerCalls: list[str] = []

        async def fakeRemoveContainer(containerId: str, *, force: bool = True) -> None:
            removeContainerCalls.append(containerId)

        with patch.object(backend, "_getClient", new=AsyncMock(return_value=mockClient)):
            with patch.object(backend, "removeContainer", side_effect=fakeRemoveContainer):
                with pytest.raises(RuntimeError, match="wait crashed"):
                    await backend.runOneshot(spec=spec)

        assert removeContainerCalls == ["fake-container-id"]

    @pytest.mark.asyncio
    async def testCleanupOnShowFailure(self) -> None:
        """Container is removed when show() raises after successful wait().

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec()

        mockContainer = AsyncMock()
        mockContainer.id = "fake-container-id"
        mockContainer.start = AsyncMock()
        mockContainer.wait = AsyncMock()
        mockContainer.show = AsyncMock(side_effect=RuntimeError("show crashed"))

        mockClient = MagicMock()
        mockClient.containers.create = AsyncMock(return_value=mockContainer)

        removeContainerCalls: list[str] = []

        async def fakeRemoveContainer(containerId: str, *, force: bool = True) -> None:
            removeContainerCalls.append(containerId)

        with patch.object(backend, "_getClient", new=AsyncMock(return_value=mockClient)):
            with patch.object(backend, "removeContainer", side_effect=fakeRemoveContainer):
                with pytest.raises(RuntimeError, match="show crashed"):
                    await backend.runOneshot(spec=spec)

        assert removeContainerCalls == ["fake-container-id"]

    @pytest.mark.asyncio
    async def testNoCleanupWhenCreateFails(self) -> None:
        """No removeContainer call when create() itself raises.

        If the container was never created, there is nothing to clean up.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec()

        mockClient = MagicMock()
        mockClient.containers.create = AsyncMock(side_effect=RuntimeError("create failed"))

        removeContainerCalls: list[str] = []

        async def fakeRemoveContainer(containerId: str, *, force: bool = True) -> None:
            removeContainerCalls.append(containerId)

        with patch.object(backend, "_getClient", new=AsyncMock(return_value=mockClient)):
            with patch.object(backend, "removeContainer", side_effect=fakeRemoveContainer):
                with pytest.raises(RuntimeError, match="create failed"):
                    await backend.runOneshot(spec=spec)

        assert removeContainerCalls == []

    @pytest.mark.asyncio
    async def testCleanupSuppressedOnRemoveError(self) -> None:
        """Container cleanup error is suppressed; original exception re-raised.

        If removeContainer itself raises, the original exception must still
        propagate — the cleanup failure must not swallow it.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec()

        mockContainer = AsyncMock()
        mockContainer.id = "fake-container-id"
        mockContainer.start = AsyncMock(side_effect=RuntimeError("start failed"))

        mockClient = MagicMock()
        mockClient.containers.create = AsyncMock(return_value=mockContainer)

        async def brokenRemoveContainer(containerId: str, *, force: bool = True) -> None:
            raise RuntimeError("remove also failed")

        with patch.object(backend, "_getClient", new=AsyncMock(return_value=mockClient)):
            with patch.object(backend, "removeContainer", side_effect=brokenRemoveContainer):
                with pytest.raises(RuntimeError, match="start failed"):
                    await backend.runOneshot(spec=spec)

    @pytest.mark.asyncio
    async def testNoCleanupOnSuccess(self) -> None:
        """removeContainer is NOT called on the success path.

        On success, the caller is responsible for cleanup via removeContainer.

        Returns:
            None
        """
        backend = DockerBackend(_makeConfig())
        spec = _makeSpec()

        mockContainer = AsyncMock()
        mockContainer.id = "fake-container-id"
        mockContainer.start = AsyncMock()
        mockContainer.wait = AsyncMock()
        mockContainer.show = AsyncMock(
            return_value={
                "State": {"ExitCode": 0, "OOMKilled": False},
            }
        )

        mockClient = MagicMock()
        mockClient.containers.create = AsyncMock(return_value=mockContainer)

        removeContainerCalls: list[str] = []

        async def fakeRemoveContainer(containerId: str, *, force: bool = True) -> None:
            removeContainerCalls.append(containerId)

        with patch.object(backend, "_getClient", new=AsyncMock(return_value=mockClient)):
            with patch.object(backend, "removeContainer", side_effect=fakeRemoveContainer):
                outcome = await backend.runOneshot(spec=spec)

        assert isinstance(outcome, ContainerOutcome)
        assert outcome.exitCode == 0
        assert outcome.containerId == "fake-container-id"
        assert removeContainerCalls == []
