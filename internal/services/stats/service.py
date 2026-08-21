"""Stats aggregation service — periodic coordinator for all stat storages.

Singleton service that registers a handler on the shared CRON_JOB 60-second tick
and gates on elapsed time. Owns the storage factory + registry — the single
construction seam for stats storages.

Usage::

    # At startup (sync):
    StatsAggregationService.getInstance().initialize(configManager, database)

    # Construct storages (factory reads [stats] enabled itself):
    llmStorage = StatsAggregationService.getInstance().createStatsStorage(
        "llm_request", dataSource="default"
    )
"""

from __future__ import annotations

import logging
import time
from threading import RLock
from typing import Any, Dict, Optional

from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.stats_storage import DatabaseStatsStorage
from internal.services.queue_service import DelayedTask, DelayedTaskFunction, QueueService
from lib.stats import NullStatsStorage, StatsStorage

logger = logging.getLogger(__name__)

# Maximum number of aggregate() calls per storage per cycle.
# Bounds a cycle at MAX_AGGREGATION_ROUNDS × batch-limit events per storage
# to prevent a runaway backlog from monopolizing the delayed queue.
MAX_AGGREGATION_ROUNDS = 10


def _parseIntKey(statsConfig: Dict[str, Any], key: str, default: int) -> int:
    """Parse an integer configuration key with a specific error message.

    Args:
        statsConfig: The configuration dictionary to read from.
        key: The configuration key to parse.
        default: The default value if the key is not present.

    Returns:
        The parsed integer value.

    Raises:
        ValueError: If the value is not a valid integer, with a message naming the key.
    """
    rawValue = statsConfig.get(key, default)

    # Reject bool explicitly (bool is a subclass of int, so check first)
    if isinstance(rawValue, bool):
        raise ValueError(f"Malformed [stats] configuration: {key}={rawValue!r} is a boolean, not an integer")

    # Reject float type
    if isinstance(rawValue, float):
        raise ValueError(f"Malformed [stats] configuration: {key}={rawValue!r} is a float, not an integer")

    # Parse the value
    try:
        parsedValue = int(rawValue)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Malformed [stats] configuration: {key}={rawValue!r} is not a valid integer") from e

    return parsedValue


class StatsAggregationService:
    """Singleton coordinator for periodic stats aggregation and retention.

    Mirrors :class:`~internal.services.stt.service.STTService` exactly:
    class-level ``_instance`` / ``_lock``, ``__new__`` create-or-return,
    ``getInstance()`` classmethod, ``hasattr(self, 'initialized')`` guard,
    and a separate ``initialize(...)`` method that receives config and
    database at startup.

    The service:
    - Registers a handler on ``DelayedTaskFunction.CRON_JOB`` (shared 60s tick)
    - Gates on elapsed time in-memory (``_lastRunTime``)
    - Owns the storage factory + registry (``createStatsStorage``)
    - Drains all registered storages sequentially with per-storage isolation
    - Purges processed events past the retention window per-datasource (deduplicated)

    Usage::

        # At startup (sync — registration is a dict append):
        StatsAggregationService.getInstance().initialize(configManager, database)

        # Construct storages (factory reads [stats] enabled itself):
        llmStorage = StatsAggregationService.getInstance().createStatsStorage("llm_request", dataSource="default")

    Attributes:
        _configManager: The application configuration manager.
        _database: The database instance for storage construction.
        _statsEnabled: Cached enabled flag (parsed once at initialize).
        _statsStorages: Registry of event type -> StatsStorage.
        _lastRunTime: Timestamp of the last cycle start (0.0 = never run).
        _intervalSeconds: Configured interval in seconds, clamped >= 60, cached at init.
        _retentionDays: Configured retention in days, clamped >= 0 (0 = keep forever), cached at init.
        _batchLimit: Configured aggregation batch limit, clamped >= 1, cached at init.
        _initialized: Whether :meth:`initialize` has completed successfully.
    """

    _instance: Optional["StatsAggregationService"] = None
    _lock = RLock()

    def __new__(cls) -> "StatsAggregationService":
        """Create or return the singleton instance.

        Returns:
            The singleton StatsAggregationService instance.
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    @classmethod
    def getInstance(cls) -> "StatsAggregationService":
        """Get or create the singleton StatsAggregationService instance.

        Returns:
            The singleton StatsAggregationService instance.
        """
        if cls._instance is None:
            return cls()
        return cls._instance

    def __init__(self) -> None:
        """Initialise the stats aggregation service.

        Only the first call executes; subsequent calls are guarded by
        the ``hasattr(self, 'initialized')`` sentinel. Does NOT read
        config — that happens in :meth:`initialize`.
        """
        if hasattr(self, "initialized"):
            return

        self.initialized = True
        self._configManager: Optional[ConfigManager] = None
        self._database: Optional[Database] = None
        self._statsEnabled: bool = False
        self._statsStorages: Dict[str, StatsStorage] = {}
        self._lastRunTime: float = 0.0
        self._intervalSeconds: int = 3600  # Default interval (1h), cached at init
        self._retentionDays: int = 30  # Default retention (30 days), cached at init
        self._batchLimit: int = 1000  # Default batch limit, cached at init
        self._initialized: bool = False

    def initialize(self, configManager: ConfigManager, database: Database) -> None:
        """Initialise the stats aggregation service with configuration and database.

        Registers the CRON_JOB delayed task handler with QueueService.
        Synchronous — registration is a dict append, nothing to await.

        Reads and parses ``[stats]`` configuration once, caching the values.
        Raises ValueError on malformed configuration values (startup fails loudly).

        Idempotent — subsequent calls after the first successful
        initialisation are silently skipped.

        Args:
            configManager: The application configuration manager.
            database: The database instance for storage construction.

        Raises:
            ValueError: If any config value is malformed (non-numeric where int required).
        """
        if self._initialized:
            logger.debug("StatsAggregationService already initialized; skipping.")
            return

        # Parse and cache configuration ONCE at initialization (fail loudly on malformed values)
        # Parse into locals first, commit atomically to keep service retryable on failure
        statsConfig: Dict[str, Any] = configManager.getStatsConfig()

        # Parse interval with clamp: minimum 60 seconds (tick granularity)
        parsedIntervalSeconds = _parseIntKey(statsConfig, "aggregation-interval-seconds", 3600)
        intervalSeconds = max(60, parsedIntervalSeconds)

        # Parse retention with clamp: minimum 0 (0 = keep forever)
        parsedRetentionDays = _parseIntKey(statsConfig, "events-retention-days", 30)
        retentionDays = max(0, parsedRetentionDays)

        # Parse batch limit with clamp: minimum 1
        parsedBatchLimit = _parseIntKey(statsConfig, "aggregation-batch-limit", 1000)
        batchLimit = max(1, parsedBatchLimit)

        # Parse enabled flag
        statsEnabled: bool = statsConfig.get("enabled", False)

        # CRITICAL ordering: set initialized flag AFTER config parse succeeds
        # and BEFORE registering the handler. A failed initialize must leave
        # the service retryable (config fixed → initialize again succeeds).
        self._configManager = configManager
        self._database = database
        self._intervalSeconds = intervalSeconds
        self._retentionDays = retentionDays
        self._batchLimit = batchLimit
        self._statsEnabled = statsEnabled
        self._initialized = True

        # Register the CRON_JOB handler (shared 60-second tick)
        QueueService.getInstance().registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, self._dtCronJob)

        logger.info(
            "StatsAggregationService initialized; aggregation cycle will run on CRON_JOB tick gated by elapsed time. "
            f"enabled={self._statsEnabled}, interval={self._intervalSeconds}s, "
            f"retention={self._retentionDays} days, batch-limit={self._batchLimit}"
        )

    def createStatsStorage(self, eventType: str, dataSource: Optional[str] = None) -> StatsStorage:
        """Create and register a stats storage for the given event type.

        Reads the cached ``enabled`` value (parsed once at initialize) — if disabled,
        returns an **unregistered** ``NullStatsStorage`` (the registry stays empty).
        If enabled, constructs ``DatabaseStatsStorage`` and registers it
        in the registry keyed by ``eventType``.

        Args:
            eventType: Event type discriminator (e.g. 'llm_request').
            dataSource: Named data source for the storage; if None,
                uses the database manager's default datasource.

        Returns:
            ``NullStatsStorage`` if stats disabled or uninitialized (unregistered),
            otherwise a registered ``DatabaseStatsStorage`` instance.
        """
        if not self._initialized or self._configManager is None:
            logger.warning(
                "StatsAggregationService not initialized or ConfigManager not set; returning NullStatsStorage"
            )
            return NullStatsStorage()

        # Use cached enabled flag (read once at initialize)
        if not self._statsEnabled:
            # Disabled — return unregistered NullStatsStorage
            return NullStatsStorage()

        # Enabled — construct DatabaseStatsStorage
        if self._database is None:
            logger.error("Database not initialized; returning NullStatsStorage")
            return NullStatsStorage()

        # Resolve dataSource: None → default, otherwise use provided
        resolvedDataSource = dataSource or self._database.manager.default

        storage = DatabaseStatsStorage(db=self._database, eventType=eventType, dataSource=resolvedDataSource)

        # Register in the registry (insertion order preserved)
        self._statsStorages[eventType] = storage

        logger.debug(f"Created and registered stats storage for event type '{eventType}'")
        return storage

    def getQueryStorage(self, eventType: str) -> StatsStorage:
        """Return the registered storage for eventType (NullStatsStorage if none).

        Provides handler-side access to the storage registry for read-only
        queries. Returns a fresh NullStatsStorage if the service is uninitialized
        or the eventType is not registered.

        Args:
            eventType: Event type discriminator (e.g., 'llm_request', 'message').

        Returns:
            Registered StatsStorage for the event type, or NullStatsStorage if none.
        """
        return self._statsStorages.get(eventType, NullStatsStorage())

    async def _dtCronJob(self, task: DelayedTask) -> None:
        """Handle a CRON_JOB delayed task (shared 60-second tick).

        Per cycle (only if registry non-empty):
        1. Gate on elapsed time: ``time.time() - _lastRunTime < intervalSeconds`` → return.
        2. For each storage in ``_statsStorages.items()`` (sequential order, using eventType key as label):
            a. Drain loop: call ``aggregate(limit=self._batchLimit)`` repeatedly until 0 or MAX_AGGREGATION_ROUNDS.
            b. Retention purge: if ``retentionDays > 0``, call ``purgeProcessed`` once per storage
               (each storage is scoped to its own event_type via its own data source).
            Per-storage try/except isolation — one storage's failure never blocks others.
        3. One INFO summary line: per-storage processed/purged counts + errors.
        4. Set ``_lastRunTime`` to cycle-start timestamp.

        Args:
            task: The delayed task triggering this handler (kwargs are empty).
        """
        # Empty registry → no-op (stats disabled or no storages created yet)
        if not self._statsStorages:
            return

        # Cycle start timestamp (used for gate advance and logging)
        cycleStart = time.time()

        # Gate: interval not elapsed → return (tick keeps ticking)
        if cycleStart - self._lastRunTime < self._intervalSeconds:
            return

        perStorageProcessed: Dict[str, int] = {}
        perStoragePurged: Dict[str, int] = {}
        perStorageErrors: Dict[str, str] = {}

        # Iterate over registry items: eventType keys ARE the labels (unique by dict construction)
        # CRITICAL: Wrap in list() to avoid RuntimeError if dict is mutated during iteration
        # (e.g., if aggregate() triggers createStatsStorage which adds a new storage)
        for eventType, storage in list(self._statsStorages.items()):
            try:
                # Drain loop: repeated aggregate() until 0 or MAX_AGGREGATION_ROUNDS
                processedTotal = 0
                for _ in range(MAX_AGGREGATION_ROUNDS):
                    processed = await storage.aggregate(limit=self._batchLimit)
                    processedTotal += processed
                    if processed == 0:
                        break

                perStorageProcessed[eventType] = processedTotal

                # Retention purge: delete processed events older than retention window
                purged = 0
                if self._retentionDays > 0:
                    purged = await storage.purgeProcessed(retentionDays=self._retentionDays)
                    logger.debug(f"Purged {purged} processed events for '{eventType}'")

                perStoragePurged[eventType] = purged

            except Exception as e:
                logger.exception(f"Stats aggregation failed for storage {eventType}")
                perStorageErrors[eventType] = str(e)

        # INFO summary line: per-storage processed/purged/errors
        summaryParts = []
        for eventType in self._statsStorages.keys():
            parts = [f"{eventType}:"]
            if eventType in perStorageProcessed:
                parts.append(f"aggregated={perStorageProcessed[eventType]}")
            if eventType in perStoragePurged:
                parts.append(f"purged={perStoragePurged[eventType]}")
            if eventType in perStorageErrors:
                parts.append(f"error={perStorageErrors[eventType][:50]}")
            summaryParts.append(" ".join(parts))

        summary = " | ".join(summaryParts) if summaryParts else "No storages processed"
        logger.info(f"Stats aggregation cycle complete: {summary}")

        # Advance gate to cycle-start timestamp
        self._lastRunTime = cycleStart
