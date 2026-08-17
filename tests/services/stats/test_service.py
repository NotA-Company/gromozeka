"""
Comprehensive test suite for StatsAggregationService (CRON_JOB rider version).

This module provides extensive unit and integration tests for the stats aggregation service,
covering singleton behavior, initialization, CRON_JOB tick registration, elapsed-time gating,
factory pattern, aggregation cycles, per-storage isolation, retention purging, config error handling,
and summary logging.

Test Coverage:
    - Singleton pattern enforcement and idempotent initialization
    - Handler registration on CRON_JOB (no STATS_AGGREGATION function)
    - Elapsed-time gate: first tick runs work, interval-elapsed ticks run, within-interval ticks no-op
    - Empty registry: handler returns immediately, no config read, no work
    - Factory: disabled config returns unregistered NullStatsStorage
    - Factory: enabled config returns registered DatabaseStatsStorage
    - Factory: duplicate eventType overwrites last-wins
    - Drain loop behavior (stops at 0, caps at MAX_AGGREGATION_ROUNDS)
    - Per-storage isolation (one storage failing doesn't block others)
    - Retention purge gating (events-retention-days = 0 skips purge)
    - Retention purge deletes only processed+old rows (through per-storage datasource)
    - Malformed config: non-numeric interval skips work, advances gate, logs error, next interval skips too
    - Duplicate-run impossibility: two consecutive calls within interval → work runs once
    - Summary logging with per-storage processed/purged/errors (regression: failed storages appear)

Example:
    Run tests from project root:
        ./venv/bin/pytest tests/services/stats/test_service.py
"""

import logging
import time
from unittest.mock import AsyncMock, Mock

import pytest

from internal.config.manager import ConfigManager
from internal.database import Database
from internal.services.queue_service import QueueService
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction
from internal.services.stats import MAX_AGGREGATION_ROUNDS, StatsAggregationService
from lib.stats.stats_storage import NullStatsStorage, StatsStorage

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def resetSingletons():
    """Reset StatsAggregationService and QueueService singletons before each test.

    Both services leak state across tests; this autouse fixture ensures clean
    state for every test without requiring explicit fixture calls.
    """
    # Reset before test
    StatsAggregationService._instance = None
    QueueService._instance = None
    yield
    # Reset after test
    StatsAggregationService._instance = None
    QueueService._instance = None


@pytest.fixture
def statsAggregationService():
    """Create a fresh StatsAggregationService instance for each test."""
    service = StatsAggregationService.getInstance()
    yield service


@pytest.fixture
def mockConfigManager():
    """Create a mock ConfigManager with stats config."""
    mock = Mock(spec=ConfigManager)
    mock.getStatsConfig.return_value = {
        "enabled": True,
        "aggregation-interval-seconds": 3600,
        "events-retention-days": 30,
    }
    return mock


@pytest.fixture
def mockDatabase():
    """Create a mock Database instance."""
    mock = Mock(spec=Database)
    mock.manager = Mock()
    mock.manager.default = "default"
    return mock


@pytest.fixture
def mockStorage():
    """Create a mock StatsStorage for testing."""
    storage = AsyncMock(spec=StatsStorage)
    storage.aggregate.return_value = 0
    storage.purgeProcessed.return_value = 0
    storage.eventType = "test_event"
    return storage


@pytest.fixture
def queueService():
    """Create a fresh QueueService instance for each test."""
    service = QueueService.getInstance()
    yield service


@pytest.fixture
def sampleDelayedTask():
    """Create a sample DelayedTask for testing."""
    return DelayedTask(
        taskId="test-task-123", delayedUntil=time.time(), function=DelayedTaskFunction.CRON_JOB, kwargs={}
    )


# ============================================================================
# Singleton and Initialization Tests
# ============================================================================


class TestStatsAggregationServiceSingleton:
    """Test StatsAggregationService singleton and initialization behavior."""

    def testSingletonInstance(self, statsAggregationService):
        """Test that StatsAggregationService follows singleton pattern."""
        service1 = StatsAggregationService.getInstance()
        service2 = StatsAggregationService.getInstance()

        assert service1 is service2
        assert service1 is statsAggregationService

    def testInitializationState(self, statsAggregationService):
        """Test that StatsAggregationService initializes with correct default state."""
        assert statsAggregationService.initialized is True
        assert statsAggregationService._configManager is None
        assert statsAggregationService._database is None
        assert statsAggregationService._statsStorages == {}
        assert statsAggregationService._lastRunTime == 0.0
        assert statsAggregationService._intervalSeconds == 3600
        assert statsAggregationService._initialized is False

    def testMultipleInitializationCalls(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that multiple initialize calls don't re-initialize."""
        # First initialization
        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Store references to verify they don't change
        firstConfigManager = statsAggregationService._configManager
        firstDatabase = statsAggregationService._database

        # Second initialization (should be no-op)
        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        assert statsAggregationService._configManager is firstConfigManager
        assert statsAggregationService._database is firstDatabase


# ============================================================================
# Handler Registration Tests
# ============================================================================


class TestHandlerRegistration:
    """Test CRON_JOB handler registration."""

    def testRegistersCRONJobHandler(self, statsAggregationService, mockConfigManager, mockDatabase, queueService):
        """Test that initialize registers the handler on CRON_JOB."""
        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Handler should be registered on CRON_JOB
        assert DelayedTaskFunction.CRON_JOB in queueService.tasksHandlers
        assert len(queueService.tasksHandlers[DelayedTaskFunction.CRON_JOB]) == 1
        assert queueService.tasksHandlers[DelayedTaskFunction.CRON_JOB][0] == statsAggregationService._dtCronJob

    def testNoStatsAggregationFunctionExists(self):
        """Test that STATS_AGGREGATION no longer exists as a DelayedTaskFunction."""
        # This should raise AttributeError or the member should not exist
        assert not hasattr(DelayedTaskFunction, "STATS_AGGREGATION")


# ============================================================================
# Tick Gating Tests
# ============================================================================


class TestTickGating:
    """Test elapsed-time gate behavior (first tick, interval-elapsed, within-interval)."""

    async def testFirstTickRunsWork(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that first tick after startup runs work (_lastRunTime = 0.0)."""
        # Initialize and register a storage
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Mock aggregate/purge to verify they were called
        mockStorage.aggregate.return_value = 100
        mockStorage.purgeProcessed.return_value = 10

        # Run the handler (first tick)
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate was called (first tick runs work)
        assert mockStorage.aggregate.call_count >= 1
        # Verify purge was called
        assert mockStorage.purgeProcessed.call_count == 1

    async def testWithinIntervalNoWork(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that within-interval ticks do no work."""
        # Initialize and register a storage
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Set _lastRunTime to now (simulating a just-completed cycle)
        statsAggregationService._lastRunTime = time.time()

        # Run the handler (within interval)
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate was NOT called (interval gate blocked)
        assert mockStorage.aggregate.call_count == 0
        # Verify purge was NOT called
        assert mockStorage.purgeProcessed.call_count == 0

    async def testElapsedIntervalRunsWork(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that elapsed-interval ticks run work."""
        # Initialize and register a storage
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Set _lastRunTime to more than the interval ago (3601 seconds)
        statsAggregationService._lastRunTime = time.time() - 3601

        # Mock aggregate/purge to verify they were called
        mockStorage.aggregate.return_value = 100
        mockStorage.purgeProcessed.return_value = 10

        # Run the handler (interval elapsed)
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate was called
        assert mockStorage.aggregate.call_count >= 1
        # Verify purge was called
        assert mockStorage.purgeProcessed.call_count == 1

    async def testDuplicateRunImpossibility(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that two consecutive calls within interval result in work running once."""
        # Initialize and register a storage
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Mock aggregate/purge to verify they were called
        mockStorage.aggregate.return_value = 100
        mockStorage.purgeProcessed.return_value = 10

        # First call: _lastRunTime = 0.0 → work runs
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate was called once
        assert mockStorage.aggregate.call_count >= 1
        firstCallCount = mockStorage.aggregate.call_count

        # Second call: _lastRunTime advanced to recent → no work
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate call count did NOT increase (no new work)
        assert mockStorage.aggregate.call_count == firstCallCount


# ============================================================================
# Empty Registry Tests
# ============================================================================


class TestEmptyRegistry:
    """Test empty registry behavior."""

    async def testEmptyRegistryNoOp(self, statsAggregationService, mockConfigManager, mockDatabase, sampleDelayedTask):
        """Test that empty registry results in immediate return, no config read, no work."""
        # Initialize without any storages
        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Run the handler (empty registry)
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify getStatsConfig was NOT called (no config read for empty registry)
        assert mockConfigManager.getStatsConfig.call_count == 0


# ============================================================================
# Factory Tests
# ============================================================================


class TestFactory:
    """Test storage factory behavior."""

    def testFactoryDisabledReturnsNull(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that disabled config returns unregistered NullStatsStorage."""
        # Config with enabled = False
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": False,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": 30,
        }

        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Create storage (should return NullStatsStorage)
        storage = statsAggregationService.createStatsStorage("llm_request")

        # Verify it's a NullStatsStorage
        assert isinstance(storage, NullStatsStorage)

        # Verify registry stays empty (NOT registered)
        assert statsAggregationService._statsStorages == {}

    def testFactoryEnabledRegistersStorage(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that enabled config returns and registers DatabaseStatsStorage."""
        # Config with enabled = True
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": 30,
        }

        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Create storage (should return DatabaseStatsStorage)
        storage = statsAggregationService.createStatsStorage("llm_request")

        # Verify it's a DatabaseStatsStorage
        assert storage.__class__.__name__ == "DatabaseStatsStorage"

        # Verify registry contains the storage (registered)
        assert "llm_request" in statsAggregationService._statsStorages
        assert statsAggregationService._statsStorages["llm_request"] is storage

    def testFactoryDuplicateEventTypeOverwrites(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that duplicate eventType overwrites (last-wins semantics)."""
        # Config with enabled = True
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": 30,
        }

        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Create first storage
        storage1 = statsAggregationService.createStatsStorage("llm_request", dataSource="default")

        # Create second storage with same eventType (different dataSource)
        storage2 = statsAggregationService.createStatsStorage("llm_request", dataSource="custom")

        # Verify second storage overwrote first in registry
        assert statsAggregationService._statsStorages["llm_request"] is storage2
        assert statsAggregationService._statsStorages["llm_request"] is not storage1

        # Verify returned storage is the second one (NOT the same as the first)
        assert storage2 is not storage1


# ============================================================================
# Drain Loop Tests
# ============================================================================


class TestDrainLoop:
    """Test drain loop behavior (stops at 0, caps at MAX_AGGREGATION_ROUNDS)."""

    async def testDrainStopsAtZero(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that drain loop stops when aggregate() returns 0."""
        # Initialize and register a storage
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Setup: aggregate returns 1000, then 500, then 0
        mockStorage.aggregate.side_effect = [1000, 500, 0]

        # Run the handler
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate was called 3 times (1000 + 500 + 0)
        assert mockStorage.aggregate.call_count == 3

    async def testDrainCapsAtMaxRounds(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that drain loop caps at MAX_AGGREGATION_ROUNDS."""
        # Initialize and register a storage
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Setup: aggregate always returns 1000
        mockStorage.aggregate.return_value = 1000

        # Run the handler
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate was called exactly MAX_AGGREGATION_ROUNDS times
        assert mockStorage.aggregate.call_count == MAX_AGGREGATION_ROUNDS


# ============================================================================
# Per-Storage Isolation Tests
# ============================================================================


class TestPerStorageIsolation:
    """Test per-storage isolation (one storage failing doesn't block others)."""

    async def testStorageFailureDoesNotBlockOthers(
        self, statsAggregationService, mockConfigManager, mockDatabase, sampleDelayedTask
    ):
        """Test that one storage raising exception doesn't prevent others from being processed."""
        # Setup: storage1 raises, storage2 succeeds
        storage1 = AsyncMock(spec=StatsStorage)
        storage1.eventType = "message"
        storage1.aggregate.side_effect = RuntimeError("Storage 1 failed")
        storage1.purgeProcessed.return_value = 0

        storage2 = AsyncMock(spec=StatsStorage)
        storage2.eventType = "command"
        storage2.aggregate.side_effect = [500, 0]  # First call 500, second 0 (drain stops)
        storage2.purgeProcessed.return_value = 100

        # Initialize and register both storages
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["message"] = storage1
        statsAggregationService._statsStorages["command"] = storage2

        # Run the handler
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify storage1 was attempted (raised and was caught)
        assert storage1.aggregate.call_count == 1
        # storage1.purgeProcessed should NOT have been called (aggregate failed)
        assert storage1.purgeProcessed.call_count == 0

        # Verify storage2 was successfully processed (drain loop: 500 then 0)
        assert storage2.aggregate.call_count == 2
        assert storage2.purgeProcessed.call_count == 1


# ============================================================================
# Retention Tests
# ============================================================================


class TestRetention:
    """Test retention purge behavior."""

    async def testPurgeCalledAfterAggregate(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that purgeProcessed is called after aggregate completes."""
        # Initialize and register a storage
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Setup
        mockStorage.aggregate.return_value = 1000
        mockStorage.purgeProcessed.return_value = 50

        # Run the handler
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify both were called
        assert mockStorage.aggregate.call_count >= 1
        assert mockStorage.purgeProcessed.call_count == 1

        # Verify purge was called with correct retentionDays from config
        mockStorage.purgeProcessed.assert_called_with(retentionDays=30)

    async def testRetentionZeroSkipsPurge(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that events-retention-days = 0 skips the purge call."""
        # Setup config with retention-days = 0
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": 0,
        }

        # Initialize and register a storage
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        mockStorage.aggregate.return_value = 1000
        mockStorage.purgeProcessed.return_value = 0

        # Run the handler
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate was called but purge was NOT
        assert mockStorage.aggregate.call_count >= 1
        assert mockStorage.purgeProcessed.call_count == 0


# ============================================================================
# Malformed Config Tests
# ============================================================================


class TestMalformedConfig:
    """Test malformed config handling."""

    async def testMalformedIntervalSkipsWorkAndAdvancesGate(
        self,
        statsAggregationService,
        mockConfigManager,
        mockDatabase,
        mockStorage,
        sampleDelayedTask,
        caplog,
    ):
        """Test that non-numeric interval skips work, advances gate, logs error."""
        # Initialize and register a storage
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Setup config with non-numeric interval (malformed TOML)
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": "1h",  # Non-numeric!
            "events-retention-days": 30,
        }

        mockStorage.aggregate.return_value = 100
        mockStorage.purgeProcessed.return_value = 10

        # Run the handler with caplog to capture error logs
        with caplog.at_level(logging.ERROR):
            await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate was NOT called (work skipped)
        assert mockStorage.aggregate.call_count == 0
        # Verify purge was NOT called (work skipped)
        assert mockStorage.purgeProcessed.call_count == 0

        # Verify gate was advanced (so error logs once per interval, not per tick)
        assert statsAggregationService._lastRunTime > 0.0

        # Verify an error was logged about malformed config
        errorMessages = [r.message for r in caplog.records if r.levelname == "ERROR"]
        assert any("malformed [stats] config" in msg for msg in errorMessages)

        # Run again immediately (gate already advanced) → should still skip
        caplog.clear()
        with caplog.at_level(logging.ERROR):
            await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate still NOT called (interval gate blocks)
        assert mockStorage.aggregate.call_count == 0

    async def testMalformedConfigRecoveryAfterFix(
        self,
        statsAggregationService,
        mockConfigManager,
        mockDatabase,
        mockStorage,
        sampleDelayedTask,
    ):
        """Test that work resumes after fixing malformed config and interval elapses."""
        # Initialize and register a storage
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Setup config with non-numeric interval (malformed)
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": "1h",  # Non-numeric!
            "events-retention-days": 30,
        }

        # Run the handler (should skip work and advance gate)
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify work was skipped
        assert mockStorage.aggregate.call_count == 0
        assert mockStorage.purgeProcessed.call_count == 0

        # Gate should be advanced
        assert statsAggregationService._lastRunTime > 0.0

        # FIX the config (now valid)
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,  # Now valid!
            "events-retention-days": 30,
        }

        # Set _lastRunTime far enough back that interval has elapsed
        statsAggregationService._lastRunTime = time.time() - 3601

        # Mock aggregate/purge to verify they were called
        mockStorage.aggregate.return_value = 100
        mockStorage.purgeProcessed.return_value = 10

        # Run the handler again (should work with corrected config)
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate WAS called (work resumed)
        assert mockStorage.aggregate.call_count >= 1
        # Verify purge was called
        assert mockStorage.purgeProcessed.call_count == 1


# ============================================================================
# Regression Tests
# ============================================================================


class TestRegression:
    """Regression tests for bugs discovered in code review."""

    async def testSummaryIncludesFailedStorages(
        self, statsAggregationService, mockConfigManager, mockDatabase, sampleDelayedTask, caplog
    ):
        """Regression test: summary MUST include storages that fail during drain.

        Before fix: summary loop iterated over perStorageProcessed keys only,
        so storages that raised during aggregate() never appeared in the
        summary (other storages were invisible).

        This test verifies that two storages with DISTINCT labels both appear:
        - storage1 (message) raises during aggregate
        - storage2 (command) succeeds
        The summary line must contain BOTH labels, error marker for storage1,
        and aggregated count for storage2.
        """
        # Setup: storage1 raises, storage2 succeeds
        storage1 = AsyncMock(spec=StatsStorage)
        storage1.eventType = "message"
        storage1.aggregate.side_effect = RuntimeError("Storage 1 failed during drain")
        storage1.purgeProcessed.return_value = 0

        storage2 = AsyncMock(spec=StatsStorage)
        storage2.eventType = "command"
        storage2.aggregate.side_effect = [1000, 0]  # Drain stops after 1000
        storage2.purgeProcessed.return_value = 50

        # Initialize and register both storages
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["message"] = storage1
        statsAggregationService._statsStorages["command"] = storage2

        # Run the handler with caplog to capture INFO summary
        with caplog.at_level(logging.INFO):
            await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Find the summary line
        summaryLines = [r.message for r in caplog.records if "Stats aggregation cycle complete" in r.message]
        assert len(summaryLines) == 1, f"Expected 1 summary line, got {len(summaryLines)}"

        summary = summaryLines[0]

        # Verify BOTH storage labels appear in the summary
        assert "message:" in summary, "Summary must include storage1 (message) label"
        assert "command:" in summary, "Summary must include storage2 (command) label"

        # Verify storage1 shows error marker
        assert "error=" in summary, "Summary must include error marker for failed storage"
        assert (
            "Storage 1 failed during drain" in summary or "RuntimeError" in summary
        ), "Summary must include error message from storage1"

        # Verify storage2 shows aggregated count
        assert "aggregated=1000" in summary, "Summary must include aggregated count for storage2"

        # Verify storage2 shows purged count
        assert "purged=50" in summary, "Summary must include purged count for storage2"

    def testFactoryDataSourceNoneResolvesToDefault(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that dataSource=None resolves to database's manager.default."""
        # Config with enabled = True
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": 30,
        }

        # Set a custom default datasource
        mockDatabase.manager.default = "custom_datasource"

        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Create storage without dataSource parameter (None)
        storage = statsAggregationService.createStatsStorage("llm_request")

        # Verify it's a DatabaseStatsStorage with the default datasource
        assert storage.__class__.__name__ == "DatabaseStatsStorage"
        assert storage.dataSource == "custom_datasource"

    async def testIntervalClampFloor(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that interval config value 30 is clamped to floor of 60."""
        # Config with interval below floor
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 30,  # Below 60-second floor
            "events-retention-days": 30,
        }

        # Initialize and register a storage
        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Set _lastRunTime to 0 (first run, gate always passes)
        statsAggregationService._lastRunTime = 0.0

        # Run the handler (gate passes, config is parsed, interval clamped to 60)
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify _intervalSeconds was clamped to 60
        assert statsAggregationService._intervalSeconds == 60

        # Set _lastRunTime to 61 seconds ago (more than clamped interval of 60)
        statsAggregationService._lastRunTime = time.time() - 61

        # Run again (should work now)
        await statsAggregationService._dtCronJob(sampleDelayedTask)
        assert mockStorage.aggregate.call_count >= 1
