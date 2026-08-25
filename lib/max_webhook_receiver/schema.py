"""Canonical DDL for the ``webhook_updates`` table.

Single source of truth for the table and index shapes: the bot's migrations
import ``getForwardDDL()`` (migration_019 ``up()`` creates; migration_029
``down()`` recreates on rollback) so the migration chain and this library can
never drift, and the standalone receiver self-heals its OWN database at
startup via ``ensureWebhookUpdatesSchema()`` — which creates BOTH the table
and the index. The receiver's database has no migration side; the self-heal
is its only schema authority.

Portability: ``CREATE TABLE IF NOT EXISTS`` is portable across
SQLite/PostgreSQL/MySQL; ``CREATE INDEX IF NOT EXISTS`` is not (MySQL rejects
it) — but 13 shipped migrations already use that form and only sqlite3/sqlink
providers are registered today, so the string lives here, single-sourced,
shared by migrations and self-heal. MySQL activation will address the index
form once, centrally, via a provider hook.
"""

from typing import List

from lib.db.providers import BaseSQLProvider, ParametrizedQuery

WEBHOOK_UPDATES_TABLE_DDL: str = """
    CREATE TABLE IF NOT EXISTS webhook_updates (
        id            TEXT      PRIMARY KEY NOT NULL,
        received_at   TIMESTAMP NOT NULL,
        update_type   TEXT      NOT NULL,
        raw_json      TEXT      NOT NULL,
        processed     INTEGER   NOT NULL DEFAULT 0,
        processed_at  TIMESTAMP
    )
    """
"""Portable table DDL (verbatim from migration_019 at extraction time)."""

WEBHOOK_UPDATES_INDEX_DDL: str = """
    CREATE INDEX IF NOT EXISTS idx_webhook_updates_unprocessed
    ON webhook_updates (processed, received_at)
    """
"""Index DDL (NOT MySQL-portable; shared by migrations + self-heal — see module docstring)."""


def getForwardDDL() -> List[ParametrizedQuery]:
    """Build the forward-migration DDL batch (table + index).

    Returns:
        List[ParametrizedQuery]: The DDL statements migrations execute
        (migration_019 up(); migration_029 down()).
    """
    return [
        ParametrizedQuery(WEBHOOK_UPDATES_TABLE_DDL),
        ParametrizedQuery(WEBHOOK_UPDATES_INDEX_DDL),
    ]


async def ensureWebhookUpdatesSchema(sqlProvider: BaseSQLProvider) -> None:
    """Create the ``webhook_updates`` table AND index when missing (self-heal).

    The receiver's own database has no migration side — this self-heal is its
    only schema authority, so it must be complete (table + index). Idempotent
    by construction.

    Args:
        sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

    Returns:
        None
    """
    await sqlProvider.execute(WEBHOOK_UPDATES_TABLE_DDL)
    await sqlProvider.execute(WEBHOOK_UPDATES_INDEX_DDL)
