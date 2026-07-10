"""Drop the obsolete v1 ``user_data`` table.

The v1 ``user_data`` key-value store has been fully superseded by the v2
``user_memories`` system (migration 020 created ``user_memories`` and backfilled
all ``user_data`` rows into it; migration 021 added soft-delete). There are
zero live production callers of ``UserDataRepository`` — the table, the
repository, and the ``db.userData`` accessor are all retired here.

``up()`` drops the table. ``down()`` re-creates the **empty** table (data
cannot be recovered after a ``DROP`` — this is structural reversibility only,
sufficient for migration-rollback testing). The re-created DDL matches the
post-migration_013 shape: composite natural key ``(user_id, chat_id, key)``,
no ``DEFAULT CURRENT_TIMESTAMP`` (migration 013 removed it repo-wide),
portable ``TEXT`` / ``INTEGER`` / ``TIMESTAMP`` column types.

Usage::

    # Applied automatically by MigrationManager on startup.
    # To test manually:
    await migration.up(sqlProvider)   # DROP TABLE IF EXISTS user_data
    await migration.down(sqlProvider)  # re-create empty user_data table
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration022DropUserData(BaseMigration):
    """Drop the obsolete ``user_data`` table.

    The table's data was migrated to ``user_memories`` (migration 020) and no
    production code reads or writes ``user_data``. This migration removes the
    now-dead table. ``down()`` re-creates it empty for structural reversibility.

    Attributes:
        version: Migration version number (22).
        description: Human-readable description of the migration.
    """

    version: int = 22
    """The version number of this migration."""
    description: str = "Drop obsolete user_data table"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop the ``user_data`` table.

        The table is obsolete: all data was backfilled into ``user_memories``
        (migration 020) and no live code references ``UserDataRepository``.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP TABLE IF EXISTS user_data"),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Re-create the **empty** ``user_data`` table.

        Structural reversibility only — rows dropped by ``up()`` cannot be
        recovered. The DDL matches the post-migration_013 shape (composite
        natural key, no ``DEFAULT CURRENT_TIMESTAMP``, portable column types).

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS user_data (
                        user_id INTEGER NOT NULL,
                        chat_id INTEGER NOT NULL,
                        key TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL,
                        PRIMARY KEY (user_id, chat_id, key)
                    )
                """),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration022DropUserData
