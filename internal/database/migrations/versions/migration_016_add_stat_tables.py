"""Create stat_events and stat_aggregates tables for statistics collection.

This migration creates two tables to support the v3 statistics library:
- stat_events: Append-only event log for raw statistics events
- stat_aggregates: Pre-computed period buckets for aggregated metrics

Both tables share a single data source ("stats"), enabling future
transactional upsert + mark-processed workflows for reliable statistics
collection and aggregation.

The stat_events table uses app-generated UUID TEXT primary keys to avoid
AUTOINCREMENT and maintain cross-RDBMS portability. The stat_aggregates
table uses a composite primary key for efficient lookups by dimension and
time period.

This migration is part of the statistics collection system that will enable
analytics on bot usage, performance metrics, and user behavior patterns.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration016AddStatTables(BaseMigration):
    """Create stat_events and stat_aggregates tables for statistics collection.

    This migration establishes the foundation for a comprehensive statistics
    collection system in Gromozeka. The stat_events table stores raw events
    in an append-only log, while stat_aggregates stores pre-computed summary
    metrics grouped by time period and dimensions.

    The stat_events table includes support for event processing workflows
    with processed flags, tracking IDs, and claim timestamps, enabling safe
    concurrent processing of statistics events. The stat_aggregates table
    supports efficient querying of pre-aggregated metrics for dashboards
    and analytics.

    The schema is designed for cross-RDBMS portability:
    - Uses TEXT for JSON and UUID fields
    - Uses INTEGER for boolean flags (0/1)
    - Uses composite primary keys (no AUTOINCREMENT)
    - Timestamps are set by application code
    - Labels hash provides compact dimension key

    Attributes:
        version: Migration version number (16).
        description: Human-readable description of the migration.
    """

    version: int = 16
    """The version number of this migration."""
    description: str = "Add stat_events and stat_aggregates tables"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create stat_events and stat_aggregates tables with supporting indexes.

        This method creates two tables:

        stat_events (append-only event log):
        - event_id: App-generated UUID TEXT primary key
        - event_type: Type of statistics event (e.g., 'message', 'llm_query')
        - event_time: Timestamp when the event occurred
        - data: JSON-encoded event payload
        - labels: JSON-encoded dimension key-value pairs
        - processed: Boolean flag (0=unprocessed, 1=processed)
        - processed_id: ID of the aggregate record that claimed this event
        - claimed_at: Timestamp when event was claimed for processing
        - created_at: Record creation timestamp

        stat_aggregates (pre-computed period buckets):
        - event_type: Type of statistics event
        - period_start: Start of the aggregation period (ISO-8601 formatted)
        - period_type: Period length (e.g., 'hour', 'day', 'week')
        - labels_hash: MD5 hex digest from labels for join capability
        - labels: JSON-encoded dimension key-value pairs
        - metric_key: Name of the metric (e.g., 'count', 'duration_sum')
        - metric_value: Numeric value of the metric
        - updated_at: Last update timestamp

        The stat_events table has indexes for:
        - Fast lookup of unprocessed events (idx_stat_events_unprocessed)
        - Event lookup by type and time (idx_stat_events_lookup)

        The stat_aggregates table uses a composite primary key for efficient
        lookups by dimension and time period.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS stat_events (
                        event_id     TEXT      NOT NULL,
                        event_type   TEXT      NOT NULL,
                        event_time   TIMESTAMP NOT NULL,
                        data         TEXT      NOT NULL,
                        labels       TEXT      NOT NULL,
                        processed    INTEGER   NOT NULL DEFAULT 0,
                        processed_id TEXT      DEFAULT NULL,
                        claimed_at   TIMESTAMP DEFAULT NULL,
                        created_at   TIMESTAMP NOT NULL,
                        PRIMARY KEY (event_id)
                    )
                """),
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_stat_events_unprocessed
                    ON stat_events (processed, processed_id, claimed_at)
                """),
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_stat_events_lookup
                    ON stat_events (event_type, event_time)
                """),
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS stat_aggregates (
                        event_type   TEXT      NOT NULL,
                        period_start TEXT      NOT NULL,
                        period_type  TEXT      NOT NULL,
                        labels_hash  TEXT      NOT NULL,
                        labels       TEXT      NOT NULL,
                        metric_key   TEXT      NOT NULL,
                        metric_value REAL      NOT NULL,
                        updated_at   TIMESTAMP NOT NULL,
                        PRIMARY KEY (event_type, period_start, period_type, labels_hash, metric_key)
                    )
                """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop stat_events and stat_aggregates tables and their indexes.

        This method removes both statistics tables and all supporting indexes.
        This is the exact inverse of the up() method, restoring the database
        to its state before this migration.

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_stat_events_lookup"),
                ParametrizedQuery("DROP INDEX IF EXISTS idx_stat_events_unprocessed"),
                ParametrizedQuery("DROP TABLE IF EXISTS stat_aggregates"),
                ParametrizedQuery("DROP TABLE IF EXISTS stat_events"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration016AddStatTables
