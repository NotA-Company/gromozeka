"""Add the ``deleted_at`` soft-delete column to ``user_memories``.

This migration is Phase 1 of the memory-compaction-v1 plan
(``docs/archive/plans/memory-compaction-v1.md`` §2). It introduces a nullable
``deleted_at TIMESTAMP`` column on ``user_memories`` so that
:meth:`UserMemoriesRepository.deleteMemory` can SOFT-DELETE a memory (set
``deleted_at``) instead of hard-``DELETE``-ing the row. The content row
survives so a historical message that references a now-deleted memory can
still resolve its content for LLM context reconstruction (via the new
:meth:`getMemoriesByIds`, which deliberately does NOT filter
``deleted_at``).

All existing read methods gain ``AND deleted_at IS NULL`` so the live
injection / search path skips soft-deleted rows.

Schema notes (cross-RDBMS portability, per AGENTS.md):
- Additive nullable column — ``ALTER TABLE ... ADD COLUMN`` is portable
  across SQLite / PostgreSQL / MySQL.
- Portable ``TIMESTAMP`` type, nullable, no ``DEFAULT`` (migration 013
  removed ``DEFAULT CURRENT_TIMESTAMP`` from every table repo-wide; the
  soft-delete timestamp is set application-side in ``deleteMemory`` via
  ``dbUtils.getCurrentTimestamp()``).
- No ``AUTOINCREMENT`` / ``SERIAL`` (N/A — this migration adds no key).
- No index on ``deleted_at`` (see plan §2.2 — every live-memory read
  already filters on the composite ``(chat_id, user_id, ...)`` indexes
  from migration 020; ``AND deleted_at IS NULL`` is a cheap residual
  predicate on the already-filtered row set).
"""

import logging
from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration

logger = logging.getLogger(__name__)


class Migration021UserMemoriesSoftDelete(BaseMigration):
    """Add the nullable ``deleted_at`` column to ``user_memories``.

    Enables soft-delete semantics: ``deleteMemory`` sets ``deleted_at`` (and
    clears vec0 + provenance) instead of removing the row, so historical
    reads (``getMemoriesByIds``) can still resolve a deleted memory's content
    while every live read skips it via ``AND deleted_at IS NULL``.

    Attributes:
        version: Migration version number (21).
        description: Human-readable description of the migration.
    """

    version: int = 21
    """The version number of this migration."""
    description: str = "Add deleted_at to user_memories"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Add the nullable ``deleted_at TIMESTAMP`` column to ``user_memories``.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("ALTER TABLE user_memories ADD COLUMN deleted_at TIMESTAMP NULL"),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """No-op: the ``deleted_at`` column is left in place.

        SQLite cannot ``DROP COLUMN`` portably across the target RDBMS set
        (SQLite / PostgreSQL / MySQL), and a rebuild-via-temp-table is heavier
        than warranted for the rollback of a nullable additive column. The
        column carries no ``DEFAULT``, is nullable, and is filtered out by the
        read methods that do not need it, so leaving it in place on rollback
        is safe.

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        logger.info(
            "migration_021 down(): leaving user_memories.deleted_at in place "
            "(nullable, additive column — safe on rollback; portable DROP COLUMN "
            "is not available across SQLite/PostgreSQL/MySQL)"
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration021UserMemoriesSoftDelete
