"""Database-backed stats storage implementation.

Provides a database-backed implementation of StatsStorage that uses the
Database manager to store raw stat events and materialized aggregates.
Both tables live in a single data source, enabling future transactional
upsert + mark-processed operations.
"""

import datetime
import hashlib
import logging
import math
import uuid
from typing import Optional, TypedDict

from lib import utils as libUtils
from lib.stats.stats_storage import GLOBAL_CONSUMER_ID
from lib.stats.stats_storage import StatsStorage as BaseStatsStorage

from . import utils as dbUtils
from .database import Database
from .providers.base import ExcludedValue

logger = logging.getLogger(__name__)


class StatsEventDict(TypedDict):
    event_id: str
    event_type: str
    event_time: datetime.datetime
    data: dict[str, float | int]
    labels: dict[str, str]
    processed: bool
    processed_id: Optional[str]
    claimed_at: Optional[datetime.datetime]
    created_at: datetime.datetime


class DatabaseStatsStorage(BaseStatsStorage):
    """Database-backed stats storage with a single data source for both tables.

    Raw events are appended to the ``stat_events`` table. The ``aggregate()``
    method claims batches of unprocessed events (including orphaned ones from
    crashed prior runs) via a single UPDATE, then computes hourly/daily/monthly/total
    buckets and upserts into ``stat_aggregates``.

    Both tables share the same data source, so when the provider gains
    transactional batch primitives, the upsert + mark-processed steps can be
    wrapped in a single transaction for exactly-once semantics.

    Attributes:
        db: Database instance for provider access.
        eventType: Event type discriminator (e.g. 'llm_request').
        dataSource: Data source name for both stat_events and stat_aggregates.
    """

    __slots__ = ("db", "eventType", "dataSource")

    def __init__(self, db: Database, eventType: str, *, dataSource: str) -> None:
        """Initialize database-backed stats storage.

        Args:
            db: Database instance from internal.database.database.
            eventType: Event type discriminator written to every event.
            dataSource: Named data source for both tables.
        """
        self.db = db
        self.eventType = eventType
        self.dataSource = dataSource

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def record(
        self,
        stats: dict[str, float | int],
        *,
        consumerId: Optional[str] = None,
        labels: Optional[dict[str, str]] = None,
        eventTime: Optional[datetime.datetime] = None,
    ) -> None:
        """Append a raw stat event to the log table. Best-effort — never raises.

        Generates a UUID event_id, merges consumerId into labels, hashes
        the canonical labels JSON, serializes stats as JSON, and inserts
        a row with ``processed = 0``.

        Args:
            stats: Metric key -> numeric value dict. Values must be finite.
            consumerId: Consumer identifier (e.g. str(chatId)). Merged into labels.
            labels: Additional dimension labels (modelName, provider, etc.).
            eventTime: When the event occurred; defaults to now (UTC).

        Returns:
            None
        """
        try:
            eventId = str(uuid.uuid4())
            now = dbUtils.getCurrentTimestamp()

            if eventTime is None:
                eventTime = now

            # Merge consumerId into labels
            mergedLabels = dict(labels or {})
            mergedLabels["consumer"] = consumerId or GLOBAL_CONSUMER_ID

            sqlProvider = await self.db.manager.getProvider(dataSource=self.dataSource, readonly=False)
            await sqlProvider.execute(
                """INSERT INTO stat_events
                   (event_id, event_type, event_time, data, labels,
                    processed, processed_id, claimed_at, created_at)
                   VALUES
                   (:eventId, :eventType, :eventTime, :data, :labels,
                    0, NULL, NULL, :createdAt)""",
                {
                    "eventId": eventId,
                    "eventType": self.eventType,
                    "eventTime": eventTime,
                    "data": stats,
                    "labels": mergedLabels,
                    "createdAt": now,
                },
            )
        except Exception:
            logger.exception("Failed to record stat event")

    async def aggregate(self, *, limit: int = 1000, orphanTimeoutSeconds: int = 3600) -> int:
        """Claim and aggregate a batch of unprocessed events.

        **v3 flow — claim-first, reclaim-in-place, global rollup, total period:**

            1. UPDATE claim: claims up to ``limit`` rows with ``processed = 0``
               whose ``processed_id IS NULL`` (never claimed) OR whose
               ``claimed_at`` is older than the orphan timeout (stale claim
               from a crashed previous run). Uses ``applyPagination()`` for
               portable LIMIT.
            2. SELECT claimed rows' data by ``processed_id = batchId``.
            3. Compute hourly/daily/monthly/total aggregates in Python.
               Each event produces rows for its own labels AND a global
               rollup (consumer replaced with ``GLOBAL_CONSUMER_ID``).
            4. Upsert into ``stat_aggregates`` (same data source).
            5. Mark claimed rows as ``processed = 1``.

        No separate orphan-reclaim pass — stale rows are reclaimed as part
        of the claim UPDATE itself.

        Args:
            limit: Maximum number of unprocessed events to claim.
            orphanTimeoutSeconds: Age in seconds after which a claimed-but-
                unprocessed row is considered orphaned. Default 3600 (1 hour).

        Returns:
            Number of events processed (0 if nothing to aggregate).
        """
        batchId = str(uuid.uuid4())
        now = dbUtils.getCurrentTimestamp()
        orphanTimeout = now - datetime.timedelta(seconds=orphanTimeoutSeconds)

        sqlProvider = await self.db.manager.getProvider(dataSource=self.dataSource, readonly=False)

        # --- Step 1: claim batch (includes orphan reclaim) ---
        #
        # Uses provider.applyPagination() for portable LIMIT. The inner select is
        # wrapped in a double-nested subquery because:
        #   - PostgreSQL does not support LIMIT in UPDATE.
        #   - MySQL forbids updating a table that also appears in a direct
        #     subquery (ERROR 1093). The double nesting materializes the inner
        #     result, bypassing MySQL's restriction.
        #   - SQLite and PostgreSQL handle double-nested subqueries natively.
        #
        innerSelect = sqlProvider.applyPagination(
            """SELECT event_id FROM stat_events
               WHERE processed = 0
                 AND (processed_id IS NULL OR claimed_at < :orphanTimeout)
               ORDER BY event_time""",
            limit=limit,
        )
        claimQuery = (
            "UPDATE stat_events SET processed_id = :batchId, claimed_at = :now "
            "WHERE event_id IN (SELECT event_id FROM (" + innerSelect + ") AS _claim)"
        )
        await sqlProvider.execute(
            claimQuery,
            {
                "batchId": batchId,
                "now": now,
                "orphanTimeout": orphanTimeout,
            },
        )

        # --- Step 2: read claimed events ---
        events = await sqlProvider.executeFetchAll(
            """SELECT *
               FROM stat_events
               WHERE processed_id = :batchId""",
            {"batchId": batchId},
        )
        nClaimed = len(events)
        if nClaimed == 0:
            return 0

        # --- Step 3: aggregate in Python ---
        aggregates: dict[tuple[str, str, str, str], float] = {}
        for _event in events:
            event = dbUtils.sqlToTypedDict(_event, StatsEventDict)

            # Build global labels: same labels but consumer = __global__
            labelsDict = event["labels"]
            labelsJson = libUtils.jsonDumps(labelsDict)

            globalLabelsDict = labelsDict.copy()
            globalLabelsDict["consumer"] = GLOBAL_CONSUMER_ID
            globalLabelsJson = libUtils.jsonDumps(globalLabelsDict)

            for periodType, truncated in _computePeriods(event["event_time"]).items():
                for metricKey, metricValue in event["data"].items():
                    # Skip non-finite values
                    if not math.isfinite(float(metricValue)):
                        continue

                    # Per-consumer aggregation
                    key = (labelsJson, truncated, periodType, metricKey)
                    aggregates[key] = aggregates.get(key, 0.0) + float(metricValue)

                    # Global rollup
                    globalKey = (globalLabelsJson, truncated, periodType, metricKey)
                    aggregates[globalKey] = aggregates.get(globalKey, 0.0) + float(metricValue)

        # --- Step 4: upsert into aggregate table ---
        # TODO: Add sqlProvider.getUpsertQuery + put all queries into batchExecute for transaction
        for (labelsJson, periodStart, periodType, metricKey), total in aggregates.items():
            await sqlProvider.upsert(
                table="stat_aggregates",
                values={
                    "event_type": self.eventType,
                    "period_start": periodStart,
                    "period_type": periodType,
                    "labels_hash": _hashLabels(labelsJson),
                    "labels": labelsJson,
                    "metric_key": metricKey,
                    "metric_value": total,
                    "updated_at": now,
                },
                conflictColumns=[
                    "event_type",
                    "period_start",
                    "period_type",
                    "labels_hash",
                    "metric_key",
                ],
                updateExpressions={
                    "metric_value": "metric_value + :metric_value",
                    "updated_at": ExcludedValue(),
                },
            )

        # --- Step 5: mark processed ---
        await sqlProvider.execute(
            """UPDATE stat_events
               SET processed = 1
               WHERE processed_id = :batchId""",
            {"batchId": batchId},
        )

        return nClaimed


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _hashLabels(labelsJson: str) -> str:
    """Compute a deterministic hash of the canonical labels JSON.

    Uses MD5 hex digest. This is sufficient for label-set disambiguation
    in a primary key. Non-cryptographic use — hash collisions are
    astronomically unlikely at this scale but not possible. If collision
    becomes a concern, the full labels JSON is stored alongside for
    disambiguation.

    Args:
        labelsJson: Canonical JSON string (sorted keys).

    Returns:
        32-character MD5 hex digest.
    """
    return hashlib.md5(labelsJson.encode("utf-8")).hexdigest()


def _computePeriods(eventTime: datetime.datetime) -> dict[str, str]:
    """Return periodType to truncatedISO mapping for hourly, daily, monthly, total.

    All timestamps are in ISO 8601 format for consistent string comparison
    and storage across RDBMS. The ``total`` period uses a fixed epoch sentinel.

    Args:
        eventTime: The event timestamp (must be UTC).

    Returns:
        dict mapping periodType to truncated ISO 8601 string.
    """
    hourly = eventTime.replace(minute=0, second=0, microsecond=0)
    daily = hourly.replace(hour=0)
    monthly = daily.replace(day=1)
    total = datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)

    return {
        "hourly": hourly.isoformat(),
        "daily": daily.isoformat(),
        "monthly": monthly.isoformat(),
        "total": total.isoformat(),
    }
