"""Tests for sandbox Protocols and supporting dataclasses.

Covers:
- Trivial stub classes for SandboxBackend, Runtime, and MetadataStore Protocols.
- Method-signature existence checks for each Protocol.
- Round-trip construction for ContainerSpec, ContainerOutcome, ManagedContainerInfo.
- Round-trip construction for SessionRecord, RunRecord, RuntimeRecord.
- Async method detection via asyncio.iscoroutinefunction.
- schemaVersion default value of 1 for metadata record dataclasses.
- slots=True verification for all new dataclasses.
"""

import asyncio
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pytest

from lib.sandbox.backends.base import (
    ContainerOutcome,
    ContainerSpec,
    ManagedContainerInfo,
)
from lib.sandbox.enums import BackendName, RuntimeName
from lib.sandbox.metadata.base import (
    RunRecord,
    RuntimeRecord,
    SessionRecord,
)
from lib.sandbox.types import ArtifactInfo, HealthcheckResult, ResourceLimits, RuntimeInfo

# ============================================================================
# Helpers — trivial stub implementations
# ============================================================================


class _StubBackend:
    """Minimal concrete implementation of SandboxBackend for testing."""

    name: BackendName = BackendName.DOCKER

    async def healthcheck(self) -> HealthcheckResult:
        """Return a healthy result.

        Returns:
            A HealthcheckResult indicating all subsystems are healthy.
        """
        return HealthcheckResult(
            ok=True,
            backend={},
            runtimes={},
            storage={},
            errors=[],
        )

    async def ensureImage(
        self,
        runtime: RuntimeInfo,
        *,
        rebuild: bool = False,
    ) -> None:
        """No-op for testing.

        Args:
            runtime: Runtime metadata (unused in stub).
            rebuild: Force rebuild flag (unused in stub).

        Returns:
            None
        """
        return None

    async def runOneshot(self, spec: ContainerSpec) -> ContainerOutcome:
        """Return a dummy outcome for testing.

        Args:
            spec: Container specification (unused in stub).

        Returns:
            A ContainerOutcome with exit code 0.
        """
        return ContainerOutcome(
            containerId="stub-id",
            exitCode=0,
            signal=None,
            oomKilled=False,
            inspects={},
        )

    async def removeContainer(
        self,
        containerId: str,
        *,
        force: bool = True,
    ) -> None:
        """No-op for testing.

        Args:
            containerId: Container ID (unused in stub).
            force: Force removal flag (unused in stub).

        Returns:
            None
        """
        return None

    async def killContainer(
        self,
        containerId: str,
        *,
        signal: str = "SIGKILL",
    ) -> None:
        """No-op for testing.

        Args:
            containerId: Container ID (unused in stub).
            signal: Signal name (unused in stub).

        Returns:
            None
        """
        return None

    async def inspectContainer(self, containerId: str) -> dict[str, Any]:
        """Return an empty dict for testing.

        Args:
            containerId: Container ID (unused in stub).

        Returns:
            An empty dictionary.
        """
        return {}

    async def listManagedContainers(self) -> list[ManagedContainerInfo]:
        """Return an empty list for testing.

        Returns:
            An empty list.
        """
        return []


class _StubRuntime:
    """Minimal concrete implementation of Runtime for testing."""

    name: RuntimeName = RuntimeName.PYTHON

    def runCommand(
        self,
        runId: str,
        *,
        hasStdin: bool,
        limits: ResourceLimits,
    ) -> list[str]:
        """Return a dummy command for testing.

        Args:
            runId: Run identifier (unused in stub).
            hasStdin: Whether stdin is expected (unused in stub).
            limits: Resource limits (unused in stub).

        Returns:
            A single-element command list.
        """
        return ["echo", "hello"]

    def installCommand(
        self,
        packages: Sequence[str],
        *,
        upgrade: bool,
    ) -> list[str]:
        """Return a dummy install command for testing.

        Args:
            packages: Package names (unused in stub).
            upgrade: Upgrade flag (unused in stub).

        Returns:
            A single-element command list.
        """
        return ["pip", "install"]

    def listCommand(self) -> list[str]:
        """Return a dummy list command for testing.

        Returns:
            A single-element command list.
        """
        return ["pip", "list"]

    def detectArtifacts(
        self,
        workspacePath: Path,
        *,
        sinceMtime: float,
    ) -> list[ArtifactInfo]:
        """Return an empty list for testing.

        Args:
            workspacePath: Workspace path (unused in stub).
            sinceMtime: Modification-time threshold (unused in stub).

        Returns:
            An empty list.
        """
        return []


class _StubMetadataStore:
    """Minimal concrete implementation of MetadataStore for testing."""

    async def loadSession(self, sessionId: str) -> SessionRecord | None:
        """Return None for testing.

        Args:
            sessionId: Session identifier (unused in stub).

        Returns:
            None
        """
        return None

    async def saveSession(self, record: SessionRecord) -> None:
        """No-op for testing.

        Args:
            record: Session record (unused in stub).

        Returns:
            None
        """
        return None

    async def deleteSession(self, sessionId: str) -> None:
        """No-op for testing.

        Args:
            sessionId: Session identifier (unused in stub).

        Returns:
            None
        """
        return None

    async def listSessions(self, *, runtime: RuntimeName | None = None) -> list[SessionRecord]:
        """Return an empty list for testing.

        Args:
            runtime: Optional runtime filter (unused in stub).

        Returns:
            An empty list.
        """
        return []

    async def loadRun(self, runId: str) -> RunRecord | None:
        """Return None for testing.

        Args:
            runId: Run identifier (unused in stub).

        Returns:
            None
        """
        return None

    async def saveRun(self, record: RunRecord) -> None:
        """No-op for testing.

        Args:
            record: Run record (unused in stub).

        Returns:
            None
        """
        return None

    async def deleteRun(self, runId: str) -> None:
        """No-op for testing.

        Args:
            runId: Run identifier (unused in stub).

        Returns:
            None
        """
        return None

    async def listRunsForSession(self, sessionId: str) -> list[RunRecord]:
        """Return an empty list for testing.

        Args:
            sessionId: Session identifier (unused in stub).

        Returns:
            An empty list.
        """
        return []

    async def loadRuntime(self, runtime: RuntimeName) -> RuntimeRecord | None:
        """Return None for testing.

        Args:
            runtime: Runtime identifier (unused in stub).

        Returns:
            None
        """
        return None

    async def saveRuntime(self, record: RuntimeRecord) -> None:
        """No-op for testing.

        Args:
            record: Runtime record (unused in stub).

        Returns:
            None
        """
        return None


# ============================================================================
# Shared fixtures
# ============================================================================

_DT = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ============================================================================
# SandboxBackend Protocol — method existence
# ============================================================================


class TestSandboxBackendMethods:
    """Verify that _StubBackend has all SandboxBackend Protocol methods."""

    def testNameAttribute(self) -> None:
        """Verify that _StubBackend exposes a name attribute.

        Returns:
            None
        """
        stub = _StubBackend()
        assert stub.name is BackendName.DOCKER

    def testHealthcheckMethod(self) -> None:
        """Verify that _StubBackend has a healthcheck method.

        Returns:
            None
        """
        stub = _StubBackend()
        assert hasattr(stub, "healthcheck")
        assert callable(stub.healthcheck)

    def testEnsureImageMethod(self) -> None:
        """Verify that _StubBackend has an ensureImage method.

        Returns:
            None
        """
        stub = _StubBackend()
        assert hasattr(stub, "ensureImage")
        assert callable(stub.ensureImage)

    def testRunOneshotMethod(self) -> None:
        """Verify that _StubBackend has a runOneshot method.

        Returns:
            None
        """
        stub = _StubBackend()
        assert hasattr(stub, "runOneshot")
        assert callable(stub.runOneshot)

    def testRemoveContainerMethod(self) -> None:
        """Verify that _StubBackend has a removeContainer method.

        Returns:
            None
        """
        stub = _StubBackend()
        assert hasattr(stub, "removeContainer")
        assert callable(stub.removeContainer)

    def testKillContainerMethod(self) -> None:
        """Verify that _StubBackend has a killContainer method.

        Returns:
            None
        """
        stub = _StubBackend()
        assert hasattr(stub, "killContainer")
        assert callable(stub.killContainer)

    def testInspectContainerMethod(self) -> None:
        """Verify that _StubBackend has an inspectContainer method.

        Returns:
            None
        """
        stub = _StubBackend()
        assert hasattr(stub, "inspectContainer")
        assert callable(stub.inspectContainer)

    def testListManagedContainersMethod(self) -> None:
        """Verify that _StubBackend has a listManagedContainers method.

        Returns:
            None
        """
        stub = _StubBackend()
        assert hasattr(stub, "listManagedContainers")
        assert callable(stub.listManagedContainers)


# ============================================================================
# Runtime Protocol — method existence
# ============================================================================


class TestRuntimeMethods:
    """Verify that _StubRuntime has all Runtime Protocol methods."""

    def testNameAttribute(self) -> None:
        """Verify that _StubRuntime exposes a name attribute.

        Returns:
            None
        """
        stub = _StubRuntime()
        assert stub.name is RuntimeName.PYTHON

    def testRunCommandMethod(self) -> None:
        """Verify that _StubRuntime has a runCommand method.

        Returns:
            None
        """
        stub = _StubRuntime()
        assert hasattr(stub, "runCommand")
        assert callable(stub.runCommand)

    def testInstallCommandMethod(self) -> None:
        """Verify that _StubRuntime has an installCommand method.

        Returns:
            None
        """
        stub = _StubRuntime()
        assert hasattr(stub, "installCommand")
        assert callable(stub.installCommand)

    def testListCommandMethod(self) -> None:
        """Verify that _StubRuntime has a listCommand method.

        Returns:
            None
        """
        stub = _StubRuntime()
        assert hasattr(stub, "listCommand")
        assert callable(stub.listCommand)

    def testDetectArtifactsMethod(self) -> None:
        """Verify that _StubRuntime has a detectArtifacts method.

        Returns:
            None
        """
        stub = _StubRuntime()
        assert hasattr(stub, "detectArtifacts")
        assert callable(stub.detectArtifacts)


# ============================================================================
# MetadataStore Protocol — method existence
# ============================================================================


class TestMetadataStoreMethods:
    """Verify that _StubMetadataStore has all MetadataStore Protocol methods."""

    def testLoadSessionMethod(self) -> None:
        """Verify that _StubMetadataStore has a loadSession method.

        Returns:
            None
        """
        stub = _StubMetadataStore()
        assert hasattr(stub, "loadSession")
        assert callable(stub.loadSession)

    def testSaveSessionMethod(self) -> None:
        """Verify that _StubMetadataStore has a saveSession method.

        Returns:
            None
        """
        stub = _StubMetadataStore()
        assert hasattr(stub, "saveSession")
        assert callable(stub.saveSession)

    def testDeleteSessionMethod(self) -> None:
        """Verify that _StubMetadataStore has a deleteSession method.

        Returns:
            None
        """
        stub = _StubMetadataStore()
        assert hasattr(stub, "deleteSession")
        assert callable(stub.deleteSession)

    def testListSessionsMethod(self) -> None:
        """Verify that _StubMetadataStore has a listSessions method.

        Returns:
            None
        """
        stub = _StubMetadataStore()
        assert hasattr(stub, "listSessions")
        assert callable(stub.listSessions)

    def testLoadRunMethod(self) -> None:
        """Verify that _StubMetadataStore has a loadRun method.

        Returns:
            None
        """
        stub = _StubMetadataStore()
        assert hasattr(stub, "loadRun")
        assert callable(stub.loadRun)

    def testSaveRunMethod(self) -> None:
        """Verify that _StubMetadataStore has a saveRun method.

        Returns:
            None
        """
        stub = _StubMetadataStore()
        assert hasattr(stub, "saveRun")
        assert callable(stub.saveRun)

    def testDeleteRunMethod(self) -> None:
        """Verify that _StubMetadataStore has a deleteRun method.

        Returns:
            None
        """
        stub = _StubMetadataStore()
        assert hasattr(stub, "deleteRun")
        assert callable(stub.deleteRun)

    def testListRunsForSessionMethod(self) -> None:
        """Verify that _StubMetadataStore has a listRunsForSession method.

        Returns:
            None
        """
        stub = _StubMetadataStore()
        assert hasattr(stub, "listRunsForSession")
        assert callable(stub.listRunsForSession)

    def testLoadRuntimeMethod(self) -> None:
        """Verify that _StubMetadataStore has a loadRuntime method.

        Returns:
            None
        """
        stub = _StubMetadataStore()
        assert hasattr(stub, "loadRuntime")
        assert callable(stub.loadRuntime)

    def testSaveRuntimeMethod(self) -> None:
        """Verify that _StubMetadataStore has a saveRuntime method.

        Returns:
            None
        """
        stub = _StubMetadataStore()
        assert hasattr(stub, "saveRuntime")
        assert callable(stub.saveRuntime)


# ============================================================================
# ContainerSpec — round-trip construction
# ============================================================================


class TestContainerSpec:
    """Verify ContainerSpec dataclass construction and field access."""

    def testRoundTripConstruction(self) -> None:
        """Verify ContainerSpec round-trip construction with all fields.

        Returns:
            None
        """
        limits = ResourceLimits(memoryMb=1024)
        spec = ContainerSpec(
            name="test-container",
            image="python:3.12",
            command=["python", "-c", "print('hello')"],
            mounts=[{"hostPath": "/tmp", "containerPath": "/workspace", "mode": "rw"}],
            env={"PYTHONUNBUFFERED": "1"},
            limits=limits,
            network="none",
            user="1000:1000",
            readOnlyRoot=True,
            capDrop=["ALL"],
            securityOpt=["no-new-privileges"],
            labels={"sandbox": "true"},
        )
        assert spec.name == "test-container"
        assert spec.image == "python:3.12"
        assert spec.command == ["python", "-c", "print('hello')"]
        assert len(spec.mounts) == 1
        assert spec.mounts[0]["hostPath"] == "/tmp"
        assert spec.env == {"PYTHONUNBUFFERED": "1"}
        assert spec.limits is limits
        assert spec.network == "none"
        assert spec.user == "1000:1000"
        assert spec.readOnlyRoot is True
        assert spec.capDrop == ["ALL"]
        assert spec.securityOpt == ["no-new-privileges"]
        assert spec.labels == {"sandbox": "true"}

    def testSlotsEnabled(self) -> None:
        """Verify ContainerSpec uses slots=True.

        Returns:
            None
        """
        assert hasattr(ContainerSpec, "__slots__")
        assert tuple(ContainerSpec.__slots__)


# ============================================================================
# ContainerOutcome — round-trip construction
# ============================================================================


class TestContainerOutcome:
    """Verify ContainerOutcome dataclass construction and field access."""

    def testRoundTripConstruction(self) -> None:
        """Verify ContainerOutcome round-trip construction with all fields.

        Returns:
            None
        """
        outcome = ContainerOutcome(
            containerId="abc123",
            exitCode=0,
            signal=None,
            oomKilled=False,
            inspects={"State": {"Running": False}},
        )
        assert outcome.containerId == "abc123"
        assert outcome.exitCode == 0
        assert outcome.signal is None
        assert outcome.oomKilled is False
        assert "State" in outcome.inspects

    def testOomKilledTrue(self) -> None:
        """Verify ContainerOutcome with oomKilled=True and non-None signal.

        Returns:
            None
        """
        outcome = ContainerOutcome(
            containerId="def456",
            exitCode=None,
            signal="SIGKILL",
            oomKilled=True,
            inspects={},
        )
        assert outcome.oomKilled is True
        assert outcome.signal == "SIGKILL"
        assert outcome.exitCode is None

    def testSlotsEnabled(self) -> None:
        """Verify ContainerOutcome uses slots=True.

        Returns:
            None
        """
        assert hasattr(ContainerOutcome, "__slots__")
        assert tuple(ContainerOutcome.__slots__)


# ============================================================================
# ManagedContainerInfo — round-trip construction
# ============================================================================


class TestManagedContainerInfo:
    """Verify ManagedContainerInfo dataclass construction and field access."""

    def testRoundTripConstruction(self) -> None:
        """Verify ManagedContainerInfo round-trip construction with all fields.

        Returns:
            None
        """
        info = ManagedContainerInfo(
            containerId="ctr-1",
            name="sandbox-run-42",
            labels={"sandbox": "true", "run": "42"},
            status="running",
            createdAt="2025-01-01T00:00:00Z",
        )
        assert info.containerId == "ctr-1"
        assert info.name == "sandbox-run-42"
        assert info.labels == {"sandbox": "true", "run": "42"}
        assert info.status == "running"
        assert info.createdAt == "2025-01-01T00:00:00Z"

    def testSlotsEnabled(self) -> None:
        """Verify ManagedContainerInfo uses slots=True.

        Returns:
            None
        """
        assert hasattr(ManagedContainerInfo, "__slots__")
        assert tuple(ManagedContainerInfo.__slots__)


# ============================================================================
# SessionRecord — round-trip construction and schemaVersion default
# ============================================================================


class TestSessionRecord:
    """Verify SessionRecord dataclass construction and defaults."""

    def testRoundTripConstruction(self) -> None:
        """Verify SessionRecord round-trip construction with all fields.

        Returns:
            None
        """
        record = SessionRecord(
            sessionId="sess-1",
            sessionHash="sha256abc",
            runtime=RuntimeName.PYTHON,
            workspacePath="/tmp/ws",
            createdAt=_DT,
            updatedAt=_DT,
            expiresAt=_DT,
            metadata={"key": "value"},
        )
        assert record.sessionId == "sess-1"
        assert record.sessionHash == "sha256abc"
        assert record.runtime is RuntimeName.PYTHON
        assert record.workspacePath == "/tmp/ws"
        assert record.metadata == {"key": "value"}

    def testSchemaVersionDefault(self) -> None:
        """Verify SessionRecord.schemaVersion defaults to 1.

        Returns:
            None
        """
        record = SessionRecord(
            sessionId="sess-2",
            sessionHash="sha256def",
            runtime=RuntimeName.PYTHON,
            workspacePath="/tmp/ws2",
            createdAt=_DT,
            updatedAt=_DT,
            expiresAt=_DT,
            metadata={},
        )
        assert record.schemaVersion == 1

    def testSchemaVersionExplicit(self) -> None:
        """Verify SessionRecord.schemaVersion can be set explicitly.

        Returns:
            None
        """
        record = SessionRecord(
            sessionId="sess-3",
            sessionHash="sha256ghi",
            runtime=RuntimeName.PYTHON,
            workspacePath="/tmp/ws3",
            createdAt=_DT,
            updatedAt=_DT,
            expiresAt=_DT,
            metadata={},
            schemaVersion=2,
        )
        assert record.schemaVersion == 2

    def testSlotsEnabled(self) -> None:
        """Verify SessionRecord uses slots=True.

        Returns:
            None
        """
        assert hasattr(SessionRecord, "__slots__")
        assert tuple(SessionRecord.__slots__)


# ============================================================================
# RunRecord — round-trip construction and schemaVersion default
# ============================================================================


class TestRunRecord:
    """Verify RunRecord dataclass construction and defaults."""

    def testRoundTripConstruction(self) -> None:
        """Verify RunRecord round-trip construction with all fields.

        Returns:
            None
        """
        record = RunRecord(
            runId="run-1",
            sessionId="sess-1",
            runtime=RuntimeName.PYTHON,
            startedAt=_DT,
            finishedAt=_DT,
            status="completed",
            exitCode=0,
        )
        assert record.runId == "run-1"
        assert record.sessionId == "sess-1"
        assert record.runtime is RuntimeName.PYTHON
        assert record.status == "completed"
        assert record.exitCode == 0

    def testSchemaVersionDefault(self) -> None:
        """Verify RunRecord.schemaVersion defaults to 1.

        Returns:
            None
        """
        record = RunRecord(
            runId="run-2",
            sessionId="sess-1",
            runtime=RuntimeName.PYTHON,
            startedAt=_DT,
            finishedAt=None,
            status="running",
            exitCode=None,
        )
        assert record.schemaVersion == 1

    def testSchemaVersionExplicit(self) -> None:
        """Verify RunRecord.schemaVersion can be set explicitly.

        Returns:
            None
        """
        record = RunRecord(
            runId="run-3",
            sessionId="sess-1",
            runtime=RuntimeName.PYTHON,
            startedAt=_DT,
            finishedAt=_DT,
            status="failed",
            exitCode=1,
            schemaVersion=3,
        )
        assert record.schemaVersion == 3

    def testSlotsEnabled(self) -> None:
        """Verify RunRecord uses slots=True.

        Returns:
            None
        """
        assert hasattr(RunRecord, "__slots__")
        assert tuple(RunRecord.__slots__)


# ============================================================================
# RuntimeRecord — round-trip construction and schemaVersion default
# ============================================================================


class TestRuntimeRecord:
    """Verify RuntimeRecord dataclass construction and defaults."""

    def testRoundTripConstruction(self) -> None:
        """Verify RuntimeRecord round-trip construction with all fields.

        Returns:
            None
        """
        record = RuntimeRecord(
            runtime=RuntimeName.PYTHON,
            runImageTag="python:3.12-run",
            installImageTag="python:3.12-install",
            libPoolPath="/var/lib/sandbox/pools/python",
            libPoolVersion="sha256xyz",
            packageCount=42,
        )
        assert record.runtime is RuntimeName.PYTHON
        assert record.runImageTag == "python:3.12-run"
        assert record.installImageTag == "python:3.12-install"
        assert record.libPoolPath == "/var/lib/sandbox/pools/python"
        assert record.libPoolVersion == "sha256xyz"
        assert record.packageCount == 42

    def testSchemaVersionDefault(self) -> None:
        """Verify RuntimeRecord.schemaVersion defaults to 1.

        Returns:
            None
        """
        record = RuntimeRecord(
            runtime=RuntimeName.PYTHON,
            runImageTag="python:3.12-run",
            installImageTag="python:3.12-install",
            libPoolPath="/var/lib/sandbox/pools/python",
            libPoolVersion="sha256xyz",
            packageCount=42,
        )
        assert record.schemaVersion == 1

    def testSchemaVersionExplicit(self) -> None:
        """Verify RuntimeRecord.schemaVersion can be set explicitly.

        Returns:
            None
        """
        record = RuntimeRecord(
            runtime=RuntimeName.PYTHON,
            runImageTag="python:3.12-run",
            installImageTag="python:3.12-install",
            libPoolPath="/var/lib/sandbox/pools/python",
            libPoolVersion="sha256xyz",
            packageCount=42,
            schemaVersion=5,
        )
        assert record.schemaVersion == 5

    def testSlotsEnabled(self) -> None:
        """Verify RuntimeRecord uses slots=True.

        Returns:
            None
        """
        assert hasattr(RuntimeRecord, "__slots__")
        assert tuple(RuntimeRecord.__slots__)


# ============================================================================
# Async method detection — asyncio.iscoroutinefunction
# ============================================================================


class TestAsyncMethods:
    """Verify that Protocol methods declared async are coroutine functions."""

    # -- SandboxBackend --

    def testBackendHealthcheckIsAsync(self) -> None:
        """Verify that SandboxBackend.healthcheck is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubBackend.healthcheck)

    def testBackendEnsureImageIsAsync(self) -> None:
        """Verify that SandboxBackend.ensureImage is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubBackend.ensureImage)

    def testBackendRunOneshotIsAsync(self) -> None:
        """Verify that SandboxBackend.runOneshot is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubBackend.runOneshot)

    def testBackendRemoveContainerIsAsync(self) -> None:
        """Verify that SandboxBackend.removeContainer is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubBackend.removeContainer)

    def testBackendKillContainerIsAsync(self) -> None:
        """Verify that SandboxBackend.killContainer is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubBackend.killContainer)

    def testBackendInspectContainerIsAsync(self) -> None:
        """Verify that SandboxBackend.inspectContainer is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubBackend.inspectContainer)

    def testBackendListManagedContainersIsAsync(self) -> None:
        """Verify that SandboxBackend.listManagedContainers is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubBackend.listManagedContainers)

    # -- Runtime (all sync) --

    def testRuntimeRunCommandIsNotAsync(self) -> None:
        """Verify that Runtime.runCommand is NOT an async method.

        Returns:
            None
        """
        assert not asyncio.iscoroutinefunction(_StubRuntime.runCommand)

    def testRuntimeInstallCommandIsNotAsync(self) -> None:
        """Verify that Runtime.installCommand is NOT an async method.

        Returns:
            None
        """
        assert not asyncio.iscoroutinefunction(_StubRuntime.installCommand)

    def testRuntimeListCommandIsNotAsync(self) -> None:
        """Verify that Runtime.listCommand is NOT an async method.

        Returns:
            None
        """
        assert not asyncio.iscoroutinefunction(_StubRuntime.listCommand)

    def testRuntimeDetectArtifactsIsNotAsync(self) -> None:
        """Verify that Runtime.detectArtifacts is NOT an async method.

        Returns:
            None
        """
        assert not asyncio.iscoroutinefunction(_StubRuntime.detectArtifacts)

    # -- MetadataStore (all async) --

    def testStoreLoadSessionIsAsync(self) -> None:
        """Verify that MetadataStore.loadSession is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubMetadataStore.loadSession)

    def testStoreSaveSessionIsAsync(self) -> None:
        """Verify that MetadataStore.saveSession is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubMetadataStore.saveSession)

    def testStoreDeleteSessionIsAsync(self) -> None:
        """Verify that MetadataStore.deleteSession is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubMetadataStore.deleteSession)

    def testStoreListSessionsIsAsync(self) -> None:
        """Verify that MetadataStore.listSessions is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubMetadataStore.listSessions)

    def testStoreLoadRunIsAsync(self) -> None:
        """Verify that MetadataStore.loadRun is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubMetadataStore.loadRun)

    def testStoreSaveRunIsAsync(self) -> None:
        """Verify that MetadataStore.saveRun is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubMetadataStore.saveRun)

    def testStoreDeleteRunIsAsync(self) -> None:
        """Verify that MetadataStore.deleteRun is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubMetadataStore.deleteRun)

    def testStoreListRunsForSessionIsAsync(self) -> None:
        """Verify that MetadataStore.listRunsForSession is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubMetadataStore.listRunsForSession)

    def testStoreLoadRuntimeIsAsync(self) -> None:
        """Verify that MetadataStore.loadRuntime is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubMetadataStore.loadRuntime)

    def testStoreSaveRuntimeIsAsync(self) -> None:
        """Verify that MetadataStore.saveRuntime is an async method.

        Returns:
            None
        """
        assert asyncio.iscoroutinefunction(_StubMetadataStore.saveRuntime)


# ============================================================================
# All new dataclasses — slots=True verification
# ============================================================================


_ALL_NEW_DATACLASSES = (
    ContainerSpec,
    ContainerOutcome,
    ManagedContainerInfo,
    SessionRecord,
    RunRecord,
    RuntimeRecord,
)


@pytest.mark.parametrize("cls", _ALL_NEW_DATACLASSES, ids=lambda c: c.__name__)
def testSlotsEnabled(cls: type) -> None:
    """Verify that every new dataclass uses slots=True.

    Args:
        cls: A dataclass to check.

    Returns:
        None
    """
    assert hasattr(cls, "__slots__"), f"{cls.__name__} should have __slots__ (slots=True expected)"
    assert len(cls.__slots__) > 0, f"{cls.__name__} __slots__ should not be empty"


# ============================================================================
# schemaVersion default — all metadata record dataclasses
# ============================================================================


_METADATA_RECORD_CLASSES = (SessionRecord, RunRecord, RuntimeRecord)


@pytest.mark.parametrize("cls", _METADATA_RECORD_CLASSES, ids=lambda c: c.__name__)
def testSchemaVersionDefaultIsOne(cls: type) -> None:
    """Verify that schemaVersion field defaults to 1 for all metadata records.

    Args:
        cls: A metadata record dataclass to check.

    Returns:
        None
    """
    schemaFields = [f for f in fields(cls) if f.name == "schemaVersion"]
    assert len(schemaFields) == 1, f"{cls.__name__} should have exactly one schemaVersion field"
    assert schemaFields[0].default == 1, f"{cls.__name__}.schemaVersion should default to 1"
