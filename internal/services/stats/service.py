"""Stats aggregation service — periodic coordinator for all stat storages.

Singleton service that registers a handler on the shared CRON_JOB 60-second tick
and gates on elapsed time. Owns the storage factory + registry — the single
construction seam for stats storages.

Usage::

    # At startup (sync):
    StatsAggregationService.getInstance().initialize(configManager, database)

    # Construct storages (factory reads [stats] enabled itself):
    llmStorage = StatsAggregationService.getInstance().createStatsStorage(
        "llm_request", statsConfig.get("llm-stats-data-source")
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
# Bounds a cycle at 10,000 events per storage (default limit=1000) to prevent
# a runaway backlog from monopolizing the delayed queue.
MAX_AGGREGATION_ROUNDS = 10


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
    - Purges processed events past the retention window per storage

    Usage::

        # At startup (sync — registration is a dict append):
        StatsAggregationService.getInstance().initialize(configManager, database)

        # Construct storages (factory reads [stats] enabled itself):
        llmStorage = service.createStatsStorage("llm_request", dataSource="default")

    Attributes:
        _configManager: The application configuration manager.
        _database: The database instance for storage construction.
        _statsStorages: Registry of event type -> StatsStorage.
        _lastRunTime: Timestamp of the last cycle start (0.0 = never run).
        _intervalSeconds: Last-known-good interval from config (default 3600).
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
        self._statsStorages: Dict[str, StatsStorage] = {}
        self._lastRunTime: float = 0.0
        self._intervalSeconds: int = 3600  # Last-known-good interval, default 1h
        self._initialized: bool = False

    def initialize(self, configManager: ConfigManager, database: Database) -> None:
        """Initialise the stats aggregation service with configuration and database.

        Registers the CRON_JOB delayed task handler with QueueService.
        Synchronous — registration is a dict append, nothing to await.

        Idempotent — subsequent calls after the first successful
        initialisation are silently skipped.

        Args:
            configManager: The application configuration manager.
            database: The database instance for storage construction.
        """
        if self._initialized:
            logger.debug("StatsAggregationService already initialized; skipping.")
            return

        self._configManager = configManager
        self._database = database

        # Set initialized flag (idempotent guard)
        self._initialized = True

        # Register the CRON_JOB handler (shared 60-second tick)
        QueueService.getInstance().registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, self._dtCronJob)

        logger.info(
            "StatsAggregationService initialized; aggregation cycle will run " "on CRON_JOB tick gated by elapsed time."
        )

    def createStatsStorage(self, eventType: str, dataSource: Optional[str] = None) -> StatsStorage:
        """Create and register a stats storage for the given event type.

        Reads ``[stats] enabled`` from config — if disabled, returns an
        **unregistered** ``NullStatsStorage`` (the registry stays empty).
        If enabled, constructs ``DatabaseStatsStorage`` and registers it
        in the registry keyed by ``eventType``.

        Args:
            eventType: Event type discriminator (e.g. 'llm_request').
            dataSource: Named data source for the storage; if None,
                uses the database manager's default datasource.

        Returns:
            ``NullStatsStorage`` if stats disabled (unregistered),
            otherwise a registered ``DatabaseStatsStorage`` instance.
        """
        if self._configManager is None:
            logger.warning("ConfigManager not initialized; returning NullStatsStorage")
            return NullStatsStorage()

        statsConfig: Dict[str, Any] = self._configManager.getStatsConfig()
        enabled = statsConfig.get("enabled", False)

        if not enabled:
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

    async def _dtCronJob(self, task: DelayedTask) -> None:
        """Handle a CRON_JOB delayed task (shared 60-second tick).

        Per cycle (only if registry non-empty):
        1. Gate on elapsed time: ``time.time() - _lastRunTime < intervalSeconds`` → return.
        2. Guard config parse with try/except: on failure, advance gate and return.
        3. For each storage in ``_statsStorages.values()`` (sequential order):
           a. Drain loop: call ``aggregate()`` repeatedly until 0 or MAX_AGGREGATION_ROUNDS.
           b. Retention purge: if ``events-retention-days > 0``, call ``purgeProcessed``.
           Per-storage try/except isolation — one storage's failure never blocks others.
        4. One INFO summary line: per-storage processed/purged counts + errors.
        5. Set ``_lastRunTime`` to cycle-start timestamp.

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

        # Guard config parse with fallback to last-known-good interval
        # On failure: skip work but advance gate so error logs once per interval, not per tick
        try:
            if self._configManager is None:
                raise ValueError("_configManager is not initialized")
            statsConfig: Dict[str, Any] = self._configManager.getStatsConfig()
            intervalSeconds = max(60, int(statsConfig.get("aggregation-interval-seconds", 3600)))
            retentionDays = int(statsConfig.get("events-retention-days", 30))

            # Store last-known-good interval
            self._intervalSeconds = intervalSeconds
        except (TypeError, ValueError):
            logger.exception("stats aggregation: malformed [stats] config; skipping cycle")
            self._lastRunTime = cycleStart  # Advance gate so error logs once per interval
            return

        perStorageProcessed: Dict[str, int] = {}
        perStoragePurged: Dict[str, int] = {}
        perStorageErrors: Dict[str, str] = {}

        for storage in self._statsStorages.values():
            # Get storage identifier for logging (eventType is the best we have)
            storageLabel = getattr(storage, "eventType", None) or type(storage).__name__

            try:
                # Drain loop: repeated aggregate() until 0 or MAX_AGGREGATION_ROUNDS
                processedTotal = 0
                for _ in range(MAX_AGGREGATION_ROUNDS):
                    processed = await storage.aggregate()
                    processedTotal += processed
                    if processed == 0:
                        break

                perStorageProcessed[storageLabel] = processedTotal

                # Retention purge: delete processed events older than retention window
                purged = 0
                if retentionDays > 0:
                    purged = await storage.purgeProcessed(retentionDays=retentionDays)

                perStoragePurged[storageLabel] = purged

            except Exception as e:
                logger.exception(f"Stats aggregation failed for storage {storageLabel}")
                perStorageErrors[storageLabel] = str(e)

        # INFO summary line: per-storage processed/purged/errors
        summaryParts = []
        for storage in self._statsStorages.values():
            storageLabel = getattr(storage, "eventType", None) or type(storage).__name__
            parts = [f"{storageLabel}:"]
            if storageLabel in perStorageProcessed:
                parts.append(f"aggregated={perStorageProcessed[storageLabel]}")
            if storageLabel in perStoragePurged:
                parts.append(f"purged={perStoragePurged[storageLabel]}")
            if storageLabel in perStorageErrors:
                parts.append(f"error={perStorageErrors[storageLabel][:50]}")
            summaryParts.append(" ".join(parts))

        summary = " | ".join(summaryParts) if summaryParts else "No storages processed"
        logger.info(f"Stats aggregation cycle complete: {summary}")

        # Advance gate to cycle-start timestamp
        self._lastRunTime = cycleStart
