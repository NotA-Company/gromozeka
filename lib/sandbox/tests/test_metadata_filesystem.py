"""Tests for FilesystemMetadataStore (lib.sandbox.metadata.filesystem).

Covers:
- CRUD round-trip for SessionRecord, RunRecord, RuntimeRecord.
- Delete operations remove records from disk.
- listSessions with and without runtime filter.
- listRunsForSession filters by sessionId.
- Concurrent writes via asyncio.gather serialise per-key.
- Malformed JSON files return None without crashing.
- Schema version mismatch (schemaVersion=99) still loads.
- Missing files return None.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lib.sandbox.enums import RuntimeName
from lib.sandbox.metadata.base import RunRecord, RuntimeRecord, SessionRecord
from lib.sandbox.metadata.filesystem import FilesystemMetadataStore
from lib.sandbox.storage import sessionHash

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def store(tmp_path: Path) -> FilesystemMetadataStore:
    """Create a FilesystemMetadataStore backed by a temp directory.

    Args:
        tmp_path: pytest-provided temporary directory.

    Returns:
        A FilesystemMetadataStore instance with directories initialised.
    """
    rootDir = tmp_path / "sandbox"
    tmpDir = tmp_path / "tmp"
    rootDir.mkdir()
    tmpDir.mkdir()
    # Create the meta subdirectories that the store expects.
    (rootDir / "meta" / "sessions").mkdir(parents=True)
    (rootDir / "meta" / "runs").mkdir(parents=True)
    (rootDir / "meta" / "runtimes").mkdir(parents=True)
    return FilesystemMetadataStore(rootDir=rootDir, tmpDir=tmpDir)


def _makeSessionRecord(
    sessionId: str = "session-1",
    runtime: RuntimeName = RuntimeName.PYTHON,
    metadata: dict[str, str] | None = None,
    schemaVersion: int = 1,
    workspacePath: str | None = None,
) -> SessionRecord:
    """Create a SessionRecord with sensible defaults for testing.

    Args:
        sessionId: The session identifier.
        runtime: The runtime name.
        metadata: Optional metadata dict.
        schemaVersion: Schema version number.
        workspacePath: Optional workspace path; defaults to /workspace/{sessionId}.

    Returns:
        A SessionRecord instance.
    """
    now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    return SessionRecord(
        sessionId=sessionId,
        sessionHash=sessionHash(sessionId),
        runtime=runtime,
        workspacePath=workspacePath if workspacePath is not None else f"/workspace/{sessionId}",
        createdAt=now,
        updatedAt=now,
        expiresAt=datetime(2025, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
        metadata=metadata if metadata is not None else {},
        schemaVersion=schemaVersion,
    )


_SENTINEL = object()


def _makeRunRecord(
    runId: str = "run-1",
    sessionId: str = "session-1",
    runtime: RuntimeName = RuntimeName.PYTHON,
    status: str = "completed",
    finishedAt: datetime | None | object = _SENTINEL,
    exitCode: int | None = 0,
    schemaVersion: int = 1,
) -> RunRecord:
    """Create a RunRecord with sensible defaults for testing.

    Args:
        runId: The run identifier.
        sessionId: The parent session identifier.
        runtime: The runtime name.
        status: Run status string.
        finishedAt: Timestamp when the run finished, None for running, or
            unset (defaults to a timestamp 5 seconds after startedAt).
        exitCode: Process exit code, or None.
        schemaVersion: Schema version number.

    Returns:
        A RunRecord instance.
    """
    startedAt = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    if finishedAt is _SENTINEL:
        finishedAt = datetime(2025, 1, 15, 12, 0, 5, tzinfo=timezone.utc)
    return RunRecord(
        runId=runId,
        sessionId=sessionId,
        runtime=runtime,
        startedAt=startedAt,
        finishedAt=finishedAt,  # type: ignore[arg-type]
        status=status,
        exitCode=exitCode,
        schemaVersion=schemaVersion,
    )


def _makeRuntimeRecord(
    runtime: RuntimeName = RuntimeName.PYTHON,
    schemaVersion: int = 1,
) -> RuntimeRecord:
    """Create a RuntimeRecord with sensible defaults for testing.

    Args:
        runtime: The runtime name.
        schemaVersion: Schema version number.

    Returns:
        A RuntimeRecord instance.
    """
    return RuntimeRecord(
        runtime=runtime,
        runImageTag="gromozeka-sandbox-python:run",
        installImageTag="gromozeka-sandbox-python:install",
        libPoolPath="/pool/python",
        libPoolVersion="abc123def456",
        packageCount=42,
        schemaVersion=schemaVersion,
    )


# ============================================================================
# SessionRecord CRUD
# ============================================================================


class TestSessionCrud:
    """CRUD round-trip tests for SessionRecord."""

    async def testSaveAndLoadRoundTrip(self, store: FilesystemMetadataStore) -> None:
        """Saving then loading a SessionRecord preserves all fields.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        record = _makeSessionRecord()
        await store.saveSession(record)
        loaded = await store.loadSession(record.sessionId)

        assert loaded is not None
        assert loaded.sessionId == record.sessionId
        assert loaded.sessionHash == record.sessionHash
        assert loaded.runtime == record.runtime
        assert loaded.workspacePath == record.workspacePath
        assert loaded.createdAt == record.createdAt
        assert loaded.updatedAt == record.updatedAt
        assert loaded.expiresAt == record.expiresAt
        assert loaded.metadata == record.metadata
        assert loaded.schemaVersion == record.schemaVersion

    async def testSaveWithMetadataRoundTrip(self, store: FilesystemMetadataStore) -> None:
        """SessionRecord with non-empty metadata round-trips correctly.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        record = _makeSessionRecord(metadata={"key1": "value1", "key2": "value2"})
        await store.saveSession(record)
        loaded = await store.loadSession(record.sessionId)

        assert loaded is not None
        assert loaded.metadata == {"key1": "value1", "key2": "value2"}

    async def testDeleteSession(self, store: FilesystemMetadataStore) -> None:
        """Deleting a session record removes it from disk.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        record = _makeSessionRecord()
        await store.saveSession(record)
        assert await store.loadSession(record.sessionId) is not None

        await store.deleteSession(record.sessionId)
        assert await store.loadSession(record.sessionId) is None

    async def testDeleteNonexistentSession(self, store: FilesystemMetadataStore) -> None:
        """Deleting a session that doesn't exist does not raise.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        # Should not raise.
        await store.deleteSession("nonexistent-session")

    async def testLoadMissingSession(self, store: FilesystemMetadataStore) -> None:
        """Loading a session that doesn't exist returns None.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        result = await store.loadSession("no-such-session")
        assert result is None


# ============================================================================
# RunRecord CRUD
# ============================================================================


class TestRunCrud:
    """CRUD round-trip tests for RunRecord."""

    async def testSaveAndLoadRoundTrip(self, store: FilesystemMetadataStore) -> None:
        """Saving then loading a RunRecord preserves all fields.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        record = _makeRunRecord()
        await store.saveRun(record)
        loaded = await store.loadRun(record.runId)

        assert loaded is not None
        assert loaded.runId == record.runId
        assert loaded.sessionId == record.sessionId
        assert loaded.runtime == record.runtime
        assert loaded.startedAt == record.startedAt
        assert loaded.finishedAt == record.finishedAt
        assert loaded.status == record.status
        assert loaded.exitCode == record.exitCode
        assert loaded.schemaVersion == record.schemaVersion

    async def testRunWithNullFinishedAt(self, store: FilesystemMetadataStore) -> None:
        """A RunRecord with finishedAt=None round-trips correctly.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        record = _makeRunRecord(finishedAt=None, exitCode=None, status="running")
        await store.saveRun(record)
        loaded = await store.loadRun(record.runId)

        assert loaded is not None
        assert loaded.finishedAt is None
        assert loaded.exitCode is None
        assert loaded.status == "running"

    async def testDeleteRun(self, store: FilesystemMetadataStore) -> None:
        """Deleting a run record removes it from disk.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        record = _makeRunRecord()
        await store.saveRun(record)
        assert await store.loadRun(record.runId) is not None

        await store.deleteRun(record.runId)
        assert await store.loadRun(record.runId) is None

    async def testDeleteNonexistentRun(self, store: FilesystemMetadataStore) -> None:
        """Deleting a run that doesn't exist does not raise.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        await store.deleteRun("nonexistent-run")

    async def testLoadMissingRun(self, store: FilesystemMetadataStore) -> None:
        """Loading a run that doesn't exist returns None.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        result = await store.loadRun("no-such-run")
        assert result is None


# ============================================================================
# RuntimeRecord CRUD
# ============================================================================


class TestRuntimeCrud:
    """CRUD round-trip tests for RuntimeRecord."""

    async def testSaveAndLoadRoundTrip(self, store: FilesystemMetadataStore) -> None:
        """Saving then loading a RuntimeRecord preserves all fields.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        record = _makeRuntimeRecord()
        await store.saveRuntime(record)
        loaded = await store.loadRuntime(record.runtime)

        assert loaded is not None
        assert loaded.runtime == record.runtime
        assert loaded.runImageTag == record.runImageTag
        assert loaded.installImageTag == record.installImageTag
        assert loaded.libPoolPath == record.libPoolPath
        assert loaded.libPoolVersion == record.libPoolVersion
        assert loaded.packageCount == record.packageCount
        assert loaded.schemaVersion == record.schemaVersion

    async def testLoadMissingRuntime(self, store: FilesystemMetadataStore) -> None:
        """Loading a runtime that doesn't exist returns None.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        result = await store.loadRuntime(RuntimeName.PYTHON)
        assert result is None


# ============================================================================
# List sessions
# ============================================================================


class TestListSessions:
    """Tests for listSessions with and without runtime filtering."""

    async def testListSessionsEmpty(self, store: FilesystemMetadataStore) -> None:
        """Listing sessions when none exist returns an empty list.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        result = await store.listSessions()
        assert result == []

    async def testListSessionsAll(self, store: FilesystemMetadataStore) -> None:
        """listSessions returns all saved sessions.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        s1 = _makeSessionRecord(sessionId="s1")
        s2 = _makeSessionRecord(sessionId="s2")
        s3 = _makeSessionRecord(sessionId="s3")
        await store.saveSession(s1)
        await store.saveSession(s2)
        await store.saveSession(s3)

        result = await store.listSessions()
        ids = {r.sessionId for r in result}
        assert ids == {"s1", "s2", "s3"}

    async def testListSessionsFilterByRuntime(self, store: FilesystemMetadataStore) -> None:
        """listSessions with runtime filter returns only matching sessions.

        Since RuntimeName currently only has PYTHON, we verify that filtering
        by PYTHON returns the expected sessions and that the filter parameter
        is wired through correctly.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        s1 = _makeSessionRecord(sessionId="s-python-1", runtime=RuntimeName.PYTHON)
        s2 = _makeSessionRecord(sessionId="s-python-2", runtime=RuntimeName.PYTHON)
        await store.saveSession(s1)
        await store.saveSession(s2)

        # Filtered by PYTHON returns both.
        pythonSessions = await store.listSessions(runtime=RuntimeName.PYTHON)
        pythonIds = {r.sessionId for r in pythonSessions}
        assert pythonIds == {"s-python-1", "s-python-2"}

        # Unfiltered also returns both.
        allSessions = await store.listSessions()
        assert len(allSessions) == 2


# ============================================================================
# List runs for session
# ============================================================================


class TestListRunsForSession:
    """Tests for listRunsForSession filtering."""

    async def testListRunsEmpty(self, store: FilesystemMetadataStore) -> None:
        """Listing runs when none exist returns an empty list.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        result = await store.listRunsForSession("session-1")
        assert result == []

    async def testListRunsFiltersBySession(self, store: FilesystemMetadataStore) -> None:
        """listRunsForSession returns only runs belonging to the given session.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        r1 = _makeRunRecord(runId="r1", sessionId="session-a")
        r2 = _makeRunRecord(runId="r2", sessionId="session-a")
        r3 = _makeRunRecord(runId="r3", sessionId="session-b")
        await store.saveRun(r1)
        await store.saveRun(r2)
        await store.saveRun(r3)

        runsA = await store.listRunsForSession("session-a")
        idsA = {r.runId for r in runsA}
        assert idsA == {"r1", "r2"}

        runsB = await store.listRunsForSession("session-b")
        idsB = {r.runId for r in runsB}
        assert idsB == {"r3"}


# ============================================================================
# Concurrent writes
# ============================================================================


class TestConcurrentWrites:
    """Tests for concurrent write serialisation via asyncio.Lock."""

    async def testConcurrentSaveSessionSameId(self, store: FilesystemMetadataStore) -> None:
        """Concurrent saveSession calls for the same sessionId serialise correctly.

        The final record on disk should be one of the written values (the last
        one to acquire the lock wins).

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        sessionId = "concurrent-session"
        records = [_makeSessionRecord(sessionId=sessionId, workspacePath=f"/workspace/{i}") for i in range(10)]

        await asyncio.gather(*(store.saveSession(r) for r in records))

        loaded = await store.loadSession(sessionId)
        assert loaded is not None
        assert loaded.sessionId == sessionId
        # The final workspacePath must be one of the written values.
        assert loaded.workspacePath.startswith("/workspace/")
        assert int(loaded.workspacePath.split("/")[-1]) in range(10)

    async def testConcurrentSaveRunSameId(self, store: FilesystemMetadataStore) -> None:
        """Concurrent saveRun calls for the same runId serialise correctly.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        runId = "concurrent-run"
        records = [_makeRunRecord(runId=runId, sessionId=f"session-{i}") for i in range(10)]

        await asyncio.gather(*(store.saveRun(r) for r in records))

        loaded = await store.loadRun(runId)
        assert loaded is not None
        assert loaded.runId == runId
        assert loaded.sessionId.startswith("session-")


# ============================================================================
# Malformed JSON recovery
# ============================================================================


class TestMalformedJson:
    """Tests for graceful handling of malformed JSON files."""

    async def testMalformedSessionJson(self, store: FilesystemMetadataStore) -> None:
        """A malformed session JSON file returns None without crashing.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        path = store._sessionPath("broken-session")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{invalid json!!!")

        result = await store.loadSession("broken-session")
        assert result is None

    async def testMalformedRunJson(self, store: FilesystemMetadataStore) -> None:
        """A malformed run JSON file returns None without crashing.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        path = store._runPath("broken-run")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json at all")

        result = await store.loadRun("broken-run")
        assert result is None

    async def testMalformedRuntimeJson(self, store: FilesystemMetadataStore) -> None:
        """A malformed runtime JSON file returns None without crashing.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        path = store._runtimePath(RuntimeName.PYTHON)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

        result = await store.loadRuntime(RuntimeName.PYTHON)
        assert result is None

    async def testSessionJsonMissingRequiredField(self, store: FilesystemMetadataStore) -> None:
        """A session JSON missing a required field returns None.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        path = store._sessionPath("missing-fields")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write valid JSON but missing required fields.
        path.write_text(json.dumps({"sessionId": "missing-fields"}))

        result = await store.loadSession("missing-fields")
        assert result is None

    async def testMalformedSessionSkippedInList(self, store: FilesystemMetadataStore) -> None:
        """Malformed session files are skipped during listSessions.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        # Save a valid session.
        good = _makeSessionRecord(sessionId="good-session")
        await store.saveSession(good)

        # Write a broken file directly.
        brokenPath = store._sessionPath("broken-session")
        brokenPath.parent.mkdir(parents=True, exist_ok=True)
        brokenPath.write_text("not json")

        result = await store.listSessions()
        assert len(result) == 1
        assert result[0].sessionId == "good-session"


# ============================================================================
# Schema version mismatch
# ============================================================================


class TestSchemaVersionMismatch:
    """Tests for forward-compatible schema version handling."""

    async def testSessionWithHighSchemaVersion(self, store: FilesystemMetadataStore) -> None:
        """A session with schemaVersion=99 still loads (no version validation yet).

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        record = _makeSessionRecord(sessionId="future-session", schemaVersion=99)
        await store.saveSession(record)
        loaded = await store.loadSession("future-session")

        assert loaded is not None
        assert loaded.schemaVersion == 99
        assert loaded.sessionId == "future-session"

    async def testRunWithHighSchemaVersion(self, store: FilesystemMetadataStore) -> None:
        """A run with schemaVersion=99 still loads.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        record = _makeRunRecord(runId="future-run", schemaVersion=99)
        await store.saveRun(record)
        loaded = await store.loadRun("future-run")

        assert loaded is not None
        assert loaded.schemaVersion == 99

    async def testRuntimeWithHighSchemaVersion(self, store: FilesystemMetadataStore) -> None:
        """A runtime with schemaVersion=99 still loads.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        record = _makeRuntimeRecord(schemaVersion=99)
        await store.saveRuntime(record)
        loaded = await store.loadRuntime(RuntimeName.PYTHON)

        assert loaded is not None
        assert loaded.schemaVersion == 99


# ============================================================================
# Missing file returns None
# ============================================================================


class TestMissingFiles:
    """Tests for loading records that don't exist on disk."""

    async def testLoadMissingSession(self, store: FilesystemMetadataStore) -> None:
        """Loading a session that doesn't exist returns None.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        assert await store.loadSession("nonexistent") is None

    async def testLoadMissingRun(self, store: FilesystemMetadataStore) -> None:
        """Loading a run that doesn't exist returns None.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        assert await store.loadRun("nonexistent") is None

    async def testLoadMissingRuntime(self, store: FilesystemMetadataStore) -> None:
        """Loading a runtime that doesn't exist returns None.

        Args:
            store: The FilesystemMetadataStore fixture.

        Returns:
            None
        """
        assert await store.loadRuntime(RuntimeName.PYTHON) is None
