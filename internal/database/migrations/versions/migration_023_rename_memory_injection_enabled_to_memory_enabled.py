"""Rename the ``chat_settings`` key ``memory-injection-enabled`` -> ``memory-enabled``.

This accompanies the production-code refactor that renamed the
``MEMORY_INJECTION_ENABLED`` enum member to ``MEMORY_ENABLED`` (Phase 1 of the
chat-settings consolidation). The enum member's TOML / persisted key string
changed from ``"memory-injection-enabled"`` to ``"memory-enabled"``, so existing
per-chat overrides stored in production ``chat_settings`` rows must be renamed
to keep working under the new key.

This is a **value-preserving, idempotent data migration** (no DDL):

- ``up()`` runs ``UPDATE chat_settings SET key = 'memory-enabled' WHERE key = 'memory-injection-enabled'``.
- ``down()`` runs the exact reverse.

Re-running either direction is a no-op: once every matching row is renamed, the
``WHERE`` clause matches zero rows.

The four settings that were outright REMOVED in the same consolidation
(``regenerate-embeddings``, ``memory-regenerate-embeddings``,
``memory-embeddings-enabled``, ``memory-retrieval-mode``) are NOT touched here —
their orphan rows are pruned by the separate cleanup script
``scripts/prune_unknown_chat_settings.py``. This migration only renames the one
key that survived the refactor under a new name.

Usage::

    # Applied automatically by MigrationManager on startup.
    # To test manually:
    await migration.up(sqlProvider)    # rename key
    await migration.down(sqlProvider)  # rename back
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration

OLD_KEY = "memory-injection-enabled"
"""The pre-refactor persisted key string for the memory-injection toggle."""

NEW_KEY = "memory-enabled"
"""The post-refactor persisted key string for the renamed MEMORY_ENABLED setting."""


class Migration023RenameMemoryInjectionEnabledToMemoryEnabled(BaseMigration):
    """Rename the ``chat_settings`` key ``memory-injection-enabled`` -> ``memory-enabled``.

    Value-preserving data migration accompanying the ``MEMORY_INJECTION_ENABLED``
    -> ``MEMORY_ENABLED`` enum rename. ``up()`` and ``down()`` are idempotent
    inverse ``UPDATE`` statements on the ``chat_settings.key`` column.

    Attributes:
        version: Migration version number (23).
        description: Human-readable description of the migration.
    """

    version: int = 23
    """The version number of this migration."""
    description: str = "Rename chat_settings key 'memory-injection-enabled' to 'memory-enabled'"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Rename the persisted key ``memory-injection-enabled`` -> ``memory-enabled``.

        Idempotent: after the rename, the ``WHERE`` clause matches zero rows on
        re-run. Only the ``key`` column is updated; ``value`` and every other
        column are preserved verbatim. Portable across SQLite / PostgreSQL /
        MySQL (plain ``UPDATE`` with ``:named`` placeholders).

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery(
                    "UPDATE chat_settings SET key = :newKey WHERE key = :oldKey",
                    {"newKey": NEW_KEY, "oldKey": OLD_KEY},
                ),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rename the persisted key ``memory-enabled`` -> ``memory-injection-enabled``.

        Exact inverse of ``up()`` and equally idempotent.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery(
                    "UPDATE chat_settings SET key = :newKey WHERE key = :oldKey",
                    {"newKey": OLD_KEY, "oldKey": NEW_KEY},
                ),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration023RenameMemoryInjectionEnabledToMemoryEnabled
