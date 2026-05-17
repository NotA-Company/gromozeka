"""Singleton manager for sandboxed code execution.

Composes one Backend with N Runtimes and one MetadataStore.
Owns the per-session lock registry and the GC loop.

Access via ``SandboxManager.getInstance()`` after calling ``injectConfig()``.
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Literal, Sequence, cast

from .backends.base import ContainerOutcome, ContainerSpec
from .backends.docker import DockerBackend
from .config import PythonRuntimeConfig, SandboxConfig
from .enums import RuntimeName
from .errors import (
    ImageBuildFailed,
    InvalidPackageSpec,
    MissingDependenciesError,
    SessionBusy,
    SessionDropped,
    SessionNotFound,
    UnknownRuntime,
)
from .gc import GarbageCollector
from .locks import GlobalRunLimiter, SessionLockRegistry, acquirePoolLock, releasePoolLock
from .metadata.base import RunRecord, RuntimeRecord, SessionRecord
from .metadata.filesystem import FilesystemMetadataStore
from .runtimes.python import PythonRuntime
from .storage import atomicWriteJson, ensureDirectoryLayout, resolveWorkspacePath, sessionHash
from .types import (
    DropSessionResult,
    FileContent,
    FileInfo,
    GcResult,
    HealthcheckResult,
    InputFile,
    LibraryInstallResult,
    LibraryRemoveResult,
    NetworkPolicy,
    PackageInfo,
    RecoveryResult,
    ResourceLimits,
    RunInfo,
    RunResult,
    RuntimeInfo,
    SessionInfo,
    SessionUsage,
    ShutdownResult,
)

logger = logging.getLogger(__name__)


class SandboxManager:
    """Singleton manager for sandboxed code execution.

    Composes one Backend with N Runtimes and one MetadataStore.
    Owns the per-session lock registry and the GC loop.

    Access via SandboxManager.getInstance() after calling injectConfig().
    """

    _instance: "SandboxManager | None" = None
    _lock = RLock()
    _configInstance: SandboxConfig | None = None

    def __new__(cls) -> "SandboxManager":
        """Create or return the singleton instance.

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

        Returns:
            The singleton SandboxManager instance.

        Raises:
            RuntimeError: If injectConfig() has not been called before getInstance().
        """
        if cls._instance is None:
            return cls()
        return cls._instance

    def __init__(self) -> None:
        """Initialise the sandbox manager.

        Only the first call executes; subsequent calls are guarded by the
        hasattr(self, 'initialized') sentinel.

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

        rootDir = Path(config.storage.rootDir)
        tmpDir = rootDir / "tmp"

        # Initialize metadata store (filesystem-backed)
        self._metadata = FilesystemMetadataStore(rootDir=rootDir, tmpDir=tmpDir)

        # Initialize lock registry
        self._lockRegistry = SessionLockRegistry(config.concurrency)

        # Initialize global run limiter
        self._globalLimiter = GlobalRunLimiter(
            maxConcurrent=config.concurrency.maxConcurrentRunsGlobal,
            waitSeconds=config.concurrency.globalQueueWaitSeconds,
        )

        # Initialize backend (Docker)
        dockerConfig = config.backend.docker
        self._backend = DockerBackend(dockerConfig)

        # Initialize runtimes
        self._runtimes: Dict[RuntimeName, Any] = {}
        if RuntimeName.PYTHON in config.runtimes:
            pythonConfig = config.runtimes[RuntimeName.PYTHON]
            self._runtimes[RuntimeName.PYTHON] = PythonRuntime(pythonConfig)

        # Initialize garbage collector
        self._gc = GarbageCollector(
            config=config.gc,
            metadataStore=self._metadata,
            rootDir=rootDir,
            backend=self._backend,
        )

        self._gcTask: asyncio.Task | None = None

        logger.info("SandboxManager initialized with rootDir=%s", rootDir)

    @classmethod
    def injectConfig(cls, config: SandboxConfig | Dict[str, Any]) -> None:
        """Inject the sandbox configuration before getInstance().

        Must be called before the first getInstance() call.

        Args:
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
        runtime: RuntimeName = RuntimeName.PYTHON,
        *,
        rebuildImage: bool = False,
    ) -> RuntimeInfo:
        """Ensure the run and install images for a runtime are present.

        Builds images if missing or rebuildImage=True. Creates the library
        pool directory and initializes the runtime metadata record.

        Args:
            runtime: The runtime to prepare.
            rebuildImage: If True, rebuild images even if they exist.

        Returns:
            RuntimeInfo with metadata about the prepared runtime.

        Raises:
            ImageBuildFailed: If image build fails.
        """
        poolDir = Path(self._config.storage.rootDir) / "runtimes" / runtime.value
        libsDir = poolDir / "libs"
        libsDir.mkdir(parents=True, exist_ok=True)

        # Get runtime config
        runtimeConfig = self._config.runtimes.get(runtime)
        if runtimeConfig is None:
            if runtime == RuntimeName.PYTHON:
                runtimeConfig = PythonRuntimeConfig()
            else:
                raise UnknownRuntime(f"Runtime {runtime} is not configured")
        runImageTag = runtimeConfig.runImageTag
        installImageTag = runtimeConfig.installImageTag

        # Attempt to ensure images
        try:
            await self._backend.ensureImage(
                RuntimeInfo(
                    name=runtime,
                    runImageTag=runImageTag,
                    installImageTag=installImageTag,
                    libPoolPath=str(libsDir),
                    libPoolVersion="",
                    packageCount=0,
                ),
                rebuild=rebuildImage,
            )
        except ImageBuildFailed:
            logger.warning("Could not build images for %s, continuing anyway", runtime.value)

        # Initialize runtime record if not exists
        existing = await self._metadata.loadRuntime(runtime)
        if existing is None:
            record = RuntimeRecord(
                runtime=runtime,
                runImageTag=runImageTag,
                installImageTag=installImageTag,
                libPoolPath=str(libsDir),
                libPoolVersion="",
                packageCount=0,
            )
            await self._metadata.saveRuntime(record)

        # Refresh package list
        poolVersion = await self._refreshPackageList(runtime, libsDir)

        return RuntimeInfo(
            name=runtime,
            runImageTag=runImageTag,
            installImageTag=installImageTag,
            libPoolPath=str(libsDir),
            libPoolVersion=poolVersion,
            packageCount=await self._countPackages(runtime),
        )

    async def listRuntimes(self) -> list[RuntimeInfo]:
        """List all known runtimes.

        Returns:
            List of RuntimeInfo for each runtime.
        """
        results: list[RuntimeInfo] = []
        for name in self._runtimes.keys():
            record = await self._metadata.loadRuntime(name)
            if record:
                results.append(
                    RuntimeInfo(
                        name=record.runtime,
                        runImageTag=record.runImageTag,
                        installImageTag=record.installImageTag,
                        libPoolPath=record.libPoolPath,
                        libPoolVersion=record.libPoolVersion,
                        packageCount=record.packageCount,
                    )
                )
        return results

    # ---- Sessions ----

    async def createSession(
        self,
        sessionId: str,
        *,
        runtime: RuntimeName = RuntimeName.PYTHON,
        forceRecreate: bool = False,
        ttlMinutes: int | None = None,
        limits: ResourceLimits | None = None,
        metadata: dict[str, str] | None = None,
    ) -> SessionInfo:
        """Create a new session or return the existing one.

        Idempotent unless forceRecreate=True. Allocates the workspace directory
        and persists the session record. No container is created.

        Args:
            sessionId: Opaque session identifier.
            runtime: The runtime for this session.
            forceRecreate: If True, drop any existing session first.
            ttlMinutes: Session idle TTL in minutes (default from config).
            limits: Resource limits for runs in this session (default from config).
            metadata: Opaque caller-supplied key-value pairs.

        Returns:
            The created or existing SessionInfo.
        """
        # Check existing session
        existing = await self._metadata.loadSession(sessionId)
        if existing is not None:
            if not forceRecreate:
                return self._recordToSessionInfo(existing)
            # forceRecreate: drop and continue
            await self._doDropSession(sessionId, force=True)

        # Compute defaults
        defaults = self._config.defaults
        effectiveTtl = ttlMinutes if ttlMinutes is not None else defaults.idleTtlMinutes
        effectiveLimits = limits if limits is not None else self._config.limits
        effectiveMetadata = metadata if metadata is not None else {}

        now = datetime.now(timezone.utc)
        sHash = sessionHash(sessionId)
        workspacePath = Path(self._config.storage.rootDir) / "sessions" / sHash / "workspace"

        # Create workspace directory
        workspacePath.mkdir(parents=True, exist_ok=True)
        os.chmod(workspacePath, self._config.storage.dirMode)

        record = SessionRecord(
            sessionId=sessionId,
            sessionHash=sHash,
            runtime=runtime,
            workspacePath=str(workspacePath),
            createdAt=now,
            updatedAt=now,
            expiresAt=now + timedelta(minutes=effectiveTtl),
            metadata=effectiveMetadata,
            schemaVersion=1,
        )

        await self._metadata.saveSession(record)
        logger.info("Created session %s (hash=%s, runtime=%s)", sessionId, sHash, runtime.value)

        info = self._recordToSessionInfo(record)
        # TODO: store limits per session (currently using config defaults)
        _ = effectiveLimits  # noqa: F841 — will be used when per-session limits are stored
        return info

    async def getSessionInfo(self, sessionId: str) -> SessionInfo | None:
        """Retrieve metadata for an existing session.

        Args:
            sessionId: Unique identifier of the session.

        Returns:
            SessionInfo if the session exists, otherwise None.
        """
        record = await self._metadata.loadSession(sessionId)
        if record is None:
            return None
        return self._recordToSessionInfo(record)

    async def getSessionUsage(self, sessionId: str) -> SessionUsage:
        """Calculate workspace usage for a session.

        Walks the workspace on disk. Separate from getSessionInfo because
        it's potentially expensive on large workspaces.

        Args:
            sessionId: The session identifier.

        Returns:
            SessionUsage with file count and total size.

        Raises:
            SessionNotFound: If the session doesn't exist.
        """
        record = await self._metadata.loadSession(sessionId)
        if record is None:
            raise SessionNotFound(f"Session {sessionId} not found")

        workspacePath = Path(record.workspacePath)
        fileCount = 0
        totalBytes = 0

        if workspacePath.exists():
            for entry in workspacePath.rglob("*"):
                if entry.is_file():
                    try:
                        totalBytes += entry.stat().st_size
                        fileCount += 1
                    except OSError:
                        pass  # skip files we can't stat

        # Count runs for this session
        runs = await self._metadata.listRunsForSession(sessionId)
        runCount = len(runs)

        return SessionUsage(
            sessionId=sessionId,
            fileCount=fileCount,
            totalBytes=totalBytes,
            runCount=runCount,
            measuredAt=datetime.now(timezone.utc),
        )

    async def listSessions(self, *, runtime: RuntimeName | None = None) -> list[SessionInfo]:
        """List sessions, optionally filtered by runtime.

        Args:
            runtime: If provided, only return sessions using this runtime.

        Returns:
            List of SessionInfo for matching sessions.
        """
        records = await self._metadata.listSessions(runtime=runtime)
        return [self._recordToSessionInfo(r) for r in records]

    async def touchSession(self, sessionId: str, *, ttlMinutes: int | None = None) -> SessionInfo:
        """Refresh a session's last-activity timestamp and optionally extend its TTL.

        Args:
            sessionId: Unique identifier of the session.
            ttlMinutes: Optional override for the new time-to-live in minutes.

        Returns:
            Updated SessionInfo after the touch.

        Raises:
            SessionNotFound: If the session doesn't exist.
        """
        record = await self._metadata.loadSession(sessionId)
        if record is None:
            raise SessionNotFound(f"Session {sessionId} not found")

        defaults = self._config.defaults
        effectiveTtl = ttlMinutes if ttlMinutes is not None else defaults.idleTtlMinutes

        now = datetime.now(timezone.utc)
        record.updatedAt = now
        record.expiresAt = now + timedelta(minutes=effectiveTtl)
        await self._metadata.saveSession(record)
        return self._recordToSessionInfo(record)

    async def dropSession(self, sessionId: str, *, force: bool = False) -> DropSessionResult:
        """Drop (destroy) a sandbox session and clean up its resources.

        Args:
            sessionId: Unique identifier of the session to drop.
            force: If True, cancel active runs and force-remove the session.

        Returns:
            DropSessionResult describing what was cleaned up.
        """
        return await self._doDropSession(sessionId, force=force)

    async def _doDropSession(self, sessionId: str, *, force: bool = False) -> DropSessionResult:
        """Internal drop implementation shared by dropSession and forceRecreate.

        Args:
            sessionId: The session to drop.
            force: If True, force-cancel waiters and bypass the session lock.

        Returns:
            DropSessionResult with cleanup details.
        """
        record = await self._metadata.loadSession(sessionId)
        errors: list[str] = []

        if record is None:
            return DropSessionResult(
                sessionId=sessionId,
                existed=False,
                runsCancelled=0,
                errors=[],
            )

        if force:
            # TODO(Phase 3): Before force-cancelling, kill the running container
            # (if any) via container label lookup. The current implementation
            # allows the holder to run to completion, which is safe in Phase 2
            # (no containers) but will need container killing in Phase 3.
            self._lockRegistry.forceCancel(sessionId)

        try:
            # Acquire session lock to serialise with in-flight runs
            await self._lockRegistry.acquire(sessionId)
        except (SessionBusy, SessionDropped):
            # If force=True, we already cancelled; proceed with cleanup
            if not force:
                raise

        try:
            # Delete workspace directory
            workspacePath = Path(record.workspacePath)
            if workspacePath.exists():
                shutil.rmtree(workspacePath)

            # Delete metadata record
            await self._metadata.deleteSession(sessionId)
        except OSError as exc:
            errors.append(str(exc))
            logger.warning("Error cleaning up session %s: %s", sessionId, exc)
        finally:
            self._lockRegistry.release(sessionId)
            self._lockRegistry.clearCancelled(sessionId)

        return DropSessionResult(
            sessionId=sessionId,
            existed=True,
            runsCancelled=0,  # TODO: track cancelled runs in Phase 3
            errors=errors,
        )

    def _getDefaultImageTag(self, runtime: RuntimeName) -> str:
        """Get the default image tag for a runtime.

        Args:
            runtime: The runtime name.

        Returns:
            The default image tag string.
        """
        if runtime == RuntimeName.PYTHON:
            return "gromozeka-sandbox-python:run"
        return "unknown"

    def _getLibPoolPath(self, runtime: RuntimeName) -> str:
        """Get the library pool directory path for a runtime.

        Args:
            runtime: The runtime name.

        Returns:
            The host path to the library pool.
        """
        return str(Path(self._config.storage.rootDir) / "runtimes" / runtime.value / "libs")

    def _runResultToDict(self, result: RunResult) -> dict:
        """Convert a RunResult to a JSON-serializable dict.

        Args:
            result: The RunResult to serialize.

        Returns:
            A dict with datetime→isoformat, enum→str conversions.
        """
        return {
            "runId": result.runId,
            "sessionId": result.sessionId,
            "runtime": result.runtime.value,
            "stdoutPath": result.stdoutPath,
            "stderrPath": result.stderrPath,
            "stdoutBytes": result.stdoutBytes,
            "stderrBytes": result.stderrBytes,
            "exitCode": result.exitCode,
            "signal": result.signal,
            "timedOut": result.timedOut,
            "oomKilled": result.oomKilled,
            "startedAt": result.startedAt.isoformat(),
            "finishedAt": result.finishedAt.isoformat(),
            "elapsedMs": result.elapsedMs,
            "networkEnabled": result.networkEnabled,
            "libPoolVersion": result.libPoolVersion,
            "error": result.error,
        }

    async def _touchSessionInternal(self, record: SessionRecord) -> None:
        """Bump the session TTL without the full touchSession API overhead.

        Args:
            record: The session record (modified in place).
        """
        now = datetime.now(timezone.utc)
        record.updatedAt = now
        record.expiresAt = now + timedelta(minutes=self._config.defaults.idleTtlMinutes)
        await self._metadata.saveSession(record)

    def _recordToSessionInfo(self, record: SessionRecord) -> SessionInfo:
        """Convert a SessionRecord to the public SessionInfo dataclass.

        Args:
            record: The persisted session record.

        Returns:
            The public SessionInfo.
        """
        return SessionInfo(
            sessionId=record.sessionId,
            runtime=record.runtime,
            workspacePath=record.workspacePath,
            createdAt=record.createdAt,
            updatedAt=record.updatedAt,
            expiresAt=record.expiresAt,
            metadata=record.metadata,
        )

    # ---- Runs ----

    async def runCode(
        self,
        sessionId: str,
        code: str,
        *,
        runtime: RuntimeName = RuntimeName.PYTHON,
        timeoutSeconds: int | None = None,
        requiredPackages: Sequence[str] = (),
        network: NetworkPolicy | None = None,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
        files: Sequence[InputFile] = (),
        limits: ResourceLimits | None = None,
    ) -> RunResult:
        """Execute code in a sandboxed container.

        Auto-creates the session if it doesn't exist. Verifies required
        packages are in the library pool before starting a container.

        Args:
            sessionId: The session identifier.
            code: The Python code to execute.
            runtime: The runtime to use.
            timeoutSeconds: Override for run timeout.
            requiredPackages: Packages that must be in the library pool.
            network: Network policy for this run.
            stdin: Text to feed as stdin.
            env: Additional environment variables.
            files: Input files to write before execution.
            limits: Resource limits for this run.

        Returns:
            RunResult with exit code, output paths, and artifact info.

        Raises:
            MissingDependenciesError: If required packages are not in the pool.
            UnknownRuntime: If the runtime is not available.
            SessionBusy: If the session's queue is full.
            SandboxBusy: If the global concurrency cap is reached.
        """
        effectiveLimits = limits if limits is not None else self._config.limits
        effectiveTimeout = timeoutSeconds if timeoutSeconds is not None else effectiveLimits.timeoutSeconds
        effectiveNetwork = network if network is not None else NetworkPolicy(enabled=False)

        # Validate runtime
        if runtime not in self._runtimes:
            raise UnknownRuntime(f"Runtime {runtime.value} is not available")

        runtimeImpl = self._runtimes[runtime]

        # Step 1: Acquire session lock (FIFO)
        await self._lockRegistry.acquire(sessionId)
        try:
            # Step 2: Acquire global run semaphore
            await self._globalLimiter.acquire()
            try:
                # Step 3: Ensure session exists (auto-create)
                record = await self._metadata.loadSession(sessionId)
                if record is None:
                    await self.createSession(
                        sessionId,
                        runtime=runtime,
                        limits=effectiveLimits,
                    )
                    record = await self._metadata.loadSession(sessionId)
                    if record is None:
                        raise RuntimeError(f"Failed to create session {sessionId}")

                # Step 4: Generate runId
                runId = uuid.uuid4().hex

                # Step 5: Verify required packages
                if requiredPackages:
                    runtimeRecord = await self._metadata.loadRuntime(runtime)
                    if runtimeRecord is None:
                        raise MissingDependenciesError(
                            missing=list(requiredPackages),
                        )
                    installed = await self.listRuntimeLibraries(runtime=runtime)
                    installedNames = {p.name for p in installed}
                    missing = [p for p in requiredPackages if p not in installedNames]
                    if missing:
                        raise MissingDependenciesError(missing=missing)

                # Step 6: Set up run directory
                workspacePath = Path(record.workspacePath)
                # Ensure workspace directory exists (might be missing if tmp_path changed)
                workspacePath.mkdir(parents=True, exist_ok=True)
                runDir = workspacePath / ".run" / runId
                runDir.mkdir(parents=True, exist_ok=True)

                # Step 7: Write main.py
                mainPath = runDir / "main.py"
                mainPath.write_text(code, encoding="utf-8")

                # Write stdin if provided
                hasStdin = stdin is not None
                if hasStdin:
                    stdinPath = runDir / "stdin"
                    stdinPath.write_text(stdin, encoding="utf-8")

                # Write input files
                for f in files:
                    destPath = resolveWorkspacePath(workspacePath, f.path.lstrip("/"))
                    destPath.parent.mkdir(parents=True, exist_ok=True)
                    if isinstance(f.content, str):
                        destPath.write_text(f.content, encoding="utf-8")
                    else:
                        destPath.write_bytes(f.content)

                # Step 8: Build ContainerSpec
                effectiveLimitsWithTimeout = ResourceLimits(
                    memoryMb=effectiveLimits.memoryMb,
                    memorySwapMb=effectiveLimits.memorySwapMb,
                    cpuCount=effectiveLimits.cpuCount,
                    pidsLimit=effectiveLimits.pidsLimit,
                    timeoutSeconds=effectiveTimeout,
                    timeoutGraceSeconds=effectiveLimits.timeoutGraceSeconds,
                )

                command = runtimeImpl.runCommand(
                    runId=runId,
                    hasStdin=hasStdin,
                    limits=effectiveLimitsWithTimeout,
                )

                # Get runtime info for image tag
                runtimeRecord = await self._metadata.loadRuntime(runtime)
                imageTag = runtimeRecord.runImageTag if runtimeRecord else self._getDefaultImageTag(runtime)

                # Get lib pool path
                hostLibPool = self._getLibPoolPath(runtime)

                mounts: list[dict[str, str]] = [
                    {"hostPath": str(workspacePath), "containerPath": "/workspace", "mode": "rw"},
                ]
                if Path(hostLibPool).exists():
                    mounts.append({"hostPath": hostLibPool, "containerPath": "/sandbox/libs", "mode": "ro"})

                # Build env
                containerEnv: dict[str, str] = {}
                if hasattr(runtimeImpl, "_config") and hasattr(runtimeImpl._config, "env"):
                    containerEnv.update(runtimeImpl._config.env)
                if env:
                    containerEnv.update(env)

                # Compute network mode
                networkMode = "bridge" if effectiveNetwork.enabled else "none"

                # Record start time for artifact detection
                startTime = datetime.now(timezone.utc)

                containerSpec = ContainerSpec(
                    name=f"sandbox-{runId}",
                    image=imageTag,
                    command=command,
                    mounts=mounts,
                    env=containerEnv,
                    limits=effectiveLimitsWithTimeout,
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

                # Step 9: Write RunInfo (status="running")
                runRecord = RunRecord(
                    runId=runId,
                    sessionId=sessionId,
                    runtime=runtime,
                    startedAt=startTime,
                    finishedAt=None,
                    status="running",
                    exitCode=None,
                )
                await self._metadata.saveRun(runRecord)

                # Step 10: Run the container and collect results.
                # Wrap in try/except to update RunRecord on failure, and
                # try/finally to always remove the container.
                try:
                    outcome = await self._backend.runOneshot(spec=containerSpec)

                    try:
                        # Step 11: Detect outcome
                        finishedAt = datetime.now(timezone.utc)
                        elapsedMs = int((finishedAt - startTime).total_seconds() * 1000)
                        timedOut = outcome.exitCode == 124
                        oomKilled = outcome.oomKilled

                        # Step 12: Read output sizes
                        stdoutPath = runDir / "stdout.log"
                        stderrPath = runDir / "stderr.log"
                        stdoutBytes = stdoutPath.stat().st_size if stdoutPath.exists() else 0
                        stderrBytes = stderrPath.stat().st_size if stderrPath.exists() else 0

                        # Step 13: Detect new artifacts (use start time as baseline)
                        sinceMtime = startTime.timestamp()
                        newArtifacts = runtimeImpl.detectArtifacts(
                            workspacePath=workspacePath,
                            sinceMtime=sinceMtime,
                        )

                        # Step 14: Build RunResult
                        libPoolVersion = runtimeRecord.libPoolVersion if runtimeRecord else "unknown"
                        error: str | None = None
                        if timedOut:
                            error = "Run timed out"
                        elif oomKilled:
                            error = "Run OOM killed"
                        elif outcome.exitCode != 0 and outcome.exitCode is not None:
                            error = f"Exit code {outcome.exitCode}"

                        result = RunResult(
                            runId=runId,
                            sessionId=sessionId,
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
                            newArtifacts=newArtifacts,
                            limits=effectiveLimitsWithTimeout,
                            networkEnabled=effectiveNetwork.enabled,
                            libPoolVersion=libPoolVersion,
                            error=error,
                        )

                        # Write result.json
                        await asyncio.to_thread(
                            atomicWriteJson,
                            runDir / "result.json",
                            self._runResultToDict(result),
                            tmpDir=Path(self._config.storage.rootDir) / "tmp",
                        )
                    finally:
                        # Step 15: Remove container (always, even on error)
                        await self._backend.removeContainer(outcome.containerId)
                except Exception as exc:
                    # Step 16 (error path): Update RunRecord to failed
                    finishedAt = datetime.now(timezone.utc)
                    runRecord.status = "failed"
                    runRecord.finishedAt = finishedAt
                    runRecord.exitCode = -1
                    await self._metadata.saveRun(runRecord)
                    logger.error("Run %s failed: %s", runId, exc)
                    raise

                # Step 16 (success path): Update RunInfo (status="completed" or "failed")
                status: Literal["completed", "failed"] = "completed" if error is None else "failed"
                runRecord.status = status
                runRecord.finishedAt = finishedAt
                runRecord.exitCode = outcome.exitCode
                await self._metadata.saveRun(runRecord)

                # Step 17: Bump session TTL
                await self._touchSessionInternal(record)

                return result

            finally:
                self._globalLimiter.release()
        finally:
            self._lockRegistry.release(sessionId)

    async def cancelRun(self, runId: str) -> bool:
        """Cancel a running container by runId.

        Looks up the container via the sandbox.runId label and sends SIGKILL.

        Args:
            runId: The run identifier.

        Returns:
            True if a container was found and killed, False otherwise.
        """
        try:
            # Look up container by label
            managed = await self._backend.listManagedContainers()
            for container in managed:
                if container.labels.get("sandbox.runId") == runId:
                    await self._backend.killContainer(container.containerId)
                    return True
            return False
        except Exception as exc:
            logger.warning("Failed to cancel run %s: %s", runId, exc)
            return False

    async def getRunInfo(self, runId: str) -> RunInfo | None:
        """Get run metadata by runId.

        Args:
            runId: The run identifier.

        Returns:
            RunInfo if found, None otherwise.
        """
        record = await self._metadata.loadRun(runId)
        if record is None:
            return None
        return RunInfo(
            runId=record.runId,
            sessionId=record.sessionId,
            runtime=record.runtime,
            startedAt=record.startedAt,
            finishedAt=record.finishedAt,
            status=cast(Literal["queued", "running", "completed", "failed", "cancelled"], record.status),
            exitCode=record.exitCode,
        )

    async def listRunsForSession(self, sessionId: str) -> list[RunInfo]:
        """List all runs for a session.

        Args:
            sessionId: The session identifier.

        Returns:
            List of RunInfo records for this session.
        """
        records = await self._metadata.listRunsForSession(sessionId)
        return [
            RunInfo(
                runId=r.runId,
                sessionId=r.sessionId,
                runtime=r.runtime,
                startedAt=r.startedAt,
                finishedAt=r.finishedAt,
                status=cast(Literal["queued", "running", "completed", "failed", "cancelled"], r.status),
                exitCode=r.exitCode,
            )
            for r in records
        ]

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
        paths and traversal attempts are rejected.

        Args:
            sessionId: The session identifier.
            path: Relative path to list (default "/" = workspace root).
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

        workspacePath = Path(record.workspacePath)
        # "/" means workspace root — resolveWorkspacePath rejects absolute paths,
        # so handle it directly.
        if path == "/":
            resolved = workspacePath.resolve()
        else:
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
            sessionId: The session identifier.
            path: Relative path to the file.
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

        # Read raw bytes first
        raw = resolved.read_bytes()
        if maxBytes is not None:
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

    async def writeFile(
        self,
        sessionId: str,
        path: str,
        content: bytes | str,
        *,
        overwrite: bool = True,
    ) -> FileInfo:
        """Write a file into the session workspace.

        Creates parent directories as needed. Content can be bytes or str
        (str is encoded as UTF-8).

        Args:
            sessionId: The session identifier.
            path: Relative path to write.
            content: The file content (bytes or str).
            overwrite: If False, raise FileExistsError when the target exists.

        Returns:
            FileInfo for the written file.

        Raises:
            SessionNotFound: If the session doesn't exist.
            PathOutsideWorkspace: If the path escapes the workspace.
            FileExistsError: If overwrite=False and the file exists.
        """
        record = await self._metadata.loadSession(sessionId)
        if record is None:
            raise SessionNotFound(f"Session {sessionId} not found")

        workspacePath = Path(record.workspacePath)
        resolved = resolveWorkspacePath(workspacePath, path)

        if resolved.exists() and not overwrite:
            raise FileExistsError(f"File exists and overwrite=False: {path}")

        # Encode str to bytes
        data = content.encode("utf-8") if isinstance(content, str) else content

        # Ensure parent directory exists
        resolved.parent.mkdir(parents=True, exist_ok=True)

        # Write the file
        resolved.write_bytes(data)
        os.chmod(resolved, self._config.storage.fileMode)

        # Bump the session TTL on write
        await self._touchSessionInternal(record)

        # Stat for the response
        stat = resolved.stat()
        return FileInfo(
            path=path,
            sizeBytes=stat.st_size,
            modifiedAt=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            isDirectory=False,
        )

    async def deleteFile(self, sessionId: str, path: str) -> bool:
        """Delete a file (or empty directory) from the session workspace.

        Args:
            sessionId: The session identifier.
            path: Relative path to delete.

        Returns:
            True if the file was deleted, False if it didn't exist.

        Raises:
            SessionNotFound: If the session doesn't exist.
            PathOutsideWorkspace: If the path escapes the workspace.
        """
        record = await self._metadata.loadSession(sessionId)
        if record is None:
            raise SessionNotFound(f"Session {sessionId} not found")

        workspacePath = Path(record.workspacePath)
        resolved = resolveWorkspacePath(workspacePath, path)

        if not resolved.exists():
            return False

        if resolved.is_dir():
            resolved.rmdir()  # only empty dirs
        else:
            resolved.unlink()

        # Bump session TTL
        await self._touchSessionInternal(record)

        return True

    # ---- Library pool (admin API) ----

    async def listRuntimeLibraries(
        self,
        runtime: RuntimeName = RuntimeName.PYTHON,
    ) -> list[PackageInfo]:
        """List installed packages in the runtime library pool.

        Reads the packages.json file from the runtime's pool directory.

        Args:
            runtime: The runtime whose library pool to query.

        Returns:
            List of PackageInfo for each installed package.
        """
        packagesPath = Path(self._config.storage.rootDir) / "runtimes" / runtime.value / "packages.json"
        if not packagesPath.exists():
            return []
        try:
            data = json.loads(packagesPath.read_text())
            return [PackageInfo(name=p["name"], version=p["version"]) for p in data]
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning("Failed to read packages.json for %s: %s", runtime.value, exc)
            return []

    async def installRuntimeLibraries(
        self,
        packages: Sequence[str],
        *,
        runtime: RuntimeName = RuntimeName.PYTHON,
        upgrade: bool = False,
        timeoutSeconds: int = 600,
    ) -> LibraryInstallResult:
        """Install packages into the runtime library pool.

        Acquires an fcntl.flock on pool.lock, validates package specs,
        runs a dedicated install container, and refreshes the package list.

        Args:
            packages: Package specs (PEP 508 names, possibly with version constraints).
            runtime: The runtime to install into.
            upgrade: If True, upgrade existing packages.
            timeoutSeconds: Timeout for the install operation.

        Returns:
            LibraryInstallResult with installed, skipped, and failed packages.

        Raises:
            InvalidPackageSpec: If a package spec is malformed or malicious.
            LibraryPoolLocked: If another process holds the install lock.
            LibraryInstallFailed: If the install container fails.
            UnknownRuntime: If the runtime is not available.
        """
        if not packages:
            return LibraryInstallResult(
                runtime=runtime,
                installed=[],
                skipped=[],
                failed=[],
                poolVersion="",
            )

        runtimeImpl = self._runtimes.get(runtime)
        if runtimeImpl is None:
            raise UnknownRuntime(f"Runtime {runtime.value} is not available")

        poolDir = Path(self._config.storage.rootDir) / "runtimes" / runtime.value

        # Step 1: Validate package specs
        validated: list[str] = []
        for spec in packages:
            cleaned = spec.strip()
            if not cleaned:
                continue
            self._validatePackageSpec(cleaned)
            validated.append(cleaned)

        if not validated:
            return LibraryInstallResult(
                runtime=runtime,
                installed=[],
                skipped=[],
                failed=[],
                poolVersion="",
            )

        # Step 2: Acquire fcntl lock
        lockHandle = await acquirePoolLock(runtime, poolDir)
        try:
            # Step 3: Get install image tag
            runtimeRecord = await self._metadata.loadRuntime(runtime)
            installImage = runtimeRecord.installImageTag if runtimeRecord else "gromozeka-sandbox-python:install"

            # Step 4: Ensure libs directory
            libsDir = poolDir / "libs"
            libsDir.mkdir(parents=True, exist_ok=True)

            # Step 5: Build install command
            command = runtimeImpl.installCommand(validated, upgrade=upgrade)

            # Step 6: Build ContainerSpec
            installConfig = getattr(runtimeImpl, "_config", None)
            installContainerConfig = getattr(installConfig, "installContainer", None) if installConfig else None
            installLimits = ResourceLimits(
                memoryMb=installContainerConfig.memoryMb if installContainerConfig else 1024,
                memorySwapMb=installContainerConfig.memoryMb if installContainerConfig else 1024,
                cpuCount=1.0,
                pidsLimit=installContainerConfig.pidsLimit if installContainerConfig else 256,
                timeoutSeconds=timeoutSeconds,
                timeoutGraceSeconds=10,
            )

            spec = ContainerSpec(
                name=f"sandbox-install-{uuid.uuid4().hex[:12]}",
                image=installImage,
                command=command,
                mounts=[{"hostPath": str(libsDir.absolute()), "containerPath": "/sandbox/libs", "mode": "rw"}],
                env={},
                limits=installLimits,
                network="bridge",  # install needs internet
                user=self._config.security.user,
                readOnlyRoot=False,  # install containers need writable temp dirs
                capDrop=list(self._config.security.dropCapabilities),
                securityOpt=["no-new-privileges"] if self._config.security.noNewPrivileges else [],
                labels={
                    "sandbox.managed": "true",
                    "sandbox.purpose": "install",
                    "sandbox.runtime": runtime.value,
                },
            )

            # Step 7: Run install container
            outcome = await self._backend.runOneshot(spec=spec)

            try:
                # Parse pip output for installed/skipped/failed
                installed, skipped, failed = self._parseInstallOutput(outcome)

                # Step 8: If install succeeded, refresh package list
                poolVersion = ""
                if outcome.exitCode == 0 or len(installed) > 0:
                    poolVersion = await self._refreshPackageList(runtime, libsDir)
            finally:
                # Step 9: Remove container (always, even on error)
                if outcome.containerId:
                    await self._backend.removeContainer(outcome.containerId)

            return LibraryInstallResult(
                runtime=runtime,
                installed=installed,
                skipped=skipped,
                failed=failed,
                poolVersion=poolVersion,
            )
        finally:
            releasePoolLock(lockHandle)

    async def removeRuntimeLibraries(
        self,
        packages: Sequence[str],
        *,
        runtime: RuntimeName = RuntimeName.PYTHON,
    ) -> LibraryRemoveResult:
        """Remove packages from the runtime library pool.

        Args:
            packages: Package names (not specs, just names) to remove.
            runtime: The runtime to remove from.

        Returns:
            LibraryRemoveResult with removed and notFound lists.

        Raises:
            LibraryPoolLocked: If another process holds the install lock.
            UnknownRuntime: If the runtime is not available.
        """
        runtimeImpl = self._runtimes.get(runtime)
        if runtimeImpl is None:
            raise UnknownRuntime(f"Runtime {runtime.value} is not available")

        poolDir = Path(self._config.storage.rootDir) / "runtimes" / runtime.value

        # Acquire flock
        lockHandle = await acquirePoolLock(runtime, poolDir)
        try:
            libsDir = poolDir / "libs"
            notFound: list[str] = []
            removed: list[str] = []

            if not libsDir.exists():
                return LibraryRemoveResult(runtime=runtime, removed=[], notFound=list(packages), poolVersion="")

            for pkg in packages:
                cleaned = pkg.strip()
                if not cleaned:
                    continue
                # Try to find and remove the package directory
                removedAny = False
                for entry in libsDir.iterdir():
                    if entry.is_dir() and entry.name.lower().replace("_", "-") == cleaned.lower().replace("_", "-"):
                        shutil.rmtree(entry)
                        removed.append(cleaned)
                        removedAny = True
                        break
                # Also check for .dist-info directories
                if not removedAny:
                    for entry in libsDir.glob(f"{cleaned}-*.dist-info"):
                        shutil.rmtree(entry)
                        removed.append(cleaned)
                        removedAny = True
                        break
                if not removedAny:
                    notFound.append(cleaned)

            # Refresh package list
            poolVersion = await self._refreshPackageList(runtime, libsDir)

            return LibraryRemoveResult(
                runtime=runtime,
                removed=removed,
                notFound=notFound,
                poolVersion=poolVersion,
            )
        finally:
            releasePoolLock(lockHandle)

    # ---- Operational ----

    async def healthcheck(self) -> HealthcheckResult:
        """Run a full health check on the sandbox system.

        Pings the backend, checks each runtime, and verifies the storage
        directory is writable.

        Returns:
            HealthcheckResult with overall ok status and per-component details.
        """
        errors: list[str] = []

        # Backend health
        backendResult = await self._backend.healthcheck()
        errors.extend(backendResult.errors)

        # Runtime health
        runtimesHealth: dict[str, dict[str, Any]] = {}
        for name in self._runtimes.keys():
            try:
                record = await self._metadata.loadRuntime(name)
                if record is None:
                    runtimesHealth[name.value] = {"ok": False, "error": "No metadata record"}
                    errors.append(f"Runtime {name.value} has no metadata record")
                else:
                    runtimesHealth[name.value] = {
                        "ok": True,
                        "imageTag": record.runImageTag,
                        "poolVersion": record.libPoolVersion,
                        "packageCount": record.packageCount,
                    }
            except Exception as exc:
                runtimesHealth[name.value] = {"ok": False, "error": str(exc)}
                errors.append(f"Runtime {name.value} check failed: {exc}")

        # Storage health
        storageHealth: dict[str, Any] = {}
        try:
            rootDir = Path(self._config.storage.rootDir)
            if not rootDir.exists():
                storageHealth = {"ok": False, "error": "Root directory does not exist"}
                errors.append("Storage root directory does not exist")
            elif not os.access(rootDir, os.W_OK):
                storageHealth = {"ok": False, "error": "Root directory is not writable"}
                errors.append("Storage root directory is not writable")
            else:
                storageHealth = {"ok": True, "path": str(rootDir)}
        except Exception as exc:
            storageHealth = {"ok": False, "error": str(exc)}
            errors.append(f"Storage check failed: {exc}")

        return HealthcheckResult(
            ok=len(errors) == 0,
            backend=backendResult.backend,
            runtimes=runtimesHealth,
            storage=storageHealth,
            errors=errors,
        )

    async def shutdown(self, *, cleanVolumes: bool = False) -> ShutdownResult:
        """Shut down the sandbox manager.

        Closes the backend connection and optionally cleans all sessions.

        Args:
            cleanVolumes: If True, drop every session before shutting down.

        Returns:
            ShutdownResult with cleanup counts and errors.
        """
        errors: list[str] = []
        cleanedVolumes = 0

        if cleanVolumes:
            try:
                sessions = await self._metadata.listSessions()
                for session in sessions:
                    try:
                        await self.dropSession(session.sessionId, force=True)
                        cleanedVolumes += 1
                    except Exception as exc:
                        errors.append(f"Failed to drop session {session.sessionId}: {exc}")
            except Exception as exc:
                errors.append(f"Failed to list sessions for cleanup: {exc}")

        # Close backend
        try:
            if hasattr(self._backend, "close"):
                await self._backend.close()
        except Exception as exc:
            errors.append(f"Failed to close backend: {exc}")

        return ShutdownResult(
            cleanedVolumes=cleanedVolumes,
            errors=errors,
        )

    async def recover(self) -> RecoveryResult:
        """Run startup recovery: reconcile state after a crash.

        Kills and removes all managed containers, reconciles metadata
        with on-disk state, and refreshes library pool versions.

        Returns:
            RecoveryResult with counts of reaped containers, released locks,
            reconciled pools, and any errors.
        """
        errors: list[str] = []
        reapedContainers = 0
        releasedLocks = 0
        reconciledPools = 0

        # Step 1: Kill and remove all managed containers
        try:
            managed = await self._backend.listManagedContainers()
            for container in managed:
                try:
                    await self._backend.killContainer(container.containerId)
                    await self._backend.removeContainer(container.containerId, force=True)
                    reapedContainers += 1
                except Exception as exc:
                    errors.append(f"Failed to reap container {container.containerId}: {exc}")
        except Exception as exc:
            errors.append(f"Failed to list managed containers: {exc}")

        # Step 2: Reconcile metadata with on-disk workspace presence
        try:
            sessions = await self._metadata.listSessions()
            for session in sessions:
                workspacePath = Path(session.workspacePath)
                if not workspacePath.exists():
                    logger.warning(
                        "Recovery: session %s metadata exists but workspace is missing",
                        session.sessionId,
                    )
                    await self._metadata.deleteSession(session.sessionId)
                    releasedLocks += 1
        except Exception as exc:
            errors.append(f"Failed to reconcile sessions: {exc}")

        # Step 3: Refresh pool versions for each runtime
        for name in self._runtimes.keys():
            try:
                libsDir = Path(self._config.storage.rootDir) / "runtimes" / name.value / "libs"
                if libsDir.exists():
                    await self._refreshPackageList(name, libsDir)
                    reconciledPools += 1
            except Exception as exc:
                errors.append(f"Failed to reconcile pool for {name.value}: {exc}")

        return RecoveryResult(
            reapedContainers=reapedContainers,
            releasedLocks=releasedLocks,
            reconciledPools=reconciledPools,
            errors=errors,
        )

    async def collectGarbage(self) -> GcResult:
        """Run garbage collection on all sandbox resources.

        Removes expired sessions, orphan workspace directories, stale run
        records, and orphan containers (container GC is a stub in Phase 2).

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

        containers, sessions, runs, orphans, errors = await self._gc.collectAll()
        return GcResult(
            removedContainers=containers,
            removedSessions=sessions,
            removedRuns=runs,
            removedOrphans=orphans,
            errors=errors,
        )

    # ---- Library pool helpers ----

    def _validatePackageSpec(self, spec: str) -> None:
        """Validate a package spec for install.

        Rejects specs containing shell metacharacters or starting with '-'.

        Args:
            spec: The package spec string.

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

        # Basic PEP 508 validation (lightweight)
        try:
            from packaging.requirements import Requirement

            Requirement(spec)
        except ImportError:
            pass  # packaging not required for basic validation
        except Exception as exc:
            raise InvalidPackageSpec(spec=spec, reason=str(exc)) from exc

    def _parseInstallOutput(
        self,
        outcome: ContainerOutcome,
    ) -> tuple[list[PackageInfo], list[str], list[tuple[str, str]]]:
        """Parse pip install output from container outcome.

        Args:
            outcome: Container outcome from the install container.

        Returns:
            Tuple of (installed, skipped, failed) packages.
        """
        installed: list[PackageInfo] = []
        skipped: list[str] = []
        failed: list[tuple[str, str]] = []

        if outcome.exitCode == 0:
            # All packages installed successfully — _refreshPackageList
            # handles the detailed name/version enumeration.
            installed.append(PackageInfo(name="packages", version="installed"))
        else:
            failed.append(("install", f"pip exited with code {outcome.exitCode}"))

        return installed, skipped, failed

    async def _refreshPackageList(
        self,
        runtime: RuntimeName,
        libsDir: Path,
    ) -> str:
        """Refresh the installed package list by scanning the libs directory.

        Walks the libs directory for .dist-info directories to determine
        installed packages and their versions, then writes packages.json
        and updates the runtime record.

        Args:
            runtime: The runtime name.
            libsDir: Path to the library pool directory.

        Returns:
            The new poolVersion (SHA-256 of the package list).
        """
        runtimeImpl = self._runtimes.get(runtime)
        if runtimeImpl is None:
            return ""

        packages: list[dict[str, str]] = []
        if libsDir.exists():
            # Collect .dist-info directories for package name/version
            distInfoDirs = sorted(libsDir.glob("*.dist-info"))
            for distInfo in distInfoDirs:
                # Format: {name}-{version}.dist-info
                dirName = distInfo.name
                if dirName.endswith(".dist-info"):
                    nameVersion = dirName[: -len(".dist-info")]
                    # Split on last hyphen before version — PEP 427
                    # The version starts after the last '-' that is followed
                    # by a digit.
                    parts = nameVersion.rsplit("-", 1)
                    if len(parts) == 2:
                        name, version = parts
                        packages.append({"name": name, "version": version})
                    else:
                        packages.append({"name": nameVersion, "version": "unknown"})

        # Save packages.json
        packagesPath = Path(self._config.storage.rootDir) / "runtimes" / runtime.value / "packages.json"
        packagesPath.parent.mkdir(parents=True, exist_ok=True)
        packagesPath.write_text(json.dumps(packages, indent=2))

        # Compute poolVersion
        sortedNames = sorted(f"{p['name']}=={p['version']}" for p in packages)
        poolVersion = hashlib.sha256("\n".join(sortedNames).encode()).hexdigest()

        # Update runtime record
        runtimeRecord = await self._metadata.loadRuntime(runtime)
        if runtimeRecord:
            runtimeRecord.libPoolVersion = poolVersion
            runtimeRecord.packageCount = len(packages)
            await self._metadata.saveRuntime(runtimeRecord)

        return poolVersion

    async def _countPackages(self, runtime: RuntimeName) -> int:
        """Count installed packages for a runtime.

        Args:
            runtime: The runtime name.

        Returns:
            Number of installed packages.
        """
        record = await self._metadata.loadRuntime(runtime)
        return record.packageCount if record else 0
