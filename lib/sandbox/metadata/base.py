"""Protocol and dataclasses for sandbox metadata persistence.

Defines the :class:`MetadataStore` protocol that every persistence backend
(filesystem, database) must implement, along with the :class:`SessionInfo`
dataclass used to represent session metadata on disk.

Classes:
    SessionInfo: Persisted metadata for a sandbox session.
    MetadataStore: Protocol for persistence backends (filesystem, database).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import List

from ..enums import RuntimeName
from ..types import PackageInfo, RunInfo, SessionInfo


class MetadataStore(ABC):
    """Protocol for persistence backends (filesystem, database).

    Every metadata store must implement this interface so that
    :class:`SandboxManager` can persist and recover session and run state
    without knowing the concrete storage mechanism.
    """

    @abstractmethod
    async def loadSession(self, sessionId: str) -> SessionInfo | None:
        """Load a session record by ID.

        Args:
            sessionId: Unique identifier for the session.

        Returns:
            The session record, or None if not found.
        """
        ...

    @abstractmethod
    async def saveSession(self, record: SessionInfo) -> None:
        """Persist a session record.

        Args:
            record: The session record to save.

        Returns:
            None
        """
        ...

    @abstractmethod
    async def deleteSession(self, sessionId: str) -> None:
        """Delete a session record by ID.

        Args:
            sessionId: Unique identifier for the session.

        Returns:
            None
        """
        ...

    @abstractmethod
    async def listSessions(self) -> list[str]:
        """List session records.

        Returns:
            List of session IDs.
        """
        ...

    @abstractmethod
    async def loadRun(self, runId: str) -> RunInfo | None:
        """Load a run record by ID.

        Args:
            runId: Unique identifier for the run.

        Returns:
            The run record, or None if not found.
        """
        ...

    @abstractmethod
    async def saveRun(self, record: RunInfo) -> None:
        """Persist a run record.

        Args:
            record: The run record to save.

        Returns:
            None
        """
        ...

    @abstractmethod
    async def deleteRun(self, runId: str) -> None:
        """Delete a run record by ID.

        Args:
            runId: Unique identifier for the run.

        Returns:
            None
        """
        ...

    @abstractmethod
    async def listRunsForSession(self, sessionId: str) -> List[RunInfo]:
        """List all run records for a given session.

        Args:
            sessionId: Unique identifier for the parent session.

        Returns:
            List of run records belonging to the session.
        """
        ...

    @abstractmethod
    async def loadPackagesInfo(self, runtime: RuntimeName) -> List[PackageInfo]:
        """Load installed package information for a runtime.

        Args:
            runtime: The runtime to load package info for.

        Returns:
            List of PackageInfo for installed packages.
        """
        ...

    @abstractmethod
    async def savePackagesInfo(self, runtime: RuntimeName, packagesInfo: Sequence[PackageInfo]) -> None:
        """Save installed package information for a runtime.

        Args:
            runtime: The runtime to save package info for.
            packagesInfo: List of PackageInfo to save.

        Returns:
            None
        """
        ...
