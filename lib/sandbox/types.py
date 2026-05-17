"""Public data classes for the sandbox library.

Defines all input and output dataclasses used throughout the sandbox execution
system.  Input classes are frozen (immutable); output classes are mutable so
callers can update them in-place when needed.

Enums are imported from :mod:`lib.sandbox.enums` — they are NOT redefined here.

Classes:
    NetworkPolicy: Controls network access for a sandboxed session.
    ResourceLimits: CPU, memory, and timeout constraints for a sandboxed run.
    InputFile: A file to inject into the sandbox workspace before execution.
    SessionInfo: Metadata about an active sandbox session.
    SessionUsage: Disk and run-count usage metrics for a session.
    ShutdownResult: Result of shutting down the sandbox manager.
    RunInfo: Status metadata for a single code execution run.
    RunResult: Full output of a completed (or failed) code execution run.
    ArtifactInfo: A file artifact produced or modified during a run.
    FileInfo: Lightweight metadata about a file inside the workspace.
    FileContent: File content read back from the workspace (may be truncated).
    PackageInfo: A resolved package name and version.
    LibraryInstallResult: Outcome of installing libraries into a runtime pool.
    LibraryRemoveResult: Outcome of removing libraries from a runtime pool.
    DropSessionResult: Outcome of dropping (destroying) a sandbox session.
    HealthcheckResult: Aggregated health status of the sandbox subsystem.
    GcResult: Outcome of a garbage-collection sweep.
    RecoveryResult: Outcome of a crash-recovery pass.
    RuntimeInfo: Static metadata about a configured runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from .enums import RuntimeName

# ============================================================================
# Input classes (frozen — immutable after construction)
# ============================================================================


@dataclass(slots=True, frozen=True)
class NetworkPolicy:
    """Controls whether a sandboxed session has network access.

    Attributes:
        enabled: If True, the session is allowed to make network requests.
    """

    enabled: bool = False


@dataclass(slots=True, frozen=True)
class ResourceLimits:
    """CPU, memory, and timeout constraints for a sandboxed run.

    Attributes:
        memoryMb: Maximum memory in megabytes.
        memorySwapMb: Swap allowance in megabytes. ``None`` disables swap
            entirely; equal to ``memoryMb`` allows full swap.
        cpuCount: Fractional CPU core limit.
        pidsLimit: Maximum number of PIDs inside the container.
        timeoutSeconds: Wall-clock timeout before SIGTERM.
        timeoutGraceSeconds: Grace period after SIGTERM before SIGKILL.
    """

    memoryMb: int = 512
    memorySwapMb: int | None = 512
    cpuCount: float = 1.0
    pidsLimit: int = 64
    timeoutSeconds: int = 30
    timeoutGraceSeconds: int = 5

    @classmethod
    def fromDict(cls, data: dict) -> "ResourceLimits":
        """Construct a ResourceLimits from a dict with kebab-case keys.

        Args:
            data: Dictionary with kebab-case keys.

        Returns:
            A ResourceLimits instance.
        """
        return cls(
            memoryMb=int(data.get("memory-mb", 512)),
            memorySwapMb=int(data.get("memory-swap-mb", 512)) if data.get("memory-swap-mb") is not None else None,
            cpuCount=float(data.get("cpu-count", 1.0)),
            pidsLimit=int(data.get("pids-limit", 64)),
            timeoutSeconds=int(data.get("timeout-seconds", 30)),
            timeoutGraceSeconds=int(data.get("timeout-grace-seconds", 5)),
        )


@dataclass(slots=True, frozen=True)
class InputFile:
    """A file to inject into the sandbox workspace before execution.

    Attributes:
        path: Destination path relative to ``/workspace``.
        content: File content as bytes or a UTF-8 string.
        overwrite: If True, replace an existing file at the same path.
    """

    path: str
    content: bytes | str
    overwrite: bool = True


# ============================================================================
# Output classes (mutable — callers may update in-place)
# ============================================================================


@dataclass(slots=True)
class ArtifactInfo:
    """A file artifact produced or modified during a run.

    Attributes:
        path: Path relative to the workspace root.
        sizeBytes: File size in bytes.
        modifiedAt: Last-modified timestamp.
        mimeType: MIME type if known, otherwise None.
        sha256: Hex-encoded SHA-256 digest if computed, otherwise None.
    """

    path: str
    sizeBytes: int
    modifiedAt: datetime
    mimeType: str | None
    sha256: str | None


@dataclass(slots=True)
class SessionInfo:
    """Metadata about an active sandbox session.

    Attributes:
        sessionId: Unique identifier for the session.
        runtime: Runtime environment used by this session.
        workspacePath: Host-side path to the workspace directory.
        createdAt: Timestamp when the session was created.
        updatedAt: Timestamp when the session was last updated.
        expiresAt: Timestamp when the session will expire.
        metadata: Opaque key-value pairs controlled by the caller.
    """

    sessionId: str
    runtime: RuntimeName
    workspacePath: str
    createdAt: datetime
    updatedAt: datetime
    expiresAt: datetime
    metadata: dict[str, str]

    @classmethod
    def fromRecord(cls, record: Any) -> "SessionInfo":
        """Construct a SessionInfo from a SessionRecord.

        Args:
            record: The persisted session record (duck-typed for import cycle avoidance).

        Returns:
            A SessionInfo instance.
        """
        return cls(
            sessionId=record.sessionId,
            runtime=record.runtime,
            workspacePath=record.workspacePath,
            createdAt=record.createdAt,
            updatedAt=record.updatedAt,
            expiresAt=record.expiresAt,
            metadata=record.metadata,
        )


@dataclass(slots=True)
class SessionUsage:
    """Disk and run-count usage metrics for a session.

    Attributes:
        sessionId: Unique identifier for the session.
        fileCount: Number of files in the workspace.
        totalBytes: Total size of all files in bytes.
        runCount: Number of runs executed in this session.
        measuredAt: Timestamp when the measurement was taken.
    """

    sessionId: str
    fileCount: int
    totalBytes: int
    runCount: int
    measuredAt: datetime


@dataclass(slots=True)
class ShutdownResult:
    """Result of shutting down the sandbox manager.

    Attributes:
        cleanedVolumes: Number of workspace volumes removed during shutdown.
        errors: Non-fatal errors encountered during shutdown.
    """

    cleanedVolumes: int
    errors: list[str]


@dataclass(slots=True)
class RunInfo:
    """Status metadata for a single code execution run.

    Attributes:
        runId: Unique identifier for the run.
        sessionId: Session that owns this run.
        runtime: Runtime environment used for this run.
        startedAt: Timestamp when the run started.
        finishedAt: Timestamp when the run finished, or None if still running.
        status: Current status of the run.
        exitCode: Process exit code, or None if not yet available.
    """

    runId: str
    sessionId: str
    runtime: RuntimeName
    startedAt: datetime
    finishedAt: datetime | None
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    exitCode: int | None

    @classmethod
    def fromRecord(cls, record: Any) -> "RunInfo":
        """Construct a RunInfo from a RunRecord.

        Args:
            record: The persisted run record (duck-typed for import cycle avoidance).

        Returns:
            A RunInfo instance.
        """
        return cls(
            runId=record.runId,
            sessionId=record.sessionId,
            runtime=record.runtime,
            startedAt=record.startedAt,
            finishedAt=record.finishedAt,
            status=record.status,
            exitCode=record.exitCode,
        )


@dataclass(slots=True)
class RunResult:
    """Full output of a completed (or failed) code execution run.

    Attributes:
        runId: Unique identifier for the run.
        sessionId: Session that owns this run.
        runtime: Runtime environment used for this run.
        stdoutPath: Relative workspace path to stdout capture.
        stderrPath: Relative workspace path to stderr capture.
        stdoutBytes: Full size of stdout on disk.
        stderrBytes: Full size of stderr on disk.
        exitCode: Process exit code, or None if not available.
        signal: Termination signal name, or None.
        timedOut: True if the run exceeded its timeout limit.
        oomKilled: True if the run was killed due to out-of-memory.
        startedAt: Timestamp when the run started.
        finishedAt: Timestamp when the run finished.
        elapsedMs: Wall-clock elapsed time in milliseconds.
        newArtifacts: Files that appeared or changed during the run.
        limits: Resource limits that were applied to this run.
        networkEnabled: Whether the run actually had network access.
        libPoolVersion: Version hash of the library pool used.
        error: Error message if the run failed, otherwise None.
    """

    runId: str
    sessionId: str
    runtime: RuntimeName
    stdoutPath: str
    stderrPath: str
    stdoutBytes: int
    stderrBytes: int
    exitCode: int | None
    signal: str | None
    timedOut: bool
    oomKilled: bool
    startedAt: datetime
    finishedAt: datetime
    elapsedMs: int
    newArtifacts: list[ArtifactInfo]
    limits: ResourceLimits
    networkEnabled: bool
    libPoolVersion: str
    error: str | None

    def toDict(self) -> dict[str, Any]:
        """Convert a RunResult to a JSON-serializable dict.

        Returns:
            A dict with datetime→isoformat, enum→str conversions.
        """
        return {
            "runId": self.runId,
            "sessionId": self.sessionId,
            "runtime": self.runtime.value,
            "stdoutPath": self.stdoutPath,
            "stderrPath": self.stderrPath,
            "stdoutBytes": self.stdoutBytes,
            "stderrBytes": self.stderrBytes,
            "exitCode": self.exitCode,
            "signal": self.signal,
            "timedOut": self.timedOut,
            "oomKilled": self.oomKilled,
            "startedAt": self.startedAt.isoformat(),
            "finishedAt": self.finishedAt.isoformat(),
            "elapsedMs": self.elapsedMs,
            "networkEnabled": self.networkEnabled,
            "libPoolVersion": self.libPoolVersion,
            "error": self.error,
        }


@dataclass(slots=True)
class FileInfo:
    """Lightweight metadata about a file inside the workspace.

    Attributes:
        path: Path relative to the workspace root.
        sizeBytes: File size in bytes.
        modifiedAt: Last-modified timestamp.
        isDirectory: True if the entry is a directory.
    """

    path: str
    sizeBytes: int
    modifiedAt: datetime
    isDirectory: bool


@dataclass(slots=True)
class FileContent:
    """File content read back from the workspace (may be truncated).

    Attributes:
        path: Path relative to the workspace root.
        sizeBytes: Full file size on disk.
        bytesRead: Number of bytes actually read (may be less than sizeBytes).
        truncated: True if the content was truncated due to a size limit.
        content: File content as bytes or a UTF-8 string.
    """

    path: str
    sizeBytes: int
    bytesRead: int
    truncated: bool
    content: bytes | str


@dataclass(slots=True)
class PackageInfo:
    """A resolved package name and version.

    Attributes:
        name: Package name.
        version: Package version string.
    """

    name: str
    version: str


@dataclass(slots=True)
class LibraryInstallResult:
    """Outcome of installing libraries into a runtime pool.

    Attributes:
        runtime: Runtime environment that was targeted.
        installed: Packages that were successfully installed.
        skipped: Package names that were already present.
        failed: Packages that failed to install, with reasons.
        poolVersion: SHA-256 hash of the sorted (name, version) tuples.
    """

    runtime: RuntimeName
    installed: list[PackageInfo]
    skipped: list[str]
    failed: list[tuple[str, str]]
    poolVersion: str


@dataclass(slots=True)
class LibraryRemoveResult:
    """Outcome of removing libraries from a runtime pool.

    Attributes:
        runtime: Runtime environment that was targeted.
        removed: Package names that were successfully removed.
        notFound: Package names that were not present in the pool.
        poolVersion: SHA-256 hash of the sorted (name, version) tuples.
    """

    runtime: RuntimeName
    removed: list[str]
    notFound: list[str]
    poolVersion: str


@dataclass(slots=True)
class DropSessionResult:
    """Outcome of dropping (destroying) a sandbox session.

    Attributes:
        sessionId: Unique identifier of the session that was dropped.
        existed: True if the session existed at drop time.
        runsCancelled: Number of active runs that were cancelled.
        errors: Non-fatal errors encountered during cleanup.
    """

    sessionId: str
    existed: bool
    runsCancelled: int
    errors: list[str]


@dataclass(slots=True)
class HealthcheckResult:
    """Aggregated health status of the sandbox subsystem.

    Attributes:
        ok: True if all subsystems are healthy.
        backend: Backend-specific health details.
        runtimes: Per-runtime health details.
        storage: Storage subsystem health details.
        errors: List of error messages from unhealthy subsystems.
    """

    ok: bool
    backend: dict[str, Any]
    runtimes: dict[str, dict[str, Any]]
    storage: dict[str, Any]
    errors: list[str]


@dataclass(slots=True)
class GcResult:
    """Outcome of a garbage-collection sweep.

    Attributes:
        removedContainers: Number of containers removed.
        removedSessions: Number of expired sessions removed.
        removedRuns: Number of stale run records removed.
        removedOrphans: Number of orphaned resources removed.
        errors: Non-fatal errors encountered during collection.
    """

    removedContainers: int
    removedSessions: int
    removedRuns: int
    removedOrphans: int
    errors: list[str]


@dataclass(slots=True)
class RecoveryResult:
    """Outcome of a crash-recovery pass.

    Attributes:
        reapedContainers: Number of stale containers reaped.
        releasedLocks: Number of stale locks released.
        reconciledPools: Number of library pools reconciled.
        errors: Non-fatal errors encountered during recovery.
    """

    reapedContainers: int
    releasedLocks: int
    reconciledPools: int
    errors: list[str]


@dataclass(slots=True)
class RuntimeInfo:
    """Static metadata about a configured runtime.

    Attributes:
        name: Runtime identifier.
        runImageTag: Docker image tag used for execution.
        installImageTag: Docker image tag used for library installation.
        libPoolPath: Host-side path to the pre-installed library pool.
        libPoolVersion: SHA-256 hash of the library pool contents.
        packageCount: Number of pre-installed packages in the pool.
    """

    name: RuntimeName
    runImageTag: str
    installImageTag: str
    libPoolPath: str
    libPoolVersion: str
    packageCount: int
