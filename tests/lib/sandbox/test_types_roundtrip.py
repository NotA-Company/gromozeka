"""Regression tests for toDict/fromDict round-trip correctness in sandbox types.

Covers:
- ResourceLimits: kebab-case key round-trip and default alignment.
- SessionInfo: datetime serialization and nested ResourceLimits round-trip.
- RunInfo: enum and datetime serialization round-trip.
- PackageInfo: simple string round-trip (baseline, should already work).

These tests exist because ``slottedObjectToDict`` produces camelCase keys
and raw Python objects (enums, datetimes), while ``fromDict`` expects
kebab-case keys (for ResourceLimits) and serialized values (ISO strings,
enum values).  The custom ``toDict`` methods on each class must produce
output that ``fromDict`` can parse back without data loss.
"""

from datetime import datetime, timezone

from lib.sandbox.enums import RunStatus, RuntimeName
from lib.sandbox.types import PackageInfo, ResourceLimits, RunInfo, RunResult, SessionInfo

# ============================================================================
# ResourceLimits
# ============================================================================


def testResourceLimitsRoundTripPreservesAllValues() -> None:
    """Verify that ResourceLimits.fromDict(rl.toDict()) preserves all fields.

    This is the core regression test for the camelCase/kebab-case mismatch:
    ``slottedObjectToDict`` used to produce ``memoryMb`` but ``fromDict``
    expected ``memory-mb``, causing all values to silently revert to defaults.
    """
    rl = ResourceLimits(
        memoryMb=1024,
        memorySwapMb=2048,
        cpuCount=2.0,
        pidsLimit=128,
        timeoutSeconds=60,
        timeoutGraceSeconds=15,
    )
    restored = ResourceLimits.fromDict(rl.toDict())
    assert restored.memoryMb == 1024
    assert restored.memorySwapMb == 2048
    assert restored.cpuCount == 2.0
    assert restored.pidsLimit == 128
    assert restored.timeoutSeconds == 60
    assert restored.timeoutGraceSeconds == 15


def testResourceLimitsRoundTripWithNoneSwap() -> None:
    """Verify that ResourceLimits round-trip preserves memorySwapMb=None.

    None is a valid value for memorySwapMb (meaning swap is disabled).
    toDict should omit it; fromDict should reconstruct it as None.
    """
    rl = ResourceLimits(memoryMb=512, memorySwapMb=None)
    d = rl.toDict()
    assert "memory-swap-mb" not in d
    restored = ResourceLimits.fromDict(d)
    assert restored.memorySwapMb is None


def testResourceLimitsToDictProducesKebabCaseKeys() -> None:
    """Verify that ResourceLimits.toDict() produces kebab-case keys."""
    rl = ResourceLimits()
    d = rl.toDict()
    assert "memory-mb" in d
    assert "cpu-count" in d
    assert "pids-limit" in d
    assert "timeout-seconds" in d
    assert "timeout-grace-seconds" in d
    # camelCase keys must NOT be present
    assert "memoryMb" not in d
    assert "cpuCount" not in d
    assert "pidsLimit" not in d
    assert "timeoutSeconds" not in d
    assert "timeoutGraceSeconds" not in d


def testResourceLimitsFromDictDefaultsMatchDataclassDefaults() -> None:
    """Verify that fromDict({}) produces the same values as ResourceLimits().

    Previously fromDict defaulted timeout-seconds to 60 and
    timeout-grace-seconds to 10, while the dataclass defaults were 30 and 5.
    """
    fromDefaults = ResourceLimits.fromDict({})
    dataclassDefaults = ResourceLimits()
    assert fromDefaults.memoryMb == dataclassDefaults.memoryMb
    assert fromDefaults.memorySwapMb == dataclassDefaults.memorySwapMb
    assert fromDefaults.cpuCount == dataclassDefaults.cpuCount
    assert fromDefaults.pidsLimit == dataclassDefaults.pidsLimit
    assert fromDefaults.timeoutSeconds == dataclassDefaults.timeoutSeconds
    assert fromDefaults.timeoutGraceSeconds == dataclassDefaults.timeoutGraceSeconds


def testResourceLimitsFromDictMinimumEnforcement() -> None:
    """Verify that fromDict enforces minimums for memory and timeout fields."""
    rl = ResourceLimits.fromDict(
        {
            "memory-mb": 1,
            "cpu-count": 0.01,
            "pids-limit": 1,
            "timeout-seconds": 5,
            "timeout-grace-seconds": -10,
        }
    )
    assert rl.memoryMb == 32  # min 32
    assert rl.cpuCount == 0.1  # min 0.1
    assert rl.pidsLimit == 8  # min 8
    assert rl.timeoutSeconds == 30  # min 30
    assert rl.timeoutGraceSeconds == 0  # min 0


# ============================================================================
# SessionInfo
# ============================================================================


def testSessionInfoRoundTripPreservesAllValues() -> None:
    """Verify that SessionInfo.fromDict(si.toDict()) preserves all fields.

    This tests both datetime serialization (ISO strings) and the nested
    ResourceLimits round-trip (kebab-case keys).
    """
    now = datetime(2025, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
    limits = ResourceLimits(memoryMb=2048, cpuCount=2.0, pidsLimit=128, timeoutSeconds=60, timeoutGraceSeconds=10)
    si = SessionInfo(
        sessionId="sess-abc123",
        sessionHash="hash_abc123",
        workspacePath="/tmp/workspace",
        createdAt=now,
        updatedAt=now,
        expiresAt=now,
        limits=limits,
        metadata={"key": "value"},
    )
    restored = SessionInfo.fromDict(si.toDict())
    assert restored.sessionId == "sess-abc123"
    assert restored.sessionHash == "hash_abc123"
    assert restored.workspacePath == "/tmp/workspace"
    assert restored.createdAt == now
    assert restored.updatedAt == now
    assert restored.expiresAt == now
    assert restored.limits.memoryMb == 2048
    assert restored.limits.cpuCount == 2.0
    assert restored.limits.pidsLimit == 128
    assert restored.limits.timeoutSeconds == 60
    assert restored.limits.timeoutGraceSeconds == 10
    assert restored.metadata == {"key": "value"}


def testSessionInfoToDictProducesJsonSerializableValues() -> None:
    """Verify that SessionInfo.toDict() produces JSON-serializable values.

    Datetimes must be ISO strings, not datetime objects.
    ResourceLimits must use kebab-case keys, not camelCase.
    """
    now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    si = SessionInfo(
        sessionId="s1",
        sessionHash="h1",
        workspacePath="/ws",
        createdAt=now,
        updatedAt=now,
        expiresAt=now,
        limits=ResourceLimits(),
        metadata={},
    )
    d = si.toDict()
    # Datetimes must be strings, not datetime objects
    assert isinstance(d["createdAt"], str)
    assert isinstance(d["updatedAt"], str)
    assert isinstance(d["expiresAt"], str)
    # Nested limits must use kebab-case keys
    assert "memory-mb" in d["limits"]
    assert "memoryMb" not in d["limits"]


# ============================================================================
# RunInfo
# ============================================================================


def testRunInfoRoundTripPreservesAllValues() -> None:
    """Verify that RunInfo.fromDict(ri.toDict()) preserves all fields.

    This tests enum serialization (to .value strings) and datetime
    serialization (to ISO strings).
    """
    started = datetime(2025, 3, 10, 8, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2025, 3, 10, 8, 0, 5, tzinfo=timezone.utc)
    ri = RunInfo(
        runId="run-001",
        sessionId="sess-001",
        runtime=RuntimeName.PYTHON,
        startedAt=started,
        finishedAt=finished,
        status=RunStatus.COMPLETED,
        exitCode=0,
    )
    restored = RunInfo.fromDict(ri.toDict())
    assert restored.runId == "run-001"
    assert restored.sessionId == "sess-001"
    assert restored.runtime == RuntimeName.PYTHON
    assert restored.startedAt == started
    assert restored.finishedAt == finished
    assert restored.status == RunStatus.COMPLETED
    assert restored.exitCode == 0


def testRunInfoRoundTripWithNoneFields() -> None:
    """Verify that RunInfo round-trip preserves None for optional fields."""
    started = datetime(2025, 3, 10, 8, 0, 0, tzinfo=timezone.utc)
    ri = RunInfo(
        runId="run-002",
        sessionId="sess-002",
        runtime=RuntimeName.PYTHON,
        startedAt=started,
        finishedAt=None,
        status=RunStatus.RUNNING,
        exitCode=None,
    )
    restored = RunInfo.fromDict(ri.toDict())
    assert restored.finishedAt is None
    assert restored.exitCode is None


def testRunInfoToDictProducesJsonSerializableValues() -> None:
    """Verify that RunInfo.toDict() produces JSON-serializable values.

    Enums must be strings, datetimes must be ISO strings.
    """
    started = datetime(2025, 3, 10, 8, 0, 0, tzinfo=timezone.utc)
    ri = RunInfo(
        runId="run-003",
        sessionId="sess-003",
        runtime=RuntimeName.PYTHON,
        startedAt=started,
        finishedAt=None,
        status=RunStatus.RUNNING,
        exitCode=None,
    )
    d = ri.toDict()
    assert isinstance(d["runtime"], str)
    assert isinstance(d["status"], str)
    assert isinstance(d["startedAt"], str)
    assert d["finishedAt"] is None
    assert d["exitCode"] is None


# ============================================================================
# PackageInfo
# ============================================================================


def testPackageInfoRoundTripPreservesAllValues() -> None:
    """Verify that PackageInfo.fromDict(pi.toDict()) preserves all fields.

    PackageInfo only has simple string fields, so this is a baseline test
    that should always pass even with slottedObjectToDict.
    """
    pi = PackageInfo(name="numpy", version="1.26.0")
    restored = PackageInfo.fromDict(pi.toDict())
    assert restored.name == "numpy"
    assert restored.version == "1.26.0"


# ============================================================================
# RunResult
# ============================================================================


def testRunResultRoundTripPreservesAllValues() -> None:
    """Verify that RunResult.fromDict(rr.toDict()) preserves all fields.

    This tests enum serialization, datetime serialization, and the workDir
    field which defaults to empty string when absent from the dict.
    """
    started = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2025, 6, 1, 10, 0, 3, tzinfo=timezone.utc)
    rr = RunResult(
        runId="test-run-id",
        sessionId="sess-001",
        workDir=".run/test-run-id/work",
        runtime=RuntimeName.PYTHON,
        stdoutPath="stdout.txt",
        stderrPath="stderr.txt",
        stdoutBytes=42,
        stderrBytes=0,
        exitCode=0,
        signal=None,
        timedOut=False,
        oomKilled=False,
        startedAt=started,
        finishedAt=finished,
        elapsedMs=3000,
        networkEnabled=False,
        error=None,
    )
    restored = RunResult.fromDict(rr.toDict())
    assert restored.runId == "test-run-id"
    assert restored.sessionId == "sess-001"
    assert restored.workDir == ".run/test-run-id/work"
    assert restored.runtime == RuntimeName.PYTHON
    assert restored.stdoutPath == "stdout.txt"
    assert restored.stderrPath == "stderr.txt"
    assert restored.stdoutBytes == 42
    assert restored.stderrBytes == 0
    assert restored.exitCode == 0
    assert restored.signal is None
    assert restored.timedOut is False
    assert restored.oomKilled is False
    assert restored.startedAt == started
    assert restored.finishedAt == finished
    assert restored.elapsedMs == 3000
    assert restored.networkEnabled is False
    assert restored.error is None


def testRunResultRoundTripDefaultsWorkDirToEmptyString() -> None:
    """Verify that RunResult.fromDict() defaults workDir to empty string when absent.

    Older serialisations won't include workDir, so fromDict must handle its
    absence gracefully.
    """
    started = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2025, 6, 1, 10, 0, 1, tzinfo=timezone.utc)
    data = {
        "runId": "run-old",
        "sessionId": "sess-old",
        # workDir intentionally omitted
        "runtime": "python",
        "stdoutPath": "out.txt",
        "stderrPath": "err.txt",
        "stdoutBytes": 10,
        "stderrBytes": 5,
        "exitCode": 1,
        "signal": None,
        "timedOut": False,
        "oomKilled": False,
        "startedAt": started.isoformat(),
        "finishedAt": finished.isoformat(),
        "elapsedMs": 1000,
        "networkEnabled": True,
        "error": "boom",
    }
    restored = RunResult.fromDict(data)
    assert restored.workDir == ""
    assert restored.runId == "run-old"
    assert restored.error == "boom"


def testRunResultToDictProducesJsonSerializableValues() -> None:
    """Verify that RunResult.toDict() produces JSON-serializable values.

    Enums must be strings, datetimes must be ISO strings, workDir must be a
    plain string.
    """
    started = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2025, 6, 1, 10, 0, 2, tzinfo=timezone.utc)
    rr = RunResult(
        runId="run-003",
        sessionId="sess-003",
        workDir=".run/run-003/work",
        runtime=RuntimeName.PYTHON,
        stdoutPath="stdout.txt",
        stderrPath="stderr.txt",
        stdoutBytes=0,
        stderrBytes=0,
        exitCode=0,
        signal=None,
        timedOut=False,
        oomKilled=False,
        startedAt=started,
        finishedAt=finished,
        elapsedMs=2000,
        networkEnabled=False,
        error=None,
    )
    d = rr.toDict()
    assert isinstance(d["runtime"], str)
    assert isinstance(d["startedAt"], str)
    assert isinstance(d["finishedAt"], str)
    assert isinstance(d["workDir"], str)
    assert d["workDir"] == ".run/run-003/work"
