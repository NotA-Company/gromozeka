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
from dataclasses import fields as dataclassFields
from datetime import datetime
from pathlib import Path

from lib.sandbox.enums import RuntimeName
from lib.sandbox.metadata.base import RunRecord, RuntimeRecord, SessionRecord
from lib.sandbox.storage import atomicWriteJson, sessionHash

logger = logging.getLogger(__name__)


class FilesystemMetadataStore:
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
        self._locks: dict[str, asyncio.Lock] = {}

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

    def _serializeRecord(self, record: SessionRecord | RunRecord | RuntimeRecord) -> dict:
        """Convert a record dataclass to a JSON-serializable dict.

        Handles datetime → ISO format string and enum → string.

        Args:
            record: The record to serialize.

        Returns:
            A JSON-serializable dict.
        """
        data: dict = {}
        for field in dataclassFields(record):
            fieldValue = getattr(record, field.name)
            if isinstance(fieldValue, datetime):
                data[field.name] = fieldValue.isoformat()
            elif isinstance(fieldValue, RuntimeName):
                data[field.name] = fieldValue.value
            else:
                data[field.name] = fieldValue
        return data

    def _deserializeSessionRecord(self, data: dict) -> SessionRecord:
        """Convert a JSON dict back to a SessionRecord.

        Args:
            data: The raw dict from JSON.

        Returns:
            A SessionRecord instance.
        """
        return SessionRecord(
            sessionId=data["sessionId"],
            sessionHash=data["sessionHash"],
            runtime=RuntimeName(data["runtime"]),
            workspacePath=data["workspacePath"],
            createdAt=datetime.fromisoformat(data["createdAt"]),
            updatedAt=datetime.fromisoformat(data["updatedAt"]),
            expiresAt=datetime.fromisoformat(data["expiresAt"]),
            metadata=data.get("metadata", {}),
            schemaVersion=data.get("schemaVersion", 1),
        )

    def _deserializeRunRecord(self, data: dict) -> RunRecord:
        """Convert a JSON dict back to a RunRecord.

        Args:
            data: The raw dict from JSON.

        Returns:
            A RunRecord instance.
        """
        finishedAt = data.get("finishedAt")
        exitCode = data.get("exitCode")
        return RunRecord(
            runId=data["runId"],
            sessionId=data["sessionId"],
            runtime=RuntimeName(data["runtime"]),
            startedAt=datetime.fromisoformat(data["startedAt"]),
            finishedAt=datetime.fromisoformat(finishedAt) if finishedAt else None,
            status=data["status"],
            exitCode=exitCode if exitCode is not None else None,
            schemaVersion=data.get("schemaVersion", 1),
        )

    def _deserializeRuntimeRecord(self, data: dict) -> RuntimeRecord:
        """Convert a JSON dict back to a RuntimeRecord.

        Args:
            data: The raw dict from JSON.

        Returns:
            A RuntimeRecord instance.
        """
        return RuntimeRecord(
            runtime=RuntimeName(data["runtime"]),
            runImageTag=data["runImageTag"],
            installImageTag=data["installImageTag"],
            libPoolPath=data["libPoolPath"],
            libPoolVersion=data["libPoolVersion"],
            packageCount=data["packageCount"],
            schemaVersion=data.get("schemaVersion", 1),
        )

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

    async def loadSession(self, sessionId: str) -> SessionRecord | None:
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
            return self._deserializeSessionRecord(data)
        except (KeyError, ValueError) as exc:
            logger.warning("Malformed session record for %s: %s", sessionId, exc)
            return None

    async def saveSession(self, record: SessionRecord) -> None:
        """Atomically save a session record to disk.

        Args:
            record: The session record to persist.
        """
        path = self._sessionPath(record.sessionId)
        async with self._getLock(record.sessionId):
            await asyncio.to_thread(
                atomicWriteJson,
                path,
                self._serializeRecord(record),
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

    async def listSessions(self, *, runtime: RuntimeName | None = None) -> list[SessionRecord]:
        """List all sessions, optionally filtered by runtime.

        Args:
            runtime: If set, only return sessions for this runtime.

        Returns:
            List of session records.
        """
        sessionsDir = self._metaDir / "sessions"
        if not sessionsDir.exists():
            return []
        records: list[SessionRecord] = []
        for f in sessionsDir.glob("*.json"):
            data = self._readJsonFile(f)
            if data is None:
                continue
            try:
                record = self._deserializeSessionRecord(data)
                if runtime is None or record.runtime == runtime:
                    records.append(record)
            except (KeyError, ValueError):
                logger.warning("Skipping malformed session file: %s", f)
        return records

    # ---- Run operations ----

    async def loadRun(self, runId: str) -> RunRecord | None:
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
            return self._deserializeRunRecord(data)
        except (KeyError, ValueError) as exc:
            logger.warning("Malformed run record for %s: %s", runId, exc)
            return None

    async def saveRun(self, record: RunRecord) -> None:
        """Atomically save a run record to disk.

        Args:
            record: The run record to persist.
        """
        path = self._runPath(record.runId)
        async with self._getLock(record.runId):
            await asyncio.to_thread(
                atomicWriteJson,
                path,
                self._serializeRecord(record),
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

    async def listRunsForSession(self, sessionId: str) -> list[RunRecord]:
        """List all runs for a given session.

        Args:
            sessionId: The session identifier.

        Returns:
            List of run records for this session.
        """
        runsDir = self._metaDir / "runs"
        if not runsDir.exists():
            return []
        records: list[RunRecord] = []
        for f in runsDir.glob("*.json"):
            data = self._readJsonFile(f)
            if data is None:
                continue
            try:
                record = self._deserializeRunRecord(data)
                if record.sessionId == sessionId:
                    records.append(record)
            except (KeyError, ValueError):
                logger.warning("Skipping malformed run file: %s", f)
        return records

    # ---- Runtime operations ----

    async def loadRuntime(self, runtime: RuntimeName) -> RuntimeRecord | None:
        """Load a runtime record from disk.

        Args:
            runtime: The runtime name.

        Returns:
            The RuntimeRecord, or None if not found or malformed.
        """
        data = self._readJsonFile(self._runtimePath(runtime))
        if data is None:
            return None
        try:
            return self._deserializeRuntimeRecord(data)
        except (KeyError, ValueError) as exc:
            logger.warning("Malformed runtime record for %s: %s", runtime, exc)
            return None

    async def saveRuntime(self, record: RuntimeRecord) -> None:
        """Atomically save a runtime record to disk.

        Args:
            record: The runtime record to persist.
        """
        path = self._runtimePath(record.runtime)
        async with self._getLock(f"runtime_{record.runtime.value}"):
            await asyncio.to_thread(
                atomicWriteJson,
                path,
                self._serializeRecord(record),
                tmpDir=self._tmpDir,
            )
