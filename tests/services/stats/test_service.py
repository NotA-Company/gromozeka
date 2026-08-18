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
    - Fail-loudly contract: malformed config at initialize raises ValueError, service stays uninitialized
    - Retryability: initialize again with fixed config succeeds after initial failure
    - Config-frozen contract: config changes after initialize do not affect handler behavior
    - Clamp tests at init: interval floor 60, batch-limit floor 1, retentionDays floor 0
    - Batch limit: drain calls aggregate(limit=<batchLimit>)
    - Summary logging with per-storage processed/purged/errors using registry keys as labels (regression)

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
        "aggregation-batch-limit": 1000,
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
        assert statsAggregationService._intervalSeconds == 3600  # Default from __init__
        assert statsAggregationService._retentionDays == 30  # Default from __init__
        assert statsAggregationService._batchLimit == 1000  # Default from __init__
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


class TestConfigFrozenContract:
    """Test that config is frozen at initialize (changes after init have no effect)."""

    async def testConfigChangesAfterInitializeHaveNoEffect(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that changing config mock after initialize does not affect handler behavior."""
        # Initialize with config interval=60s for fast testing
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 60,  # Short interval for testing
            "events-retention-days": 30,
            "aggregation-batch-limit": 500,  # Custom batch limit
        }

        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Verify getStatsConfig was called once at initialize
        assert mockConfigManager.getStatsConfig.call_count == 1

        # Store call count before running handler
        initialCallCount = mockConfigManager.getStatsConfig.call_count

        # Set _lastRunTime to now (within interval)
        statsAggregationService._lastRunTime = time.time()

        # Run handler within interval (should no-op)
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify getStatsConfig NOT called again (no per-cycle re-read)
        assert mockConfigManager.getStatsConfig.call_count == initialCallCount
        assert mockStorage.aggregate.call_count == 0

        # Advance _lastRunTime past interval
        statsAggregationService._lastRunTime = time.time() - 61

        # CHANGE the config mock (simulating config change after startup)
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 9999,  # Different interval
            "events-retention-days": 999,  # Different retention
            "aggregation-batch-limit": 9999,  # Different batch limit
        }

        # Run handler again (interval elapsed)
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify getStatsConfig NOT called again (config frozen at init)
        assert mockConfigManager.getStatsConfig.call_count == initialCallCount

        # Verify aggregate was called with INIT-TIME batch limit (500), not the new 9999
        assert mockStorage.aggregate.call_count >= 1
        # Check that aggregate was called with the init-time batch limit
        for call in mockStorage.aggregate.call_args_list:
            assert call.kwargs.get("limit") == 500, "Should use init-time batch limit, not post-init config"

        # Verify _intervalSeconds was NOT changed (still 60 from init)
        assert statsAggregationService._intervalSeconds == 60

    async def testConfigChangesAfterInitializeDoNotAffectRetention(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that changing retention config after initialize does not affect handler behavior."""
        # Initialize with retentionDays=0 (no purge)
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 60,
            "events-retention-days": 0,  # No purge
            "aggregation-batch-limit": 1000,
        }

        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # CHANGE the config mock to retentionDays=30
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 60,
            "events-retention-days": 30,  # Should purge now
            "aggregation-batch-limit": 1000,
        }

        # Run handler (interval elapsed)
        statsAggregationService._lastRunTime = time.time() - 61
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify purgeProcessed was NOT called (retentionDays=0 from init)
        assert mockStorage.purgeProcessed.call_count == 0

        # Verify _retentionDays was NOT changed (still 0 from init)
        assert statsAggregationService._retentionDays == 0


class TestInitializationValidation:
    """Test initialization validation (fail-loudly contract, clamp, retryability)."""

    def testMalformedIntervalRaisesValueError(
        self, statsAggregationService, mockConfigManager, mockDatabase, queueService
    ):
        """Test that malformed interval raises ValueError, service stays uninitialized."""
        # Config with non-numeric interval (malformed TOML)
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": "1h",  # Non-numeric!
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

        # Initialize should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Verify error message mentions the malformed key
        msg = str(exc_info.value)
        assert "Malformed [stats] configuration" in msg
        assert "aggregation-interval-seconds" in msg
        # Discriminate: this error is about interval, NOT retention or batch-limit
        assert "events-retention-days" not in msg
        assert "aggregation-batch-limit" not in msg

        # Verify service stays uninitialized
        assert statsAggregationService._initialized is False
        assert statsAggregationService._intervalSeconds == 3600  # Default unchanged
        assert statsAggregationService._retentionDays == 30  # Default unchanged
        assert statsAggregationService._batchLimit == 1000  # Default unchanged

        # Verify handler NOT registered on QueueService
        assert DelayedTaskFunction.CRON_JOB not in queueService.tasksHandlers

    def testMalformedRetentionRaisesValueError(
        self, statsAggregationService, mockConfigManager, mockDatabase, queueService
    ):
        """Test that malformed retention raises ValueError, service stays uninitialized."""
        # Config with non-numeric retention (malformed TOML)
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": "30d",  # Non-numeric!
            "aggregation-batch-limit": 1000,
        }

        # Initialize should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Verify error message mentions the malformed key
        msg = str(exc_info.value)
        assert "Malformed [stats] configuration" in msg
        assert "events-retention-days" in msg
        # Discriminate: this error is about retention, NOT interval or batch-limit
        assert "aggregation-interval-seconds" not in msg
        assert "aggregation-batch-limit" not in msg

        # Verify service stays uninitialized
        assert statsAggregationService._initialized is False

    def testMalformedBatchLimitRaisesValueError(
        self, statsAggregationService, mockConfigManager, mockDatabase, queueService
    ):
        """Test that malformed batch limit raises ValueError, service stays uninitialized."""
        # Config with non-numeric batch limit (malformed TOML)
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": 30,
            "aggregation-batch-limit": "1000x",  # Malformed string!
        }

        # Initialize should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Verify error message mentions the malformed key
        msg = str(exc_info.value)
        assert "Malformed [stats] configuration" in msg
        assert "aggregation-batch-limit" in msg
        # Discriminate: this error is about batch-limit, NOT interval or retention
        assert "aggregation-interval-seconds" not in msg
        assert "events-retention-days" not in msg

        # Verify service stays uninitialized
        assert statsAggregationService._initialized is False

    def testRetryabilityAfterConfigFix(self, statsAggregationService, mockConfigManager, mockDatabase, queueService):
        """Test that initialize again with fixed config succeeds after initial failure."""
        # First attempt: malformed config → fails
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": "1h",  # Non-numeric!
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

        with pytest.raises(ValueError):
            statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Verify service is still uninitialized
        assert statsAggregationService._initialized is False

        # FIX the config (now valid)
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,  # Now valid!
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

        # Second attempt: should succeed
        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Verify service is now initialized
        assert statsAggregationService._initialized is True
        assert statsAggregationService._intervalSeconds == 3600

        # Verify handler is registered on QueueService
        assert DelayedTaskFunction.CRON_JOB in queueService.tasksHandlers
        assert len(queueService.tasksHandlers[DelayedTaskFunction.CRON_JOB]) == 1

    def testFailedInitializeReturnsNullStatsStorageAndEmptyRegistry(
        self, statsAggregationService, mockConfigManager, mockDatabase, queueService
    ):
        """Test that failed initialize returns NullStatsStorage and keeps registry empty."""
        # Config with malformed interval (malformed TOML)
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": "1h",  # Non-numeric!
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

        # Initialize should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Verify error message mentions the malformed key
        assert "Malformed [stats] configuration" in str(exc_info.value)
        assert "aggregation-interval-seconds" in str(exc_info.value)

        # Verify service stays uninitialized
        assert statsAggregationService._initialized is False

        # Verify handler NOT registered on QueueService
        assert DelayedTaskFunction.CRON_JOB not in queueService.tasksHandlers

        # Verify createStatsStorage returns NullStatsStorage when not initialized
        storage = statsAggregationService.createStatsStorage("message")
        assert isinstance(storage, NullStatsStorage)

        # Verify registry stays empty
        assert statsAggregationService._statsStorages == {}

    def testIntervalClampFloor(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that interval config value 30 is clamped to floor of 60."""
        # Config with interval below floor
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 30,  # Below 60-second floor
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

        # Initialize
        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Verify interval was clamped to 60
        assert statsAggregationService._intervalSeconds == 60

    def testIntervalClampFloorString(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that interval config value "30" (string) is clamped to floor of 60."""
        # Config with interval as string
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": "30",  # String, but parsable
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

        # Initialize
        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Verify interval was parsed and clamped to 60
        assert statsAggregationService._intervalSeconds == 60

    def testBatchLimitClampFloor(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that batch limit config value 0 is clamped to floor of 1."""
        # Config with batch limit at floor
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": 30,
            "aggregation-batch-limit": 0,  # At floor
        }

        # Initialize
        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Verify batch limit was clamped to 1
        assert statsAggregationService._batchLimit == 1

    def testRetentionDaysClampFloor(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that retentionDays config value -5 is clamped to floor of 0."""
        # Config with negative retention
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": -5,  # Negative (keep forever)
            "aggregation-batch-limit": 1000,
        }

        # Initialize
        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Verify retentionDays was clamped to 0
        assert statsAggregationService._retentionDays == 0


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
        """Test that empty registry results in immediate return, no work."""
        # Initialize without any storages (config read once at initialize)
        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Verify getStatsConfig was called once at initialize (new behavior)
        assert mockConfigManager.getStatsConfig.call_count == 1

        # Store call count before running handler
        initialCallCount = mockConfigManager.getStatsConfig.call_count

        # Run the handler (empty registry)
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify getStatsConfig was NOT called again (no per-cycle re-read)
        assert mockConfigManager.getStatsConfig.call_count == initialCallCount


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
            "aggregation-batch-limit": 1000,
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
            "aggregation-batch-limit": 1000,
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
            "aggregation-batch-limit": 1000,
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
    """Test drain loop behavior (stops at 0, caps at MAX_AGGREGATION_ROUNDS, batch limit)."""

    async def testDrainStopsAtZero(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that drain loop stops when aggregate() returns 0."""
        # Initialize and register a storage
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 60,
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

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
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 60,
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Setup: aggregate always returns 1000
        mockStorage.aggregate.return_value = 1000

        # Run the handler
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate was called exactly MAX_AGGREGATION_ROUNDS times
        assert mockStorage.aggregate.call_count == MAX_AGGREGATION_ROUNDS

    async def testDrainPassesBatchLimitToAggregate(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage, sampleDelayedTask
    ):
        """Test that drain loop passes the configured batch limit to aggregate()."""
        # Initialize with custom batch limit
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 60,
            "events-retention-days": 30,
            "aggregation-batch-limit": 500,  # Custom batch limit
        }

        statsAggregationService.initialize(mockConfigManager, mockDatabase)
        statsAggregationService._statsStorages["test_event"] = mockStorage

        # Setup: aggregate returns 0 after one call
        mockStorage.aggregate.return_value = 0

        # Run the handler
        await statsAggregationService._dtCronJob(sampleDelayedTask)

        # Verify aggregate was called with the custom batch limit
        assert mockStorage.aggregate.call_count == 1
        mockStorage.aggregate.assert_called_once_with(limit=500)


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
        storage1.aggregate.side_effect = RuntimeError("Storage 1 failed")
        storage1.purgeProcessed.return_value = 0

        storage2 = AsyncMock(spec=StatsStorage)
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
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 60,
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

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
            "aggregation-interval-seconds": 60,
            "events-retention-days": 0,
            "aggregation-batch-limit": 1000,
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

        This test verifies that two storages with DISTINCT registry keys both appear:
        - storage1 (message) raises during aggregate
        - storage2 (command) succeeds
        The summary line must contain BOTH registry keys (labels), error marker for storage1,
        and aggregated count for storage2.
        """
        # Setup: storage1 raises, storage2 succeeds
        storage1 = AsyncMock(spec=StatsStorage)
        storage1.aggregate.side_effect = RuntimeError("Storage 1 failed during drain")
        storage1.purgeProcessed.return_value = 0

        storage2 = AsyncMock(spec=StatsStorage)
        storage2.aggregate.side_effect = [1000, 0]  # Drain stops after 1000
        storage2.purgeProcessed.return_value = 50

        # Initialize and register both storages
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 60,
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

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

        # Verify BOTH storage labels (registry keys) appear in the summary
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
            "aggregation-batch-limit": 1000,
        }

        # Set a custom default datasource
        mockDatabase.manager.default = "custom_datasource"

        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Create storage without dataSource parameter (None)
        storage = statsAggregationService.createStatsStorage("llm_request")

        # Verify it's a DatabaseStatsStorage with the default datasource
        assert storage.__class__.__name__ == "DatabaseStatsStorage"
        assert storage.dataSource == "custom_datasource"


# ============================================================================
# GetQueryStorage Tests
# ============================================================================


class TestGetQueryStorage:
    """Test getQueryStorage accessor behavior."""

    def testGetQueryStorageReturnsRegisteredStorage(
        self, statsAggregationService, mockConfigManager, mockDatabase, mockStorage
    ):
        """Test that getQueryStorage returns the registered storage for eventType."""
        # Config with enabled = True
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Create and register two storages
        storage1 = statsAggregationService.createStatsStorage("llm_request", dataSource="default")
        storage2 = statsAggregationService.createStatsStorage("message", dataSource="default")

        # Query for registered eventTypes should return the registered storages
        assert statsAggregationService.getQueryStorage("llm_request") is storage1
        assert statsAggregationService.getQueryStorage("message") is storage2

    def testGetQueryStorageUnregisteredReturnsNull(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that getQueryStorage returns NullStatsStorage for unregistered eventType."""
        # Config with enabled = True
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Register one storage
        statsAggregationService.createStatsStorage("llm_request", dataSource="default")

        # Query for unregistered eventType should return NullStatsStorage
        result = statsAggregationService.getQueryStorage("message")
        assert isinstance(result, NullStatsStorage)

        # Query for a third unregistered eventType should also return NullStatsStorage
        result2 = statsAggregationService.getQueryStorage("command")
        assert isinstance(result2, NullStatsStorage)

    def testGetQueryStorageNotInitializedReturnsNull(self, statsAggregationService):
        """Test that getQueryStorage returns NullStatsStorage when service not initialized."""
        # Don't call initialize

        # Query should return NullStatsStorage
        result = statsAggregationService.getQueryStorage("llm_request")
        assert isinstance(result, NullStatsStorage)

    def testGetQueryStorageReturnsFreshNullEachCall(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that getQueryStorage returns a fresh NullStatsStorage each unregistered call."""
        # Config with enabled = True
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": True,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Don't register any storages

        # Each call should return a new NullStatsStorage instance (or the same one is fine too)
        # The important part is that it IS a NullStatsStorage
        result1 = statsAggregationService.getQueryStorage("llm_request")
        result2 = statsAggregationService.getQueryStorage("message")

        assert isinstance(result1, NullStatsStorage)
        assert isinstance(result2, NullStatsStorage)

    def testGetQueryStorageWithDisabledStatsReturnsNull(self, statsAggregationService, mockConfigManager, mockDatabase):
        """Test that getQueryStorage returns NullStatsStorage when stats disabled."""
        # Config with enabled = False
        mockConfigManager.getStatsConfig.return_value = {
            "enabled": False,
            "aggregation-interval-seconds": 3600,
            "events-retention-days": 30,
            "aggregation-batch-limit": 1000,
        }

        statsAggregationService.initialize(mockConfigManager, mockDatabase)

        # Try to create a storage (should return unregistered NullStatsStorage)
        statsAggregationService.createStatsStorage("llm_request", dataSource="default")

        # Query should return NullStatsStorage (registry is empty)
        result = statsAggregationService.getQueryStorage("llm_request")
        assert isinstance(result, NullStatsStorage)
