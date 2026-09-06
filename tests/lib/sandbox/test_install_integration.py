"""Real-Docker end-to-end install coverage for SandboxManager (lib.sandbox.manager).

Restores the integration coverage lost when ``tests/scripts/test_sandbox_bootstrap.py``
was deleted (sandbox simplification arc, plan
``docs/plans/sandbox-update-simplification-v1.md`` §9): a behavior-focused test that
drives ``SandboxManager.prepareRuntime()`` + ``installRuntimeLibraries()`` against a
REAL Docker daemon — image build from the repo runtime Dockerfiles, the staged-install
container (helper-script bind + pip into a private delta), the host-side delta
merge + atomic pool swap, and the container-side package-list refresh that lands
in ``packages.json``. Unlike the deleted CLI-script test, this file is independent
of any script: it constructs the manager directly and asserts on the resulting
pool (dist-info on disk + ``listRuntimeLibraries``).

Gating mirrors ``tests/lib/sandbox/backends/test_docker.py`` exactly: integration
tests run only when the ``DOCKER_AVAILABLE`` environment variable is ``"1"`` and are
marked ``@pytest.mark.slow``::

    DOCKER_AVAILABLE=1 ./venv/bin/pytest tests/lib/sandbox/test_install_integration.py -v -m slow

The backend resolves the daemon from ``DOCKER_HOST`` when set, falling back to the
configured ``base-url`` (``unix:///var/run/docker.sock``). Context-based daemons
(Colima, Docker Desktop) must export ``DOCKER_HOST`` to their socket, e.g.::

    DOCKER_AVAILABLE=1 DOCKER_HOST=unix:///Users/me/.colima/default/docker.sock \\
        ./venv/bin/pytest tests/lib/sandbox/test_install_integration.py -v -m slow

Two deviations from the deleted test, both dictated by desktop Docker daemons
(Colima / Docker Desktop) and kept for portability:

1. The storage root lives under ``~/.gromozeka-tests/`` (unique per run, removed
   in a ``finally`` block) instead of pytest ``tmp_path``: desktop daemons only
   share ``/Users`` (and equivalents) with the VM, so bind mounts from
   ``/var/folders``/``/tmp`` silently resolve to empty VM-side directories.
2. Containers run as ``0:0`` instead of the production ``1000:1000``: desktop
   VMs present host bind-mount files as root-owned, so a non-root container
   cannot write the staging delta. The non-root hardening contract belongs to
   production config, not to this behavior test.

Cleanup contract: both image tags are derived from the same per-run UUID as
the workspace (``gromozeka-sandbox-test-install-<run-id>:run`` / ``:install``),
so stale images from aborted runs cannot make the build assertion vacuous and
concurrent runs cannot interfere. Containers created by this test are
identified by those per-run tags, force-removed, and the images themselves are
then removed. Because the backend's ``removeContainer()``/``removeImage()``
deliberately swallow ``DockerError``, cleanup postconditions are re-verified
against the daemon (no managed containers with the per-run tags, both images
gone — not-found counts as removed) and any residue fails the test via
``cleanupErrors``. All storage (pool, lock files, staging) lives under the
per-run home directory subtree; only that per-run UUID directory is removed
recursively — the shared ``test-install-integration/`` parent is never removed
recursively and is removed only when empty (guarded non-recursive ``rmdir()``),
so concurrent runs never delete each other's workspaces.
"""

import os
import shutil
import sys
import uuid
import warnings
from collections.abc import Iterator
from pathlib import Path

import aiodocker
import pytest

from lib.sandbox.backends.docker import DockerBackend
from lib.sandbox.config import (
    BasicRuntimeConfig,
    InstallContainerConfig,
    SandboxConfig,
    SecurityConfig,
    StorageConfig,
)
from lib.sandbox.enums import RuntimeName
from lib.sandbox.manager import SandboxManager
from lib.sandbox.runtimes.python.pool_staging import enumerateDistInfos

DOCKER_AVAILABLE = os.environ.get("DOCKER_AVAILABLE", "0") == "1"

# Skip marker for integration tests that need a Docker daemon
skipUnlessDocker = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="Docker not available (set DOCKER_AVAILABLE=1)",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
"""Repository root; used to resolve runtime Dockerfiles independent of CWD."""

TEST_IMAGE_PREFIX = "gromozeka-sandbox-test-install"
"""Test-scoped image tag prefix; the per-run UUID is inserted before the ``:tag``.

Never collides with production defaults (``gromozeka-sandbox-python:run`` /
``:install``) and is unique per test run.
"""

INSTALL_PACKAGE = "six"
"""Tiny pure-Python package installed end-to-end (mirrors the deleted test)."""

INSTALL_TIMEOUT_SECONDS = 300
"""Wall-clock bound for the staged-install container."""


def _makeIntegrationConfig(rootDir: str, runImageTag: str, installImageTag: str) -> SandboxConfig:
    """Create a SandboxConfig for the real-Docker install integration test.

    Args:
        rootDir: Host-side root directory for sandbox storage (a unique
            subtree under ``~/.gromozeka-tests/`` — see module docstring).
        runImageTag: Per-run run-image tag (derived from the same UUID as
            ``rootDir`` so stale images from aborted runs cannot make the
            build assertion vacuous and concurrent runs cannot interfere).
        installImageTag: Per-run install-image tag (same rationale).

    Returns:
        A SandboxConfig with a Python runtime wired to the repo's real
        runtime Dockerfiles, the given per-run image tags, and root-user
        containers (desktop-VM bind-mount compatibility).
    """
    return SandboxConfig(
        storage=StorageConfig(rootDir=rootDir),
        security=SecurityConfig(user="0:0"),
        runtimes={
            RuntimeName.PYTHON: BasicRuntimeConfig(
                runImageTag=runImageTag,
                installImageTag=installImageTag,
                runDockerfile=str(REPO_ROOT / "lib/sandbox/runtimes/python/Dockerfile"),
                installDockerfile=str(REPO_ROOT / "lib/sandbox/runtimes/python/Dockerfile.install"),
                libMountPath="/sandbox/libs/python",
                env={},
                installContainer=InstallContainerConfig(),
            )
        },
    )


@pytest.fixture(autouse=True)
def _resetSandboxManagerSingleton() -> Iterator[None]:
    """Reset the SandboxManager singleton before and after the test.

    Ensures the integration test gets a fresh singleton and never leaks
    instance/config state into (or out of) the rest of the suite.

    Yields:
        None
    """
    SandboxManager._instance = None
    SandboxManager._configInstance = None
    yield
    SandboxManager._instance = None
    SandboxManager._configInstance = None


@skipUnlessDocker
@pytest.mark.slow
class TestInstallRuntimeLibrariesIntegration:
    """End-to-end install tests that require a running Docker daemon."""

    async def testRealDockerInstallInstallsPackageIntoPool(self) -> None:
        """Verify prepareRuntime + installRuntimeLibraries work against real Docker.

        Builds the run/install images from the repo's runtime Dockerfiles
        (exercising ``ensureImage`` → real image build), installs ``six`` via
        the staged-install core (staging container with the helper-script
        bind, host-side delta merge, atomic pool swap), and asserts the
        package truly landed in the pool: a ``six-*.dist-info`` directory is
        present on disk, the host-side dist-info enumeration sees it, and
        ``listRuntimeLibraries()`` reports it via the container-side
        ``pip list`` refresh that writes ``packages.json``.

        Returns:
            None
        """
        testRunId = uuid.uuid4().hex
        storageRoot = Path.home() / ".gromozeka-tests" / "test-install-integration" / testRunId
        storageRoot.mkdir(parents=True, exist_ok=True)
        runImageTag = f"{TEST_IMAGE_PREFIX}-{testRunId}:run"
        installImageTag = f"{TEST_IMAGE_PREFIX}-{testRunId}:install"
        config = _makeIntegrationConfig(str(storageRoot), runImageTag, installImageTag)
        SandboxManager.injectConfig(config)
        manager = SandboxManager.getInstance()

        try:
            prepared = await manager.prepareRuntime(RuntimeName.PYTHON)
            assert prepared is True, "prepareRuntime() failed (image build or prep error)"

            libsDir = storageRoot / "runtimes" / "python" / "libs"
            assert libsDir.is_dir(), "Library pool directory was not created by prepareRuntime()"

            installed = await manager.installRuntimeLibraries(
                packages=[INSTALL_PACKAGE],
                runtime=RuntimeName.PYTHON,
                timeoutSeconds=INSTALL_TIMEOUT_SECONDS,
            )
            assert installed is True, "installRuntimeLibraries() failed (stage container or swap error)"

            # dist-info physically present in the swapped-in pool
            distInfoDirs = list(libsDir.glob(f"{INSTALL_PACKAGE}-*.dist-info"))
            assert distInfoDirs, f"No {INSTALL_PACKAGE}-*.dist-info directory found in {libsDir}"

            # The actual package payload (not just dist-info metadata) survived
            # the merge: six is a single-module package, so six.py must exist.
            assert (libsDir / "six.py").is_file(), f"{INSTALL_PACKAGE} payload (six.py) missing from {libsDir}"

            # Host-side enumeration sees the canonical name with a version
            poolInventory = enumerateDistInfos(libsDir)
            assert INSTALL_PACKAGE in poolInventory, (
                f"{INSTALL_PACKAGE} missing from host-side dist-info enumeration: " f"{sorted(poolInventory.keys())}"
            )

            # Metadata layer sees it too: the container-side pip-list refresh
            # must have parsed the pool and written packages.json.
            packagesInfo = await manager.listRuntimeLibraries(RuntimeName.PYTHON)
            installedNames = [packageInfo.name for packageInfo in packagesInfo]
            assert (
                INSTALL_PACKAGE in installedNames
            ), f"{INSTALL_PACKAGE} missing from listRuntimeLibraries(): {installedNames}"
        finally:
            cleanupErrors: list[str] = []
            backend = manager._backend
            # The real-Docker test always runs on DockerBackend; narrow the
            # type explicitly so a backend swap fails loudly instead of
            # silently skipping postcondition verification.
            assert isinstance(backend, DockerBackend), "backend is not DockerBackend"
            try:
                # Remove containers created by this test BEFORE the images:
                # a kept-for-post-mortem stage container would otherwise make
                # image deletion fail with a 409 conflict. Ownership is
                # identified by the per-run image tags.
                try:
                    managedContainers = await backend.listManagedContainers()
                except Exception as exc:
                    managedContainers = []
                    cleanupErrors.append(f"failed to list managed containers: {exc}")
                for container in managedContainers:
                    try:
                        inspectData = await backend.inspectContainer(container.containerId)
                        containerImage = inspectData.get("Config", {}).get("Image", "")
                    except Exception as exc:
                        cleanupErrors.append(
                            f"failed to inspect container {container.containerId} for ownership: {exc}"
                        )
                        continue
                    if containerImage not in (runImageTag, installImageTag):
                        continue
                    try:
                        await backend.removeContainer(container.containerId, force=True)
                    except Exception as exc:
                        cleanupErrors.append(f"failed to remove container {container.containerId}: {exc}")
                for imageTag in (runImageTag, installImageTag):
                    try:
                        await backend.removeImage(imageTag)
                    except Exception as exc:
                        cleanupErrors.append(f"failed to remove image {imageTag}: {exc}")

                # Postcondition verification against the daemon:
                # removeContainer()/removeImage() deliberately swallow
                # DockerError internally, so removal failures would otherwise
                # leave cleanupErrors empty while artifacts remain. Not-found
                # counts as removed; anything else is reported.
                try:
                    remainingContainers = await backend.listManagedContainers()
                except Exception as exc:
                    cleanupErrors.append(f"failed to verify container removal: {exc}")
                else:
                    for container in remainingContainers:
                        try:
                            inspectData = await backend.inspectContainer(container.containerId)
                        except Exception as exc:
                            isNotFound = isinstance(exc, aiodocker.DockerError) and exc.status == 404
                            if not isNotFound:
                                cleanupErrors.append(f"failed to re-inspect container {container.containerId}: {exc}")
                            continue
                        containerImage = inspectData.get("Config", {}).get("Image", "")
                        if containerImage in (runImageTag, installImageTag):
                            cleanupErrors.append(
                                f"container {container.containerId} (image {containerImage}) still present"
                                " after cleanup"
                            )
                try:
                    dockerClient = await backend._getClient()
                except Exception as exc:
                    dockerClient = None
                    cleanupErrors.append(f"failed to open client for image postcondition: {exc}")
                if dockerClient is not None:
                    for imageTag in (runImageTag, installImageTag):
                        try:
                            await dockerClient.images.inspect(imageTag)
                        except Exception as exc:
                            isNotFound = isinstance(exc, aiodocker.DockerError) and exc.status == 404
                            if not isNotFound:
                                cleanupErrors.append(f"failed to verify removal of image {imageTag}: {exc}")
                        else:
                            cleanupErrors.append(f"image {imageTag} still present after cleanup")
            finally:
                try:
                    await backend.close()
                except Exception as exc:
                    cleanupErrors.append(f"failed to close backend: {exc}")
                # Remove ONLY this run's UUID workspace: the shared
                # ``test-install-integration/`` parent is never removed
                # recursively and is removed only when empty (guarded
                # non-recursive ``rmdir()`` below), so concurrent runs
                # never delete each other's workspaces.
                try:
                    shutil.rmtree(storageRoot)
                except OSError as exc:
                    cleanupErrors.append(f"failed to remove storage root {storageRoot}: {exc}")
                # Best-effort removal of the shared parent once this was the
                # last workspace (non-recursive; silently kept if non-empty or
                # already gone).
                try:
                    storageRoot.parent.rmdir()
                except OSError:
                    pass
            if cleanupErrors:
                if sys.exc_info()[0] is None:
                    pytest.fail(f"Cleanup failed: {'; '.join(cleanupErrors)}")
                else:
                    warnings.warn(f"Cleanup failed (body already failed): {'; '.join(cleanupErrors)}")
