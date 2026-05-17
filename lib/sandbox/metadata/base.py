"""Protocol and dataclasses for sandbox metadata persistence.

Defines the :class:`MetadataStore` protocol that every persistence backend
(filesystem, database) must implement, along with the record dataclasses
used to represent sessions, runs, and runtime metadata on disk.

Classes:
    SessionRecord: Persisted form of SessionInfo with internal bookkeeping.
    RunRecord: Persisted form of RunInfo.
    RuntimeRecord: Persisted form of RuntimeInfo.
    MetadataStore: Protocol for persistence backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from lib.sandbox.enums import RuntimeName

if TYPE_CHECKING:
    from lib.sandbox.types import RunInfo, SessionInfo


@dataclass(slots=True)
class SessionRecord:
    """Persisted form of SessionInfo with internal bookkeeping.

    Attributes:
        sessionId: Unique identifier for the session.
        sessionHash: Hash of the session configuration for deduplication.
        runtime: Runtime environment used by this session.
        workspacePath: Host-side path to the workspace directory.
        createdAt: Timestamp when the session was created.
        updatedAt: Timestamp when the session was last updated.
        expiresAt: Timestamp when the session will expire.
        metadata: Opaque key-value pairs controlled by the caller.
        schemaVersion: Schema version for forward-compatible migrations.
    """

    sessionId: str
    sessionHash: str
    runtime: RuntimeName
    workspacePath: str
    createdAt: datetime
    updatedAt: datetime
    expiresAt: datetime
    metadata: dict[str, str]
    schemaVersion: int = 1

    def toSessionInfo(self) -> SessionInfo:
        """Convert this record to a SessionInfo.

        Returns:
            A SessionInfo instance.
        """
        from lib.sandbox.types import SessionInfo

        return SessionInfo(
            sessionId=self.sessionId,
            runtime=self.runtime,
            workspacePath=self.workspacePath,
            createdAt=self.createdAt,
            updatedAt=self.updatedAt,
            expiresAt=self.expiresAt,
            metadata=self.metadata,
        )


@dataclass(slots=True)
class RunRecord:
    """Persisted form of RunInfo.

    Attributes:
        runId: Unique identifier for the run.
        sessionId: Session that owns this run.
        runtime: Runtime environment used for this run.
        startedAt: Timestamp when the run started.
        finishedAt: Timestamp when the run finished, or None if still running.
        status: Current status of the run (``"queued"``, ``"running"``,
            ``"completed"``, ``"failed"``, ``"cancelled"``).
        exitCode: Process exit code, or None if not yet available.
        schemaVersion: Schema version for forward-compatible migrations.
    """

    runId: str
    sessionId: str
    runtime: RuntimeName
    startedAt: datetime
    finishedAt: datetime | None
    status: str
    exitCode: int | None
    schemaVersion: int = 1

    def toRunInfo(self) -> RunInfo:
        """Convert this record to a RunInfo.

        Returns:
            A RunInfo instance.
        """
        from typing import Literal, cast

        from lib.sandbox.types import RunInfo

        return RunInfo(
            runId=self.runId,
            sessionId=self.sessionId,
            runtime=self.runtime,
            startedAt=self.startedAt,
            finishedAt=self.finishedAt,
            status=cast(Literal["queued", "running", "completed", "failed", "cancelled"], self.status),
            exitCode=self.exitCode,
        )


@dataclass(slots=True)
class RuntimeRecord:
    """Persisted form of runtime metadata.

    Attributes:
        runtime: Runtime identifier (use ``runtime`` not ``name`` per the
            metadata store interface).
        runImageTag: Docker image tag used for execution.
        installImageTag: Docker image tag used for library installation.
        libPoolPath: Host-side path to the pre-installed library pool.
        libPoolVersion: SHA-256 hash of the library pool contents.
        packageCount: Number of pre-installed packages in the pool.
        schemaVersion: Schema version for forward-compatible migrations.
    """

    runtime: RuntimeName
    runImageTag: str
    installImageTag: str
    libPoolPath: str
    libPoolVersion: str
    packageCount: int
    schemaVersion: int = 1


class MetadataStore(Protocol):
    """Protocol for persistence backends (filesystem, database).

    Every metadata store must implement this interface so that
    :class:`SandboxManager` can persist and recover session, run, and
    runtime state without knowing the concrete storage mechanism.
    """

    async def loadSession(self, sessionId: str) -> SessionRecord | None:
        """Load a session record by ID.

        Args:
            sessionId: Unique identifier for the session.

        Returns:
            The session record, or None if not found.
        """
        ...

    async def saveSession(self, record: SessionRecord) -> None:
        """Persist a session record.

        Args:
            record: The session record to save.

        Returns:
            None
        """
        ...

    async def deleteSession(self, sessionId: str) -> None:
        """Delete a session record by ID.

        Args:
            sessionId: Unique identifier for the session.

        Returns:
            None
        """
        ...

    async def listSessions(self, *, runtime: RuntimeName | None = None) -> list[SessionRecord]:
        """List session records, optionally filtered by runtime.

        Args:
            runtime: If provided, only return sessions for this runtime.

        Returns:
            List of matching session records.
        """
        ...

    async def loadRun(self, runId: str) -> RunRecord | None:
        """Load a run record by ID.

        Args:
            runId: Unique identifier for the run.

        Returns:
            The run record, or None if not found.
        """
        ...

    async def saveRun(self, record: RunRecord) -> None:
        """Persist a run record.

        Args:
            record: The run record to save.

        Returns:
            None
        """
        ...

    async def deleteRun(self, runId: str) -> None:
        """Delete a run record by ID.

        Args:
            runId: Unique identifier for the run.

        Returns:
            None
        """
        ...

    async def listRunsForSession(self, sessionId: str) -> list[RunRecord]:
        """List all run records for a given session.

        Args:
            sessionId: Unique identifier for the parent session.

        Returns:
            List of run records belonging to the session.
        """
        ...

    async def loadRuntime(self, runtime: RuntimeName) -> RuntimeRecord | None:
        """Load a runtime record by name.

        Args:
            runtime: Runtime identifier to look up.

        Returns:
            The runtime record, or None if not found.
        """
        ...

    async def saveRuntime(self, record: RuntimeRecord) -> None:
        """Persist a runtime record.

        Args:
            record: The runtime record to save.

        Returns:
            None
        """
        ...
