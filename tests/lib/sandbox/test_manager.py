"""Tests for SandboxManager (lib.sandbox.manager).

Covers:
- swapBackend() two-reference invariant (shared helper, defined in
  ``tests/lib/sandbox/conftest.py``): the helper must rewire BOTH
  backend captures the manager's constructor makes — ``manager._backend``
  and the ``GarbageCollector``'s constructor-time ``manager._gc._backend``
  — so the mock-backend isolation contract is pinned structurally and
  cannot regress silently when the Docker daemon is unreachable.
- runCode() workDir behaviour: RunResult.workDir is set to the expected
  workspace-relative path format and the work/ directory is created on disk.
- RunResult.workDir default: the field defaults to empty string when not
  provided.
- installRuntimeLibraries() timeout sourcing: the container timeout comes
  from the runtime's ``install-container.timeout-seconds`` config unless the
  caller passes an explicit ``timeoutSeconds`` argument.
- installRuntimeLibraries() container cleanup: the install container is
  removed after a successful install and kept (for log inspection via
  ``docker logs``) when the install fails.
- installRuntimeLibraries() staged core (docs/plans/sandbox-update-v1.md
  §5.5): the install container is a staging container — it mounts the run
  dir's ``io/`` subtree rw plus the helper read-only, NEVER the live pool —
  runs ``stageRun`` and carries the ``sandbox.purpose="install"``
  + ``sandbox.stagingRunId`` labels. Also pinned: the ratified corruption-bug
  regression (reinstalling an already-present package replaces the old
  dist-info cleanly — no lying metadata, no duplicates, no stale code),
  fresh install into an empty pool, stage failure keeps the container with
  the pool byte-identical, spec-validation semantics, and LibraryPoolLocked
  propagation.
- updateRuntimeLibraries() staged flow (docs/plans/sandbox-update-v1.md
  §5.1): the two update ContainerSpecs (pre-filter report + staged install —
  staging mount, helper bind, never the pool, stagingRunId GC liveness
  label), validation and ConfigError pre-checks, the fail-safe pre-filter
  report parsing, the empty-outdated early success (exactly ONE pool-lock
  acquisition — the opportunistic recovery pass — no stage container),
  the empty-pool false-success guard (a deferred/failed recovery with crash
  leftovers propagates instead of reporting "Nothing installed", §4.5),
  duplicate dist-info names forced outdated and healed by the
  merge (§9), the old→new diff computed from before/after pool dist-info
  enumerations, LibraryPoolLocked propagation, keep-stage-container-on-
  failure with the pool left byte-identical on disk, the update-all name
  set (enumeration ∪ packages.json, grammar-invalid names skipped), and
  the recover() crash-window adoption cases (§4.5): empty-libs adoption,
  fail-closed recovery (prepare/refresh/staging-GC skipped on failure),
  newpool→oldpool fallback, and pool-lock deferral.

The DockerBackend is replaced with a mock so that no real Docker daemon is
required; the fake pip containers write their report/delta artifacts into
the staging directory they were mounted, so the real host-side
merge/swap/enumeration machinery runs end-to-end.
"""

import fcntl
import hashlib
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.sandbox import locks as sandboxLocks
from lib.sandbox.config import (
    BasicRuntimeConfig,
    InstallContainerConfig,
    SandboxConfig,
    StorageConfig,
)
from lib.sandbox.enums import RuntimeName
from lib.sandbox.errors import ConfigError, InvalidPackageSpec, LibraryPoolLocked, PoolSwapRollbackFailed
from lib.sandbox.manager import STAGING_IO_DIRNAME, SandboxManager, _diffPoolVersions
from lib.sandbox.runtimes.python.pool_staging import DistInfoEntry
from lib.sandbox.runtimes.python.runtime import PythonRuntime
from lib.sandbox.types import ContainerOutcome, ContainerSpec, PackageInfo, PackageUpdate, RunResult
from tests.lib.sandbox.conftest import swapBackend

# ============================================================================
# Helpers
# ============================================================================


def _makeSandboxConfig(
    rootDir: str,
    *,
    installContainer: InstallContainerConfig | None = None,
) -> SandboxConfig:
    """Create a minimal SandboxConfig for testing.

    Args:
        rootDir: Host-side root directory for sandbox storage.
        installContainer: Optional install-container limits; defaults to
            ``InstallContainerConfig()`` defaults.

    Returns:
        A SandboxConfig with a Python runtime and test-friendly defaults.
    """
    return SandboxConfig(
        storage=StorageConfig(rootDir=rootDir),
        runtimes={
            RuntimeName.PYTHON: BasicRuntimeConfig(
                runImageTag="test-python:run",
                installImageTag="test-python:install",
                runDockerfile="lib/sandbox/runtimes/python/Dockerfile",
                installDockerfile="lib/sandbox/runtimes/python/Dockerfile.install",
                libMountPath="/sandbox/libs/python",
                env={},
                installContainer=installContainer if installContainer is not None else InstallContainerConfig(),
            )
        },
    )


def _makeContainerOutcome(
    *,
    exitCode: int = 0,
    containerId: str = "fake-container-id",
    signal: str | None = None,
    oomKilled: bool = False,
) -> ContainerOutcome:
    """Create a minimal ContainerOutcome for testing.

    Args:
        exitCode: Process exit code to return.
        containerId: Container id to embed in the outcome.
        signal: Signal that killed the process, if any.
        oomKilled: Whether the container was OOM-killed.

    Returns:
        A ContainerOutcome with the specified outcome fields.
    """
    return ContainerOutcome(
        containerId=containerId,
        exitCode=exitCode,
        signal=signal,
        oomKilled=oomKilled,
        inspects={},
    )


def _makeMockBackend(outcome: ContainerOutcome) -> MagicMock:
    """Create a mock backend that returns the given outcome from runOneshot.

    Args:
        outcome: The ContainerOutcome to return from runOneshot.

    Returns:
        A MagicMock configured as a DockerBackend replacement.
    """
    backend = MagicMock()
    backend.runOneshot = AsyncMock(return_value=outcome)
    backend.removeContainer = AsyncMock(return_value=None)
    backend.listManagedContainers = AsyncMock(return_value=[])
    backend.close = AsyncMock(return_value=None)
    backend.ensureImage = AsyncMock(return_value=None)
    backend.healthcheck = AsyncMock(return_value=MagicMock(ok=True, errors=[]))
    return backend


def _makeDistInfo(
    poolDir: Path,
    dirName: str,
    *,
    name: str,
    version: str,
    payloadFiles: list[str],
) -> Path:
    """Create a fake dist-info directory (METADATA + RECORD + payload files).

    Same on-disk shape pip produces under ``--target``: the METADATA
    ``Name:`` header drives enumeration, RECORD lists the payload paths.

    Args:
        poolDir: Pool (or delta) root; payload paths are created relative
            to it.
        dirName: dist-info directory name (must end with ``.dist-info``).
        name: Value for the METADATA ``Name:`` header.
        version: Value for the METADATA ``Version:`` header.
        payloadFiles: Paths owned by the package (relative to poolDir).

    Returns:
        The created dist-info directory path.
    """
    distInfoDir = poolDir / dirName
    distInfoDir.mkdir(parents=True)
    (distInfoDir / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    lines = [f"{p},sha256={'0' * 8},{11 + len(p)}" for p in payloadFiles]
    lines.append(f"{dirName}/RECORD,,")
    (distInfoDir / "RECORD").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for relPath in payloadFiles:
        target = poolDir / relPath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"body of {relPath} @ {version}", encoding="utf-8")
    return distInfoDir


def _makePool(libsDir: Path, packages: dict[str, str]) -> None:
    """Populate a fake pool with one dist-info per name→version.

    Args:
        libsDir: Pool directory (created including parents).
        packages: Mapping from package name to version.
    """
    for name, version in packages.items():
        _makeDistInfo(
            libsDir,
            f"{name}-{version}.dist-info",
            name=name,
            version=version,
            payloadFiles=[f"{name}/__init__.py"],
        )


def _ageDirByMtime(directory: Path, minutes: float) -> None:
    """Set a directory's mtime to be the given age in the past.

    Args:
        directory: The directory to age.
        minutes: How many minutes in the past to set the mtime.
    """
    oldTime = time.time() - (minutes * 60)
    os.utime(directory, (oldTime, oldTime))


def _oneshotSequence(
    *steps: ContainerOutcome | Callable[[ContainerSpec], Awaitable[ContainerOutcome]],
) -> Callable[[ContainerSpec], Awaitable[ContainerOutcome]]:
    """Build a runOneshot side effect dispatching steps in call order.

    AsyncMock treats side_effect LIST elements as plain return values and
    never invokes them, so the callable fake-container steps (report/delta
    writers) need this dispatcher: callable steps are awaited with the
    call's spec, plain ContainerOutcome steps are returned verbatim.

    Args:
        steps: One step per expected runOneshot call, in order.

    Returns:
        An async dispatcher usable as the runOneshot side_effect.
    """
    iterator = iter(steps)

    async def dispatch(spec: ContainerSpec) -> ContainerOutcome:
        """Return the next step's outcome for this call.

        Args:
            spec: The ContainerSpec passed to runOneshot.

        Returns:
            The step's ContainerOutcome.

        Raises:
            AssertionError: If runOneshot is called more times than steps.
        """
        try:
            step = next(iterator)
        except StopIteration as exc:
            raise AssertionError("More runOneshot calls than expected steps") from exc
        if callable(step):
            return await step(spec)
        return step

    return dispatch


def _stagingHostDir(spec: ContainerSpec) -> Path:
    """Return the host-side staging directory bound into a container spec.

    Args:
        spec: The ContainerSpec passed to runOneshot.

    Returns:
        The hostPath of the mount targeting ``STAGING_CONTAINER_PATH``.
    """
    for mount in spec.mounts:
        if mount["containerPath"] == PythonRuntime.STAGING_CONTAINER_PATH:
            return Path(mount["hostPath"])
    raise AssertionError(f"ContainerSpec has no staging mount: {spec.mounts}")


def _reportSideEffect(report: dict[str, str] | str | None) -> Callable[[ContainerSpec], Awaitable[ContainerOutcome]]:
    """Build a runOneshot side effect behaving as the dry-run report container.

    Args:
        report: Mapping serialised as the report's ``install[]`` entries, a
            raw string written verbatim (unparseable-report case), or None
            to write nothing (missing report file).

    Returns:
        An async callable usable as an AsyncMock side_effect element.
    """

    async def effect(spec: ContainerSpec) -> ContainerOutcome:
        """Write the report into the mounted staging dir and succeed.

        Args:
            spec: The ContainerSpec the manager passed to runOneshot.

        Returns:
            A successful ContainerOutcome for the pre-filter container.
        """
        if report is not None:
            stagingDir = _stagingHostDir(spec)
            stagingDir.mkdir(parents=True, exist_ok=True)
            if isinstance(report, str):
                (stagingDir / "report.json").write_text(report, encoding="utf-8")
            else:
                installList = [{"metadata": {"name": name, "version": version}} for name, version in report.items()]
                (stagingDir / "report.json").write_text(json.dumps({"install": installList}), encoding="utf-8")
        return _makeContainerOutcome(exitCode=0, containerId="prefilter-cid")

    return effect


def _deltaSideEffect(delta: dict[str, str]) -> Callable[[ContainerSpec], Awaitable[ContainerOutcome]]:
    """Build a runOneshot side effect behaving as the staged pip install.

    Args:
        delta: Mapping from package name to version to stage as fake
            dist-infos inside the mounted staging dir's ``delta/``.

    Returns:
        An async callable usable as an AsyncMock side_effect element.
    """

    async def effect(spec: ContainerSpec) -> ContainerOutcome:
        """Stage the fake delta into the mounted staging dir and succeed.

        Args:
            spec: The ContainerSpec the manager passed to runOneshot.

        Returns:
            A successful ContainerOutcome for the stage container.
        """
        deltaDir = _stagingHostDir(spec) / "delta"
        deltaDir.mkdir(parents=True, exist_ok=True)
        for name, version in delta.items():
            _makeDistInfo(
                deltaDir,
                f"{name}-{version}.dist-info",
                name=name,
                version=version,
                payloadFiles=[f"{name}/__init__.py"],
            )
        return _makeContainerOutcome(exitCode=0, containerId="stage-cid")

    return effect


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _resetSandboxManagerSingleton():
    """Reset SandboxManager singleton before and after each test.

    Ensures each test gets a fresh SandboxManager instance.

    Yields:
        None
    """
    SandboxManager._instance = None
    SandboxManager._configInstance = None
    yield
    SandboxManager._instance = None
    SandboxManager._configInstance = None


# ============================================================================
# Tests — swapBackend helper (two-reference invariant)
# ============================================================================


class TestSwapBackendHelper:
    """Pins the ``swapBackend`` two-reference invariant.

    ``SandboxManager.__init__`` captures the real ``DockerBackend`` twice:
    once in ``manager._backend`` and once inside the internal
    ``GarbageCollector`` (``manager._gc._backend``, the constructor-time
    ``backend=`` argument). A regression that rewires only the first
    capture leaves the GC holding the real backend, and with Docker
    unreachable (the CI default) every mock-backend test would STILL pass —
    the GC's real-Docker failures are swallowed inside ``collectGarbage()``.
    Pinning the invariant directly makes that regression fail
    deterministically, independent of daemon reachability.
    """

    def _makeFreshManager(self, tmp_path: Path) -> SandboxManager:
        """Build a fresh SandboxManager still holding its real backend.

        Same construction sequence as the per-class ``_makeManager``
        factories in this file, but WITHOUT the ``swapBackend`` call —
        the swap itself is the behaviour under test.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            A newly constructed SandboxManager (singleton reset by the
            autouse fixture) with both real backend captures in place.
        """
        SandboxManager.injectConfig(_makeSandboxConfig(str(tmp_path / "sandbox")))
        return SandboxManager.getInstance()

    def testSwapBackendReplacesBothManagerAndGcReferences(self, tmp_path: Path) -> None:
        """swapBackend must rewire BOTH manager._backend AND manager._gc._backend.

        Why the second identity matters: the ``GarbageCollector`` holds a
        SECOND, constructor-time capture of the real ``DockerBackend``
        (``SandboxManager.__init__`` passes ``backend=self._backend`` into
        the ``GarbageCollector``). A regression that removes the second
        assignment in ``swapBackend`` keeps that capture real, so
        ``recover()`` → ``collectGarbage()`` performs REAL Docker I/O
        (list/kill/remove of managed containers): the orphaned aiodocker
        client surfaces as ``ResourceWarning: Unclosed connector/socket``
        and the I/O itself is an orphan-container kill/remove hazard. The
        behavioural tests cannot catch this — the GC swallows backend
        connection failures — so only this structural identity pin makes
        the regression fail deterministically, regardless of whether a
        Docker daemon is reachable.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        manager = self._makeFreshManager(tmp_path)

        # Constructor-time precondition: both captures hold the SAME real
        # backend, so re-wiring one while missing the other is observable.
        assert (
            manager._backend is manager._gc._backend
        ), "SandboxManager.__init__ must hand the same backend to the manager and the GC"

        backend = MagicMock(name="distinctive-swap-backend")
        swapBackend(manager, backend)

        assert manager._backend is backend, "manager._backend must hold the swapped mock backend"
        assert manager._gc._backend is backend, (
            "manager._gc._backend must hold the swapped mock backend too — leaving the "
            "GC's constructor-time capture real makes recover()→collectGarbage() do real Docker I/O"
        )


# ============================================================================
# Tests — RunResult.workDir default
# ============================================================================


def testRunResultWorkDirDefaultsToEmptyString() -> None:
    """Verify that RunResult.workDir defaults to empty string.

    When a RunResult is constructed without explicitly providing workDir,
    the field must default to an empty string so that legacy serialisations
    (which lack the key) remain compatible.

    Returns:
        None
    """
    started = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2025, 6, 1, 12, 0, 1, tzinfo=timezone.utc)
    rr = RunResult(
        runId="run-default-workdir",
        sessionId="sess-001",
        runtime=RuntimeName.PYTHON,
        stdoutPath=".run/run-default-workdir/stdout.log",
        stderrPath=".run/run-default-workdir/stderr.log",
        stdoutBytes=0,
        stderrBytes=0,
        exitCode=0,
        signal=None,
        timedOut=False,
        oomKilled=False,
        startedAt=started,
        finishedAt=finished,
        elapsedMs=1000,
        networkEnabled=False,
        error=None,
    )
    assert rr.workDir == ""


# ============================================================================
# Tests — RunResult.workDir format
# ============================================================================


def testRunResultWorkDirFormatMatchesManagerOutput() -> None:
    """Verify that the workDir format matches what SandboxManager.runCode() produces.

    The manager constructs workDir as ``.run/{runId}/work``.  This test
    verifies that a RunResult with that format is well-formed and
    round-trips correctly through toDict/fromDict.

    Returns:
        None
    """
    runId = "abc-123-def"
    started = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2025, 6, 1, 12, 0, 2, tzinfo=timezone.utc)
    workDir = f".run/{runId}/work"
    rr = RunResult(
        runId=runId,
        sessionId="sess-001",
        workDir=workDir,
        runtime=RuntimeName.PYTHON,
        stdoutPath=f".run/{runId}/stdout.log",
        stderrPath=f".run/{runId}/stderr.log",
        stdoutBytes=10,
        stderrBytes=0,
        exitCode=0,
        signal=None,
        timedOut=False,
        oomKilled=False,
        startedAt=started,
        finishedAt=finished,
        elapsedMs=2000,
        networkEnabled=False,
        error=None,
    )
    assert rr.workDir == f".run/{runId}/work"
    # Round-trip through serialisation
    restored = RunResult.fromDict(rr.toDict())
    assert restored.workDir == f".run/{runId}/work"


# ============================================================================
# Tests — runCode() workDir integration (mocked backend)
# ============================================================================


async def testRunCodeSetsWorkDirAndCreatesDirectory(tmp_path: Path) -> None:
    """Verify that runCode() sets RunResult.workDir and creates the work/ directory.

    Replaces the DockerBackend with a mock so no real Docker daemon is
    needed.  After runCode() completes successfully, result.workDir must
    equal ``.run/{runId}/work`` and the directory must exist on disk inside
    the session workspace.

    Args:
        tmp_path: pytest-provided temporary directory.

    Returns:
        None
    """
    rootDir = str(tmp_path / "sandbox")
    config = _makeSandboxConfig(rootDir)
    SandboxManager.injectConfig(config)

    manager = SandboxManager.getInstance()

    # Replace the backend with a mock so no Docker calls are made.
    mockOutcome = _makeContainerOutcome(exitCode=0)
    swapBackend(manager, _makeMockBackend(mockOutcome))

    # Mark the Python runtime as prepared so prepareRuntime() is skipped.
    manager._runtimes[RuntimeName.PYTHON].markPrepared()

    result = await manager.runCode(
        sessionId="test-session",
        code="print('hello')",
        runtime=RuntimeName.PYTHON,
    )

    # workDir must follow the expected format
    assert result.workDir == f".run/{result.runId}/work"

    # The work/ directory must actually exist on disk
    workspacePath = tmp_path / "sandbox" / "sessions"
    # Find the session workspace (there should be exactly one)
    sessionDirs = list(workspacePath.iterdir())
    assert len(sessionDirs) == 1
    workDirOnDisk = sessionDirs[0] / "workspace" / ".run" / result.runId / "work"
    assert workDirOnDisk.is_dir(), f"Expected work directory {workDirOnDisk} to exist"


async def testRunCodeWorkDirIsWorkspaceRelative(tmp_path: Path) -> None:
    """Verify that workDir is a workspace-relative path, not absolute.

    The workDir field must be relative to the session workspace root
    (e.g. ``.run/<runId>/work``), never an absolute filesystem path.

    Args:
        tmp_path: pytest-provided temporary directory.

    Returns:
        None
    """
    rootDir = str(tmp_path / "sandbox")
    config = _makeSandboxConfig(rootDir)
    SandboxManager.injectConfig(config)

    manager = SandboxManager.getInstance()
    mockOutcome = _makeContainerOutcome(exitCode=0)
    swapBackend(manager, _makeMockBackend(mockOutcome))
    manager._runtimes[RuntimeName.PYTHON].markPrepared()

    result = await manager.runCode(
        sessionId="test-session-rel",
        code="pass",
        runtime=RuntimeName.PYTHON,
    )

    # workDir must not start with '/' (it's workspace-relative)
    assert not result.workDir.startswith("/"), f"workDir must be relative, got: {result.workDir}"
    # workDir must start with '.run/'
    assert result.workDir.startswith(".run/"), f"workDir must start with '.run/', got: {result.workDir}"
    # workDir must end with '/work'
    assert result.workDir.endswith("/work"), f"workDir must end with '/work', got: {result.workDir}"


# ============================================================================
# Tests — installRuntimeLibraries() timeout sourcing (mocked backend)
# ============================================================================


class TestInstallRuntimeLibrariesTimeout:
    """Pins the dead-config bug: install-container.timeout-seconds was ignored.

    Before the fix, ``installRuntimeLibraries()`` took ``timeoutSeconds: int = 600``
    as a method-parameter default and never read the parsed
    ``InstallContainerConfig.timeoutSeconds``. Every caller (the ``/sandbox install``
    handler) omitted the argument, so the configured timeout
    was dead config and installs were watchdog-killed at 600s+60s+1s regardless of
    configuration.
    """

    async def testInstallUsesConfiguredInstallTimeout(self, tmp_path: Path) -> None:
        """Install container timeout must come from install-container config.

        With ``install-container.timeout-seconds = 7200`` configured and no explicit
        ``timeoutSeconds`` argument, the ContainerSpec passed to runOneshot must
        carry ``limits.timeoutSeconds == 7200``. Before the fix it carried the
        hard-coded method default 600.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = str(tmp_path / "sandbox")
        config = _makeSandboxConfig(
            rootDir,
            installContainer=InstallContainerConfig(timeoutSeconds=7200, memoryMb=2048, pidsLimit=128),
        )
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        swapBackend(manager, backend)

        success = await manager.installRuntimeLibraries(
            packages=["pybullet"],
            runtime=RuntimeName.PYTHON,
        )
        assert success is True

        # First runOneshot call is the staged-install (stage) container (a
        # second one may follow from _refreshPackageList on the success
        # path).
        installSpec = backend.runOneshot.await_args_list[0].kwargs["spec"]
        assert (
            installSpec.limits.timeoutSeconds == 7200
        ), "install-container.timeout-seconds config must drive the install container timeout"

    async def testInstallExplicitTimeoutOverridesConfig(self, tmp_path: Path) -> None:
        """An explicit timeoutSeconds argument must win over the config value.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = str(tmp_path / "sandbox")
        config = _makeSandboxConfig(
            rootDir,
            installContainer=InstallContainerConfig(timeoutSeconds=7200),
        )
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        swapBackend(manager, backend)

        success = await manager.installRuntimeLibraries(
            packages=["pybullet"],
            runtime=RuntimeName.PYTHON,
            timeoutSeconds=300,
        )
        assert success is True

        installSpec = backend.runOneshot.await_args_list[0].kwargs["spec"]
        assert installSpec.limits.timeoutSeconds == 300, "explicit timeoutSeconds argument must override config"

    async def testInstallDefaultConfigTimeoutRemains600(self, tmp_path: Path) -> None:
        """Default config (no timeout-seconds override) must keep the 600s timeout.

        Pins that the fallback does not change behaviour for deployments that
        rely on the default install timeout.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = str(tmp_path / "sandbox")
        config = _makeSandboxConfig(rootDir)
        SandboxManager.injectConfig(config)

        manager = SandboxManager.getInstance()
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        swapBackend(manager, backend)

        success = await manager.installRuntimeLibraries(
            packages=["pybullet"],
            runtime=RuntimeName.PYTHON,
        )
        assert success is True

        installSpec = backend.runOneshot.await_args_list[0].kwargs["spec"]
        assert installSpec.limits.timeoutSeconds == 600


# ============================================================================
# Tests — installRuntimeLibraries() container cleanup (mocked backend)
# ============================================================================


class TestInstallRuntimeLibrariesContainerCleanup:
    """Pins the install-container leak: successful installs must remove the container.

    Before the fix, ``installRuntimeLibraries()`` never removed the install
    container (success or failure), violating the ``runOneshot`` contract that the
    caller collects artifacts and then calls ``removeContainer``. Failed installs
    deliberately KEEP the container so the operator can inspect logs via
    ``docker logs <containerId>``.
    """

    def _makeManager(self, tmp_path: Path, backend: MagicMock) -> SandboxManager:
        """Build a SandboxManager wired to the given mock backend.

        Args:
            tmp_path: pytest-provided temporary directory.
            backend: Mock backend to inject.

        Returns:
            A SandboxManager instance with the mock backend installed.
        """
        SandboxManager.injectConfig(_makeSandboxConfig(str(tmp_path / "sandbox")))
        manager = SandboxManager.getInstance()
        swapBackend(manager, backend)
        return manager

    async def testInstallRemovesInstallContainerOnSuccess(self, tmp_path: Path) -> None:
        """A successful install must remove the install container.

        The success path launches two containers (install, then the package-list
        refresh); both must be removed. Before the fix only the list container was
        removed — the install container leaked.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0, containerId="install-cid-1"))
        backend.runOneshot = AsyncMock(
            side_effect=[
                _makeContainerOutcome(exitCode=0, containerId="install-cid-1"),
                _makeContainerOutcome(exitCode=0, containerId="list-cid-2"),
            ]
        )
        manager = self._makeManager(tmp_path, backend)

        success = await manager.installRuntimeLibraries(
            packages=["pybullet"],
            runtime=RuntimeName.PYTHON,
        )
        assert success is True

        removedIds = [call.args[0] for call in backend.removeContainer.await_args_list]
        assert "install-cid-1" in removedIds, "install container must be removed after a successful install"

    async def testInstallKeepsContainerOnFailureForLogInspection(self, tmp_path: Path) -> None:
        """A failed install must NOT remove the install container.

        The container is kept on purpose so the operator can inspect pip output
        via ``docker logs <containerId>``.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=1, containerId="install-cid-fail"))
        manager = self._makeManager(tmp_path, backend)

        success = await manager.installRuntimeLibraries(
            packages=["pybullet"],
            runtime=RuntimeName.PYTHON,
        )
        assert success is False

        backend.removeContainer.assert_not_awaited()

    async def testInstallRemoveFailureDoesNotFailInstall(self, tmp_path: Path) -> None:
        """A removeContainer error after a successful install must not fail the install.

        Cleanup is best-effort: the install already succeeded, so a removal
        failure is logged and the method still returns True.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0, containerId="install-cid-3"))
        backend.runOneshot = AsyncMock(
            side_effect=[
                _makeContainerOutcome(exitCode=0, containerId="install-cid-3"),
                _makeContainerOutcome(exitCode=0, containerId="list-cid-4"),
            ]
        )
        backend.removeContainer = AsyncMock(side_effect=RuntimeError("docker daemon gone"))
        manager = self._makeManager(tmp_path, backend)

        success = await manager.installRuntimeLibraries(
            packages=["pybullet"],
            runtime=RuntimeName.PYTHON,
        )
        assert success is True


# ============================================================================
# Tests — installRuntimeLibraries() staged core (docs/plans/sandbox-update-v1.md §5.5)
# ============================================================================


class TestInstallRuntimeLibrariesStagedCore:
    """Install routed through the shared staged copy → stage → merge → swap core.

    Pins the NEW install container contract (plan §5.5): the install
    container is a staging container — it mounts the run dir's ``io/``
    subtree read-write and the helper script read-only, NEVER the live
    pool — runs ``stageRun`` and carries the
    ``sandbox.purpose="install"`` + ``sandbox.stagingRunId`` labels. Also
    pins the ratified corruption-bug regression: reinstalling an
    already-present package cleanly replaces the old dist-info (the old
    live-pool ``pip --target`` path skipped code replacement but wrote the
    new dist-info — lying metadata, duplicate dist-infos, stale code).
    """

    def _makeManager(self, tmp_path: Path, backend: MagicMock) -> SandboxManager:
        """Build a SandboxManager wired to the given mock backend.

        Args:
            tmp_path: pytest-provided temporary directory.
            backend: Mock backend to inject.

        Returns:
            A SandboxManager instance with the mock backend installed.
        """
        SandboxManager.injectConfig(_makeSandboxConfig(str(tmp_path / "sandbox")))
        manager = SandboxManager.getInstance()
        swapBackend(manager, backend)
        return manager

    def _libsDir(self, tmp_path: Path) -> Path:
        """Return the Python runtime's library pool directory path.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            The pool directory path (not created).
        """
        return tmp_path / "sandbox" / "runtimes" / "python" / "libs"

    async def testInstallContainerSpecStagesIntoIoSubtree(self, tmp_path: Path) -> None:
        """The install container mounts the io/ subtree, never the pool (plan §5.5).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _deltaSideEffect({"pybullet": "3.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        success = await manager.installRuntimeLibraries(
            packages=["pybullet"],
            runtime=RuntimeName.PYTHON,
        )

        assert success is True
        assert backend.runOneshot.await_count == 2  # stage container + list refresh

        runtimeImpl = manager._runtimes[RuntimeName.PYTHON]
        stageSpec = backend.runOneshot.await_args_list[0].kwargs["spec"]
        assert stageSpec.command == runtimeImpl.stageRun(Path("io"), ["pybullet"]).command
        assert stageSpec.name.startswith("sandbox-install-")
        assert stageSpec.labels["sandbox.purpose"] == "install"
        assert stageSpec.labels["sandbox.managed"] == "true"
        assert stageSpec.labels["sandbox.runtime"] == "python"
        assert stageSpec.labels["sandbox.stagingRunId"], "the GC liveness label must be present"
        # Mounts: staging io/ rw + helper ro — the live pool is NEVER mounted.
        assert len(stageSpec.mounts) == 2
        poolMounts = [m for m in stageSpec.mounts if m["containerPath"] == runtimeImpl._config.libMountPath]
        assert poolMounts == []
        stagingMounts = [m for m in stageSpec.mounts if m["containerPath"] == PythonRuntime.STAGING_CONTAINER_PATH]
        assert stagingMounts and stagingMounts[0]["mode"] == "rw"
        helperMounts = [m for m in stageSpec.mounts if m["containerPath"] == PythonRuntime.UPDATE_HELPER_CONTAINER_PATH]
        assert helperMounts and helperMounts[0]["mode"] == "ro"
        # Mount scope: the container sees ONLY the io/ subtree — the pool
        # copies live outside every mount.
        assert stagingMounts[0]["hostPath"].endswith(f"/{STAGING_IO_DIRNAME}")
        assert all("newpool" not in m["hostPath"] and "oldpool" not in m["hostPath"] for m in stageSpec.mounts)

    async def testReinstallingPresentPackageReplacesOldDistInfo(self, tmp_path: Path) -> None:
        """Regression: reinstalling an installed package replaces it cleanly.

        The pool holds numpy 1.0 (METADATA + RECORD + payload files,
        including ``numpy/old_extra.py`` present only in the old version).
        Installing numpy==2.0 must leave EXACTLY one numpy dist-info
        (2.0), recreate the shared path ``numpy/__init__.py`` from the new
        version, and drop the old-only file — no lying metadata, no
        duplicate dist-infos, no stale code. The pre-fix live-pool
        ``pip --target`` path (no ``--upgrade`` satisfaction check) skipped
        code replacement but still wrote the new dist-info (ratified bug,
        plan §1 fact 3 / §5.5).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        libsDir = self._libsDir(tmp_path)
        _makeDistInfo(
            libsDir,
            "numpy-1.0.dist-info",
            name="numpy",
            version="1.0",
            payloadFiles=["numpy/__init__.py", "numpy/old_extra.py"],
        )
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _deltaSideEffect({"numpy": "2.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        success = await manager.installRuntimeLibraries(
            packages=["numpy==2.0"],
            runtime=RuntimeName.PYTHON,
        )

        assert success is True
        # Exactly one dist-info for the name remains — the staged one.
        assert [p.name for p in libsDir.glob("numpy-*.dist-info")] == ["numpy-2.0.dist-info"]
        assert not (libsDir / "numpy-1.0.dist-info").exists()
        # The shared path was deleted per the old RECORD, then recreated
        # from the delta — its content is the NEW version's.
        initPath = libsDir / "numpy" / "__init__.py"
        assert initPath.is_file()
        assert initPath.read_text(encoding="utf-8") == "body of numpy/__init__.py @ 2.0"
        # The old-only payload file is gone with the old dist-info.
        assert not (libsDir / "numpy" / "old_extra.py").exists()
        # The surviving metadata is truthful.
        metadata = (libsDir / "numpy-2.0.dist-info" / "METADATA").read_text(encoding="utf-8")
        assert "Name: numpy" in metadata
        assert "Version: 2.0" in metadata

    async def testFreshInstallIntoEmptyPool(self, tmp_path: Path) -> None:
        """First install into an empty (absent) pool lands the staged delta.

        The copy of the empty dir merges the delta in and the swap puts it
        live (plan §5.5: works naturally).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _deltaSideEffect({"numpy": "2.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        success = await manager.installRuntimeLibraries(
            packages=["numpy"],
            runtime=RuntimeName.PYTHON,
        )

        assert success is True
        libsDir = self._libsDir(tmp_path)
        assert (libsDir / "numpy-2.0.dist-info").is_dir()
        assert (libsDir / "numpy" / "__init__.py").read_text(encoding="utf-8") == "body of numpy/__init__.py @ 2.0"

    async def testStageFailureKeepsContainerAndPoolUntouched(self, tmp_path: Path) -> None:
        """A failed stage keeps the container and leaves the pool byte-identical.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _makeContainerOutcome(exitCode=1, containerId="install-stage-cid-fail"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        beforeHash = TestUpdateRuntimeLibraries._hashTree(self._libsDir(tmp_path))

        success = await manager.installRuntimeLibraries(
            packages=["pybullet"],
            runtime=RuntimeName.PYTHON,
        )

        assert success is False
        # The failed stage container is kept for docker logs post-mortem.
        removedIds = [call.args[0] for call in backend.removeContainer.await_args_list]
        assert "install-stage-cid-fail" not in removedIds
        # The pool tree is byte-identical: no partial mutation.
        assert TestUpdateRuntimeLibraries._hashTree(self._libsDir(tmp_path)) == beforeHash
        # Staging run dirs are cleaned up even on failure.
        assert list((tmp_path / "sandbox" / "tmp").iterdir()) == []

    async def testAllSpecsInvalidRaisesWithoutContainer(self, tmp_path: Path) -> None:
        """Every spec failing validation raises before any container call.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)

        with pytest.raises(InvalidPackageSpec):
            await manager.installRuntimeLibraries(["--upgrade", "bad&spec"], runtime=RuntimeName.PYTHON)

        backend.runOneshot.assert_not_awaited()

    async def testPartialSpecFailureProceedsWithValidSpecs(self, tmp_path: Path) -> None:
        """Partially invalid specs proceed; only the valid ones reach the container.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _deltaSideEffect({"numpy": "2.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        success = await manager.installRuntimeLibraries(["numpy", "bad&spec"], runtime=RuntimeName.PYTHON)

        assert success is True
        runtimeImpl = manager._runtimes[RuntimeName.PYTHON]
        stageSpec = backend.runOneshot.await_args_list[0].kwargs["spec"]
        assert stageSpec.command == runtimeImpl.stageRun(Path("io"), ["numpy"]).command
        assert "bad&spec" not in stageSpec.command
        assert (self._libsDir(tmp_path) / "numpy-2.0.dist-info").is_dir()

    async def testPoolLockedPropagatesWithoutBackendCall(self, tmp_path: Path) -> None:
        """A pre-held pool flock surfaces as LibraryPoolLocked before any container.

        Install has no pre-filter: the whole flow lives inside the pool
        lock, so a held lock raises before anything runs.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolDir = tmp_path / "sandbox" / "runtimes" / "python"
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)

        poolDir.mkdir(parents=True)
        lockHandle = open(poolDir / "pool.lock", "a")  # noqa: SIM115
        try:
            fcntl.flock(lockHandle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(LibraryPoolLocked):
                await manager.installRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)
        finally:
            lockHandle.close()

        backend.runOneshot.assert_not_awaited()
        assert not self._libsDir(tmp_path).exists()


# ============================================================================
# Tests — updateRuntimeLibraries (mocked backend)
# ============================================================================


class TestUpdateRuntimeLibraries:
    """Tests for SandboxManager.updateRuntimeLibraries with a mocked backend.

    The fake pip containers (see ``_reportSideEffect`` / ``_deltaSideEffect``)
    write their artifacts into the staging directory they were mounted, so
    the real host-side copy → merge → swap → enumerate machinery runs
    end-to-end on disk.
    """

    def _makeManager(self, tmp_path: Path, backend: MagicMock) -> SandboxManager:
        """Build a SandboxManager wired to the given mock backend.

        Args:
            tmp_path: pytest-provided temporary directory.
            backend: Mock backend to inject.

        Returns:
            A SandboxManager instance with the mock backend installed.
        """
        SandboxManager.injectConfig(_makeSandboxConfig(str(tmp_path / "sandbox")))
        manager = SandboxManager.getInstance()
        swapBackend(manager, backend)
        return manager

    def _libsDir(self, tmp_path: Path) -> Path:
        """Return the Python runtime's library pool directory path.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            The pool directory path (not created).
        """
        return tmp_path / "sandbox" / "runtimes" / "python" / "libs"

    async def testReportAndStageContainerSpecs(self, tmp_path: Path) -> None:
        """Pre-filter and stage ContainerSpecs mount the io/ subtree, never the pool.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "2.0"}),
                self._scopeCheckingStage({"numpy": "2.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        result = await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert backend.runOneshot.await_count == 3  # pre-filter, stage, list refresh

        runtimeImpl = manager._runtimes[RuntimeName.PYTHON]
        reportSpec = backend.runOneshot.await_args_list[0].kwargs["spec"]
        stageSpec = backend.runOneshot.await_args_list[1].kwargs["spec"]
        assert reportSpec.command == runtimeImpl.reportRun(Path("io"), ["numpy"]).command
        assert stageSpec.command == runtimeImpl.stageRun(Path("io"), ["numpy"]).command

        for spec in (reportSpec, stageSpec):
            assert spec.labels["sandbox.purpose"] == "update"
            assert spec.labels["sandbox.managed"] == "true"
            assert spec.labels["sandbox.runtime"] == "python"
            # Staging dir rw + helper ro — and the live pool is NEVER mounted.
            assert len(spec.mounts) == 2
            poolMounts = [m for m in spec.mounts if m["containerPath"] == runtimeImpl._config.libMountPath]
            assert poolMounts == []
            stagingMounts = [m for m in spec.mounts if m["containerPath"] == PythonRuntime.STAGING_CONTAINER_PATH]
            assert stagingMounts and stagingMounts[0]["mode"] == "rw"
            helperMounts = [m for m in spec.mounts if m["containerPath"] == PythonRuntime.UPDATE_HELPER_CONTAINER_PATH]
            assert helperMounts and helperMounts[0]["mode"] == "ro"
            # Mount scope: containers see ONLY the io/ subtree — the pool
            # copies live outside every mount.
            assert stagingMounts[0]["hostPath"].endswith(f"/{STAGING_IO_DIRNAME}")
            assert all("newpool" not in m["hostPath"] and "oldpool" not in m["hostPath"] for m in spec.mounts)

        # The staged core really merged + swapped on disk.
        assert (self._libsDir(tmp_path) / "numpy-2.0.dist-info").is_dir()
        assert not (self._libsDir(tmp_path) / "numpy-1.0.dist-info").exists()
        assert result.updated == [PackageUpdate(name="numpy", oldVersion="1.0", newVersion="2.0")]

    @staticmethod
    def _scopeCheckingStage(delta: dict[str, str]) -> Callable[[ContainerSpec], Awaitable[ContainerOutcome]]:
        """Build a stage step asserting the mount scope before staging the delta.

        Args:
            delta: Mapping from package name to version to stage.

        Returns:
            An async callable usable as an AsyncMock side_effect element.
        """

        async def effect(spec: ContainerSpec) -> ContainerOutcome:
            """Assert the io/ mount scope, then behave as the stage container.

            While the stage container runs, ``newpool`` must be a sibling of
            the mounted io/ subtree — never inside it.

            Args:
                spec: The ContainerSpec the manager passed to runOneshot.

            Returns:
                A successful ContainerOutcome for the stage container.

            Raises:
                AssertionError: If newpool is inside the mounted subtree.
            """
            stagingDir = _stagingHostDir(spec)
            assert stagingDir.name == STAGING_IO_DIRNAME
            assert (stagingDir.parent / "newpool").is_dir(), "newpool must live outside every container mount"
            assert not (stagingDir / "newpool").exists(), "newpool must not be inside the mounted io/ subtree"
            return await _deltaSideEffect(delta)(spec)

        return effect

    async def testAllSpecsInvalidRaisesWithoutContainer(self, tmp_path: Path) -> None:
        """Every spec failing validation raises before any container call.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)

        with pytest.raises(InvalidPackageSpec):
            await manager.updateRuntimeLibraries(["--upgrade", "bad&spec"], runtime=RuntimeName.PYTHON)

        backend.runOneshot.assert_not_awaited()

    async def testPartialSpecFailureProceedsWithFailedSpecs(self, tmp_path: Path) -> None:
        """Partially invalid specs proceed in one container; failures are recorded.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)

        result = await manager.updateRuntimeLibraries(["numpy", "bad&spec"], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert len(result.failedSpecs) == 1
        assert result.failedSpecs[0][0] == "bad&spec"
        spec = backend.runOneshot.await_args_list[0].kwargs["spec"]
        assert spec.command[-1] == "numpy"
        assert "bad&spec" not in spec.command

    async def testLibraryPoolLockedPropagates(self, tmp_path: Path) -> None:
        """A pre-held pool flock surfaces as LibraryPoolLocked.

        The read-only pre-filter runs before the lock (plan §4.1); the lock
        error hits when the mutation phase is attempted, so exactly one
        backend call (the pre-filter) happens and no mutation container runs.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        poolDir = tmp_path / "sandbox" / "runtimes" / "python"
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(side_effect=_oneshotSequence(_reportSideEffect({"numpy": "2.0"})))
        manager = self._makeManager(tmp_path, backend)

        lockHandle = open(poolDir / "pool.lock", "a")  # noqa: SIM115
        try:
            fcntl.flock(lockHandle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(LibraryPoolLocked):
                await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)
        finally:
            lockHandle.close()

        # Only the pre-filter ran; no mutation container, no swap.
        assert backend.runOneshot.await_count == 1
        assert (self._libsDir(tmp_path) / "numpy-1.0.dist-info").is_dir()

    @staticmethod
    def _hashTree(root: Path) -> dict[str, str]:
        """Hash every entry under a directory tree.

        Args:
            root: Directory to hash recursively.

        Returns:
            Mapping from relative path to file digest (or a ``<dir>`` marker).
        """
        result: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            relPath = str(path.relative_to(root))
            if path.is_file():
                result[relPath] = hashlib.sha256(path.read_bytes()).hexdigest()
            elif path.is_dir():
                result[relPath] = "<dir>"
            else:
                result[relPath] = "<other>"
        return result

    async def testStageFailureKeepsContainerAndLeavesPoolByteIdentical(self, tmp_path: Path) -> None:
        """A failed stage keeps the container AND leaves the pool byte-identical on disk.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        poolDir = tmp_path / "sandbox" / "runtimes" / "python"
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "2.0"}),
                _makeContainerOutcome(exitCode=1, containerId="stage-cid-fail"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        beforeHash = self._hashTree(self._libsDir(tmp_path))

        result = await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        assert result.success is False
        assert result.containerId == "stage-cid-fail"
        assert result.metadataRefreshed is None
        assert result.updated == []
        assert result.unchanged == []
        # The pre-filter container is removed (read-only probe); the failed
        # stage container is kept for docker logs post-mortem.
        removedIds = [call.args[0] for call in backend.removeContainer.await_args_list]
        assert "prefilter-cid" in removedIds
        assert "stage-cid-fail" not in removedIds
        # The pool tree is byte-identical: no holes, by construction.
        assert self._hashTree(self._libsDir(tmp_path)) == beforeHash
        # Staging run dirs are cleaned up even on failure.
        assert list((tmp_path / "sandbox" / "tmp").iterdir()) == []
        assert (poolDir / "pool.lock").exists()  # lock file survived, outside libs/

    async def testSuccessRemovesStageContainerAndRefreshes(self, tmp_path: Path) -> None:
        """A successful update removes the stage container and refreshes metadata.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "2.0"}),
                _deltaSideEffect({"numpy": "2.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        result = await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.containerId is None
        assert result.metadataRefreshed is True
        removedIds = [call.args[0] for call in backend.removeContainer.await_args_list]
        assert "stage-cid" in removedIds

    async def testDiffComputedFromPoolEnumerations(self, tmp_path: Path) -> None:
        """The old→new diff comes from before/after dist-info enumerations.

        Pool: numpy 1.0, requests 2.0, scipy 1.0. The staged delta upgrades
        numpy to 2.0 and adds pillow 9.0 (fresh, no prior version); requests
        and scipy are untouched and report as unchanged.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0", "requests": "2.0", "scipy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "2.0", "pillow": "9.0"}),
                _deltaSideEffect({"numpy": "2.0", "pillow": "9.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        result = await manager.updateRuntimeLibraries(["numpy", "pillow"], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.metadataRefreshed is True
        assert result.updated == [
            PackageUpdate(name="numpy", oldVersion="1.0", newVersion="2.0"),
            PackageUpdate(name="pillow", oldVersion=None, newVersion="9.0"),
        ]
        assert result.unchanged == [
            PackageUpdate(name="requests", oldVersion="2.0", newVersion="2.0"),
            PackageUpdate(name="scipy", oldVersion="1.0", newVersion="1.0"),
        ]

    def testDiffPoolVersionsClassifiesAllTransitions(self) -> None:
        """_diffPoolVersions pins upgrade/unchanged/fresh/vanished classification.

        Returns:
            None
        """
        updated, unchanged = _diffPoolVersions(
            {"numpy": "1.0", "requests": "2.0", "scipy": "1.0"},
            {"numpy": "2.0", "requests": "2.0", "pillow": "9.0"},
        )
        assert updated == [
            PackageUpdate(name="numpy", oldVersion="1.0", newVersion="2.0"),
            PackageUpdate(name="pillow", oldVersion=None, newVersion="9.0"),
            PackageUpdate(name="scipy", oldVersion="1.0", newVersion=None),
        ]
        assert unchanged == [PackageUpdate(name="requests", oldVersion="2.0", newVersion="2.0")]

    async def testRefreshFailureKeepsSuccessWithStaleMetadataFlag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A refresh crash after a successful swap degrades to metadataRefreshed=False.

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "2.0"}),
                _deltaSideEffect({"numpy": "2.0"}),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        async def failingRefresh(rt: RuntimeName, libsDir: Path) -> bool:
            """Simulate the list-container step crashing.

            Args:
                rt: The runtime being refreshed.
                libsDir: The library pool directory (unused).

            Returns:
                Never returns; raises RuntimeError.
            """
            raise RuntimeError("docker gone mid-refresh")

        monkeypatch.setattr(manager, "_refreshPackageList", failingRefresh)

        result = await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.metadataRefreshed is False

    async def testFailedListRefreshPreservesMetadata(self, tmp_path: Path) -> None:
        """A non-zero list-container exit preserves old metadata, metadataRefreshed=False.

        Before the fix, ``_refreshPackageList`` ignored the list container's
        outcome: the empty/partial stdout was parsed into an empty package
        list, overwrote packages.json, and every previous package looked
        vanished — while ``metadataRefreshed=True`` was reported.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "2.0"}),
                _deltaSideEffect({"numpy": "2.0"}),
                _makeContainerOutcome(exitCode=3, containerId="list-cid-fail"),
            )
        )
        manager = self._makeManager(tmp_path, backend)
        await manager._metadata.savePackagesInfo(
            RuntimeName.PYTHON,
            [PackageInfo(name="numpy", version="1.0")],
        )

        result = await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.metadataRefreshed is False
        # Old metadata must be intact — not overwritten by the failed refresh.
        assert await manager._metadata.loadPackagesInfo(RuntimeName.PYTHON) == [
            PackageInfo(name="numpy", version="1.0")
        ]
        # The failed list container is still cleaned up.
        removedIds = [call.args[0] for call in backend.removeContainer.await_args_list]
        assert "list-cid-fail" in removedIds

    async def testOomKilledListRefreshPreservesMetadata(self, tmp_path: Path) -> None:
        """An OOM-killed list container preserves old metadata too.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "2.0"}),
                _deltaSideEffect({"numpy": "2.0"}),
                _makeContainerOutcome(exitCode=137, oomKilled=True, containerId="list-cid-oom"),
            )
        )
        manager = self._makeManager(tmp_path, backend)
        await manager._metadata.savePackagesInfo(
            RuntimeName.PYTHON,
            [PackageInfo(name="numpy", version="1.0")],
        )

        result = await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.metadataRefreshed is False
        assert await manager._metadata.loadPackagesInfo(RuntimeName.PYTHON) == [
            PackageInfo(name="numpy", version="1.0")
        ]

    async def testInstallSucceedsEvenWhenListRefreshFails(self, tmp_path: Path) -> None:
        """Install stays best-effort: a failed list refresh must not fail the install.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=[
                _makeContainerOutcome(exitCode=0, containerId="install-cid-ok"),
                _makeContainerOutcome(exitCode=3, containerId="list-cid-fail"),
            ]
        )
        manager = self._makeManager(tmp_path, backend)

        success = await manager.installRuntimeLibraries(
            packages=["pybullet"],
            runtime=RuntimeName.PYTHON,
        )

        assert success is True

    async def testPreFilterFailSafeBadReportStagesAllSpecs(self, tmp_path: Path) -> None:
        """An unparseable pip report fails safe: every spec is staged (plan §4.2).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0", "requests": "2.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect("this is not json"),
                _deltaSideEffect({}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        result = await manager.updateRuntimeLibraries(["numpy", "requests"], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.upToDate == []
        runtimeImpl = manager._runtimes[RuntimeName.PYTHON]
        stageSpec = backend.runOneshot.await_args_list[1].kwargs["spec"]
        assert stageSpec.command == runtimeImpl.stageRun(Path("io"), ["numpy", "requests"]).command

    async def testMissingReportFileFailsSafeToo(self, tmp_path: Path) -> None:
        """A pre-filter that wrote no report at all also stages every spec.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect(None),
                _deltaSideEffect({}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        result = await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.upToDate == []
        assert backend.runOneshot.await_count == 3  # stage container ran

    async def testEmptyOutdatedEarlyReturnsWithSingleRecoveryLock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An all-current pre-filter result returns success with no stage container.

        The opportunistic crash-recovery pass (finding: an early request must
        not create an empty libs that suppresses adoption) takes the pool
        lock once at method start, non-blocking; the staging phase never
        runs — no stage container, no second lock acquisition.

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(side_effect=_oneshotSequence(_reportSideEffect({"numpy": "1.0"})))
        manager = self._makeManager(tmp_path, backend)

        lockCalls: list[str] = []
        realPoolLock = sandboxLocks.poolLock

        @asynccontextmanager
        async def recordingPoolLock(rt: RuntimeName, lockPoolDir: Path):
            """Record pool-lock acquisitions around the real lock.

            Args:
                rt: The runtime whose pool to lock.
                lockPoolDir: The pool directory to lock.

            Yields:
                None
            """
            lockCalls.append(str(lockPoolDir))
            async with realPoolLock(rt, lockPoolDir):
                yield

        monkeypatch.setattr(sandboxLocks, "poolLock", recordingPoolLock)

        result = await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.upToDate == ["numpy"]
        assert result.updated == []
        assert result.unchanged == []
        assert result.containerId is None
        assert result.metadataRefreshed is None
        # Exactly one backend call (the pre-filter): zero stage containers,
        # and exactly one lock acquisition — the opportunistic recovery pass
        # at method start, never the mutation phase.
        assert backend.runOneshot.await_count == 1
        assert len(lockCalls) == 1

    async def testUpdateAllNameSetUnionsEnumerationAndMetadata(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Update-all specs = pool enumeration ∪ packages.json; invalid names skipped.

        The pool holds numpy + requests (valid names) plus a planted
        dist-info whose METADATA Name is ``-r`` (grammar-invalid → skipped
        with a warning); packages.json adds the phantom ``pillow`` which has
        no pool version and is reinstalled (self-heal, plan §6).

        Args:
            tmp_path: pytest-provided temporary directory.
            caplog: pytest log capture fixture.

        Returns:
            None
        """
        libsDir = self._libsDir(tmp_path)
        _makePool(libsDir, {"numpy": "1.0", "requests": "1.0"})
        _makeDistInfo(libsDir, "evil-1.0.dist-info", name="-r", version="1.0", payloadFiles=[])
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))

        capturedSpecs: list[list[str]] = []
        reportEffect = _reportSideEffect(None)  # missing report → fail-safe full stage
        deltaEffect = _deltaSideEffect({"numpy": "2.0", "requests": "2.0", "pillow": "9.0"})

        async def recordingReport(spec: ContainerSpec) -> ContainerOutcome:
            """Record the pre-filter specs, then behave as the report container.

            Args:
                spec: The ContainerSpec passed to runOneshot.

            Returns:
                The report container outcome.
            """
            capturedSpecs.append(spec.command[spec.command.index("--") + 1 :])
            return await reportEffect(spec)

        async def recordingStage(spec: ContainerSpec) -> ContainerOutcome:
            """Record the stage specs, then behave as the stage container.

            Args:
                spec: The ContainerSpec passed to runOneshot.

            Returns:
                The stage container outcome.
            """
            capturedSpecs.append(spec.command[spec.command.index("--") + 1 :])
            return await deltaEffect(spec)

        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                recordingReport,
                recordingStage,
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)
        await manager._metadata.savePackagesInfo(
            RuntimeName.PYTHON,
            [
                PackageInfo(name="numpy", version="1.0"),
                PackageInfo(name="pillow", version="0.5"),
            ],
        )

        with caplog.at_level(logging.WARNING, logger="lib.sandbox.manager"):
            result = await manager.updateRuntimeLibraries(None, runtime=RuntimeName.PYTHON)

        assert result.success is True
        # Sorted union of enumeration {numpy, requests} and packages.json
        # {numpy, pillow}; the grammar-invalid "-r" never reaches an argv.
        assert capturedSpecs[0] == ["numpy", "pillow", "requests"]
        assert capturedSpecs[1] == capturedSpecs[0]
        assert "-r" in caplog.text
        # Self-heal: the phantom was reinstalled into the pool.
        assert (libsDir / "pillow-9.0.dist-info").is_dir()

    async def testEmptyPoolNoArgEarlyReturnsWithoutBackendCall(self, tmp_path: Path) -> None:
        """Update-all on an empty pool returns "Nothing installed" without a container.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)

        result = await manager.updateRuntimeLibraries(None, runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.updated == []
        assert result.unchanged == []
        assert result.upToDate == []
        assert result.containerId is None
        assert result.metadataRefreshed is None
        backend.runOneshot.assert_not_awaited()

    async def testEmptyPoolUpdateAllSucceedsWithMissingHelper(self, tmp_path: Path) -> None:
        """Update-all on an empty pool succeeds with no containers even if the helper is missing.

        Regression pin for the pre-check consolidation: the empty-pool
        short-circuit precedes the pre-filter container, so the helper
        pre-check inside ``_runPrefilterContainer`` never fires for this
        path. Restoring the old outer pre-check in ``updateRuntimeLibraries``
        would raise ``ConfigError`` here instead.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)
        manager._runtimes[RuntimeName.PYTHON].updateHelperHostPath = (  # type: ignore[method-assign]
            lambda: tmp_path / "missing-dir" / "pool_pip_runner.py"
        )

        result = await manager.updateRuntimeLibraries(None, runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.updated == []
        assert result.unchanged == []
        assert result.upToDate == []
        assert result.containerId is None
        assert result.metadataRefreshed is None
        backend.runOneshot.assert_not_awaited()

    async def testEmptyNamedListUpdatesNothing(self, tmp_path: Path) -> None:
        """A named-but-empty request updates nothing; only None means "all".

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)

        result = await manager.updateRuntimeLibraries([], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.updated == []
        assert result.upToDate == []
        backend.runOneshot.assert_not_awaited()

    async def testMissingHelperRaisesConfigError(self, tmp_path: Path) -> None:
        """A helper script missing on the host raises ConfigError before any container.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)
        manager._runtimes[RuntimeName.PYTHON].updateHelperHostPath = (  # type: ignore[method-assign]
            lambda: tmp_path / "missing-dir" / "pool_pip_runner.py"
        )

        with pytest.raises(ConfigError):
            await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        backend.runOneshot.assert_not_awaited()

    async def testCrossFsStagingRaisesConfigError(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A staging dir on a different filesystem than the pool raises ConfigError.

        Simulated by mocking ``os.stat`` (as seen from pool_staging) to
        report a foreign ``st_dev`` for the merged copy; the real stat result
        is used otherwise. The pool stays untouched and the run dir is
        cleaned.

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "2.0"}),
                _deltaSideEffect({"numpy": "2.0"}),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        realStat = os.stat

        def fakeStat(path: str, **kwargs: bool) -> os.stat_result:
            """Report a foreign st_dev for the staging pool copy.

            Args:
                path: The path being stated (str or Path at runtime; both
                    stringify for the newpool check and stat identically).
                **kwargs: Keyword arguments from the caller (e.g.
                    ``follow_symlinks`` from ``shutil.copystat``; forwarded).

            Returns:
                The real stat result, with st_dev swapped for the newpool dir.
            """
            result = realStat(path, **kwargs)
            if str(path).endswith("newpool"):
                fields = list(result)
                fields[2] = 999999  # st_dev index — simulate another mount
                return os.stat_result(tuple(fields))
            return result

        monkeypatch.setattr("lib.sandbox.runtimes.python.pool_staging.os.stat", fakeStat)

        with pytest.raises(ConfigError):
            await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        # Pool untouched; staging run dir cleaned up.
        assert (self._libsDir(tmp_path) / "numpy-1.0.dist-info").is_dir()
        assert list((tmp_path / "sandbox" / "tmp").iterdir()) == []

    async def testRollbackFailurePreservesRunDirForRecovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A swap whose rollback ALSO fails preserves the run dir for recover().

        Renames #2 (newpool → libs) and #3 (oldpool → libs, the rollback)
        both fail: ``libs`` is absent and the only complete pool copies
        survive inside the run dir. The unconditional cleanup of the old
        implementation deleted them, leaving recovery nothing to adopt.

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "2.0"}),
                _deltaSideEffect({"numpy": "2.0"}),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        realRename = Path.rename

        def failingSwapAndRollback(path: Path, target: Path) -> Path:
            """Fail exactly the swap's second rename and its rollback.

            Args:
                path: The path being renamed.
                target: The rename destination.

            Returns:
                The real rename result for unrelated renames (e.g. the
                initial pool → parking rename).

            Raises:
                OSError: For newpool→libs (swap) and oldpool→libs (rollback).
            """
            if path.name in {"newpool", "oldpool"} and target.name == "libs":
                raise OSError(28, "No space left on device")
            return realRename(path, target)

        monkeypatch.setattr(Path, "rename", failingSwapAndRollback)

        with pytest.raises(PoolSwapRollbackFailed):
            await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        monkeypatch.undo()

        # The run dir survived and still holds BOTH complete copies.
        tmpEntries = list((tmp_path / "sandbox" / "tmp").iterdir())
        assert len(tmpEntries) == 1
        runDir = tmpEntries[0]
        assert (runDir / "newpool" / "numpy-2.0.dist-info").is_dir()
        assert (runDir / "oldpool" / "numpy-1.0.dist-info").is_dir()
        # The live pool is absent — the hole recover() must fill.
        assert not self._libsDir(tmp_path).exists()

        # Recovery adopts the preserved newpool copy, closing the hole.
        backend.runOneshot = AsyncMock(return_value=_makeContainerOutcome(exitCode=0, containerId="list-cid"))
        assert await manager.recover() is True
        assert (self._libsDir(tmp_path) / "numpy-2.0.dist-info").is_dir()
        assert not (self._libsDir(tmp_path) / "numpy-1.0.dist-info").exists()
        assert not runDir.exists(), "the adopted run dir is deleted after recovery"

    async def testTimeoutOverrideDrivesBothContainers(self, tmp_path: Path) -> None:
        """An explicit timeoutSeconds overrides the install-container config on both runs.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "2.0"}),
                _deltaSideEffect({"numpy": "2.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        result = await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON, timeoutSeconds=333)

        assert result.success is True
        reportSpec = backend.runOneshot.await_args_list[0].kwargs["spec"]
        stageSpec = backend.runOneshot.await_args_list[1].kwargs["spec"]
        assert reportSpec.limits.timeoutSeconds == 333
        assert stageSpec.limits.timeoutSeconds == 333

    async def testUpdateContainersCarryStagingRunIdLabel(self, tmp_path: Path) -> None:
        """Both update containers are labeled with their staging run id.

        The label is container GC's liveness marker: while the labeled run
        dir exists under tmp/, the container is in-flight, not an orphan.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "2.0"}),
                _deltaSideEffect({"numpy": "2.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        await manager.updateRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        reportSpec = backend.runOneshot.await_args_list[0].kwargs["spec"]
        stageSpec = backend.runOneshot.await_args_list[1].kwargs["spec"]
        reportRunId = reportSpec.labels["sandbox.stagingRunId"]
        stageRunId = stageSpec.labels["sandbox.stagingRunId"]
        assert reportRunId and stageRunId
        # Each container is labeled with ITS OWN staging run dir name.
        assert reportRunId != stageRunId

    async def testDuplicateDistInfoNameForcedOutdatedAndHealed(self, tmp_path: Path) -> None:
        """A name with MULTIPLE dist-infos is staged even when the report matches one.

        The pre-filter's baseline picks the first enumerated dist-info
        version; if that one matches the pip report the package used to be
        classified up-to-date and the duplicates were never healed. BOTH
        duplicate dist-infos here parse to the SAME version ("1.0") and the
        pip report pins that exact version, so the ordinary version-mismatch
        path can never fire and ONLY the duplicate-name guard can force the
        package into the outdated set — deterministically, regardless of
        iterdir order (production re-enumerates the pool in a second
        independent walk, so with differing duplicate versions the
        unordered scans could disagree and let this test pass via the
        mismatch path even with the guard broken). The forced outdated
        classification sends the name through the staged merge, which
        removes every old dist-info (plan §9).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        libsDir = self._libsDir(tmp_path)
        _makeDistInfo(libsDir, "foo-1.0.dist-info", name="foo", version="1.0", payloadFiles=["foo/__init__.py"])
        _makeDistInfo(libsDir, "foo-legacy-1.0.dist-info", name="foo", version="1.0", payloadFiles=["foo/legacy.py"])

        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)

        # Identical parsed versions make the version comparison classify
        # the spec up-to-date no matter which duplicate the first-entry
        # selection picks — only the duplicate guard can force it into the
        # staged heal path. The helper call here pins the duplicate set
        # only; the report version is hard-coded, never derived from this
        # test's own walk.
        _, duplicateNames = manager._enumeratePoolWithDuplicates(libsDir)
        assert duplicateNames == {"foo"}, "the helper must flag the duplicated name"
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"foo": "1.0"}),
                _deltaSideEffect({"foo": "3.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )

        result = await manager.updateRuntimeLibraries(["foo"], runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.upToDate == [], "the duplicated name must not be classified up-to-date"
        assert (libsDir / "foo-3.0.dist-info").is_dir()
        assert not (libsDir / "foo-1.0.dist-info").exists()
        assert not (libsDir / "foo-legacy-1.0.dist-info").exists(), "the merge must heal duplicate dist-infos"

    def testEnumeratePoolWithDuplicatesVersionsAndDuplicateNames(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_enumeratePoolWithDuplicates walks ONCE and pins FIRST-entry selection.

        Uses a controlled ``enumerateDistInfos`` spy — patched at the
        manager module's imported reference (manager.py binds it with a
        ``from`` import) — returning a deterministic inventory, so the
        merged Step-3 helper's invariants (plan §6) are pinned exactly:
        the enumeration runs EXACTLY ONCE per call, the version map keeps
        the FIRST dist-info entry per name, and names carrying multiple
        entries land in the duplicate set. None of that is pinnable against
        a real-filesystem scan, where iterdir order is not deterministic
        (APFS).

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        libsDir = self._libsDir(tmp_path)
        libsDir.mkdir(parents=True)
        spyPoolRoots: list[Path] = []

        def spyEnumerateDistInfos(poolRoot: Path) -> dict[str, list[DistInfoEntry]]:
            """Deterministic stand-in for the real dist-info enumeration.

            Args:
                poolRoot: Pool directory handed to the helper.

            Returns:
                A fixed two-entry "foo" inventory (versions 1.0 and 2.0)
                plus a single-entry "bar" (version 0.9).
            """
            spyPoolRoots.append(poolRoot)
            return {
                "foo": [
                    DistInfoEntry(path=poolRoot / "foo-1.0.dist-info", version="1.0"),
                    DistInfoEntry(path=poolRoot / "foo-2.0.dist-info", version="2.0"),
                ],
                "bar": [DistInfoEntry(path=poolRoot / "bar-0.9.dist-info", version="0.9")],
            }

        monkeypatch.setattr("lib.sandbox.manager.enumerateDistInfos", spyEnumerateDistInfos)

        manager = self._makeManager(tmp_path, _makeMockBackend(_makeContainerOutcome(exitCode=0)))
        versions, duplicateNames = manager._enumeratePoolWithDuplicates(libsDir)

        assert spyPoolRoots == [libsDir], "the helper must perform EXACTLY ONE enumeration walk"
        assert versions == {"foo": "1.0", "bar": "0.9"}, "the FIRST enumerated entry per name must win"
        assert duplicateNames == {"foo"}

    def testEnumeratePoolWithDuplicatesPropagatesOSError(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """_enumeratePoolWithDuplicates PROPAGATES OSError (fail-loud contract).

        An unreadable pool must abort the update rather than silently pass
        the duplicates check: the merged single-walk helper propagates
        ``enumerateDistInfos``'s ``OSError`` — only the missing-directory
        case is tolerated (as empty results). The deleted second walk
        (``_collectDuplicatePoolNames``) was the only ``OSError`` swallower
        on the Step-3 path, so this pins that the swallow did not survive
        the merge (plan §6, OSError posture resolved as PROPAGATE).

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        libsDir = self._libsDir(tmp_path)
        libsDir.mkdir(parents=True)

        def raiseOSError(poolRoot: Path) -> dict[str, list[DistInfoEntry]]:
            """Simulate a pool that became unreadable mid-walk.

            Args:
                poolRoot: Pool directory handed to the helper.

            Returns:
                Never returns; always raises OSError.

            Raises:
                OSError: Always — models an unreadable pool directory.
            """
            raise OSError(f"unreadable pool: {poolRoot}")

        monkeypatch.setattr("lib.sandbox.manager.enumerateDistInfos", raiseOSError)

        manager = self._makeManager(tmp_path, _makeMockBackend(_makeContainerOutcome(exitCode=0)))

        with pytest.raises(OSError):
            manager._enumeratePoolWithDuplicates(libsDir)

    def testEnumeratePoolWithDuplicatesMissingPoolYieldsEmpty(self, tmp_path: Path) -> None:
        """_enumeratePoolWithDuplicates tolerates a MISSING pool directory.

        The pre-check flow relies on a missing libs dir yielding empty
        results instead of raising.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        manager = self._makeManager(tmp_path, _makeMockBackend(_makeContainerOutcome(exitCode=0)))

        versions, duplicateNames = manager._enumeratePoolWithDuplicates(self._libsDir(tmp_path))

        assert versions == {}
        assert duplicateNames == set()

    async def testUpdateAllAdoptsCrashLeftoverBeforeCollectingNames(self, tmp_path: Path) -> None:
        """update-all must adopt crash leftovers before enumerating the pool.

        Without the opportunistic recovery pass, an absent libs dir makes
        update-all short-circuit to "Nothing installed" (success) while the
        complete newpool copy sits unrecovered in staging — and a later
        prepareRuntime would create an empty libs that suppresses adoption
        for good.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        runDir = rootDir / "tmp" / "run-1"
        _makePool(runDir / "newpool", {"numpy": "2.0"})
        _makePool(runDir / "oldpool", {"numpy": "1.0"})
        # The live pool is absent — crash between the swap renames (both
        # copies survive; the sibling oldpool proves the swap began).

        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "3.0"}),
                _deltaSideEffect({"numpy": "3.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        SandboxManager.injectConfig(_makeSandboxConfig(str(rootDir)))
        manager = SandboxManager.getInstance()
        swapBackend(manager, backend)

        result = await manager.updateRuntimeLibraries(None, runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.updated == [PackageUpdate(name="numpy", oldVersion="2.0", newVersion="3.0")]
        libsDir = self._libsDir(tmp_path)
        assert (libsDir / "numpy-3.0.dist-info").is_dir()
        assert not runDir.exists(), "the adopted run dir is deleted after recovery"

    async def testBusyLockAndLeftoversPropagateInsteadOfFalseSuccess(self, tmp_path: Path) -> None:
        """An empty update-all find with a deferred recovery never fakes success.

        With the pool lock held (the opportunistic recovery pass defers) and
        crash leftovers under tmp/, the pre-fix code returned the
        "Nothing installed" success while the complete swap copy sat
        stranded in staging. The guard re-attempts recovery before trusting
        the empty find: the still-busy lock propagates LibraryPoolLocked,
        and once the lock is released the next call adopts the leftover and
        completes the update.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        poolDir = rootDir / "runtimes" / "python"
        runDir = rootDir / "tmp" / "run-1"
        _makePool(runDir / "newpool", {"numpy": "2.0"})
        _makePool(runDir / "oldpool", {"numpy": "1.0"})
        # The live pool is absent — crash between the swap renames (both
        # copies survive; the sibling oldpool proves the swap began).

        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        backend.runOneshot = AsyncMock(
            side_effect=_oneshotSequence(
                _reportSideEffect({"numpy": "3.0"}),
                _deltaSideEffect({"numpy": "3.0"}),
                _makeContainerOutcome(exitCode=0, containerId="list-cid"),
            )
        )
        manager = self._makeManager(tmp_path, backend)

        poolDir.mkdir(parents=True)
        lockHandle = open(poolDir / "pool.lock", "a")  # noqa: SIM115
        try:
            fcntl.flock(lockHandle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(LibraryPoolLocked):
                await manager.updateRuntimeLibraries(None, runtime=RuntimeName.PYTHON)
        finally:
            lockHandle.close()

        # Fail closed while the lock was held: nothing ran, leftovers intact.
        backend.runOneshot.assert_not_awaited()
        assert (runDir / "newpool" / "numpy-2.0.dist-info").is_dir()

        # After release, recovery adopts the leftover and the update runs.
        result = await manager.updateRuntimeLibraries(None, runtime=RuntimeName.PYTHON)

        assert result.success is True
        assert result.updated == [PackageUpdate(name="numpy", oldVersion="2.0", newVersion="3.0")]
        assert (self._libsDir(tmp_path) / "numpy-3.0.dist-info").is_dir()
        assert not runDir.exists(), "the adopted run dir is deleted after recovery"

    async def testFailedRecoveryRenamePropagatesInsteadOfFalseSuccess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failing empty-find recovery propagates instead of faking success.

        Every adoption/restoration rename fails transiently: the empty-pool
        update-all find must not be reported as a successful "Nothing
        installed" — the recovery error propagates and the crash leftovers
        stay intact for a retry.

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        runDir = rootDir / "tmp" / "run-1"
        _makePool(runDir / "newpool", {"numpy": "2.0"})
        _makePool(runDir / "oldpool", {"numpy": "1.0"})
        # The live pool is absent — crash between the swap renames.

        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)

        realRename = Path.rename

        def failingAdoption(path: Path, target: Path) -> Path:
            """Fail exactly the pool-adoption renames (newpool/oldpool → libs).

            Args:
                path: The path being renamed.
                target: The rename destination.

            Returns:
                The real rename result for unrelated renames.

            Raises:
                OSError: For the newpool→libs and oldpool→libs renames.
            """
            if path.name in {"newpool", "oldpool"} and target.name == "libs":
                raise OSError(16, "Device or resource busy")
            return realRename(path, target)

        monkeypatch.setattr(Path, "rename", failingAdoption)

        with pytest.raises(OSError):
            await manager.updateRuntimeLibraries(None, runtime=RuntimeName.PYTHON)

        monkeypatch.undo()

        # Fail closed: leftovers intact, live pool still absent, no containers.
        assert (runDir / "newpool" / "numpy-2.0.dist-info").is_dir()
        assert (runDir / "oldpool" / "numpy-1.0.dist-info").is_dir()
        assert not self._libsDir(tmp_path).exists()
        backend.runOneshot.assert_not_awaited()


# ============================================================================
# Tests — recover() crash-window adoption (docs/plans/sandbox-update-v1.md §4.5)
# ============================================================================


class TestRecoverCrashWindowAdoption:
    """Tests for the recover() staging adoption/restoration step (plan §4.5)."""

    def _makeManager(self, tmp_path: Path, backend: MagicMock) -> SandboxManager:
        """Build a SandboxManager wired to the given mock backend.

        Args:
            tmp_path: pytest-provided temporary directory.
            backend: Mock backend to inject.

        Returns:
            A SandboxManager instance with the mock backend installed.
        """
        SandboxManager.injectConfig(_makeSandboxConfig(str(tmp_path / "sandbox")))
        manager = SandboxManager.getInstance()
        swapBackend(manager, backend)
        return manager

    def _libsDir(self, tmp_path: Path) -> Path:
        """Return the Python runtime's library pool directory path.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            The pool directory path (not created).
        """
        return tmp_path / "sandbox" / "runtimes" / "python" / "libs"

    async def testAdoptsNewpoolWhenLibsMissing(self, tmp_path: Path) -> None:
        """Case 1: libs missing + surviving newpool → adopted; run dir deleted.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        runDir = rootDir / "tmp" / "run-1"
        _makePool(runDir / "newpool", {"numpy": "2.0"})
        _makePool(runDir / "oldpool", {"numpy": "1.0"})

        manager = self._makeManager(tmp_path, _makeMockBackend(_makeContainerOutcome(exitCode=0)))

        assert await manager.recover() is True

        libsDir = self._libsDir(tmp_path)
        assert (libsDir / "numpy-2.0.dist-info").is_dir(), "the complete newpool must be adopted"
        assert not (libsDir / "numpy-1.0.dist-info").exists()
        assert not runDir.exists(), "the run dir (incl. sibling oldpool) must be deleted"

    async def testAdoptsNewestNewpool(self, tmp_path: Path) -> None:
        """Case 1 (multi): the newest surviving newpool wins.

        Both run dirs carry newpool+oldpool (swap began in each); the
        newest merged copy is adopted.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        oldRun = rootDir / "tmp" / "run-a"
        newRun = rootDir / "tmp" / "run-b"
        _makePool(oldRun / "newpool", {"numpy": "2.0"})
        _makePool(oldRun / "oldpool", {"numpy": "1.0"})
        _makePool(newRun / "newpool", {"numpy": "3.0"})
        _makePool(newRun / "oldpool", {"numpy": "2.0"})
        _ageDirByMtime(oldRun / "newpool", minutes=30)
        _ageDirByMtime(newRun / "newpool", minutes=1)

        manager = self._makeManager(tmp_path, _makeMockBackend(_makeContainerOutcome(exitCode=0)))

        assert await manager.recover() is True

        assert (self._libsDir(tmp_path) / "numpy-3.0.dist-info").is_dir()

    async def testRestoresOldpoolWhenNoNewpool(self, tmp_path: Path) -> None:
        """Case 2: libs missing + only oldpool → pre-update pool restored.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        runDir = rootDir / "tmp" / "run-2"
        _makePool(runDir / "oldpool", {"numpy": "1.0"})

        manager = self._makeManager(tmp_path, _makeMockBackend(_makeContainerOutcome(exitCode=0)))

        assert await manager.recover() is True

        libsDir = self._libsDir(tmp_path)
        assert (libsDir / "numpy-1.0.dist-info").is_dir(), "the pre-update pool must be restored"
        assert not runDir.exists()

    async def testNoAdoptionWhenLibsPresent(self, tmp_path: Path) -> None:
        """Case 3: libs present → no adoption; stale newpool left for GC.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        _makePool(self._libsDir(tmp_path), {"numpy": "1.0"})
        _makePool(rootDir / "tmp" / "run-3" / "newpool", {"numpy": "9.9"})

        manager = self._makeManager(tmp_path, _makeMockBackend(_makeContainerOutcome(exitCode=0)))

        assert await manager.recover() is True

        libsDir = self._libsDir(tmp_path)
        assert (libsDir / "numpy-1.0.dist-info").is_dir(), "the live pool must stay untouched"
        assert not (libsDir / "numpy-9.9.dist-info").exists()
        assert (rootDir / "tmp" / "run-3" / "newpool").exists(), "staging leftovers are GC's job"

    async def testNoopWithoutCrashLeftovers(self, tmp_path: Path) -> None:
        """Case 3 (empty): libs missing + empty tmp → fresh pool, nothing adopted.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        manager = self._makeManager(tmp_path, _makeMockBackend(_makeContainerOutcome(exitCode=0)))

        assert await manager.recover() is True

        # prepareRuntime's refresh step recreates an empty pool dir; nothing
        # was adopted into it.
        libsDir = self._libsDir(tmp_path)
        assert not any(libsDir.glob("*.dist-info"))

    async def testAdoptsNewpoolDespitePreCreatedEmptyLibs(self, tmp_path: Path) -> None:
        """An EMPTY libs dir (pre-created before the recovery tick) must not suppress adoption.

        prepareRuntime/install/an early run can create an empty libs before
        the first recovery tick; treating any existing libs as a live pool
        would leave the complete newpool/oldpool copies unrecoverable.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        runDir = rootDir / "tmp" / "run-1"
        _makePool(runDir / "newpool", {"numpy": "2.0"})
        _makePool(runDir / "oldpool", {"numpy": "1.0"})
        self._libsDir(tmp_path).mkdir(parents=True)  # empty destination

        manager = self._makeManager(tmp_path, _makeMockBackend(_makeContainerOutcome(exitCode=0)))

        assert await manager.recover() is True

        libsDir = self._libsDir(tmp_path)
        assert (libsDir / "numpy-2.0.dist-info").is_dir(), "the complete newpool must be adopted"
        assert not (libsDir / "numpy-1.0.dist-info").exists()
        assert not runDir.exists(), "the adopted run dir is deleted after recovery"

    async def testNewpoolOnlyLeftoverIsGarbageEmptyLibsStays(self, tmp_path: Path) -> None:
        """Regression: a newpool WITHOUT oldpool is uncommitted staging garbage.

        A hard crash during copy/merge (before the swap's first rename)
        leaves a partial newpool and NO oldpool. Adoption is reserved for
        both-present run dirs (swap began ⇒ merge was complete): the garbage
        newpool stays for staging GC and the pre-created EMPTY libs dir is
        NOT removed or adopted away.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        runDir = rootDir / "tmp" / "run-1"
        _makePool(runDir / "newpool", {"numpy": "2.0"})  # partial copy, no oldpool sibling
        libsDir = self._libsDir(tmp_path)
        libsDir.mkdir(parents=True)  # empty live pool dir

        manager = self._makeManager(tmp_path, _makeMockBackend(_makeContainerOutcome(exitCode=0)))

        assert await manager.recover() is True

        assert libsDir.is_dir(), "the pre-created libs dir must stay in place"
        assert not any(libsDir.iterdir()), "the empty live pool must stay untouched"
        assert not (libsDir / "numpy-2.0.dist-info").exists(), "the partial newpool must NOT be adopted"
        assert (runDir / "newpool" / "numpy-2.0.dist-info").is_dir(), "garbage newpool is left for staging GC"

    async def testInstallRecoversLeftoversWithEmptyLibsPreCreated(self, tmp_path: Path) -> None:
        """installRuntimeLibraries adopts crash leftovers before creating/using libs.

        Regression for the pre-op recovery wiring: with a pre-created empty
        libs dir and a complete newpool leftover, the install (which runs
        under the pool lock) must adopt the leftover pool instead of
        blessing the empty pool.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        runDir = rootDir / "tmp" / "run-1"
        _makePool(runDir / "newpool", {"numpy": "2.0"})
        _makePool(runDir / "oldpool", {"numpy": "1.0"})
        self._libsDir(tmp_path).mkdir(parents=True)  # empty destination

        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        SandboxManager.injectConfig(_makeSandboxConfig(str(rootDir)))
        manager = SandboxManager.getInstance()
        swapBackend(manager, backend)

        success = await manager.installRuntimeLibraries(["numpy"], runtime=RuntimeName.PYTHON)

        assert success is True
        libsDir = self._libsDir(tmp_path)
        assert (libsDir / "numpy-2.0.dist-info").is_dir(), "the leftover pool must be adopted before install"
        assert not runDir.exists(), "the adopted run dir is deleted after recovery"

    async def testRecoveryFailureSkipsPrepareRefreshAndStagingGc(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transient adoption failure fails closed: no prepare/refresh/staging-GC.

        Every adoption/restoration rename raises transiently. Recovery must
        leave the leftovers (aged beyond staging retention) intact and run no
        containers at all — prepareRuntime would create an empty libs over
        the hole and the staging-GC reaper would destroy the only recoverable
        copies. A retry after the transient failure succeeds.

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        runDir = rootDir / "tmp" / "run-1"
        _makePool(runDir / "newpool", {"numpy": "2.0"})
        _makePool(runDir / "oldpool", {"numpy": "1.0"})
        # The RUN DIR is the staging-GC entry: age it beyond retention so
        # reaping it this tick is exactly what fail-closed must prevent.
        _ageDirByMtime(runDir, minutes=120)

        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)

        realRename = Path.rename

        def failingAdoption(path: Path, target: Path) -> Path:
            """Fail exactly the pool-adoption renames (newpool/oldpool → libs).

            Args:
                path: The path being renamed.
                target: The rename destination.

            Returns:
                The real rename result for unrelated renames.

            Raises:
                OSError: For the newpool→libs and oldpool→libs renames.
            """
            if path.name in {"newpool", "oldpool"} and target.name == "libs":
                raise OSError(16, "Device or resource busy")
            return realRename(path, target)

        monkeypatch.setattr(Path, "rename", failingAdoption)

        # recover() reports completion; the per-runtime failure is logged,
        # not raised — but the runtime must be excluded from prepare/refresh
        # and staging GC this tick (fail closed).
        assert await manager.recover() is True

        assert not backend.ensureImage.await_count, "prepareRuntime must be skipped for the failed runtime"
        assert not backend.runOneshot.await_count, "refresh must be skipped for the failed runtime"
        assert not self._libsDir(tmp_path).exists()
        assert (runDir / "newpool" / "numpy-2.0.dist-info").is_dir(), "leftovers must survive staging GC"
        assert (runDir / "oldpool" / "numpy-1.0.dist-info").is_dir()

        monkeypatch.undo()

        # Retry after the transient failure adopts the leftover pool.
        assert await manager.recover() is True
        assert (self._libsDir(tmp_path) / "numpy-2.0.dist-info").is_dir()
        assert not runDir.exists()

    async def testNewpoolAdoptionFailureFallsBackToOldpool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When newpool adoption fails, oldpool restoration is attempted as fallback.

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        runDir = rootDir / "tmp" / "run-1"
        _makePool(runDir / "newpool", {"numpy": "2.0"})
        _makePool(runDir / "oldpool", {"numpy": "1.0"})

        manager = self._makeManager(tmp_path, _makeMockBackend(_makeContainerOutcome(exitCode=0)))

        realRename = Path.rename

        def failingNewpoolAdoption(path: Path, target: Path) -> Path:
            """Fail exactly the newpool→libs adoption rename.

            Args:
                path: The path being renamed.
                target: The rename destination.

            Returns:
                The real rename result for the oldpool fallback rename.

            Raises:
                OSError: For the newpool→libs adoption rename.
            """
            if path.name == "newpool" and target.name == "libs":
                raise OSError(16, "Device or resource busy")
            return realRename(path, target)

        monkeypatch.setattr(Path, "rename", failingNewpoolAdoption)

        assert await manager.recover() is True

        libsDir = self._libsDir(tmp_path)
        assert (libsDir / "numpy-1.0.dist-info").is_dir(), "oldpool restoration must be attempted as fallback"
        assert not (libsDir / "numpy-2.0.dist-info").exists()
        assert not runDir.exists()

    async def testRecoveryDefersWhenPoolLockHeld(self, tmp_path: Path) -> None:
        """A pre-held pool flock defers recovery without destroying leftovers.

        Recovery must not block on lock contention (and must not race the
        holder): the leftovers — aged beyond staging retention — stay intact
        and the next recovery tick after release adopts them.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        poolDir = rootDir / "runtimes" / "python"
        runDir = rootDir / "tmp" / "run-1"
        _makePool(runDir / "newpool", {"numpy": "2.0"})
        _makePool(runDir / "oldpool", {"numpy": "1.0"})
        # The RUN DIR is the staging-GC entry: age it beyond retention so a
        # GC tick that is not deferred would reap it.
        _ageDirByMtime(runDir, minutes=120)

        backend = _makeMockBackend(_makeContainerOutcome(exitCode=0))
        manager = self._makeManager(tmp_path, backend)

        poolDir.mkdir(parents=True)
        lockHandle = open(poolDir / "pool.lock", "a")  # noqa: SIM115
        try:
            fcntl.flock(lockHandle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert await manager.recover() is True
        finally:
            lockHandle.close()

        # Deferred: leftovers intact (despite their age), pool untouched,
        # no prepare/refresh containers ran.
        assert (runDir / "newpool" / "numpy-2.0.dist-info").is_dir(), "leftovers must survive staging GC"
        assert not self._libsDir(tmp_path).exists()
        backend.ensureImage.assert_not_awaited()
        backend.runOneshot.assert_not_awaited()

        # After release, the next recovery tick adopts the leftover.
        assert await manager.recover() is True
        assert (self._libsDir(tmp_path) / "numpy-2.0.dist-info").is_dir()
        assert not runDir.exists()
