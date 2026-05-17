"""Tests for sandbox dataclasses (lib.sandbox.types).

Covers:
- Round-trip construction for each dataclass with default and explicit values.
- ``slots=True`` verification (no ``__dict__`` attribute).
- Frozen dataclasses reject attribute mutation (TypeError).
- ``RunResult.newArtifacts`` is typed as ``list[ArtifactInfo]``.
- ``ResourceLimits`` default values match the design spec.
- Package-level re-export via ``from lib.sandbox import``.
"""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from lib.sandbox import (
    ArtifactInfo,
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
from lib.sandbox.enums import RuntimeName
from lib.sandbox.types import ArtifactInfo as ArtifactInfoDirect
from lib.sandbox.types import DropSessionResult as DropSessionResultDirect
from lib.sandbox.types import FileContent as FileContentDirect
from lib.sandbox.types import FileInfo as FileInfoDirect
from lib.sandbox.types import GcResult as GcResultDirect
from lib.sandbox.types import HealthcheckResult as HealthcheckResultDirect
from lib.sandbox.types import InputFile as InputFileDirect
from lib.sandbox.types import LibraryInstallResult as LibraryInstallResultDirect
from lib.sandbox.types import LibraryRemoveResult as LibraryRemoveResultDirect
from lib.sandbox.types import NetworkPolicy as NetworkPolicyDirect
from lib.sandbox.types import PackageInfo as PackageInfoDirect
from lib.sandbox.types import RecoveryResult as RecoveryResultDirect
from lib.sandbox.types import ResourceLimits as ResourceLimitsDirect
from lib.sandbox.types import RunInfo as RunInfoDirect
from lib.sandbox.types import RunResult as RunResultDirect
from lib.sandbox.types import RuntimeInfo as RuntimeInfoDirect
from lib.sandbox.types import SessionInfo as SessionInfoDirect
from lib.sandbox.types import SessionUsage as SessionUsageDirect
from lib.sandbox.types import ShutdownResult as ShutdownResultDirect

# ============================================================================
# Helpers
# ============================================================================

_FROZEN_CLASSES = (NetworkPolicy, ResourceLimits, InputFile)
_MUTABLE_CLASSES = (
    ArtifactInfo,
    DropSessionResult,
    FileContent,
    FileInfo,
    GcResult,
    HealthcheckResult,
    LibraryInstallResult,
    LibraryRemoveResult,
    PackageInfo,
    RecoveryResult,
    RunInfo,
    RunResult,
    RuntimeInfo,
    SessionInfo,
    SessionUsage,
    ShutdownResult,
)
_ALL_CLASSES = _FROZEN_CLASSES + _MUTABLE_CLASSES

_DT = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ============================================================================
# slots=True verification
# ============================================================================


@pytest.mark.parametrize("cls", _ALL_CLASSES, ids=lambda c: c.__name__)
def testSlotsEnabled(cls: type) -> None:
    """Verify that every dataclass uses slots=True by checking __slots__.

    Args:
        cls: A dataclass to check.

    Returns:
        None
    """
    assert hasattr(cls, "__slots__"), f"{cls.__name__} should have __slots__ (slots=True expected)"
    # Verify __slots__ is non-empty (contains at least the field names)
    assert len(cls.__slots__) > 0, f"{cls.__name__} __slots__ should not be empty"


# ============================================================================
# Frozen dataclasses — immutability
# ============================================================================


def testNetworkPolicyFrozen() -> None:
    """Verify that NetworkPolicy rejects attribute mutation.

    Returns:
        None
    """
    policy = NetworkPolicy(enabled=True)
    with pytest.raises(FrozenInstanceError):
        policy.enabled = False  # type: ignore[misc]


def testResourceLimitsFrozen() -> None:
    """Verify that ResourceLimits rejects attribute mutation.

    Returns:
        None
    """
    limits = ResourceLimits(memoryMb=1024)
    with pytest.raises(FrozenInstanceError):
        limits.memoryMb = 2048  # type: ignore[misc]


def testInputFileFrozen() -> None:
    """Verify that InputFile rejects attribute mutation.

    Returns:
        None
    """
    f = InputFile(path="a.txt", content="hello")
    with pytest.raises(FrozenInstanceError):
        f.path = "b.txt"  # type: ignore[misc]


# ============================================================================
# NetworkPolicy
# ============================================================================


def testNetworkPolicyDefaultValues() -> None:
    """Verify NetworkPolicy defaults (enabled=False).

    Returns:
        None
    """
    policy = NetworkPolicy()
    assert policy.enabled is False


def testNetworkPolicyExplicitValues() -> None:
    """Verify NetworkPolicy with explicit enabled=True.

    Returns:
        None
    """
    policy = NetworkPolicy(enabled=True)
    assert policy.enabled is True


# ============================================================================
# ResourceLimits
# ============================================================================


def testResourceLimitsDefaultValues() -> None:
    """Verify ResourceLimits defaults match the design spec.

    Returns:
        None
    """
    limits = ResourceLimits()
    assert limits.memoryMb == 512
    assert limits.memorySwapMb == 512
    assert limits.cpuCount == 1.0
    assert limits.pidsLimit == 64
    assert limits.timeoutSeconds == 30
    assert limits.timeoutGraceSeconds == 5


def testResourceLimitsExplicitValues() -> None:
    """Verify ResourceLimits with explicit values.

    Returns:
        None
    """
    limits = ResourceLimits(
        memoryMb=2048,
        memorySwapMb=None,
        cpuCount=2.0,
        pidsLimit=128,
        timeoutSeconds=60,
        timeoutGraceSeconds=10,
    )
    assert limits.memoryMb == 2048
    assert limits.memorySwapMb is None
    assert limits.cpuCount == 2.0
    assert limits.pidsLimit == 128
    assert limits.timeoutSeconds == 60
    assert limits.timeoutGraceSeconds == 10


# ============================================================================
# InputFile
# ============================================================================


def testInputFileDefaultValues() -> None:
    """Verify InputFile defaults (overwrite=True).

    Returns:
        None
    """
    f = InputFile(path="a.txt", content=b"data")
    assert f.overwrite is True


def testInputFileExplicitValues() -> None:
    """Verify InputFile with explicit overwrite=False and string content.

    Returns:
        None
    """
    f = InputFile(path="dir/b.txt", content="hello", overwrite=False)
    assert f.path == "dir/b.txt"
    assert f.content == "hello"
    assert f.overwrite is False


def testInputFileBytesContent() -> None:
    """Verify InputFile accepts bytes content.

    Returns:
        None
    """
    f = InputFile(path="binary.bin", content=b"\x00\x01\x02")
    assert isinstance(f.content, bytes)


# ============================================================================
# ArtifactInfo
# ============================================================================


def testArtifactInfoConstruction() -> None:
    """Verify ArtifactInfo round-trip construction.

    Returns:
        None
    """
    info = ArtifactInfo(
        path="output.txt",
        sizeBytes=42,
        modifiedAt=_DT,
        mimeType="text/plain",
        sha256="abc123",
    )
    assert info.path == "output.txt"
    assert info.sizeBytes == 42
    assert info.modifiedAt is _DT
    assert info.mimeType == "text/plain"
    assert info.sha256 == "abc123"


def testArtifactInfoNoneOptionalFields() -> None:
    """Verify ArtifactInfo with None for optional fields.

    Returns:
        None
    """
    info = ArtifactInfo(path="x", sizeBytes=0, modifiedAt=_DT, mimeType=None, sha256=None)
    assert info.mimeType is None
    assert info.sha256 is None


# ============================================================================
# SessionInfo
# ============================================================================


def testSessionInfoConstruction() -> None:
    """Verify SessionInfo round-trip construction.

    Returns:
        None
    """
    info = SessionInfo(
        sessionId="sess-1",
        runtime=RuntimeName.PYTHON,
        workspacePath="/tmp/ws",
        createdAt=_DT,
        updatedAt=_DT,
        expiresAt=_DT,
        metadata={"key": "value"},
    )
    assert info.sessionId == "sess-1"
    assert info.runtime is RuntimeName.PYTHON
    assert info.workspacePath == "/tmp/ws"
    assert info.metadata == {"key": "value"}


# ============================================================================
# SessionUsage
# ============================================================================


def testSessionUsageConstruction() -> None:
    """Verify SessionUsage round-trip construction.

    Returns:
        None
    """
    usage = SessionUsage(
        sessionId="sess-1",
        fileCount=10,
        totalBytes=4096,
        runCount=3,
        measuredAt=_DT,
    )
    assert usage.sessionId == "sess-1"
    assert usage.fileCount == 10
    assert usage.totalBytes == 4096
    assert usage.runCount == 3


# ============================================================================
# ShutdownResult
# ============================================================================


def testShutdownResultConstruction() -> None:
    """Verify ShutdownResult round-trip construction.

    Returns:
        None
    """
    result = ShutdownResult(cleanedVolumes=3, errors=["volume-busy"])
    assert result.cleanedVolumes == 3
    assert result.errors == ["volume-busy"]


def testShutdownResultEmptyErrors() -> None:
    """Verify ShutdownResult with no errors.

    Returns:
        None
    """
    result = ShutdownResult(cleanedVolumes=0, errors=[])
    assert result.cleanedVolumes == 0
    assert result.errors == []


# ============================================================================
# RunInfo
# ============================================================================


def testRunInfoConstruction() -> None:
    """Verify RunInfo round-trip construction with status='completed'.

    Returns:
        None
    """
    info = RunInfo(
        runId="run-1",
        sessionId="sess-1",
        runtime=RuntimeName.PYTHON,
        startedAt=_DT,
        finishedAt=_DT,
        status="completed",
        exitCode=0,
    )
    assert info.runId == "run-1"
    assert info.status == "completed"
    assert info.exitCode == 0


def testRunInfoRunningStatus() -> None:
    """Verify RunInfo with status='running' and exitCode=None.

    Returns:
        None
    """
    info = RunInfo(
        runId="run-2",
        sessionId="sess-1",
        runtime=RuntimeName.PYTHON,
        startedAt=_DT,
        finishedAt=None,
        status="running",
        exitCode=None,
    )
    assert info.status == "running"
    assert info.exitCode is None
    assert info.finishedAt is None


# ============================================================================
# RunResult
# ============================================================================


def testRunResultConstruction() -> None:
    """Verify RunResult round-trip construction.

    Returns:
        None
    """
    limits = ResourceLimits(memoryMb=1024)
    artifact = ArtifactInfo(path="out.txt", sizeBytes=100, modifiedAt=_DT, mimeType=None, sha256=None)
    result = RunResult(
        runId="run-1",
        sessionId="sess-1",
        runtime=RuntimeName.PYTHON,
        stdoutPath="stdout.txt",
        stderrPath="stderr.txt",
        stdoutBytes=50,
        stderrBytes=0,
        exitCode=0,
        signal=None,
        timedOut=False,
        oomKilled=False,
        startedAt=_DT,
        finishedAt=_DT,
        elapsedMs=1200,
        newArtifacts=[artifact],
        limits=limits,
        networkEnabled=False,
        libPoolVersion="v1",
        error=None,
    )
    assert result.runId == "run-1"
    assert result.newArtifacts == [artifact]
    assert result.limits is limits
    assert result.networkEnabled is False
    assert result.error is None


def testRunResultNewArtifactsTypedList() -> None:
    """Verify that RunResult.newArtifacts holds ArtifactInfo instances.

    Returns:
        None
    """
    artifacts = [
        ArtifactInfo(path="a.txt", sizeBytes=10, modifiedAt=_DT, mimeType=None, sha256=None),
        ArtifactInfo(path="b.txt", sizeBytes=20, modifiedAt=_DT, mimeType="text/plain", sha256="deadbeef"),
    ]
    result = RunResult(
        runId="run-3",
        sessionId="sess-2",
        runtime=RuntimeName.PYTHON,
        stdoutPath="stdout.txt",
        stderrPath="stderr.txt",
        stdoutBytes=0,
        stderrBytes=0,
        exitCode=1,
        signal="SIGTERM",
        timedOut=True,
        oomKilled=False,
        startedAt=_DT,
        finishedAt=_DT,
        elapsedMs=30000,
        newArtifacts=artifacts,
        limits=ResourceLimits(),
        networkEnabled=True,
        libPoolVersion="v2",
        error="timeout",
    )
    assert len(result.newArtifacts) == 2
    for item in result.newArtifacts:
        assert isinstance(item, ArtifactInfo)
    assert result.newArtifacts[0].path == "a.txt"
    assert result.newArtifacts[1].sha256 == "deadbeef"


# ============================================================================
# FileInfo
# ============================================================================


def testFileInfoConstruction() -> None:
    """Verify FileInfo round-trip construction.

    Returns:
        None
    """
    info = FileInfo(path="src/main.py", sizeBytes=256, modifiedAt=_DT, isDirectory=False)
    assert info.path == "src/main.py"
    assert info.sizeBytes == 256
    assert info.isDirectory is False


# ============================================================================
# FileContent
# ============================================================================


def testFileContentConstruction() -> None:
    """Verify FileContent round-trip construction with bytes content.

    Returns:
        None
    """
    fc = FileContent(
        path="output.bin",
        sizeBytes=1024,
        bytesRead=512,
        truncated=True,
        content=b"\x00" * 512,
    )
    assert fc.path == "output.bin"
    assert fc.sizeBytes == 1024
    assert fc.bytesRead == 512
    assert fc.truncated is True
    assert len(fc.content) == 512


def testFileContentStringContent() -> None:
    """Verify FileContent accepts string content.

    Returns:
        None
    """
    fc = FileContent(
        path="hello.txt",
        sizeBytes=5,
        bytesRead=5,
        truncated=False,
        content="hello",
    )
    assert fc.content == "hello"
    assert fc.truncated is False


# ============================================================================
# PackageInfo
# ============================================================================


def testPackageInfoConstruction() -> None:
    """Verify PackageInfo round-trip construction.

    Returns:
        None
    """
    pkg = PackageInfo(name="requests", version="2.31.0")
    assert pkg.name == "requests"
    assert pkg.version == "2.31.0"


# ============================================================================
# LibraryInstallResult
# ============================================================================


def testLibraryInstallResultConstruction() -> None:
    """Verify LibraryInstallResult round-trip construction.

    Returns:
        None
    """
    result = LibraryInstallResult(
        runtime=RuntimeName.PYTHON,
        installed=[PackageInfo(name="numpy", version="1.26.0")],
        skipped=["requests"],
        failed=[("broken-pkg", "build error")],
        poolVersion="sha256abc",
    )
    assert result.runtime is RuntimeName.PYTHON
    assert len(result.installed) == 1
    assert result.installed[0].name == "numpy"
    assert result.skipped == ["requests"]
    assert result.failed == [("broken-pkg", "build error")]
    assert result.poolVersion == "sha256abc"


# ============================================================================
# LibraryRemoveResult
# ============================================================================


def testLibraryRemoveResultConstruction() -> None:
    """Verify LibraryRemoveResult round-trip construction.

    Returns:
        None
    """
    result = LibraryRemoveResult(
        runtime=RuntimeName.PYTHON,
        removed=["numpy"],
        notFound=["nonexistent"],
        poolVersion="sha256def",
    )
    assert result.removed == ["numpy"]
    assert result.notFound == ["nonexistent"]


# ============================================================================
# DropSessionResult
# ============================================================================


def testDropSessionResultConstruction() -> None:
    """Verify DropSessionResult round-trip construction.

    Returns:
        None
    """
    result = DropSessionResult(
        sessionId="sess-1",
        existed=True,
        runsCancelled=2,
        errors=[],
    )
    assert result.sessionId == "sess-1"
    assert result.existed is True
    assert result.runsCancelled == 2


# ============================================================================
# HealthcheckResult
# ============================================================================


def testHealthcheckResultConstruction() -> None:
    """Verify HealthcheckResult round-trip construction.

    Returns:
        None
    """
    result = HealthcheckResult(
        ok=True,
        backend={"docker": {"running": True}},
        runtimes={"python": {"healthy": True}},
        storage={"available": True},
        errors=[],
    )
    assert result.ok is True
    assert "docker" in result.backend
    assert "python" in result.runtimes


# ============================================================================
# GcResult
# ============================================================================


def testGcResultConstruction() -> None:
    """Verify GcResult round-trip construction.

    Returns:
        None
    """
    result = GcResult(
        removedContainers=3,
        removedSessions=1,
        removedRuns=5,
        removedOrphans=2,
        errors=["orphan lock"],
    )
    assert result.removedContainers == 3
    assert result.removedSessions == 1
    assert result.removedRuns == 5
    assert result.removedOrphans == 2
    assert result.errors == ["orphan lock"]


# ============================================================================
# RecoveryResult
# ============================================================================


def testRecoveryResultConstruction() -> None:
    """Verify RecoveryResult round-trip construction.

    Returns:
        None
    """
    result = RecoveryResult(
        reapedContainers=2,
        releasedLocks=1,
        reconciledPools=1,
        errors=[],
    )
    assert result.reapedContainers == 2
    assert result.releasedLocks == 1
    assert result.reconciledPools == 1


# ============================================================================
# RuntimeInfo
# ============================================================================


def testRuntimeInfoConstruction() -> None:
    """Verify RuntimeInfo round-trip construction.

    Returns:
        None
    """
    info = RuntimeInfo(
        name=RuntimeName.PYTHON,
        runImageTag="python:3.12-run",
        installImageTag="python:3.12-install",
        libPoolPath="/var/lib/sandbox/pools/python",
        libPoolVersion="sha256xyz",
        packageCount=42,
    )
    assert info.name is RuntimeName.PYTHON
    assert info.runImageTag == "python:3.12-run"
    assert info.packageCount == 42


# ============================================================================
# Package-level re-export
# ============================================================================


def testPackageReExportAllTypes() -> None:
    """Verify that all dataclasses are importable from lib.sandbox (package re-export).

    Returns:
        None
    """
    direct_classes = [
        ArtifactInfoDirect,
        DropSessionResultDirect,
        FileContentDirect,
        FileInfoDirect,
        GcResultDirect,
        HealthcheckResultDirect,
        InputFileDirect,
        LibraryInstallResultDirect,
        LibraryRemoveResultDirect,
        NetworkPolicyDirect,
        PackageInfoDirect,
        RecoveryResultDirect,
        ResourceLimitsDirect,
        RunInfoDirect,
        RunResultDirect,
        RuntimeInfoDirect,
        SessionInfoDirect,
        SessionUsageDirect,
        ShutdownResultDirect,
    ]
    package_classes = [
        ArtifactInfo,
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
    ]
    for direct, pkg in zip(direct_classes, package_classes):
        assert direct is pkg, f"{direct.__name__} from lib.sandbox.types is not the same as from lib.sandbox"


# ============================================================================
# Mutable classes allow attribute mutation
# ============================================================================


def testMutableClassAllowsMutation() -> None:
    """Verify that a mutable dataclass allows attribute reassignment.

    Returns:
        None
    """
    pkg = PackageInfo(name="old", version="1.0")
    pkg.name = "new"
    assert pkg.name == "new"


def testMutableSessionInfoAllowsMutation() -> None:
    """Verify that SessionInfo allows attribute reassignment.

    Returns:
        None
    """
    info = SessionInfo(
        sessionId="s1",
        runtime=RuntimeName.PYTHON,
        workspacePath="/tmp/ws",
        createdAt=_DT,
        updatedAt=_DT,
        expiresAt=_DT,
        metadata={},
    )
    info.metadata = {"updated": "true"}
    assert info.metadata == {"updated": "true"}
