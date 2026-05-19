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

import lib.utils as libUtils

from . import locks
from .backends.base import SandboxBackend
from .backends.docker import DockerBackend
from .config import SandboxConfig
from .enums import RunStatus, RuntimeName
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
from .locks import GlobalRunLimiter, SessionLockRegistry
from .metadata.filesystem import FilesystemMetadataStore
from .runtimes.base import Runtime
from .runtimes.python import PythonRuntime
from .storage import atomicWriteJson, ensureDirectoryLayout, resolveWorkspacePath, sessionHash
from .types import (
    ContainerSpec,
    FileContent,
    FileInfo,
    GcResult,
    HealthcheckResult,
    NetworkPolicy,
    PackageInfo,
    ResourceLimits,
    RunInfo,
    RunResult,
    SessionInfo,
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

        Args:
            cls: The SandboxManager class.

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

    async def listSessions(self) -> list[str]:
        """List all sessions.

        Args:
            self: The SandboxManager instance.

        Returns:
            List of session IDs.
        """
        return await self._metadata.listSessions()

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

                # No need to try to kill container, as we are removeing it with force=True
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
                        logger.error(f"Missing required {runtime} libs: {missing}")
                        raise MissingDependenciesError(missing=missing)

                # Step 6: Set up run directory
                workspacePath = Path(sessionInfo.workspacePath)
                # Ensure workspace directory exists (might be missing if tmp_path changed)
                workspacePath.mkdir(parents=True, exist_ok=True)
                os.chmod(workspacePath, self._config.storage.dirMode)
                runDir = workspacePath / ".run" / runId
                runDir.mkdir(parents=True, exist_ok=True)

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
                if Path(hostLibPool).exists():
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
                        timedOut = outcome.exitCode == 124
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
                        await self._backend.removeContainer(outcome.containerId)
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
        paths and traversal attempts are rejected.

        Args:
            self: The SandboxManager instance.
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

        workspacePath = Path(record.workspacePath).resolve().absolute()
        # "/" means workspace root — resolveWorkspacePath rejects absolute paths,
        # so handle it directly.
        if path == "/":
            resolved = workspacePath.resolve().absolute()
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
            self: The SandboxManager instance.
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
        timeoutSeconds: int = 600,
    ) -> bool:
        """Install packages into the runtime library pool.

        Acquires an fcntl.flock on pool.lock, validates package specs,
        runs a dedicated install container, and refreshes the package list.

        Args:
            self: The SandboxManager instance.
            packages: Package specs (PEP 508 names, possibly with version constraints).
            runtime: The runtime to install into.
            upgrade: If True, upgrade existing packages.
            timeoutSeconds: Timeout for the install operation.

        Returns:
            True if installation succeeded, False otherwise.

        Raises:
            InvalidPackageSpec: If a package spec is malformed or malicious.
            LibraryPoolLocked: If another process holds the install lock.
            LibraryInstallFailed: If the install container fails.
            UnknownRuntime: If the runtime is not available.
        """
        if not packages:
            return True

        runtimeImpl = self._runtimes.get(runtime)
        if runtimeImpl is None:
            raise UnknownRuntime(f"Runtime {runtime.value} is not available")

        poolDir = Path(self._config.storage.rootDir) / "runtimes" / runtime.value

        # Step 1: Validate package specs
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

        # Step 2: Acquire fcntl lock
        async with locks.poolLock(runtime, poolDir):  # as lockHandle:
            # Step 4: Ensure libs directory
            libsDir = poolDir / "libs"
            libsDir.mkdir(parents=True, exist_ok=True)

            # Step 5: Build install command

            # Step 6: Build ContainerSpec
            installContainerConfig = runtimeImpl._config.installContainer
            defaultLimits = self._config.limits

            # Step 7: Run install container
            outcome = await self._backend.runOneshot(
                spec=ContainerSpec(
                    name=f"sandbox-install-{uuid.uuid4().hex[:12]}",
                    image=runtimeImpl._config.installImageTag,
                    command=runtimeImpl.installCommand(validated, upgrade=upgrade),
                    mounts=[
                        {
                            "hostPath": str(libsDir.absolute()),
                            "containerPath": runtimeImpl._config.libMountPath,
                            "mode": "rw",
                        }
                    ],
                    env={},
                    limits=ResourceLimits(
                        memoryMb=installContainerConfig.memoryMb,
                        # Set equal to memoryMb to disable swap (Docker MemorySwap == total limit)
                        memorySwapMb=installContainerConfig.memoryMb,
                        cpuCount=defaultLimits.cpuCount,
                        pidsLimit=installContainerConfig.pidsLimit,
                        timeoutSeconds=timeoutSeconds,
                        timeoutGraceSeconds=60,
                    ),
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
            )

            return all(
                [
                    not outcome.oomKilled,
                    outcome.signal is None,
                    outcome.exitCode == 0,
                ]
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
                sessions = await self._metadata.listSessions()
                for sessionId in sessions:
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
        with on-disk state, and refreshes library pool versions.

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
                    await self._backend.killContainer(container.containerId)
                    await self._backend.removeContainer(container.containerId, force=True)
                except Exception as exc:
                    logger.error(f"Failed to reap container {container.containerId}: {exc}")
        except Exception as exc:
            logger.error(f"Failed to list managed containers: {exc}")

        # Step 2: Reconcile metadata with on-disk workspace presence
        try:
            sessions = await self._metadata.listSessions()
            for sessionId in sessions:
                sessionInfo = await self._metadata.loadSession(sessionId)
                if sessionInfo is None:
                    # Imposiburu, actually
                    logger.error("Session info file not found for session %s", sessionId)
                    continue
                workspacePath = Path(sessionInfo.workspacePath)
                if not workspacePath.exists():
                    logger.warning(
                        "Recovery: session %s metadata exists but workspace is missing",
                        sessionId,
                    )
                    await self._metadata.deleteSession(sessionId)
        except Exception as exc:
            logger.error(f"Failed to reconcile sessions: {exc}")

        # Step 3: Refresh pool versions for each runtime
        for name in self._runtimes.keys():
            try:
                libsDir = Path(self._config.storage.rootDir) / "runtimes" / name.value / "libs"
                if libsDir.exists():
                    await self._refreshPackageList(name, libsDir)
            except Exception as exc:
                logger.error(f"Failed to reconcile pool for {name.value}: {exc}")

        # Step 4: Collect garbage
        gcRet = await self.collectGarbage()
        for errMsg in gcRet.errors:
            logger.error(errMsg)

        return True

    async def collectGarbage(self) -> GcResult:
        """Run garbage collection on all sandbox resources.

        Removes expired sessions, orphan workspace directories, stale run
        records, and orphan containers (container GC is a stub in Phase 2).

        Args:
            self: The SandboxManager instance.

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
            runtime does not exist or if container execution fails (non-zero exit code
            or error).
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
                name=f"sandbox-list-{uuid.uuid4().hex[:12]}",
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

        try:
            await self._backend.removeContainer(outcome.containerId)
        except Exception as exc:
            logger.error("Failed to remove list container %s: %s", outcome.containerId, exc)
        stdoutPath.unlink(missing_ok=True)
        stderrPath.unlink(missing_ok=True)

        packages = runtimeImpl.parseListCommandOutput(outcome=outcome, stdout=stdoutStr, stderr=stderrStr)
        await self._metadata.savePackagesInfo(runtime=runtime, packagesInfo=packages)
        return True
