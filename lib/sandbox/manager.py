"""Singleton manager for sandboxed code execution.

Composes one Backend with N Runtimes and one MetadataStore.
Owns the per-session lock registry and the GC loop.

Access via ``SandboxManager.getInstance()`` after calling ``injectConfig()``.
"""

import asyncio
import logging
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Sequence, Tuple

from packaging.utils import canonicalize_name

import lib.utils as libUtils

from . import locks
from .backends.base import SandboxBackend
from .backends.docker import DockerBackend
from .config import SandboxConfig
from .enums import RunStatus, RuntimeName
from .errors import (
    ConfigError,
    ImageBuildFailed,
    InvalidPackageSpec,
    LibraryPoolLocked,
    MissingDependenciesError,
    PoolSwapRollbackFailed,
    SessionBusy,
    SessionDropped,
    SessionNotFound,
    UnknownRuntime,
)
from .gc import GarbageCollector
from .locks import GlobalRunLimiter, SessionLockRegistry
from .metadata.filesystem import FilesystemMetadataStore
from .runtimes.base import Runtime
from .runtimes.python import PythonRuntime
from .runtimes.python.pool_staging import (
    canonicalizeName,
    enumerateDistInfos,
    extractSpecName,
    isValidCanonicalName,
    mergeStagedDelta,
    parsePipReport,
    swapPools,
)
from .storage import atomicWriteJson, ensureDirectoryLayout, resolveWorkspacePath, sessionHash
from .types import (
    ContainerSpec,
    FileContent,
    FileInfo,
    GcResult,
    HealthcheckResult,
    LibraryUpdateResult,
    NetworkPolicy,
    PackageInfo,
    PackageUpdate,
    ResourceLimits,
    RunInfo,
    RunResult,
    SessionInfo,
    ShutdownResult,
)

logger = logging.getLogger(__name__)

STAGING_IO_DIRNAME = "io"
"""Name of the container I/O subtree inside a staging run directory.

The ONLY part of a run dir any update container sees (mounted rw at the
runtime's ``STAGING_CONTAINER_PATH``): it holds ``report.json`` and
``delta/``. ``newpool``/``oldpool`` live OUTSIDE it, directly in the run
dir, so package build code running in the stage container can never touch
the future live pool.
"""


def _splitOutdatedSpecs(
    specs: Sequence[str],
    baselineVersions: dict[str, str],
    report: dict[str, str] | None,
    duplicateNames: set[str],
) -> tuple[list[str], list[str]]:
    """Split specs into outdated vs already-current using the parsed pip report.

    A spec is already current only when the report resolved it to exactly the
    version currently enumerated from the pool. Everything else is treated as
    outdated and staged: an unparseable report (fail-safe, plan §4.2 — a wrong
    skip would leave packages outdated, a full stage merely re-installs), an
    entry missing from the report, or a spec with no pool version (fresh
    install, packages.json-only phantom). A name carrying MULTIPLE dist-info
    entries (legacy duplicate install) is always forced outdated: the report
    matches at most one of them, and only a staged merge heals duplicates by
    removing every old dist-info (plan §9).

    Args:
        specs: Specs handed to the pre-filter container (validated host-side;
            for update-all these are canonical names).
        baselineVersions: Canonical name → version enumerated from the pool.
        report: Parsed pip report (canonical name → resolved version), or
            None when the report could not be parsed.
        duplicateNames: Canonical names with multiple dist-info entries in
            the pool; forced into the outdated set.

    Returns:
        Tuple of (outdatedSpecs, upToDateSpecs), both in input order.
    """
    outdated: list[str] = []
    upToDate: list[str] = []
    for spec in specs:
        canonicalName = canonicalizeName(extractSpecName(spec))
        if canonicalName in duplicateNames:
            outdated.append(spec)
            continue
        resolvedVersion = report.get(canonicalName) if report is not None else None
        baselineVersion = baselineVersions.get(canonicalName)
        if resolvedVersion is not None and baselineVersion is not None and resolvedVersion == baselineVersion:
            upToDate.append(spec)
        else:
            outdated.append(spec)
    return outdated, upToDate


def _diffPoolVersions(
    beforeVersions: dict[str, str],
    afterVersions: dict[str, str],
) -> tuple[list[PackageUpdate], list[PackageUpdate]]:
    """Compute the old→new diff from before/after pool enumerations (plan §5.1).

    Args:
        beforeVersions: Canonical name → version enumerated before the swap.
        afterVersions: Canonical name → version enumerated after the swap.

    Returns:
        Tuple of (updated, unchanged) PackageUpdate lists sorted by name;
        ``oldVersion`` is None for fresh installs and ``newVersion`` None for
        packages that vanished from the pool.
    """
    updated: list[PackageUpdate] = []
    unchanged: list[PackageUpdate] = []
    for name in sorted(set(beforeVersions.keys()) | set(afterVersions.keys())):
        oldVersion = beforeVersions.get(name)
        newVersion = afterVersions.get(name)
        updateEntry = PackageUpdate(name=name, oldVersion=oldVersion, newVersion=newVersion)
        if oldVersion == newVersion:
            unchanged.append(updateEntry)
        else:
            updated.append(updateEntry)
    return updated, unchanged


class SandboxManager:
    """Singleton manager for sandboxed code execution.

    Composes one Backend with N Runtimes and one MetadataStore.
    Owns the per-session lock registry and the GC loop.

    Access via SandboxManager.getInstance() after calling injectConfig().
    """

    _instance: "SandboxManager | None" = None
    """The singleton instance, or None if not yet created."""

    _lock = RLock()
    """Thread lock protecting singleton initialization."""

    _configInstance: SandboxConfig | None = None
    """Injected sandbox configuration (class-level, set via injectConfig)."""

    _config: SandboxConfig
    """Runtime sandbox configuration loaded at initialization."""

    _rootDir: Path
    """Root directory for sandbox storage (sessions, runtimes, tmp)."""

    _tmpDir: Path
    """Temporary directory for atomic writes and intermediate artifacts."""

    _metadata: FilesystemMetadataStore
    """Backing store for session and run metadata records."""

    _lockRegistry: SessionLockRegistry
    """Per-session run queue and cancel token registry."""

    _globalLimiter: GlobalRunLimiter
    """Global semaphore limiting concurrent runs across all sessions."""

    _backend: SandboxBackend
    """Container backend (Docker, or future alternatives)."""

    _runtimes: Dict[RuntimeName, Runtime]
    """Available runtimes keyed by RuntimeName enum."""

    _gc: GarbageCollector
    """Garbage collector for expired sessions and orphan resources."""

    def __new__(cls) -> "SandboxManager":
        """Create or return the singleton instance.

        Args:
            cls: The SandboxManager class.

        Returns:
            The singleton SandboxManager instance.
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    @classmethod
    def getInstance(cls) -> "SandboxManager":
        """Get or create the singleton SandboxManager instance.

        Config must be injected via injectConfig() before calling this method.
        If config is missing, raises RuntimeError immediately — preventing the
        singleton from being stored in a broken state.

        Args:
            cls: The SandboxManager class.

        Returns:
            The singleton SandboxManager instance.

        Raises:
            RuntimeError: If injectConfig() has not been called before getInstance().
        """
        if cls._configInstance is None:
            raise RuntimeError("SandboxConfig not injected. Call injectConfig() first.")
        if cls._instance is None:
            return cls()
        return cls._instance

    def __init__(self) -> None:
        """Initialise the sandbox manager.

        Only the first call executes; subsequent calls are guarded by the
        hasattr(self, 'initialized') sentinel.

        Args:
            self: The SandboxManager instance.

        Raises:
            RuntimeError: If config is not injected via injectConfig().
        """
        if hasattr(self, "initialized"):
            return
        self.initialized = True
        config = SandboxManager._configInstance
        if config is None:
            raise RuntimeError("SandboxConfig not injected")
        self._config = config

        # Ensure storage directories exist
        ensureDirectoryLayout(config.storage)

        self._rootDir = Path(config.storage.rootDir)
        self._tmpDir = self._rootDir / "tmp"

        # Initialize metadata store (filesystem-backed)
        # TODO: Add base class for MetadataStore + DBClass
        self._metadata = FilesystemMetadataStore(rootDir=self._rootDir, tmpDir=self._tmpDir)

        # Initialize lock registry
        self._lockRegistry = SessionLockRegistry(config.concurrency)

        # Initialize global run limiter
        self._globalLimiter = GlobalRunLimiter(
            maxConcurrent=config.concurrency.maxConcurrentRunsGlobal,
            waitSeconds=config.concurrency.globalQueueWaitSeconds,
        )

        # Initialize backend (Docker)
        dockerConfig = config.backend.docker
        self._backend: SandboxBackend = DockerBackend(dockerConfig)

        # Initialize runtimes
        self._runtimes: Dict[RuntimeName, Runtime] = {}
        if RuntimeName.PYTHON in config.runtimes:
            self._runtimes[RuntimeName.PYTHON] = PythonRuntime(config.runtimes[RuntimeName.PYTHON])

        # Initialize runtime preparation locks (one per runtime to prevent race conditions)
        self._runtimePrepLocks: Dict[RuntimeName, asyncio.Lock] = {}
        for runtime in self._runtimes:
            self._runtimePrepLocks[runtime] = asyncio.Lock()

        # Initialize garbage collector
        self._gc = GarbageCollector(
            config=config.gc,
            metadataStore=self._metadata,
            rootDir=self._rootDir,
            backend=self._backend,
        )

        logger.info("SandboxManager initialized with rootDir=%s", self._rootDir)

    @classmethod
    def injectConfig(cls, config: SandboxConfig | Dict[str, Any]) -> None:
        """Inject the sandbox configuration before getInstance().

        Must be called before the first getInstance() call.

        Args:
            cls: The SandboxManager class.
            config: The full sandbox configuration (SandboxConfig or dict).

        Raises:
            RuntimeError: If config is injected after the instance is created.
        """
        if not isinstance(config, SandboxConfig):
            config = SandboxConfig.fromDict(config)
        if cls._instance is not None:
            raise RuntimeError("SandboxManager instance already created. Cannot inject config.")
        cls._configInstance = config

    # ---- Runtime / image management ----

    async def prepareRuntime(
        self,
        runtime: RuntimeName,
        *,
        rebuildImage: bool = False,
    ) -> bool:
        """Ensure the run and install images for a runtime are present.

        Builds images if missing or rebuildImage=True. Creates the library
        pool directory and initializes the runtime metadata record.

        Args:
            self: The SandboxManager instance.
            runtime: The runtime to prepare.
            rebuildImage: If True, rebuild images even if they exist.

        Returns:
            True if images are present and prepared, False otherwise.

        Raises:
            ImageBuildFailed: If image build fails.
        """
        if runtime not in self._runtimes:
            raise ValueError(f"Runtime '{runtime}' is not initialized.")

        poolDir = Path(self._config.storage.rootDir) / "runtimes" / runtime.value
        libsDir = poolDir / "libs"
        libsDir.mkdir(parents=True, exist_ok=True)

        # Get runtime config
        runtimeConfig = self._runtimes[runtime]._config

        async with self._runtimePrepLocks[runtime]:
            # Attempt to ensure images
            try:
                await self._backend.ensureImage(
                    imageTag=runtimeConfig.runImageTag,
                    imageFile=str(Path(runtimeConfig.runDockerfile).absolute()),
                    rebuild=rebuildImage,
                )
            except ImageBuildFailed as exc:
                logger.exception(exc)
                logger.warning(f"Could not build run image for {runtime}")
                # Don't mark prepared if run image failed
                return self._runtimes[runtime].isPrepared()

            try:
                await self._backend.ensureImage(
                    imageTag=runtimeConfig.installImageTag,
                    imageFile=str(Path(runtimeConfig.installDockerfile).absolute()),
                    rebuild=rebuildImage,
                )
            except ImageBuildFailed as exc:
                logger.exception(exc)
                logger.warning(f"Could not build install image for {runtime}")
                return self._runtimes[runtime].isPrepared()

            # Only mark prepared if both images were built successfully
            self._runtimes[runtime].markPrepared()
            return True

    async def listRuntimes(self) -> Sequence[RuntimeName]:
        """List all known runtimes.

        Args:
            self: The SandboxManager instance.

        Returns:
            Sequence of runtime names.
        """
        return tuple(self._runtimes.keys())

    # ---- Sessions ----

    async def createSession(
        self,
        sessionId: str,
        *,
        forceRecreate: bool = False,
        ttlMinutes: int | None = None,
        limits: ResourceLimits | None = None,
        metadata: dict[str, str] | None = None,
    ) -> bool:
        """Create a new session or return the existing one.

        Idempotent unless forceRecreate=True. Allocates the workspace directory
        and persists the session record. No container is created.

        Args:
            self: The SandboxManager instance.
            sessionId: Opaque session identifier.
            forceRecreate: If True, drop any existing session first.
            ttlMinutes: Session idle TTL in minutes (default from config).
            limits: Resource limits for runs in this session (default from config).
            metadata: Opaque caller-supplied key-value pairs.

        Returns:
            True if session was created or exists, False otherwise.
        """
        # Check existing session
        existing = await self._metadata.loadSession(sessionId)
        if existing is not None:
            if not forceRecreate:
                return True
            # forceRecreate: drop and continue
            await self.dropSession(sessionId, force=True)

        # Compute defaults
        defaults = self._config.defaults
        effectiveTtl = ttlMinutes if ttlMinutes is not None else defaults.idleTtlMinutes
        effectiveLimits = limits if limits is not None else self._config.limits
        effectiveMetadata = metadata if metadata is not None else {}

        now = libUtils.now()
        sHash = sessionHash(sessionId)
        workspacePath = Path(self._config.storage.rootDir) / "sessions" / sHash / "workspace"

        # Create workspace directory
        workspacePath.mkdir(parents=True, exist_ok=True)
        # Reset permissions on every use as a security measure, even if the directory already exists.
        os.chmod(workspacePath, self._config.storage.dirMode)

        await self._metadata.saveSession(
            SessionInfo(
                sessionId=sessionId,
                sessionHash=sHash,
                workspacePath=str(workspacePath),
                createdAt=now,
                updatedAt=now,
                expiresAt=now + timedelta(minutes=effectiveTtl),
                limits=effectiveLimits,
                metadata=effectiveMetadata,
            )
        )
        logger.info("Created session %s (hash=%s)", sessionId, sHash)

        return True

    async def listSessions(self) -> list[SessionInfo]:
        """List all sessions.

        Args:
            self: The SandboxManager instance.

        Returns:
            List of session IDs.
        """
        return await self._metadata.loadAllSessions()

    async def touchSession(self, sessionId: str, *, ttlMinutes: int | None = None) -> bool:
        """Refresh a session's last-activity timestamp and optionally extend its TTL.

        Args:
            self: The SandboxManager instance.
            sessionId: Unique identifier of the session.
            ttlMinutes: Optional override for the new time-to-live in minutes.

        Returns:
            True if the session was successfully updated.

        Raises:
            SessionNotFound: If the session doesn't exist.
        """
        record = await self._metadata.loadSession(sessionId)
        if record is None:
            raise SessionNotFound(f"Session {sessionId} not found")

        defaults = self._config.defaults
        effectiveTtl = ttlMinutes if ttlMinutes is not None else defaults.idleTtlMinutes

        await self._touchSessionInternal(record=record, ttlMinutes=effectiveTtl)
        return True

    async def dropSession(self, sessionId: str, *, force: bool = False) -> Sequence[Exception]:
        """Drop (destroy) a sandbox session and clean up its resources.

        Args:
            self: The SandboxManager instance.
            sessionId: Unique identifier of the session to drop.
            force: If True, cancel active runs and force-remove the session.

        Returns:
            Sequence of any errors encountered during cleanup.
        """
        record = await self._metadata.loadSession(sessionId)
        errors: list[Exception] = []

        if record is None:
            return []

        if force:
            for container in await self._backend.listManagedContainers():
                if container.labels.get("sandbox.sessionId", None) != sessionId:
                    continue

                # No need to try to kill container, as we are removing it with force=True
                try:
                    await self._backend.removeContainer(containerId=container.containerId, force=True)
                except Exception as exc:
                    logger.warning(
                        "Failed to remove container %s for session %s: %s", container.containerId, sessionId, exc
                    )

            self._lockRegistry.forceCancel(sessionId)

        try:
            # Acquire session lock to serialise with in-flight runs
            await self._lockRegistry.acquire(sessionId)
        except (SessionBusy, SessionDropped):
            # If force=True, we already cancelled; proceed with cleanup
            if not force:
                raise

        try:
            # Delete all run records for this session before deleting the session itself
            runs = await self._metadata.listRunsForSession(sessionId)
            for run in runs:
                try:
                    await self._metadata.deleteRun(run.runId)
                except Exception as exc:
                    logger.warning("Failed to delete run %s for session %s: %s", run.runId, sessionId, exc)

            # Delete workspace directory
            workspacePath = Path(record.workspacePath)
            if workspacePath.exists():
                shutil.rmtree(workspacePath)

            # Delete metadata record
            await self._metadata.deleteSession(sessionId)
        except OSError as exc:
            errors.append(exc)
            logger.warning("Error cleaning up session %s: %s", sessionId, exc)
        finally:
            self._lockRegistry.release(sessionId)
            self._lockRegistry.clearCancelled(sessionId)

        return errors

    def _getLibPoolPath(self, runtime: RuntimeName) -> Path:
        """Get the library pool directory path for a runtime.

        Args:
            self: The SandboxManager instance.
            runtime: The runtime name.

        Returns:
            The host path to the library pool.
        """

        return Path(self._config.storage.rootDir) / "runtimes" / runtime.value / "libs"

    async def _touchSessionInternal(self, record: SessionInfo, ttlMinutes: int) -> None:
        """Bump the session TTL without the full touchSession API overhead.

        Args:
            self: The SandboxManager instance.
            record: The session record (modified in place).
            ttlMinutes: The new TTL in minutes.
        """
        now = datetime.now(timezone.utc)
        record.updatedAt = now
        record.expiresAt = now + timedelta(minutes=ttlMinutes)
        await self._metadata.saveSession(record)

    # ---- Runs ----

    async def runCode(
        self,
        sessionId: str,
        code: str,
        *,
        runtime: RuntimeName,
        requiredPackages: Optional[Sequence[str]] = None,
        network: NetworkPolicy | None = None,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> RunResult:
        """Execute code in a sandboxed container.

        Auto-creates the session if it doesn't exist. Verifies required
        packages are in the library pool before starting a container.

        Args:
            self: The SandboxManager instance.
            sessionId: The session identifier.
            code: The Python code to execute.
            runtime: The runtime to use.
            requiredPackages: Packages that must be in the library pool.
            network: Network policy for this run.
            stdin: Text to feed as stdin.
            env: Additional environment variables.

        Returns:
            RunResult with exit code, output paths, and error status.

        Raises:
            MissingDependenciesError: If required packages are not in the pool.
            UnknownRuntime: If the runtime is not available.
            SessionBusy: If the session's queue is full.
            SandboxBusy: If the global concurrency cap is reached.
        """
        effectiveNetwork = network if network is not None else NetworkPolicy(enabled=False)

        # Validate runtime
        if runtime not in self._runtimes:
            raise UnknownRuntime(f"Runtime {runtime.value} is not available")

        runtimeImpl = self._runtimes[runtime]

        # Step 1: Acquire session lock (FIFO)
        async with self._lockRegistry.sessionLock(sessionId):
            # Step 2: Acquire global run semaphore
            async with self._globalLimiter.runSlot():
                # Prepare runtime if it isn't already
                if not runtimeImpl.isPrepared():
                    await self.prepareRuntime(runtime=runtime)

                # Step 3: Ensure session exists (auto-create)
                await self.createSession(sessionId)
                sessionInfo = await self._metadata.loadSession(sessionId)
                if sessionInfo is None:
                    raise RuntimeError(f"Failed to create session {sessionId}")

                # Step 4: Generate runId
                runId = str(uuid.uuid4())

                # Step 5: Verify required packages
                if requiredPackages:
                    installedNames = {p.name for p in await self.listRuntimeLibraries(runtime=runtime)}
                    missing = [p for p in requiredPackages if p not in installedNames]
                    if missing:
                        logger.warning(f"Missing required {runtime} libs: {missing}")
                        raise MissingDependenciesError(missing=missing)

                # Step 6: Set up run directory
                workspacePath = Path(sessionInfo.workspacePath)
                # Ensure workspace directory exists (might be missing if tmp_path changed)
                workspacePath.mkdir(parents=True, exist_ok=True)
                # Reset permissions on every use as a security measure, even if the directory already exists.
                os.chmod(workspacePath, self._config.storage.dirMode)
                runDir = workspacePath / ".run" / runId
                runDir.mkdir(parents=True, exist_ok=True)

                # Step 6b: Create per-run working directory
                workDirPath = runDir / "work"
                workDirPath.mkdir(parents=True, exist_ok=True)

                # Step 7: Write main.py
                mainPath = runDir / runtimeImpl.getScriptName()
                mainPath.write_text(code, encoding="utf-8")

                # Write stdin if provided
                hasStdin = stdin is not None
                if hasStdin:
                    stdinPath = runDir / "stdin"
                    stdinPath.write_text(stdin, encoding="utf-8")

                # Step 8: Build ContainerSpec
                # Get lib pool path
                hostLibPool = self._getLibPoolPath(runtime)

                mounts: list[dict[str, str]] = [
                    {"hostPath": str(workspacePath.absolute()), "containerPath": "/workspace", "mode": "rw"},
                ]
                if hostLibPool.exists():
                    mounts.append(
                        {
                            "hostPath": str(hostLibPool.absolute()),
                            "containerPath": runtimeImpl._config.libMountPath,
                            "mode": "ro",
                        }
                    )

                # Build env
                containerEnv: dict[str, str] = {}
                containerEnv.update(runtimeImpl._config.env)
                if env:
                    containerEnv.update(env)

                # Compute network mode
                networkMode = "bridge" if effectiveNetwork.enabled else "none"

                # Record start time for artifact detection
                startTime = libUtils.now()

                # Step 9: Write RunInfo (status="running")
                runRecord = RunInfo(
                    runId=runId,
                    sessionId=sessionId,
                    runtime=runtime,
                    startedAt=startTime,
                    finishedAt=None,
                    status=RunStatus.RUNNING,
                    exitCode=None,
                )
                await self._metadata.saveRun(runRecord)

                # Step 10: Run the container and collect results.
                # Wrap in try/except to update RunRecord on failure, and
                # try/finally to always remove the container.
                try:
                    outcome = await self._backend.runOneshot(
                        spec=ContainerSpec(
                            name=f"sandbox-{runId}",
                            image=runtimeImpl._config.runImageTag,
                            command=runtimeImpl.runCommand(
                                runId=runId,
                                hasStdin=hasStdin,
                                limits=sessionInfo.limits,
                            ),
                            mounts=mounts,
                            env=containerEnv,
                            limits=sessionInfo.limits,
                            network=networkMode,
                            user=self._config.security.user,
                            readOnlyRoot=self._config.security.readOnlyRootfs,
                            capDrop=list(self._config.security.dropCapabilities),
                            securityOpt=["no-new-privileges"] if self._config.security.noNewPrivileges else [],
                            labels={
                                "sandbox.managed": "true",
                                "sandbox.runId": runId,
                                "sandbox.sessionId": sessionId,
                                "sandbox.runtime": runtime.value,
                                "sandbox.createdAt": startTime.isoformat(),
                            },
                        )
                    )

                    try:
                        # Step 11: Detect outcome
                        finishedAt = datetime.now(timezone.utc)
                        elapsedMs = int((finishedAt - startTime).total_seconds() * 1000)
                        timedOut = outcome.exitCode == 124 or outcome.signal == "SIGKILL"
                        oomKilled = outcome.oomKilled

                        # Step 12: Read output sizes
                        stdoutPath = runDir / "stdout.log"
                        stderrPath = runDir / "stderr.log"
                        stdoutBytes = stdoutPath.stat().st_size if stdoutPath.exists() else 0
                        stderrBytes = stderrPath.stat().st_size if stderrPath.exists() else 0

                        # Step 14: Build RunResult
                        error: str | None = None
                        if timedOut:
                            error = "Run timed out"
                        elif oomKilled:
                            error = "Run OOM killed"
                        elif outcome.exitCode != 0 and outcome.exitCode is not None:
                            error = f"Exit code {outcome.exitCode}"

                        # Step 16 (success path): Update RunInfo (status="completed" or "failed")
                        runRecord.status = RunStatus.COMPLETED if error is None else RunStatus.FAILED
                        runRecord.exitCode = outcome.exitCode
                        runRecord.finishedAt = finishedAt
                        await self._metadata.saveRun(runRecord)

                        result = RunResult(
                            runId=runId,
                            sessionId=sessionId,
                            workDir=f".run/{runId}/work",
                            runtime=runtime,
                            stdoutPath=f".run/{runId}/stdout.log",
                            stderrPath=f".run/{runId}/stderr.log",
                            stdoutBytes=stdoutBytes,
                            stderrBytes=stderrBytes,
                            exitCode=outcome.exitCode,
                            signal=outcome.signal,
                            timedOut=timedOut,
                            oomKilled=oomKilled,
                            startedAt=startTime,
                            finishedAt=finishedAt,
                            elapsedMs=elapsedMs,
                            networkEnabled=effectiveNetwork.enabled,
                            error=error,
                        )

                        # Write result.json
                        atomicWriteJson(
                            runDir / "result.json",
                            result.toDict(),
                            tmpDir=Path(self._config.storage.rootDir) / "tmp",
                        )
                    finally:
                        # Step 15: Remove container (always, even on error)
                        try:
                            await self._backend.removeContainer(outcome.containerId)
                        except Exception:
                            logger.exception("Failed to remove container %s", outcome.containerId)
                except Exception as exc:
                    # Step 16 (error path): Update RunRecord to failed
                    finishedAt = datetime.now(timezone.utc)
                    runRecord.status = RunStatus.FAILED
                    runRecord.finishedAt = finishedAt
                    runRecord.exitCode = -1
                    await self._metadata.saveRun(runRecord)
                    logger.error("Run %s failed: %s", runId, exc)
                    logger.exception(exc)
                    raise

                # Step 17: Bump session TTL
                await self._touchSessionInternal(sessionInfo, ttlMinutes=self._config.defaults.idleTtlMinutes)

                return result

    async def cancelRun(self, runId: str) -> bool:
        """Cancel a running container by runId.

        Looks up the container via the sandbox.runId label and sends SIGKILL.

        Args:
            self: The SandboxManager instance.
            runId: The run identifier.

        Returns:
            True if a container was found and killed, False otherwise.
        """
        try:
            # Look up container by label
            for container in await self._backend.listManagedContainers():
                if container.labels.get("sandbox.runId") == runId:
                    await self._backend.killContainer(container.containerId)
                    return True
            return False
        except Exception as exc:
            logger.warning("Failed to cancel run %s: %s", runId, exc)
            return False

    async def listRunsForSession(self, sessionId: str) -> List[RunInfo]:
        """List all runs for a session.

        Args:
            self: The SandboxManager instance.
            sessionId: The session identifier.

        Returns:
            List of RunInfo records for this session.
        """
        return await self._metadata.listRunsForSession(sessionId)

    # ---- Files & artifacts ----

    async def listFiles(
        self,
        sessionId: str,
        *,
        path: str = "/",
        recursive: bool = False,
    ) -> list[FileInfo]:
        """List files in a session workspace.

        All paths are resolved relative to the session workspace. Absolute
        paths are normalised to relative form (stripping ``/workspace``
        prefix or leading ``/``) before resolution. Paths that escape the
        workspace via traversal or symlinks are rejected.

        Args:
            self: The SandboxManager instance.
            sessionId: The session identifier.
            path: Path to list (absolute or relative, default "/" = workspace root).
            recursive: If True, recurse into subdirectories.

        Returns:
            List of FileInfo for each entry in the directory.

        Raises:
            SessionNotFound: If the session doesn't exist.
            PathOutsideWorkspace: If the path escapes the workspace.
        """
        record = await self._metadata.loadSession(sessionId)
        if record is None:
            raise SessionNotFound(f"Session {sessionId} not found")

        workspacePath = Path(record.workspacePath).absolute()
        # logger.debug("Listing files in session %s (%s) at path %s", sessionId, workspacePath, path)
        resolved = resolveWorkspacePath(workspacePath, path)

        if not resolved.exists():
            return []

        results: list[FileInfo] = []
        iterator = resolved.rglob("*") if recursive else resolved.iterdir()
        for entry in iterator:
            try:
                stat = entry.stat()
                results.append(
                    FileInfo(
                        path=str(entry.relative_to(workspacePath)),
                        sizeBytes=stat.st_size if entry.is_file() else 0,
                        modifiedAt=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        isDirectory=entry.is_dir(),
                    )
                )
            except OSError:
                continue  # skip files we can't stat

        return results

    async def readFile(
        self,
        sessionId: str,
        path: str,
        *,
        maxBytes: int | None = None,
        encoding: str | None = "utf-8",
    ) -> FileContent:
        """Read a file from the session workspace.

        Enforces maxBytes at read time. Reports whether the content was
        truncated and how many bytes were actually read.

        Args:
            self: The SandboxManager instance.
            sessionId: The session identifier.
            path: Path to the file (absolute or relative).
            maxBytes: Maximum bytes to read (None = no limit).
            encoding: Text encoding for string output (None = raw bytes).

        Returns:
            FileContent with the path, sizes, truncation flag, and content.

        Raises:
            SessionNotFound: If the session doesn't exist.
            PathOutsideWorkspace: If the path escapes the workspace.
            FileNotFoundError: If the file doesn't exist.
        """
        record = await self._metadata.loadSession(sessionId)
        if record is None:
            raise SessionNotFound(f"Session {sessionId} not found")

        workspacePath = Path(record.workspacePath)
        resolved = resolveWorkspacePath(workspacePath, path)

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not resolved.is_file():
            raise IsADirectoryError(f"Path is a directory: {path}")

        fullSize = resolved.stat().st_size
        truncated = maxBytes is not None and fullSize > maxBytes

        # Read at most maxBytes+1 to detect truncation without loading the entire file
        with resolved.open("rb") as fh:
            raw = fh.read(maxBytes + 1) if maxBytes is not None else fh.read()
        if truncated:
            raw = raw[:maxBytes]

        content: bytes | str
        if encoding is not None:
            content = raw.decode(encoding)
        else:
            content = raw

        return FileContent(
            path=path,
            sizeBytes=fullSize,
            bytesRead=len(raw),
            truncated=truncated,
            content=content,
        )

    # ---- Library pool (admin API) ----

    async def listRuntimeLibraries(
        self,
        runtime: RuntimeName,
    ) -> List[PackageInfo]:
        """List installed packages in the runtime library pool.

        Reads the packages.json file from the runtime's pool directory.

        Args:
            self: The SandboxManager instance.
            runtime: The runtime whose library pool to query.

        Returns:
            List of PackageInfo for each installed package.
        """
        return await self._metadata.loadPackagesInfo(runtime)

    async def installRuntimeLibraries(
        self,
        packages: Sequence[str],
        *,
        runtime: RuntimeName,
        upgrade: bool = False,
        timeoutSeconds: int | None = None,
    ) -> bool:
        """Install packages into the runtime library pool via staged install + atomic swap.

        Routes through the SAME staged core as
        :meth:`updateRuntimeLibraries` (docs/plans/sandbox-update-v1.md
        §5.5): under the pool lock the pool is copied host-side, pip stages
        into a private delta inside a container that does NOT mount the
        live pool, the delta is merged into the copy (the old dist-info is
        deleted per its RECORD — reinstalling an already-present package
        cleanly replaces it instead of corrupting the pool), and the copy
        replaces the pool atomically. A stage failure leaves the live pool
        untouched and keeps the stage container for post-mortem log
        inspection (``docker logs <containerId>``). On success the package
        list is refreshed best-effort.

        The ``upgrade`` flag is a documented no-op: pip ``--target`` has no
        satisfaction check, so a staged install always resolves and
        installs fresh into the empty delta — there is nothing for
        ``--upgrade`` to upgrade. The parameter is kept only for
        ``scripts/sandbox_bootstrap.py`` call compatibility.

        Args:
            self: The SandboxManager instance.
            packages: Package specs (PEP 508 names, possibly with version constraints).
            runtime: The runtime to install into.
            upgrade: Unused; kept for ``scripts/sandbox_bootstrap.py``
                compatibility. A staged install always resolves fresh —
                pip ``--target`` performs no satisfaction check, so there
                is no prior version in the delta for ``--upgrade`` to
                replace.
            timeoutSeconds: Timeout for the install operation. When None (default),
                falls back to the runtime's ``install-container.timeout-seconds``
                config value.

        Returns:
            True if installation succeeded, False otherwise.

        Raises:
            InvalidPackageSpec: If a package spec is malformed or malicious.
            LibraryPoolLocked: If another process holds the install lock.
            UnknownRuntime: If the runtime is not available.
            ConfigError: If the helper script is missing on the host, or the
                staging area is on a different filesystem than the pool.
            OSError: If crash-recovery adoption failed under the pool lock
                (fail closed — the crash leftovers stay retryable).
            LibraryInstallFailed: If the staged delta is malformed or unsafe to merge.
            PoolSwapRollbackFailed: If the swap's second rename AND its
                inline rollback both failed; the staging run dir is
                preserved for startup recovery (plan §4.5).
        """
        if not packages:
            return True

        runtimeImpl = self._runtimes.get(runtime)
        if runtimeImpl is None:
            raise UnknownRuntime(f"Runtime {runtime.value} is not available")

        poolDir = Path(self._config.storage.rootDir) / "runtimes" / runtime.value

        # Step 1: Validate package specs (partial failures are logged and
        # skipped; a complete failure raises).
        validated: list[str] = []
        failedPackages: Sequence[Tuple[str, str]] = []
        for spec in packages:
            try:
                cleaned = spec.strip()
                if not cleaned:
                    failedPackages.append((spec, "Empty spec"))
                    continue
                await self._validatePackageSpec(cleaned, runtime=runtime)
                validated.append(cleaned)
            except InvalidPackageSpec as e:
                logger.warning(f"Required package {spec} does not look like valid spec: {e}")
                failedPackages.append((spec, str(e)))

        if not validated:
            if failedPackages:
                # All specs failed - provide detailed error
                failedSpecs = ", ".join([f"{spec}: {reason}" for spec, reason in failedPackages])
                raise InvalidPackageSpec(spec=packages[0], reason=f"All package specs failed validation: {failedSpecs}")
            return False

        # Step 2: Acquire fcntl lock and run the staged core inside it
        async with locks.poolLock(runtime, poolDir):
            # Crash recovery before anything may create or use the pool
            # (plan §4.5): a hard crash mid-swap leaves complete newpool/
            # oldpool copies in staging, but recovery normally waits for the
            # first cron tick — and the libs mkdir inside the staged core
            # would create an empty pool that suppresses adoption of those
            # copies. Adopting here (cheap, idempotent, under the lock we
            # already hold) closes the hole immediately. A failed adoption
            # raises and fails the install — fail closed, leftovers stay
            # retryable.
            self._recoverRuntimePool(runtime)

            # Step 3: Staged copy → stage container → merge → swap (plan
            # §5.5). pip never writes the live pool. On stage failure the
            # container is kept for post-mortem and the pool is untouched.
            success, _keptContainerId = await self._runStagedInstall(
                runtime, runtimeImpl, validated, timeoutSeconds, purpose="install"
            )

            # Step 4: Refresh package metadata after a successful swap so
            # that listRuntimeLibraries() reflects the newly installed
            # packages (best-effort: a failed refresh does not fail the
            # install).
            if success:
                libsDir = poolDir / "libs"
                try:
                    await self._refreshPackageList(runtime, libsDir)
                except Exception:
                    logger.exception(
                        "Failed to refresh package list after successful install for %s",
                        runtime.value,
                    )

            return success

    async def updateRuntimeLibraries(
        self,
        packages: Sequence[str] | None,
        *,
        runtime: RuntimeName,
        timeoutSeconds: int | None = None,
    ) -> LibraryUpdateResult:
        """Update packages in the runtime library pool via staged install + atomic swap.

        Pre-filters outdated specs with a read-only dry-run container, then —
        under the pool lock — copies the pool, stages pip's output in a private
        delta, merges it into the copy, and swaps atomically. A failure at any
        point leaves the live pool untouched. On success the containers are
        removed and the package list refreshed; on failure the stage container
        is kept for ``docker logs`` post-mortem.

        Args:
            self: The SandboxManager instance.
            packages: Specs to update (PEP 508, same grammar as install), or
                None to update every package known to the pool (§6).
            runtime: The runtime whose pool to update.
            timeoutSeconds: Timeout override applied to both container runs;
                None falls back to ``install-container.timeout-seconds``.

        Returns:
            LibraryUpdateResult with the old→new diff, already-current specs,
            and failure details. ``metadataRefreshed`` is None when no
            refresh was attempted (no-op results and stage failures), False
            when the post-swap refresh failed (stale packages.json — the
            diff remains accurate, computed from pool enumerations), True
            when it succeeded.

        Raises:
            InvalidPackageSpec: If every named spec fails validation.
            LibraryPoolLocked: If another process holds the pool lock (either
                the in-lock recovery/mutation phase, or the update-all
                empty-find recovery retry while a holder is still active).
            UnknownRuntime: If the runtime is not available.
            ConfigError: If the helper script is missing on the host, or the
                staging area is on a different filesystem than the pool.
            OSError: If crash-recovery adoption failed (the opportunistic
                pass, the in-lock retry, or the empty-find retry) — fail
                closed, the crash leftovers stay retryable.
            LibraryInstallFailed: If the staged delta is malformed or unsafe to merge.
            PoolSwapRollbackFailed: If the swap's second rename AND its
                inline rollback both failed; the staging run dir is preserved
                for startup recovery (plan §4.5).
        """
        runtimeImpl = self._runtimes.get(runtime)
        if runtimeImpl is None:
            raise UnknownRuntime(f"Runtime {runtime.value} is not available")

        poolDir = Path(self._config.storage.rootDir) / "runtimes" / runtime.value
        libsDir = poolDir / "libs"

        # Opportunistic crash recovery before anything may create or inspect
        # the pool (plan §4.5): the cron recover() normally handles this on
        # its first tick, but an early request could otherwise enumerate an
        # empty pool (update-all would report "Nothing installed") and the
        # staged install below would create an empty libs dir that
        # suppresses adoption of the complete crash copies. Cheap,
        # idempotent, and non-blocking: when the pool lock is busy or
        # reconciliation fails, the pass defers and recovery is re-attempted
        # later — the mutation phase under the lock, or (update-all only)
        # the empty-find guard below (fail closed).
        reconciliationOk = await self._reconcileRuntimePool(runtime, refreshMetadata=False)

        # A named-but-empty request updates nothing; only None means "all".
        if packages is not None and not packages:
            return LibraryUpdateResult(
                runtime=runtime,
                success=True,
                updated=[],
                unchanged=[],
                upToDate=[],
                failedSpecs=[],
                containerId=None,
                metadataRefreshed=None,
            )

        # Step 1: Validate named specs (partial failures proceed, recorded in
        # failedSpecs; only an all-fail batch raises before any container).
        failedSpecs: list[tuple[str, str]] = []
        validated: list[str] = []
        if packages is not None:
            for spec in packages:
                try:
                    cleaned = spec.strip()
                    if not cleaned:
                        failedSpecs.append((spec, "Empty spec"))
                        continue
                    await self._validatePackageSpec(cleaned, runtime=runtime)
                    validated.append(cleaned)
                except InvalidPackageSpec as e:
                    logger.warning(f"Package {spec} does not look like valid spec: {e}")
                    failedSpecs.append((spec, str(e)))

            if not validated:
                # All specs failed - raise before any container starts.
                failedList = ", ".join([f"{spec}: {reason}" for spec, reason in failedSpecs])
                raise InvalidPackageSpec(spec=packages[0], reason=f"All package specs failed validation: {failedList}")

        # Step 2: Pre-check the helper script exists on the host — a missing
        # file-bind silently becomes a directory in Docker. Both update
        # containers (pre-filter and stage) bind it read-only.
        helperPath = runtimeImpl.updateHelperHostPath()
        if not helperPath.is_file():
            raise ConfigError(
                f"Update helper script not found on host: {helperPath} (expected next to the install Dockerfile)"
            )

        # Step 3: Build the pre-filter spec set. Update-all is driven host-side
        # (plan §6): pool dist-info enumeration ∪ packages.json names. An empty
        # pool short-circuits with a "Nothing installed" result — no container,
        # no lock — but ONLY when the opportunistic recovery pass succeeded.
        # When it deferred (lock busy) or failed AND crash leftovers exist
        # under tmp/, the pool may be empty precisely because the complete
        # swap copies are stranded in staging: re-attempt recovery under the
        # pool lock before trusting the empty find. A recovery that still
        # fails raises (fail closed — LibraryPoolLocked from a still-busy
        # lock, OSError from failed renames) instead of reporting a false
        # success that would leave the leftovers to staging GC.
        if packages is None:
            updateAllNames = await self._collectUpdateAllNames(runtime, libsDir)
            if not updateAllNames and not reconciliationOk and self._hasPoolCrashLeftovers():
                async with locks.poolLock(runtime, poolDir):
                    self._recoverRuntimePool(runtime)
                # A successful adoption re-populated the pool: re-collect the
                # name set. A still-empty set means the leftovers were GC
                # debris beside a live pool — the empty result below is honest.
                updateAllNames = await self._collectUpdateAllNames(runtime, libsDir)
            if not updateAllNames:
                return LibraryUpdateResult(
                    runtime=runtime,
                    success=True,
                    updated=[],
                    unchanged=[],
                    upToDate=[],
                    failedSpecs=failedSpecs,
                    containerId=None,
                    metadataRefreshed=None,
                )
            prefilterSpecs: list[str] = sorted(updateAllNames)
        else:
            prefilterSpecs = validated

        # Step 4: Baseline enumeration — the host-side dist-info parse doubles
        # as the diff baseline and the already-current comparison source
        # (plan §5.1; packages.json is no longer the diff source). Names with
        # multiple dist-info entries are tracked separately: they are forced
        # outdated so the staged merge heals the duplicates (plan §9).
        baselineVersions = self._enumeratePoolVersions(libsDir)
        duplicateNames = self._collectDuplicatePoolNames(libsDir)

        # Step 5: Outdated pre-filter — read-only dry-run report container,
        # run BEFORE the pool lock; the live pool is not mounted (plan §4.1
        # step 1). Report resolution is fail-safe: an unparseable report
        # treats every spec as outdated.
        outdatedSpecs, upToDate = await self._runPrefilterContainer(
            runtime, runtimeImpl, prefilterSpecs, baselineVersions, duplicateNames, timeoutSeconds
        )

        # Empty outdated subset → success immediately: no lock, no mutation
        # container, zero stage calls (plan §9).
        if not outdatedSpecs:
            return LibraryUpdateResult(
                runtime=runtime,
                success=True,
                updated=[],
                unchanged=[],
                upToDate=upToDate,
                failedSpecs=failedSpecs,
                containerId=None,
                metadataRefreshed=None,
            )

        async with locks.poolLock(runtime, poolDir):
            # Crash leftovers may still be unadopted (the opportunistic
            # start-of-method pass deferred on lock contention): adopt them
            # BEFORE the baseline enumeration — the staged install's
            # libsDir.mkdir would otherwise create an empty pool over the
            # leftovers. A failed adoption raises and fails the update
            # (fail closed, leftovers stay retryable).
            self._recoverRuntimePool(runtime)

            # Re-enumerate the baseline under the lock — the pre-lock snapshot
            # may be stale. Accepted per plan §5.1: staging a since-updated
            # package is an idempotent same-version reinstall; a since-outdated
            # skip merely waits for the next update.
            beforeVersions = self._enumeratePoolVersions(libsDir)

            # Mechanism steps 3-6: copy → stage → merge → swap.
            success, keptContainerId = await self._runStagedInstall(
                runtime, runtimeImpl, outdatedSpecs, timeoutSeconds, purpose="update"
            )
            if not success:
                return LibraryUpdateResult(
                    runtime=runtime,
                    success=False,
                    updated=[],
                    unchanged=[],
                    upToDate=upToDate,
                    failedSpecs=failedSpecs,
                    containerId=keptContainerId,
                    metadataRefreshed=None,
                )

            afterVersions = self._enumeratePoolVersions(libsDir)

            try:
                metadataRefreshed = await self._refreshPackageList(runtime, libsDir)
            except Exception:
                logger.exception("Failed to refresh package list after successful update for %s", runtime.value)
                metadataRefreshed = False

        # Diff from the before/after pool enumerations, computed outside the
        # lock from the captured point-in-time snapshots.
        updated, unchanged = _diffPoolVersions(beforeVersions, afterVersions)
        return LibraryUpdateResult(
            runtime=runtime,
            success=True,
            updated=updated,
            unchanged=unchanged,
            upToDate=upToDate,
            failedSpecs=failedSpecs,
            containerId=None,
            metadataRefreshed=metadataRefreshed,
        )

    # ---- Operational ----

    async def healthcheck(self) -> HealthcheckResult:
        """Run a full health check on the sandbox system.

        Pings the backend, checks each runtime, and verifies the storage
        directory is writable.

        Args:
            self: The SandboxManager instance.

        Returns:
            HealthcheckResult with overall ok status and per-component details.
        """
        errors: list[str] = []

        # Backend health
        backendResult = await self._backend.healthcheck()
        errors.extend(backendResult.errors)

        return HealthcheckResult(
            ok=len(errors) == 0 and (backendResult.ok),
            errors=errors,
        )

    async def shutdown(self, *, cleanVolumes: bool = False) -> ShutdownResult:
        """Shut down the sandbox manager.

        Closes the backend connection and optionally cleans all sessions.

        Args:
            self: The SandboxManager instance.
            cleanVolumes: If True, drop every session before shutting down.

        Returns:
            ShutdownResult with cleanup counts and errors.
        """
        errors: list[str] = []
        cleanedVolumes = 0

        if cleanVolumes:
            try:
                for session in await self._metadata.loadAllSessions():
                    sessionId = session.sessionId
                    try:
                        await self.dropSession(sessionId, force=True)
                        cleanedVolumes += 1
                    except Exception as exc:
                        errMsg = f"Failed to drop session {sessionId}: {exc}"
                        errors.append(errMsg)
                        logger.error(errMsg)
            except Exception as exc:
                errMsg = f"Failed to list sessions for cleanup: {exc}"
                errors.append(errMsg)
                logger.error(errMsg)

        # Cancel active runs across all sessions before closing backend
        cancelledRuns = 0
        if not cleanVolumes:
            try:
                for session in await self._metadata.loadAllSessions():
                    sessionId = session.sessionId
                    runs = await self._metadata.listRunsForSession(sessionId)
                    for run in runs:
                        if run.status == RunStatus.RUNNING:
                            try:
                                await self.cancelRun(run.runId)
                                cancelledRuns += 1
                            except Exception as exc:
                                logger.warning("Failed to cancel run %s during shutdown: %s", run.runId, exc)
            except Exception as exc:
                logger.error("Failed to cancel active runs during shutdown: %s", exc)

        logger.info("Shutdown cancelled %d active runs", cancelledRuns)

        # Close backend
        try:
            await self._backend.close()
        except Exception as exc:
            errMsg = f"Failed to close backend: {exc}"
            errors.append(errMsg)
            logger.error(errMsg)

        return ShutdownResult(
            cleanedVolumes=cleanedVolumes,
            errors=errors,
        )

    async def recover(self) -> bool:
        """Run startup recovery: reconcile state after a crash.

        Kills and removes all managed containers, reconciles metadata
        with on-disk state, adopts or restores library pools left mid-swap
        by a crash (plan §4.5), and refreshes library pool versions.

        Args:
            self: The SandboxManager instance.

        Returns:
            True if recovery succeeded.
        """
        # Step 1: Kill and remove all managed containers
        try:
            managed = await self._backend.listManagedContainers()
            for container in managed:
                try:
                    logger.debug(f"Recovery: killing old container {container.containerId}")
                    await self._backend.killContainer(container.containerId)
                    await self._backend.removeContainer(container.containerId, force=True)
                except Exception as exc:
                    logger.error(f"Failed to reap container {container.containerId}: {exc}")
        except Exception as exc:
            logger.error(f"Failed to list managed containers: {exc}")

        # Step 2: Reconcile metadata with on-disk workspace presence
        try:
            sessions = await self._metadata.loadAllSessions()
            for sessionInfo in sessions:
                workspacePath = Path(sessionInfo.workspacePath)
                if not workspacePath.exists():
                    logger.warning(
                        "Recovery: session %s metadata exists but workspace is missing",
                        sessionInfo.sessionId,
                    )
                    # Clean up orphaned run records before deleting the session
                    runs = await self._metadata.listRunsForSession(sessionInfo.sessionId)
                    for run in runs:
                        try:
                            logger.debug(
                                f"Recovery: deleting orphaned run {run.runId} for session {sessionInfo.sessionId}"
                            )
                            await self._metadata.deleteRun(run.runId)
                        except Exception as exc:
                            logger.warning(
                                "Recovery: failed to delete orphaned run %s for session %s: %s",
                                run.runId,
                                sessionInfo.sessionId,
                                exc,
                            )
                    await self._metadata.deleteSession(sessionInfo.sessionId)
        except Exception as exc:
            logger.error(f"Failed to reconcile sessions: {exc}")

        # Step 2b: Mark stale RUNNING runs as FAILED
        try:
            sessions = await self._metadata.loadAllSessions()
            for sessionInfo in sessions:
                runs = await self._metadata.listRunsForSession(sessionInfo.sessionId)
                for run in runs:
                    if run.status == RunStatus.RUNNING:
                        run.status = RunStatus.FAILED
                        run.finishedAt = datetime.now(timezone.utc)
                        run.exitCode = -1
                        await self._metadata.saveRun(run)
                        logger.info("Recovery: marked stale run %s as FAILED", run.runId)
        except Exception as exc:
            logger.error("Failed to reconcile stale runs: %s", exc)

        # Step 3: Adopt or restore pools left mid-swap by a hard crash
        # (docs/plans/sandbox-update-v1.md §4.5), then refresh the recovered
        # pool — both under the runtime's pool lock so a concurrent install/
        # update holder wins instead of racing the adoption (its result would
        # otherwise be reported failed and stale metadata could win).
        # Acquisition is non-blocking: when a holder is active, recovery
        # defers to a later tick and the crash leftovers stay untouched.
        # Reconciliation is tracked per runtime — a runtime whose pool could
        # not be reconciled is skipped by steps 4 and 5 (fail closed):
        # preparing it would create an empty libs dir over the leftovers and
        # the staging-GC pass could reap them beyond retention, destroying
        # the only recoverable copies.
        reconciledRuntimes: set[RuntimeName] = set()
        for name in self._runtimes.keys():
            if await self._reconcileRuntimePool(name, refreshMetadata=True):
                reconciledRuntimes.add(name)
            else:
                logger.error(
                    "Recovery: pool reconciliation failed for %s; skipping prepare/refresh/staging-GC for it "
                    "(crash leftovers stay retryable)",
                    name.value,
                )

        # Step 4: Ensure images for the runtimes whose pool reconciled
        # cleanly. The package-list refresh for a recovered pool already
        # happened inside the locked reconciliation above.
        for name in self._runtimes.keys():
            if name not in reconciledRuntimes:
                continue
            try:
                await self.prepareRuntime(name)
            except Exception as exc:
                logger.error(f"Failed to prepare runtime {name.value}: {exc}")

        # Step 5: Collect garbage — with the staging-artifact pass skipped
        # when any runtime failed reconciliation: its crash leftovers may
        # already be older than retention, and reaping them this tick would
        # destroy the only recoverable pool copies.
        allReconciled = len(reconciledRuntimes) == len(self._runtimes)
        gcRet = await self.collectGarbage(includeStaging=allReconciled)
        for errMsg in gcRet.errors:
            logger.error(errMsg)

        return True

    def _recoverRuntimePool(self, runtime: RuntimeName) -> None:
        """Adopt or restore a runtime pool left mid-swap by a hard crash (plan §4.5).

        The staged-install swap is two renames; a crash between them leaves
        NO pool at the ``libs`` path. A ``newpool`` is adopted ONLY when its
        sibling ``oldpool`` exists in the same run dir: the first swap
        rename (libs → oldpool) happens strictly after the merge completed,
        so both-present proves the newpool is a complete post-merge copy,
        and adopting it completes the interrupted update. A newpool WITHOUT
        oldpool is uncommitted staging debris (a crash before or during
        copy/merge) — never adopted, left for the staging GC pass;
        otherwise a surviving ``oldpool`` restores the pre-update pool;
        neither means a fresh pool and nothing to do.

        An existing but EMPTY ``libs`` directory does not suppress recovery
        when an actionable leftover exists: ``prepareRuntime``, an install,
        or an early sandbox run can create one before the first recovery
        tick, so it is removed before adopting/restoring a complete copy.
        With newpool-only debris present, the empty ``libs`` stays (the
        debris is garbage, not a recoverable pool). A non-empty ``libs`` is
        a live pool and always wins — its staging leftovers are GC debris.
        When newpool adoption fails, oldpool restoration is attempted as a
        fallback (each attempt guarded); if every attempted rename fails,
        the last error is re-raised so callers fail closed and the
        leftovers stay retryable. The pool lock file lives OUTSIDE the
        swapped directory (plan §4.4) and is unaffected. Staging leftovers
        not adopted here are reaped by the staging GC pass by age (backstop).

        Args:
            self: The SandboxManager instance.
            runtime: The runtime whose pool to reconcile.

        Raises:
            OSError: If pool adoption/restoration was attempted and every
                attempt failed; the crash leftovers are left intact.
        """
        poolDir = Path(self._config.storage.rootDir) / "runtimes" / runtime.value
        libsDir = poolDir / "libs"
        if not self._tmpDir.is_dir():
            return

        # Collect candidate crash leftovers: (mtime, kind, newPoolDir,
        # oldPoolDir, runDir). A newpool is an adoption candidate ONLY when
        # its sibling oldpool exists too (both-present proves the swap began,
        # hence the merge was complete by the ordering guarantee); a
        # newpool-only run dir is uncommitted staging garbage and is skipped.
        # Oldpool-only run dirs are restoration candidates. When newpool
        # adoption fails, the SIBLING oldpool in the same run dir is the
        # restoration fallback, so both are tracked. Both-present candidates
        # sort before oldpool-only ones (a surviving merged copy always
        # wins), newest mtime first within a kind.
        candidates: list[tuple[float, int, Path | None, Path | None, Path]] = []
        for entry in self._tmpDir.iterdir():
            if not entry.is_dir():
                continue
            newPoolDir = entry / "newpool"
            oldPoolDir = entry / "oldpool"
            try:
                if newPoolDir.is_dir() and oldPoolDir.is_dir():
                    candidates.append((newPoolDir.stat().st_mtime, 0, newPoolDir, oldPoolDir, entry))
                elif oldPoolDir.is_dir():
                    candidates.append((oldPoolDir.stat().st_mtime, 1, None, oldPoolDir, entry))
                # A newpool-only (or empty) run dir: crash before the swap
                # began — uncommitted staging garbage, deliberately NOT an
                # adoption candidate; the staging GC reaps it by age.
            except OSError as exc:
                logger.warning("Recovery: cannot inspect staging candidate %s: %s", entry, exc)
                continue

        if libsDir.exists() and any(libsDir.iterdir()):
            # A non-empty live pool wins; leftovers are GC debris.
            return

        if not candidates:
            # No actionable crash leftovers: an absent libs is a fresh pool;
            # an existing (empty) one stays — newpool-only debris must not
            # trigger adoption away from it.
            return

        if libsDir.exists():
            # An empty libs dir (e.g. pre-created by prepareRuntime, an
            # early request, or an install before this recovery tick) must
            # not suppress adoption of the complete copies below. Reached
            # only with an actionable candidate (both-present or oldpool).
            libsDir.rmdir()

        candidates.sort(key=lambda candidate: (candidate[1], -candidate[0]))
        _, _, newPoolDir, oldPoolDir, runDir = candidates[0]

        failures: list[OSError] = []
        if newPoolDir is not None:
            # Case 1: adopt the newest complete copy — the interrupted
            # update finished its merge, so this completes it.
            try:
                poolDir.mkdir(parents=True, exist_ok=True)
                newPoolDir.rename(libsDir)
            except OSError as exc:
                logger.error(
                    "Recovery: newpool adoption failed for %s (%s); falling back to oldpool restoration",
                    runtime.value,
                    exc,
                )
                failures.append(exc)
            else:
                logger.warning(
                    "Recovery: adopted staging pool %s as %s for %s (interrupted staged install)",
                    newPoolDir,
                    libsDir,
                    runtime.value,
                )
                # The sibling oldpool (inside the run dir) is debris now.
                shutil.rmtree(runDir, ignore_errors=True)
                return
        if oldPoolDir is not None:
            # Case 2: restore the pre-update pool — either the only survivor
            # or the fallback after the newpool adoption failed above (the
            # sibling copy inside the same run dir).
            try:
                poolDir.mkdir(parents=True, exist_ok=True)
                oldPoolDir.rename(libsDir)
            except OSError as exc:
                logger.error(
                    "Recovery: oldpool restoration failed for %s (%s); leftovers stay retryable",
                    runtime.value,
                    exc,
                )
                failures.append(exc)
            else:
                logger.warning(
                    "Recovery: restored pre-update pool %s as %s for %s",
                    oldPoolDir,
                    libsDir,
                    runtime.value,
                )
                shutil.rmtree(runDir, ignore_errors=True)
                return
        if failures:
            # Every attempted rename failed: surface the failure so the
            # caller skips refresh/staging-GC for this runtime (fail closed)
            # instead of treating the hole as an accepted empty pool.
            raise failures[-1]

    def _hasPoolCrashLeftovers(self) -> bool:
        """Check whether any staging run dir still holds unadopted pool copies.

        Cheap read-only mirror of the candidate scan in
        :meth:`_recoverRuntimePool`: a directory under ``<root>/tmp/`` carrying
        a ``newpool`` or ``oldpool`` subdirectory is a crash-leftover
        candidate. Used by the update-all empty-find guard to distinguish the
        normal fresh/empty pool from a pool that looks empty because the swap
        copies are stranded in staging.

        Args:
            self: The SandboxManager instance.

        Returns:
            True when at least one crash-leftover candidate exists under tmp/.
        """
        if not self._tmpDir.is_dir():
            return False
        for entry in self._tmpDir.iterdir():
            if not entry.is_dir():
                continue
            if (entry / "newpool").is_dir() or (entry / "oldpool").is_dir():
                return True
        return False

    async def _reconcileRuntimePool(self, runtime: RuntimeName, *, refreshMetadata: bool) -> bool:
        """Run crash recovery for one runtime's pool under a non-blocking pool lock.

        Wraps :meth:`_recoverRuntimePool` in the runtime's pool lock (the
        lock file lives outside the swapped directory, plan §4.4, so the
        adoption cannot race a lock holder's mutations). With
        ``refreshMetadata`` the package list is refreshed inside the same
        critical section, so a recovered pool is immediately reflected in
        ``packages.json`` and stale metadata cannot win over a lock holder.

        The lock acquisition is non-blocking: when another process holds the
        pool lock, recovery is deferred (False) and the crash leftovers stay
        untouched and retryable — callers must not block startup on lock
        contention. Any reconciliation failure also yields False so callers
        can fail closed (skip preparation, refresh, and staging GC for this
        runtime).

        Args:
            self: The SandboxManager instance.
            runtime: The runtime whose pool to reconcile.
            refreshMetadata: When True, refresh packages.json after a
                successful reconciliation (or for an existing live pool).

        Returns:
            True when the pool is reconciled (or had nothing to do); False
            when the pool lock was busy or reconciliation failed.
        """
        poolDir = Path(self._config.storage.rootDir) / "runtimes" / runtime.value
        libsDir = poolDir / "libs"
        try:
            async with locks.poolLock(runtime, poolDir):
                self._recoverRuntimePool(runtime)
                if refreshMetadata and libsDir.exists():
                    await self._refreshPackageList(runtime, libsDir)
                return True
        except LibraryPoolLocked:
            logger.info("Recovery: pool lock busy for %s; deferring pool recovery to a later tick", runtime.value)
            return False
        except Exception as exc:
            logger.error("Recovery: pool reconciliation failed for %s: %s", runtime.value, exc)
            return False

    async def collectGarbage(self, *, includeStaging: bool = True) -> GcResult:
        """Run garbage collection on all sandbox resources.

        Removes expired sessions, orphan workspace directories, stale run
        records, and orphan containers; optionally also stale staging
        artifacts under ``<root>/tmp``.

        Args:
            self: The SandboxManager instance.
            includeStaging: When False, the staging-artifact pass under
                ``<root>/tmp`` is skipped. Recovery uses this to keep a
                failed runtime's crash leftovers retryable — they may
                already be older than retention and reaping them would
                destroy the only recoverable pool copies.

        Returns:
            GcResult with counts of removed items and any errors.
        """
        if not self._config.gc.enabled:
            logger.debug("GC is disabled in config")
            return GcResult(
                removedContainers=0,
                removedSessions=0,
                removedRuns=0,
                removedOrphans=0,
                errors=["GC disabled by configuration"],
            )

        containers, sessions, runs, orphans, errors = await self._gc.collectAll(includeStaging=includeStaging)
        return GcResult(
            removedContainers=containers,
            removedSessions=sessions,
            removedRuns=runs,
            removedOrphans=orphans,
            errors=errors,
        )

    # ---- Library pool helpers ----

    def _enumeratePoolVersions(self, libsDir: Path) -> dict[str, str]:
        """Snapshot installed versions by enumerating the pool's dist-infos.

        Host-side dist-info enumeration is the diff baseline and the
        already-current comparison source (plan §5.1); ``packages.json`` is
        derived metadata and no longer the diff source.

        Args:
            self: The SandboxManager instance.
            libsDir: The library pool directory to enumerate.

        Returns:
            Mapping from canonical package name (PEP 503) to version (first
            entry when legacy duplicate installs exist); empty when the pool
            directory does not exist yet.
        """
        if not libsDir.is_dir():
            return {}
        versions: dict[str, str] = {}
        for canonicalName, entries in enumerateDistInfos(libsDir).items():
            if entries:
                versions[canonicalName] = entries[0].version
        return versions

    def _collectDuplicatePoolNames(self, libsDir: Path) -> set[str]:
        """Find pool names carrying MULTIPLE dist-info entries (duplicate installs).

        Used by the pre-filter: a duplicated name is always forced into the
        outdated set because the pip report can match at most one of its
        dist-infos, and only a staged merge removes every old dist-info
        (healing the duplicates, plan §9).

        Args:
            self: The SandboxManager instance.
            libsDir: The library pool directory to enumerate.

        Returns:
            Set of canonical names with more than one dist-info entry; empty
            when the pool directory cannot be enumerated.
        """
        if not libsDir.is_dir():
            return set()
        try:
            inventory = enumerateDistInfos(libsDir)
        except OSError as exc:
            logger.warning("update: cannot enumerate pool duplicates for %s: %s", libsDir, exc)
            return set()
        return {canonicalName for canonicalName, entries in inventory.items() if len(entries) > 1}

    async def _collectUpdateAllNames(self, runtime: RuntimeName, libsDir: Path) -> set[str]:
        """Build the update-all name set: pool enumeration ∪ packages.json (plan §6).

        The union self-heals drift in both directions: pool-only packages get
        updated; packages.json-only phantoms have no pool version, fail the
        already-current comparison, and are reinstalled. Every name is
        grammar-validated before entering any argv — hostile or corrupted
        names are skipped with a warning, never handed to pip.

        Args:
            self: The SandboxManager instance.
            runtime: The runtime whose pool to update.
            libsDir: The library pool directory.

        Returns:
            Set of valid canonical package names to hand to the pre-filter.
        """
        names: set[str] = set()
        if libsDir.is_dir():
            for canonicalName in enumerateDistInfos(libsDir):
                if isValidCanonicalName(canonicalName):
                    names.add(canonicalName)
                else:
                    logger.warning("update-all: skipping pool name failing the grammar check: %r", canonicalName)
        try:
            packagesInfo = await self.listRuntimeLibraries(runtime)
        except Exception as exc:
            logger.warning(
                "update-all: cannot read packages.json for %s (%s); using enumeration only",
                runtime.value,
                exc,
            )
            packagesInfo = []
        for packageInfo in packagesInfo:
            canonicalName = canonicalize_name(packageInfo.name)
            if isValidCanonicalName(canonicalName):
                names.add(canonicalName)
            else:
                logger.warning("update-all: skipping packages.json name failing the grammar check: %r", canonicalName)
        return names

    def _stagingLimits(self, runtimeImpl: Runtime, timeoutSeconds: int | None) -> ResourceLimits:
        """Build the resource limits shared by both update containers.

        Args:
            self: The SandboxManager instance.
            runtimeImpl: The runtime providing the install-container config.
            timeoutSeconds: Timeout override; None falls back to the runtime's
                ``install-container.timeout-seconds`` config value.

        Returns:
            ResourceLimits for a staging container (pre-filter or stage).
        """
        updateContainerConfig = runtimeImpl._config.installContainer
        defaultLimits = self._config.limits
        return ResourceLimits(
            memoryMb=updateContainerConfig.memoryMb,
            # Set equal to memoryMb to disable swap (Docker MemorySwap == total limit)
            memorySwapMb=updateContainerConfig.memoryMb,
            cpuCount=defaultLimits.cpuCount,
            pidsLimit=updateContainerConfig.pidsLimit,
            timeoutSeconds=(timeoutSeconds if timeoutSeconds is not None else updateContainerConfig.timeoutSeconds),
            timeoutGraceSeconds=60,
        )

    def _stagingMounts(self, runtimeImpl: Runtime, runDir: Path) -> list[dict[str, str]]:
        """Build the mounts shared by both update containers (plan §4.2).

        Only the run dir's container I/O subtree (``<runDir>/io``) is mounted
        read-write, plus the helper script read-only. The rest of the run dir
        — ``newpool`` and ``oldpool`` in particular — is never visible to a
        container: package build code must not be able to modify the future
        live pool copy and bypass the controlled merge. The live pool itself
        is NEVER mounted into a networked container — pip (the attack surface
        touching PyPI) only ever sees a scratch delta.

        Args:
            self: The SandboxManager instance.
            runtimeImpl: The runtime providing the container-side paths.
            runDir: Host-side per-run staging directory (must already contain
                the ``io/`` subtree).

        Returns:
            Mount list for the ContainerSpec.
        """
        return [
            {
                "hostPath": str((runDir / STAGING_IO_DIRNAME).absolute()),
                "containerPath": runtimeImpl.STAGING_CONTAINER_PATH,
                "mode": "rw",
            },
            {
                "hostPath": str(runtimeImpl.updateHelperHostPath().absolute()),
                "containerPath": runtimeImpl.UPDATE_HELPER_CONTAINER_PATH,
                "mode": "ro",
            },
        ]

    async def _runPrefilterContainer(
        self,
        runtime: RuntimeName,
        runtimeImpl: Runtime,
        specs: Sequence[str],
        baselineVersions: dict[str, str],
        duplicateNames: set[str],
        timeoutSeconds: int | None,
    ) -> tuple[list[str], list[str]]:
        """Run the read-only dry-run pre-filter container (plan §4.1 step 1).

        Runs BEFORE the pool lock; the live pool is not mounted. The pip
        report is parsed host-side and split fail-safe: an unparseable report
        treats every spec as outdated (full stage, plan §4.2), and names with
        multiple dist-info entries are always staged so the merge heals the
        duplicates. The container is labeled with its staging run id and
        removed best-effort on every path — the keep-container post-mortem
        contract applies to the stage container only.

        Args:
            self: The SandboxManager instance.
            runtime: The runtime whose pool to update.
            runtimeImpl: The runtime implementation.
            specs: Specs to resolve (named specs, or the sorted update-all
                name set).
            baselineVersions: Canonical name → version enumerated from the pool.
            duplicateNames: Canonical names with multiple dist-info entries;
                forced into the outdated set.
            timeoutSeconds: Timeout override; None falls back to config.

        Returns:
            Tuple of (outdatedSpecs, upToDateSpecs).
        """
        runId = uuid.uuid4().hex
        runDir = self._tmpDir / runId
        try:
            runDir.mkdir(parents=True, exist_ok=True)
            # The container's rw mount is scoped to this io/ subtree only.
            (runDir / STAGING_IO_DIRNAME).mkdir(exist_ok=True)
            outcome = await self._backend.runOneshot(
                spec=ContainerSpec(
                    name=f"sandbox-update-{runId}",
                    image=runtimeImpl._config.installImageTag,
                    command=runtimeImpl.reportCommand(list(specs)),
                    mounts=self._stagingMounts(runtimeImpl, runDir),
                    env={},
                    limits=self._stagingLimits(runtimeImpl, timeoutSeconds),
                    network="bridge",  # pip needs internet
                    user=self._config.security.user,
                    readOnlyRoot=False,  # update containers need writable temp dirs
                    capDrop=list(self._config.security.dropCapabilities),
                    securityOpt=["no-new-privileges"] if self._config.security.noNewPrivileges else [],
                    labels={
                        "sandbox.managed": "true",
                        "sandbox.purpose": "update",
                        "sandbox.runtime": runtime.value,
                        # Liveness marker for container GC: while this dir
                        # exists under tmp/, the container is a legitimate
                        # in-flight update container, not an orphan.
                        "sandbox.stagingRunId": runId,
                    },
                )
            )
            try:
                await self._backend.removeContainer(outcome.containerId)
            except Exception as exc:
                logger.error("Failed to remove update pre-filter container %s: %s", outcome.containerId, exc)
            report = parsePipReport(runDir / STAGING_IO_DIRNAME / "report.json")
            return _splitOutdatedSpecs(specs, baselineVersions, report, duplicateNames)
        finally:
            shutil.rmtree(runDir, ignore_errors=True)

    async def _runStagedInstall(
        self,
        runtime: RuntimeName,
        runtimeImpl: Runtime,
        specs: Sequence[str],
        timeoutSeconds: int | None,
        *,
        purpose: str,
    ) -> tuple[bool, str | None]:
        """Run the shared staged-install core: copy → stage → merge → swap.

        Implements docs/plans/sandbox-update-v1.md §4.1 steps 3-6 plus the
        run-dir cleanup of step 7. pip never writes the live pool: the pool
        is copied host-side on the same filesystem, pip stages into a private
        delta inside a container that does NOT mount the pool (containers see
        only the run dir's ``io/`` subtree — ``newpool``/``oldpool`` are
        outside every mount), the delta is merged into the copy, and the copy
        replaces the pool via two atomic renames with inline rollback. The
        renames start only after the merge completed, so a surviving
        ``newpool`` is always a complete pool (crash-window adoption
        contract, plan §4.5). Shared with installRuntimeLibraries from Phase
        1I on.

        If the swap's second rename AND its inline rollback both fail, the
        run dir is deliberately NOT cleaned up: ``libs`` is absent and the
        only complete copies survive inside it, so startup recovery can adopt
        one ("no holes, ever"); the failure is re-raised as
        ``PoolSwapRollbackFailed`` after logging.

        Args:
            self: The SandboxManager instance.
            runtime: The runtime whose pool to mutate.
            runtimeImpl: The runtime implementation.
            specs: Validated specs to install into the staging delta.
            timeoutSeconds: Timeout override for the stage container; None
                falls back to the runtime's ``install-container.timeout-seconds``
                config value.
            purpose: Value for the ``sandbox.purpose`` container label and the
                container-name prefix (``"update"`` today, ``"install"`` from
                Phase 1I on).

        Returns:
            Tuple of (success, keptContainerId): success is True when the
            swap completed; keptContainerId is set only on stage failure —
            the container is kept for ``docker logs`` post-mortem and the
            pool is untouched.

        Raises:
            ConfigError: If the helper script is missing on the host, or the
                staging area is on a different filesystem than the pool.
            LibraryInstallFailed: If the staged delta is malformed or unsafe to merge.
            PoolSwapRollbackFailed: If the swap and its inline rollback both
                failed; the run dir is preserved for recovery.
        """
        if not specs:
            return (True, None)

        # Pre-check the helper file-bind: a missing file-bind silently
        # becomes a directory in Docker.
        helperPath = runtimeImpl.updateHelperHostPath()
        if not helperPath.is_file():
            raise ConfigError(
                f"Update helper script not found on host: {helperPath} (expected next to the install Dockerfile)"
            )

        poolDir = Path(self._config.storage.rootDir) / "runtimes" / runtime.value
        libsDir = poolDir / "libs"
        libsDir.mkdir(parents=True, exist_ok=True)

        runId = uuid.uuid4().hex
        runDir = self._tmpDir / runId
        rollbackFailed = False
        try:
            runDir.mkdir(parents=True, exist_ok=True)
            # Container I/O subtree: the ONLY part of the run dir the stage
            # container sees. newpool below stays outside every mount, so
            # package build code cannot modify the future live pool.
            ioDir = runDir / STAGING_IO_DIRNAME
            ioDir.mkdir(exist_ok=True)

            # Step 3 (copy): private same-filesystem copy, before any
            # container runs; requires ~2× pool disk headroom briefly.
            newPoolDir = runDir / "newpool"
            shutil.copytree(libsDir, newPoolDir, symlinks=True)

            # Step 4 (stage): pip writes into the private delta; the live
            # pool is not mounted into the container at all.
            outcome = await self._backend.runOneshot(
                spec=ContainerSpec(
                    name=f"sandbox-{purpose}-{runId}",
                    image=runtimeImpl._config.installImageTag,
                    command=runtimeImpl.stageInstallCommand(list(specs)),
                    mounts=self._stagingMounts(runtimeImpl, runDir),
                    env={},
                    limits=self._stagingLimits(runtimeImpl, timeoutSeconds),
                    network="bridge",  # pip needs internet
                    user=self._config.security.user,
                    readOnlyRoot=False,  # update containers need writable temp dirs
                    capDrop=list(self._config.security.dropCapabilities),
                    securityOpt=["no-new-privileges"] if self._config.security.noNewPrivileges else [],
                    labels={
                        "sandbox.managed": "true",
                        "sandbox.purpose": purpose,
                        "sandbox.runtime": runtime.value,
                        # Liveness marker for container GC: while this dir
                        # exists under tmp/, the container is a legitimate
                        # in-flight stage container, not an orphan. A failed
                        # (kept, post-mortem) container's run dir is removed
                        # on return, so it stays reapable.
                        "sandbox.stagingRunId": runId,
                    },
                )
            )

            stageOk = not outcome.oomKilled and outcome.signal is None and outcome.exitCode == 0
            if not stageOk:
                # Keep the failed stage container for post-mortem log
                # inspection (docker logs <containerId>); GC reaps it per
                # orphan-container-retention-minutes. The pool is untouched.
                logger.warning(
                    "Staged install failed; keeping container %s for inspection (docker logs %s)",
                    outcome.containerId,
                    outcome.containerId,
                )
                return (False, outcome.containerId)
            # Best-effort removal of the stage container (runOneshot
            # contract: the caller removes the container after collecting
            # the outcome).
            try:
                await self._backend.removeContainer(outcome.containerId)
            except Exception as exc:
                logger.error("Failed to remove staged-install container %s: %s", outcome.containerId, exc)

            # Step 5 (merge): host-side, on the private copy — never the
            # live pool.
            deltaDir = ioDir / "delta"
            deltaDir.mkdir(exist_ok=True)  # defensive: an absent delta merges as a no-op
            mergeStagedDelta(newPoolDir, deltaDir)

            # Step 6 (swap): two renames with inline rollback; raises
            # ConfigError when staging landed on a different filesystem
            # than the pool (plan §4.6), and PoolSwapRollbackFailed when
            # the rollback itself fails too.
            try:
                swapPools(libsDir, newPoolDir, runDir / "oldpool")
            except PoolSwapRollbackFailed as exc:
                rollbackFailed = True
                logger.error(
                    "Staged install %s: %s Preserving run dir %s for startup recovery.",
                    runId,
                    exc,
                    runDir,
                )
                raise
            return (True, None)
        finally:
            if not rollbackFailed:
                # Best-effort run-dir cleanup; crash leftovers are GC-reaped
                # (plan §4.6). A rollback-failed run dir is deliberately
                # preserved: `libs` is absent and oldpool+newpool inside it
                # are the only complete copies — recovery must be able to
                # adopt one ("no holes, ever", plan §4.5).
                shutil.rmtree(runDir, ignore_errors=True)

    async def _validatePackageSpec(self, spec: str, *, runtime: RuntimeName) -> None:
        """Validate a package spec for install.

        Rejects specs containing shell metacharacters or starting with '-'.

        Args:
            self: The SandboxManager instance.
            spec: The package spec string.
            runtime: The runtime to validate against.

        Raises:
            InvalidPackageSpec: If the spec is invalid.
        """
        # Reject shell metacharacters
        dangerous = {"&", "|", ";", "`", "$(", "\n", "\r"}
        for char in dangerous:
            if char in spec:
                raise InvalidPackageSpec(spec=spec, reason=f"Contains shell metacharacter: {repr(char)}")
        # Reject flag-like specs
        if spec.startswith("-"):
            raise InvalidPackageSpec(spec=spec, reason="Spec starts with '-'")

        if runtime in self._runtimes:
            await self._runtimes[runtime].validatePackageSpec(spec)

    async def _refreshPackageList(
        self,
        runtime: RuntimeName,
        libsDir: Path,
    ) -> bool:
        """Refresh the installed package list by launching a container.

        Launches a one-shot container using the runtime's list command to query
        installed packages, writes packages.json, and updates the runtime record.

        Args:
            self: The SandboxManager instance.
            runtime: The runtime name.
            libsDir: Path to the library pool directory (mounted into the container).

        Returns:
            True if the package list was successfully refreshed. Returns False if the
            runtime does not exist, if container execution fails (non-zero exit code,
            killed by a signal, or OOM), or if an error occurs — in failure cases the
            existing packages.json metadata is preserved untouched.
        """
        runtimeImpl = self._runtimes.get(runtime)
        if runtimeImpl is None:
            return False

        runId = str(uuid.uuid4())
        stdoutFilename = f"{runId}.stdout"
        stderrFilename = f"{runId}.stderr"
        installContainerConfig = runtimeImpl._config.installContainer
        defaultLimits = self._config.limits

        outcome = await self._backend.runOneshot(
            spec=ContainerSpec(
                name=f"sandbox-list-{uuid.uuid4().hex}",
                image=runtimeImpl._config.installImageTag,
                command=runtimeImpl.listCommand(
                    stdoutPath=f"/data/{stdoutFilename}",
                    stderrPath=f"/data/{stderrFilename}",
                ),
                mounts=[
                    {
                        "hostPath": str(libsDir.absolute()),
                        "containerPath": runtimeImpl._config.libMountPath,
                        "mode": "rw",
                    },
                    {
                        "hostPath": str(self._tmpDir.absolute()),
                        "containerPath": "/data",
                        "mode": "rw",
                    },
                ],
                env={},
                limits=ResourceLimits(
                    memoryMb=installContainerConfig.memoryMb,
                    # Set equal to memoryMb to disable swap (Docker MemorySwap == total limit)
                    memorySwapMb=installContainerConfig.memoryMb,
                    cpuCount=defaultLimits.cpuCount,
                    pidsLimit=installContainerConfig.pidsLimit,
                    timeoutSeconds=300,
                    timeoutGraceSeconds=60,
                ),
                network="bridge",  # install needs internet
                user=self._config.security.user,
                readOnlyRoot=False,  # install containers need writable temp dirs
                capDrop=list(self._config.security.dropCapabilities),
                securityOpt=["no-new-privileges"] if self._config.security.noNewPrivileges else [],
                labels={
                    "sandbox.managed": "true",
                    "sandbox.purpose": "list",
                    "sandbox.runtime": runtime.value,
                },
            )
        )

        stdoutPath = self._tmpDir / stdoutFilename
        stderrPath = self._tmpDir / stderrFilename
        stdoutStr = stdoutPath.read_text() if stdoutPath.exists() else ""
        stderrStr = stderrPath.read_text() if stderrPath.exists() else ""

        # A failed (or timed-out / OOM-killed) list container must never be
        # mistaken for an empty pool: its empty or partial stdout would
        # overwrite packages.json and make every previous package look
        # vanished. On failure, clean up and preserve the existing metadata.
        refreshOk = outcome.exitCode == 0 and outcome.signal is None and not outcome.oomKilled
        if not refreshOk:
            logger.warning(
                "Package list refresh failed for %s (exitCode=%s, signal=%s, oomKilled=%s); "
                "preserving existing package metadata",
                runtime.value,
                outcome.exitCode,
                outcome.signal,
                outcome.oomKilled,
            )

        try:
            await self._backend.removeContainer(outcome.containerId)
        except Exception as exc:
            logger.error("Failed to remove list container %s: %s", outcome.containerId, exc)
        stdoutPath.unlink(missing_ok=True)
        stderrPath.unlink(missing_ok=True)

        if not refreshOk:
            return False

        packages = runtimeImpl.parseListCommandOutput(outcome=outcome, stdout=stdoutStr, stderr=stderrStr)
        await self._metadata.savePackagesInfo(runtime=runtime, packagesInfo=packages)
        logger.debug(f"Refreshed package list for {runtime.value}: {packages}")
        # logger.debug(f"outcome: {outcome}")
        # logger.debug(f"stdout: {stdoutStr}")
        # logger.debug(f"stderr: {stderrStr}")
        return True
