"""Backfill chat_messages into stat_aggregates and drop legacy tables.

This migration (version 27) preserves historical message statistics by migrating all
data from ``chat_messages`` into the ``stat_aggregates`` table as ``message`` events,
then drops both legacy tables (``chat_stats`` and ``chat_user_stats``) that have been
write-only since migration_001.

The back-fill writes pre-aggregated rows directly to ``stat_aggregates`` for
three periods (daily, monthly, total) with two label-sets per period (per-consumer
and ``__global__`` rollup). No ``hourly`` rows are written; hourly rows are
intentionally not back-filled (historical intra-day distribution is not preserved).

The back-fill uses the same canonicalization (``lib.utils.jsonDumps``) and hashing
(``_hashLabels`` from ``internal.database.stats_storage``) as the live aggregator,
ensuring identical hashes for identical label sets.

**Source data:** ``chat_messages`` table (full message history with real
``message_category`` and ``message_type`` values, plus ``message_text`` for
text_length calculation). The back-fill applies the same exclusions as live
recording: rows with NULL, ``DELETED``, or ``UNSPECIFIED`` ``message_category``
are skipped.

**Historical data note:** Unlike the legacy ``chat_user_stats`` counters (which
unconditionally counted everything, including DELETED rewrites-era rows), the
new back-fill matches live-event semantics — counts may differ slightly from the
legacy counters. Both bot-authored and user-authored rows are included (direction
is derivable at query time via ``user_id`` comparison with the bot's ID).

The ``down()`` migration recreates both legacy tables empty — the original data
is not restorable (destroyed by the DROP in ``up()``).
"""

import datetime

from lib import utils as libUtils
from lib.stats.stats_storage import GLOBAL_CONSUMER_ID

from ...models import MessageCategory
from ...providers import BaseSQLProvider, ExcludedValue, ParametrizedQuery
from ...stats_storage import _hashLabels
from ...utils import getCurrentTimestamp
from ..base import BaseMigration


class Migration027DropChatStatsBackfillAggregates(BaseMigration):
    """Backfill chat_messages into stat_aggregates and drop legacy tables.

    This migration preserves historical message statistics by migrating all data
    from ``chat_messages`` into the ``stat_aggregates`` table as ``message``
    events, then drops both legacy daily-counter tables (``chat_stats`` and
    ``chat_user_stats``).

    The back-fill reads individual message rows from ``chat_messages``, groups
    them by ``(chatId, userId, datePart, messageCategory, messageType)``, and
    aggregates ``message_count`` and ``text_length``. It produces 12 rows per
    unique bucket (three periods × two label-sets × two metrics), using
    Python-side pre-aggregation and a replace-style upsert (idempotent re-runs).

    **Exclusions:** Rows with NULL, ``DELETED``, or ``UNSPECIFIED``
    ``message_category`` are skipped (matches live recording semantics).

    **Periods:** ``daily`` (date truncated to midnight), ``monthly`` (first of
    month), ``total`` (epoch sentinel).

    **Label-sets:** Per-consumer (``consumer = str(chatId)``) and ``__global__``
    rollup. Labels include ``consumer``, ``user_id``, ``chat_type``,
    ``message_category``, ``message_type``. Historical direction is derivable at
    query time via ``user_id`` comparison with the bot's ID.

    **Historical data note:** Unlike the legacy ``chat_user_stats`` counters
    (which unconditionally counted everything), the new back-fill matches
    live-event semantics — counts may differ slightly from the legacy counters.

    Attributes:
        version: Migration version number (27).
        description: Human-readable description of the migration.
    """

    version: int = 27
    """The version number of this migration."""
    description: str = "Backfill chat_messages into stat_aggregates and drop legacy tables"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Backfill chat_messages into stat_aggregates and drop legacy tables.

        The migration performs two steps in sequence:

        1. **Back-fill:** Read all rows from ``chat_messages``, group by
           ``(chatId, userId, datePart, messageCategory, messageType)``, and
           write aggregate rows to ``stat_aggregates``:
           - Three periods: ``daily`` (date truncated to midnight),
             ``monthly`` (first of month), ``total`` (epoch sentinel).
           - Two label-sets: per-consumer and ``__global__`` rollup.
           - Two metrics: ``message_count`` (row count), ``text_length`` (sum of
             lengths).
           - Upsert with SUM accumulation for metric_value.
           - Exclusions: Skip rows with NULL, ``DELETED``, or ``UNSPECIFIED``
             ``message_category`` (matches live recording semantics).

        2. **Drop:** Remove both legacy tables (``chat_stats`` and
            ``chat_user_stats``) using portable ``DROP TABLE IF EXISTS``.

        **Memory usage:** Messages are fetched chat-by-chat (``SELECT DISTINCT
        chat_id`` first, then rows per chat) to avoid loading the entire
        ``chat_messages`` table into memory at once. The aggregates dict grows
        with unique buckets (acceptable).

        **Date handling:** Date-part truncation is done in Python (``rowDate.date()``)
        for portability across SQLite/PostgreSQL/MySQL — no SQL date functions are used.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        # ------------------------------------------------------------------
        # Step 1: Back-fill chat_messages -> stat_aggregates
        # ------------------------------------------------------------------

        # Check if the source table exists (deterministic, no broad except)
        # If it doesn't exist, skip backfill entirely (migration was already run)
        existingTables = set(await sqlProvider.listTables(likePattern="%"))
        if "chat_messages" not in existingTables:
            # Skip backfill and proceed to drop statements (which will be no-ops with IF EXISTS)
            pass
        else:
            # Fetch all distinct chat_ids first (bounded memory: iterate chat-by-chat)
            distinctChats = await sqlProvider.executeFetchAll("SELECT DISTINCT chat_id FROM chat_messages")

        totalSentinel = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc).isoformat()
        now = getCurrentTimestamp()

        # Python-side pre-aggregation: accumulate all values in memory, then upsert once per bucket
        # Key: (labelsJson, periodType, periodStart, metricKey) -> summed metric_value
        aggregates: dict[tuple[str, str, str, str], float] = {}

        if "chat_messages" in existingTables:
            for chatRow in distinctChats:
                chatId = chatRow["chat_id"]
                # Fetch all messages for this chat
                chatMessages = await sqlProvider.executeFetchAll(
                    """SELECT chat_id, user_id, date, message_category, message_type, message_text
                       FROM chat_messages
                       WHERE chat_id = :chatId""",
                    {"chatId": chatId},
                )

                for row in chatMessages:
                    chatId = row["chat_id"]
                    userId = row["user_id"]
                    dateVal = row["date"]
                    messageCategory = row["message_category"]
                    messageType = row["message_type"]
                    messageText = row["message_text"]

                    # Exclusions: skip rows with NULL, DELETED, or UNSPECIFIED message_category
                    # Compare against the enum .value strings directly (columns store the StrEnum values)
                    if messageCategory is None:
                        continue
                    if messageCategory in (MessageCategory.DELETED.value, MessageCategory.UNSPECIFIED.value):
                        continue

                    # SQLite returns timestamps as strings; convert to datetime
                    if isinstance(dateVal, str):
                        dateVal = datetime.datetime.fromisoformat(dateVal)

                    # Derive chat_type from chat_id sign (repo convention)
                    chatType = "private" if chatId > 0 else "group"

                    # Date-part truncation in Python (portability rule)
                    datePart = dateVal.date()

                    # Calculate text_length in Python (no SQL LENGTH)
                    textLength = len(messageText or "")

                    # Compute period starts for daily/monthly/total
                    # Reconstruct datetime from datePart for truncation
                    dateMidnight = datetime.datetime.combine(datePart, datetime.time.min, tzinfo=datetime.timezone.utc)
                    dailyStart = _dayISO(dateMidnight)
                    monthlyStart = _monthISO(dateMidnight)

                    periods = [
                        ("daily", dailyStart),
                        ("monthly", monthlyStart),
                        ("total", totalSentinel),
                    ]

                    # Build per-consumer labels
                    perConsumerLabels = {
                        "consumer": str(chatId),
                        "user_id": str(userId),
                        "chat_type": chatType,
                        "message_category": messageCategory,
                        "message_type": messageType,
                    }

                    perConsumerLabelsJson = libUtils.jsonDumps(perConsumerLabels)

                    # Build __global__ labels (without chatId)
                    globalLabels = {
                        "consumer": GLOBAL_CONSUMER_ID,
                        "user_id": str(userId),
                        "chat_type": chatType,
                        "message_category": messageCategory,
                        "message_type": messageType,
                    }

                    globalLabelsJson = libUtils.jsonDumps(globalLabels)

                    # Accumulate metrics in Python for both label-sets and all periods
                    for periodType, periodStart in periods:
                        # Per-consumer: message_count = 1, text_length = len(messageText)
                        keyCount = (perConsumerLabelsJson, periodType, periodStart, "message_count")
                        aggregates[keyCount] = aggregates.get(keyCount, 0.0) + 1.0

                        keyLength = (perConsumerLabelsJson, periodType, periodStart, "text_length")
                        aggregates[keyLength] = aggregates.get(keyLength, 0.0) + float(textLength)

                        # __global__ rollup: same metrics
                        globalKeyCount = (globalLabelsJson, periodType, periodStart, "message_count")
                        aggregates[globalKeyCount] = aggregates.get(globalKeyCount, 0.0) + 1.0

                        globalKeyLength = (globalLabelsJson, periodType, periodStart, "text_length")
                        aggregates[globalKeyLength] = aggregates.get(globalKeyLength, 0.0) + float(textLength)

        # --- Step 1b: Upsert accumulated aggregates (one row per unique key) ---
        for (labelsJson, periodType, periodStart, metricKey), total in aggregates.items():
            labelsHash = _hashLabels(labelsJson)
            await sqlProvider.upsert(
                table="stat_aggregates",
                values={
                    "event_type": "message",
                    "period_start": periodStart,
                    "period_type": periodType,
                    "labels_hash": labelsHash,
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
                    "metric_value": ExcludedValue(),  # Replace with final summed value (no incremental +)
                    "updated_at": ExcludedValue(),
                },
            )

        # ------------------------------------------------------------------
        # Step 2: Drop legacy tables
        # ------------------------------------------------------------------

        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP TABLE IF EXISTS chat_stats"),
                ParametrizedQuery("DROP TABLE IF EXISTS chat_user_stats"),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Recreate legacy tables empty (data not restorable).

        This migration's up() destroys the original ``chat_stats`` and
        ``chat_user_stats`` data via DROP, so the down() migration can only
        recreate the tables empty — the historical data is not recoverable.

        The table schemas match migration_001:132-150.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS chat_stats (
                        chat_id INTEGER NOT NULL,
                        date TIMESTAMP NOT NULL,
                        messages_count INTEGER DEFAULT 0 NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL,
                        PRIMARY KEY (chat_id, date)
                    )
                """),
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS chat_user_stats (
                        chat_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        date TIMESTAMP NOT NULL,
                        messages_count INTEGER DEFAULT 0 NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL,
                        PRIMARY KEY (chat_id, user_id, date)
                    )
                """),
            ]
        )


def getMigration() -> type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        type[BaseMigration]: The migration class for this module.
    """
    return Migration027DropChatStatsBackfillAggregates


# ------------------------------------------------------------------
# Internal helpers (mirroring stats_storage.py for hash compatibility)
# ------------------------------------------------------------------


def _dayISO(dateVal: datetime.datetime) -> str:
    """Convert a date timestamp to ISO-8601 daily period start.

    Mirrors the daily truncation from ``_computePeriods`` in stats_storage.py:
    truncates to midnight and returns ISO-8601 string.

    Args:
        dateVal: Date timestamp (may carry time-of-day; truncated here).

    Returns:
        ISO-8601 UTC string for the daily period start.
    """
    # Ensure we have UTC timezone
    if dateVal.tzinfo is None:
        dateVal = dateVal.replace(tzinfo=datetime.timezone.utc)
    else:
        dateVal = dateVal.astimezone(datetime.timezone.utc)

    # Truncate to midnight (may carry time-of-day from source)
    truncated = dateVal.replace(hour=0, minute=0, second=0, microsecond=0)
    return truncated.isoformat()


def _monthISO(dateVal: datetime.datetime) -> str:
    """Convert a date timestamp to ISO-8601 monthly period start.

    Mirrors the monthly truncation from ``_computePeriods`` in stats_storage.py:
    truncates to first of month and returns ISO-8601 string.

    Args:
        dateVal: Date timestamp (may carry time-of-day; truncated here).

    Returns:
        ISO-8601 UTC string for the monthly period start.
    """
    # Ensure we have UTC timezone
    if dateVal.tzinfo is None:
        dateVal = dateVal.replace(tzinfo=datetime.timezone.utc)
    else:
        dateVal = dateVal.astimezone(datetime.timezone.utc)

    # Truncate to first of month
    truncated = dateVal.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return truncated.isoformat()
