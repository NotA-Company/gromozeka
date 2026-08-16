"""Backfill chat_user_stats into stat_aggregates and drop legacy tables.

This migration (version 27) preserves historical message counts by migrating all
data from the legacy ``chat_user_stats`` table into the ``stat_aggregates`` table
as ``message`` events, then drops both legacy tables (``chat_stats`` and
``chat_user_stats``) that have been write-only since migration_001.

The back-fill writes pre-aggregated rows directly to ``stat_aggregates`` for
three periods (daily, monthly, total) with two label-sets per period (per-consumer
and ``__global__`` rollup). No ``hourly`` rows are written because the source
granularity is per-day. No ``message_type`` label is included because it is unknown
historically (live-aggregated rows always carry ``message_type`` and will land in
different label-hash buckets).

The back-fill uses the same canonicalization (``lib.utils.jsonDumps``) and hashing
(``_hashLabels`` from ``internal.database.stats_storage``) as the live aggregator,
ensuring identical hashes for identical label sets.

**Historical data note:** Legacy counters included bot-authored messages (unconditional
increments), and message direction (sent/received) is derivable at query time via
``user_id`` comparison with the bot's ID.

The ``down()`` migration recreates both legacy tables empty — the original data
is not restorable (destroyed by the DROP in ``up()``).
"""

import datetime

from lib import utils as libUtils
from lib.stats.stats_storage import GLOBAL_CONSUMER_ID

from ...providers import BaseSQLProvider, ExcludedValue, ParametrizedQuery
from ...stats_storage import _hashLabels
from ...utils import getCurrentTimestamp
from ..base import BaseMigration


class Migration027DropChatStatsBackfillAggregates(BaseMigration):
    """Backfill chat_user_stats into stat_aggregates and drop legacy tables.

    This migration preserves historical message counts by migrating all data from
    the legacy ``chat_user_stats`` table into the ``stat_aggregates`` table as
    ``message`` events, then drops both legacy daily-counter tables
    (``chat_stats`` and ``chat_user_stats``).

    The back-fill produces six rows per source row (three periods × two label-sets),
    with SUM accumulation on upsert so multiple source rows contributing to the
    same period/label-set bucket aggregate correctly (notably the ``__global__``
    rollup, which sums across chats per ``(user_id, chat_type)``).

    **Historical data note:** Legacy counters included bot-authored messages (unconditional
    increments), and message direction (sent/received) is derivable at query time via
    ``user_id`` comparison with the bot's ID.

    Attributes:
        version: Migration version number (27).
        description: Human-readable description of the migration.
    """

    version: int = 27
    """The version number of this migration."""
    description: str = "Backfill chat_user_stats into stat_aggregates and drop legacy tables"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Backfill chat_user_stats into stat_aggregates and drop legacy tables.

        The migration performs two steps in sequence:

        1. **Back-fill:** Read all rows from ``chat_user_stats`` and write six
           aggregate rows to ``stat_aggregates`` per source row:
           - Three periods: ``daily`` (date truncated to midnight),
             ``monthly`` (first of month), ``total`` (epoch sentinel).
           - Two label-sets: per-consumer and ``__global__`` rollup.
           - Upsert with SUM accumulation for metric_value.

        2. **Drop:** Remove both legacy tables (``chat_stats`` and
           ``chat_user_stats``) using portable ``DROP TABLE IF EXISTS``.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        # ------------------------------------------------------------------
        # Step 1: Back-fill chat_user_stats -> stat_aggregates
        # ------------------------------------------------------------------

        # Check if the source table exists (deterministic, no broad except)
        # If it doesn't exist, skip backfill entirely (migration was already run)
        existingTables = set(await sqlProvider.listTables(likePattern="%"))
        if "chat_user_stats" not in existingTables:
            # Skip backfill and proceed to drop statements (which will be no-ops with IF EXISTS)
            sourceRows = []
        else:
            # Fetch all source rows and backfill
            sourceRows = await sqlProvider.executeFetchAll("""SELECT chat_id, user_id, date, messages_count
                   FROM chat_user_stats""")

        totalSentinel = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc).isoformat()
        now = getCurrentTimestamp()

        for row in sourceRows:
            chatId = row["chat_id"]
            userId = row["user_id"]
            dateVal = row["date"]
            count = row["messages_count"]

            # SQLite returns timestamps as strings; convert to datetime
            if isinstance(dateVal, str):
                dateVal = datetime.datetime.fromisoformat(dateVal)

            # Derive chat_type from chat_id sign (repo convention)
            chatType = "private" if chatId > 0 else "group"

            # Build the two label-sets (per-consumer and __global__ rollup)
            labelSets = [
                {"consumer": str(chatId), "user_id": str(userId), "chat_type": chatType},
                {"consumer": GLOBAL_CONSUMER_ID, "user_id": str(userId), "chat_type": chatType},
            ]

            # Compute period starts for daily/monthly/total
            # Note: dateVal is already midnight timestamp from saveChatMessage
            dailyStart = _dayISO(dateVal)
            monthlyStart = _monthISO(dateVal)

            periods = [
                ("daily", dailyStart),
                ("monthly", monthlyStart),
                ("total", totalSentinel),
            ]

            # Write six rows per source row (3 periods × 2 label-sets)
            for labels in labelSets:
                labelsJson = libUtils.jsonDumps(labels)
                labelsHash = _hashLabels(labelsJson)

                for periodType, periodStart in periods:
                    await sqlProvider.upsert(
                        table="stat_aggregates",
                        values={
                            "event_type": "message",
                            "period_start": periodStart,
                            "period_type": periodType,
                            "labels_hash": labelsHash,
                            "labels": labelsJson,
                            "metric_key": "message_count",
                            "metric_value": count,
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
        dateVal: Date timestamp (already midnight from saveChatMessage).

    Returns:
        ISO-8601 UTC string for the daily period start.
    """
    # Ensure we have UTC timezone
    if dateVal.tzinfo is None:
        dateVal = dateVal.replace(tzinfo=datetime.timezone.utc)
    else:
        dateVal = dateVal.astimezone(datetime.timezone.utc)

    # Truncate to midnight (already midnight from saveChatMessage, but ensure)
    truncated = dateVal.replace(hour=0, minute=0, second=0, microsecond=0)
    return truncated.isoformat()


def _monthISO(dateVal: datetime.datetime) -> str:
    """Convert a date timestamp to ISO-8601 monthly period start.

    Mirrors the monthly truncation from ``_computePeriods`` in stats_storage.py:
    truncates to first of month and returns ISO-8601 string.

    Args:
        dateVal: Date timestamp (already midnight from saveChatMessage).

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
