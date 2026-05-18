"""Filesystem-backed metadata store for sandbox sessions, runs, and runtimes.

Implements the :class:`MetadataStore` protocol using JSON files stored under
``${rootDir}/meta/`` with the layout::

    meta/sessions/<sessionHash>.json
    meta/runs/<runId>.json
    meta/runtimes/<runtimeName>.json

All writes go through :func:`atomicWriteJson` for crash safety.  Per-key
:class:`asyncio.Lock` instances serialise concurrent writes to the same record
so that overlapping ``saveSession`` / ``saveRun`` / ``saveRuntime`` calls never
leave a file in a partially-written state.

Classes:
    FilesystemMetadataStore: MetadataStore implementation backed by JSON files.
"""

import asyncio
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import List

from lib.utils import TTLDict

from ..enums import RuntimeName
from ..storage import atomicWriteJson, sessionHash
from ..types import PackageInfo, RunInfo, SessionInfo
from .base import MetadataStore

logger = logging.getLogger(__name__)


class FilesystemMetadataStore(MetadataStore):
    """MetadataStore implementation backed by JSON files on the host filesystem.

    Records are stored under ``${rootDir}/meta/`` with the layout::

        sessions/<sessionHash>.json
        runs/<runId>.json
        runtimes/<runtimeName>.json

    All writes go through :func:`atomicWriteJson` for crash safety.
    Per-key :class:`asyncio.Lock` serialises concurrent writes to the same
    record.

    Args:
        rootDir: The sandbox storage root directory.
        tmpDir: Directory for temporary files during atomic writes.
    """

    def __init__(self, rootDir: Path, tmpDir: Path) -> None:
        """Initialise the filesystem metadata store.

        Args:
            rootDir: The sandbox storage root directory.
            tmpDir: Directory for temporary files during atomic writes.
        """
        self._rootDir = rootDir
        self._tmpDir = tmpDir
        self._metaDir = rootDir / "meta"
        self._locks: TTLDict[str, asyncio.Lock] = TTLDict[str, asyncio.Lock]().setDefaultTTL(300).setGCTimeout(600)

    # ---- Private helpers ----

    def _getLock(self, key: str) -> asyncio.Lock:
        """Get or create a per-key asyncio.Lock for serialising writes.

        Args:
            key: The lock key (e.g., sessionId, runId).

        Returns:
            The asyncio.Lock for this key.
        """
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _sessionPath(self, sessionId: str) -> Path:
        """Get the JSON file path for a session record.

        Args:
            sessionId: The session identifier.

        Returns:
            The file path.
        """
        return self._metaDir / "sessions" / f"{sessionHash(sessionId)}.json"

    def _runPath(self, runId: str) -> Path:
        """Get the JSON file path for a run record.

        Args:
            runId: The run identifier.

        Returns:
            The file path.
        """
        return self._metaDir / "runs" / f"{runId}.json"

    def _runtimePath(self, runtime: RuntimeName) -> Path:
        """Get the JSON file path for a runtime record.

        Args:
            runtime: The runtime name.

        Returns:
            The file path.
        """
        return self._metaDir / "runtimes" / f"{runtime.value}.json"

    def _readJsonFile(self, path: Path) -> dict | None:
        """Read and parse a JSON file. Returns None if the file doesn't exist.

        Args:
            path: The file path.

        Returns:
            The parsed dict, or None.
        """
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read metadata file: %s", path, exc_info=True)
            return None

    # ---- Session operations ----

    async def loadSession(self, sessionId: str) -> SessionInfo | None:
        """Load a session record from disk.

        Args:
            sessionId: The session identifier.

        Returns:
            The SessionRecord, or None if not found or malformed.
        """
        data = self._readJsonFile(self._sessionPath(sessionId))
        if data is None:
            return None
        try:
            return SessionInfo.fromDict(data)
        except (KeyError, ValueError) as exc:
            logger.warning("Malformed session record for %s: %s", sessionId, exc)
            return None

    async def saveSession(self, record: SessionInfo) -> None:
        """Atomically save a session record to disk.

        Args:
            record: The session record to persist.
        """
        path = self._sessionPath(record.sessionId)
        async with self._getLock(record.sessionId):
            atomicWriteJson(
                path,
                record.toDict(),
                tmpDir=self._tmpDir,
            )

    async def deleteSession(self, sessionId: str) -> None:
        """Delete a session record from disk.

        Args:
            sessionId: The session identifier.
        """
        path = self._sessionPath(sessionId)
        async with self._getLock(sessionId):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to delete session file: %s", path, exc_info=True)

    async def listSessions(self) -> list[str]:
        """List all sessions.

        Returns:
            List of session IDs.
        """
        sessionsDir = self._metaDir / "sessions"
        if not sessionsDir.exists():
            return []
        records: list[str] = []
        for f in sessionsDir.glob("*.json"):
            data = self._readJsonFile(f)
            if not isinstance(data, dict):
                logger.warning(f"Session file {f} is not valid json file")
                continue
            try:
                record = SessionInfo.fromDict(data)
                records.append(record.sessionId)
            except (KeyError, ValueError):
                logger.warning(f"Skipping malformed session file: {f}")
        return records

    # ---- Run operations ----

    async def loadRun(self, runId: str) -> RunInfo | None:
        """Load a run record from disk.

        Args:
            runId: The run identifier.

        Returns:
            The RunRecord, or None if not found or malformed.
        """
        data = self._readJsonFile(self._runPath(runId))
        if data is None:
            return None
        try:
            return RunInfo.fromDict(data)
        except (KeyError, ValueError) as exc:
            logger.warning("Malformed run record for %s: %s", runId, exc)
            return None

    async def saveRun(self, record: RunInfo) -> None:
        """Atomically save a run record to disk.

        Args:
            record: The run record to persist.
        """
        path = self._runPath(record.runId)
        async with self._getLock(record.runId):
            atomicWriteJson(
                path,
                record.toDict(),
                tmpDir=self._tmpDir,
            )

    async def deleteRun(self, runId: str) -> None:
        """Delete a run record from disk.

        Args:
            runId: The run identifier.
        """
        path = self._runPath(runId)
        async with self._getLock(runId):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to delete run file: %s", path, exc_info=True)

    async def listRunsForSession(self, sessionId: str) -> list[RunInfo]:
        """List all runs for a given session.

        Args:
            sessionId: The session identifier.

        Returns:
            List of run records for this session.
        """
        runsDir = self._metaDir / "runs"
        if not runsDir.exists():
            return []
        records: list[RunInfo] = []
        for f in runsDir.glob("*.json"):
            data = self._readJsonFile(f)
            if data is None:
                continue
            try:
                record = RunInfo.fromDict(data)
                if record.sessionId == sessionId:
                    records.append(record)
            except (KeyError, ValueError):
                logger.warning("Skipping malformed run file: %s", f)
        return records

    def _packagesInfoPath(self, runtime: RuntimeName) -> Path:
        """Get the JSON file path for runtime package information.

        Args:
            runtime: The runtime name.

        Returns:
            The file path for package info JSON.
        """
        return self._metaDir / "runtimes" / runtime.value / "packages.json"

    async def loadPackagesInfo(self, runtime: RuntimeName) -> List[PackageInfo]:
        """Load installed package information for a runtime.

        Args:
            runtime: The runtime to load package info for.

        Returns:
            List of PackageInfo for installed packages. Returns empty list if
            no package information is available or on parse errors.
        """
        data = self._readJsonFile(self._packagesInfoPath(runtime))
        if data is None:
            return []
        try:
            return [PackageInfo.fromDict(v) for v in data]
        except (KeyError, ValueError) as exc:
            logger.warning("Malformed packages record for %s: %s", runtime, exc)
            return []

    async def savePackagesInfo(self, runtime: RuntimeName, packagesInfo: Sequence[PackageInfo]) -> None:
        """Save installed package information for a runtime.

        Args:
            runtime: The runtime to save package info for.
            packagesInfo: List of PackageInfo to save.
        """
        async with self._getLock(runtime.value):
            atomicWriteJson(
                self._packagesInfoPath(runtime),
                [v.toDict() for v in packagesInfo],
                tmpDir=self._tmpDir,
            )
