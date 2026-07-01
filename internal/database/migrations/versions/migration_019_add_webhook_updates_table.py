"""Add webhook_updates table for Max webhook support.

This migration introduces the ``webhook_updates`` table used by the Max
Messenger webhook integration. Incoming webhook payloads from Max are
written here by a thin webhook receiver; a background consumer then polls
the unprocessed rows, dispatches them to the bot, and marks them processed.

The table is intentionally minimal: it stores the raw JSON body verbatim
(``raw_json``) plus a coarse ``update_type`` tag, so the consumer can decode
and route the payload without the schema having to know about every Max
event shape up front.

Schema notes (cross-RDBMS portability):
- ``id`` is a TEXT primary key holding an application-generated UUID. No
  AUTOINCREMENT/SERIAL — primary key generation is delegated to the app so
  the same DDL runs on SQLite/PostgreSQL/MySQL.
- No ``DEFAULT CURRENT_TIMESTAMP``; ``received_at`` and ``processed_at`` are
  set explicitly by application code (migration 013 removed DB timestamp
  defaults repo-wide for the same reason).
- ``processed`` is an INTEGER boolean stored as 0/1; the ``DEFAULT 0`` is
  portable integer-literal default, not a dialect-specific construct.
- ``idx_webhook_updates_unprocessed`` indexes the ``(processed, received_at)``
  pair, which is exactly the access pattern of the unprocessed-updates query
  (``WHERE processed = 0 ORDER BY received_at ASC``).
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration019AddWebhookUpdatesTable(BaseMigration):
    """Add the webhook_updates table backing Max webhook ingestion.

    Stores one row per incoming Max webhook payload. Unprocessed rows are
    polled by a consumer, dispatched, and then marked processed; a TTL-based
    cleanup reaps old processed rows.

    Attributes:
        version: Migration version number (19).
        description: Human-readable description of the migration.
    """

    version: int = 19
    """The version number of this migration."""
    description: str = "Add webhook_updates table"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create the webhook_updates table and its unprocessed-rows index.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS webhook_updates (
                        id            TEXT      PRIMARY KEY NOT NULL,
                        received_at   TIMESTAMP NOT NULL,
                        update_type   TEXT      NOT NULL,
                        raw_json      TEXT      NOT NULL,
                        processed     INTEGER   NOT NULL DEFAULT 0,
                        processed_at  TIMESTAMP
                    )
                    """),
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_webhook_updates_unprocessed
                    ON webhook_updates (processed, received_at)
                    """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop the unprocessed-rows index then the webhook_updates table.

        Index is dropped before the table so the rollback mirrors the forward
        migration and stays valid on providers that require an explicit
        index drop.

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_webhook_updates_unprocessed"),
                ParametrizedQuery("DROP TABLE IF EXISTS webhook_updates"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration019AddWebhookUpdatesTable
