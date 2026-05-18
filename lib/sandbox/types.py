"""Public data classes for the sandbox library.

Defines all input and output dataclasses used throughout the sandbox execution
system.  Input classes are frozen (immutable); output classes are mutable so
callers can update them in-place when needed.

Enums are imported from :mod:`lib.sandbox.enums` — they are NOT redefined here.

Classes:
    NetworkPolicy: Controls network access for a sandboxed session.
    ResourceLimits: CPU, memory, and timeout constraints for a sandboxed run.
    ShutdownResult: Result of shutting down the sandbox manager.
    RunInfo: Status metadata for a single code execution run.
    RunResult: Full output of a completed (or failed) code execution run.
    FileInfo: Lightweight metadata about a file inside the workspace.
    FileContent: File content read back from the workspace (may be truncated).
    PackageInfo: A resolved package name and version.
    HealthcheckResult: Aggregated health status of the sandbox subsystem.
    GcResult: Outcome of a garbage-collection sweep.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict

import lib.utils as libUtils

from .enums import RunStatus, RuntimeName

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
        memorySwapMb: Total memory+swap limit in megabytes (Docker MemorySwap).
            When set, the effective swap available is ``memorySwapMb - memoryMb``.
            When set to ``None`` (default), swap is disabled by setting
            MemorySwap equal to memoryMb.
        cpuCount: Fractional CPU core limit.
        pidsLimit: Maximum number of PIDs inside the container.
        timeoutSeconds: Wall-clock timeout before SIGTERM.
        timeoutGraceSeconds: Grace period after SIGTERM before SIGKILL.
    """

    memoryMb: int = 512
    memorySwapMb: int | None = None
    cpuCount: float = 1.0
    pidsLimit: int = 64
    timeoutSeconds: int = 30
    timeoutGraceSeconds: int = 5

    def toDict(self) -> Dict[str, Any]:
        """Convert a ResourceLimits to a JSON-serializable dict.

        Returns:
            A dict representation of the ResourceLimits.
        """
        return libUtils.slottedObjectToDict(self, recursive=True)

    @classmethod
    def fromDict(cls, data: dict) -> "ResourceLimits":
        """Construct a ResourceLimits from a dict with kebab-case keys.

        Args:
            data: Dictionary with kebab-case keys.

        Returns:
            A ResourceLimits instance.
        """
        memorySwapMb = None
        rawSwap = data.get("memory-swap-mb")
        if rawSwap is not None and rawSwap != "":
            memorySwapMb = max(32, int(rawSwap))
        return cls(
            memoryMb=max(32, int(data.get("memory-mb", 512))),
            memorySwapMb=memorySwapMb,
            cpuCount=max(0.1, float(data.get("cpu-count", 1.0))),
            pidsLimit=max(8, int(data.get("pids-limit", 64))),
            timeoutSeconds=max(30, int(data.get("timeout-seconds", 60))),
            timeoutGraceSeconds=max(0, int(data.get("timeout-grace-seconds", 10))),
        )


# ============================================================================
# Output classes (mutable — callers may update in-place)
# ============================================================================


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
    status: RunStatus
    exitCode: int | None

    def toDict(self) -> Dict[str, Any]:
        """Convert a RunInfo to a JSON-serializable dict.

        Returns:
            A dict representation of the RunInfo with datetime→isoformat and enum→str conversions.
        """
        return libUtils.slottedObjectToDict(self, recursive=True)

    @classmethod
    def fromDict(cls, data: Dict[str, Any]) -> "RunInfo":
        """Construct a RunInfo from a dict.

        Args:
            data: Dictionary containing run info data with camelCase keys.

        Returns:
            A RunInfo instance.
        """
        return RunInfo(
            runId=data["runId"],
            sessionId=data["sessionId"],
            runtime=RuntimeName(data["runtime"]),
            startedAt=datetime.fromisoformat(data["startedAt"]),
            finishedAt=datetime.fromisoformat(data["finishedAt"]) if data.get("finishedAt") is not None else None,
            status=RunStatus(data["status"]),
            exitCode=int(data["exitCode"]) if data.get("exitCode") is not None else None,
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
        networkEnabled: Whether the run actually had network access.
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
    networkEnabled: bool
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

    def toDict(self) -> Dict[str, Any]:
        """Convert a PackageInfo to a JSON-serializable dict.

        Returns:
            A dict representation of the PackageInfo.
        """
        return libUtils.slottedObjectToDict(self, recursive=True)

    @classmethod
    def fromDict(cls, data: Dict[str, Any]) -> "PackageInfo":
        """Construct a PackageInfo from a dict.

        Args:
            data: Dictionary containing package name and version.

        Returns:
            A PackageInfo instance.
        """
        return PackageInfo(
            name=data["name"],
            version=data.get("version", ""),
        )


@dataclass(slots=True)
class HealthcheckResult:
    """Aggregated health status of the sandbox subsystem.

    Attributes:
        ok: True if all subsystems are healthy.
        errors: List of error messages from unhealthy subsystems.
    """

    ok: bool
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
class SessionInfo:
    """Persisted metadata for a sandbox session.

    Attributes:
        sessionId: Unique identifier for the session.
        sessionHash: Hash of the session ID for stable filesystem naming.
        workspacePath: Host-side path to the workspace directory.
        createdAt: Timestamp when the session was created.
        updatedAt: Timestamp when the session was last updated.
        expiresAt: Timestamp when the session will expire.
        limits: Resource limits for runs in this session.
        metadata: Opaque key-value pairs controlled by the caller.
    """

    sessionId: str
    sessionHash: str
    workspacePath: str
    createdAt: datetime
    updatedAt: datetime
    expiresAt: datetime
    limits: ResourceLimits
    metadata: dict[str, str]

    def toDict(self) -> Dict[str, Any]:
        """Convert the SessionInfo to a dictionary.

        Returns:
            Dictionary representation of the SessionInfo.
        """
        return libUtils.slottedObjectToDict(self, recursive=True)

    @classmethod
    def fromDict(cls, data: Dict[str, Any]) -> "SessionInfo":
        """Create a SessionInfo from a dictionary.

        Args:
            data: Dictionary containing SessionInfo fields with keys
                matching the field names. Datetime fields must be ISO format.

        Returns:
            SessionInfo instance reconstructed from the dictionary.

        Raises:
            KeyError: If required keys are missing from data.
            ValueError: If datetime values are not valid ISO format.
        """
        return SessionInfo(
            sessionId=data["sessionId"],
            sessionHash=data["sessionHash"],
            workspacePath=data["workspacePath"],
            createdAt=datetime.fromisoformat(data["createdAt"]),
            updatedAt=datetime.fromisoformat(data["updatedAt"]),
            expiresAt=datetime.fromisoformat(data["expiresAt"]),
            limits=ResourceLimits.fromDict(data["limits"]),
            metadata=data.get("metadata", {}),
        )


@dataclass(slots=True)
class ContainerSpec:
    """Specification for creating and running a container.

    Attributes:
        name: Container name.
        image: Container image tag.
        command: Command and arguments to execute inside the container.
        mounts: Volume mount specifications (hostPath, containerPath, mode).
        env: Environment variables to inject into the container.
        limits: Resource limits (CPU, memory, timeout) for the container.
        network: Network mode — ``"none"`` or ``"bridge"``.
        user: ``uid:gid`` string for the container process.
        readOnlyRoot: If True, mount the root filesystem as read-only.
        capDrop: Linux capabilities to drop.
        securityOpt: Additional Docker security options.
        labels: Key-value labels attached to the container.
    """

    name: str
    image: str
    command: list[str]
    mounts: list[dict[str, str]]
    env: dict[str, str]
    limits: ResourceLimits
    network: str
    user: str
    readOnlyRoot: bool
    capDrop: list[str]
    securityOpt: list[str]
    labels: dict[str, str]


@dataclass(slots=True)
class ContainerOutcome:
    """Result of running a container to completion.

    Attributes:
        containerId: Docker container ID.
        exitCode: Process exit code, or None if not available.
        signal: Termination signal name, or None.
        oomKilled: True if the container was killed due to out-of-memory.
        inspects: Raw Docker inspect output for the container.
    """

    containerId: str
    exitCode: int | None
    signal: str | None
    oomKilled: bool
    inspects: dict[str, Any]


@dataclass(slots=True)
class ManagedContainerInfo:
    """Metadata about a managed container.

    Attributes:
        containerId: Docker container ID.
        name: Container name.
        labels: Key-value labels attached to the container.
        status: Container status string (e.g. ``"running"``, ``"exited"``).
        createdAt: ISO-8601 timestamp when the container was created.
    """

    containerId: str
    name: str
    labels: dict[str, str]
    status: str
    createdAt: str
