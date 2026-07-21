"""Normalise embedding provenance into a ``models`` lookup table.

This migration implements Phase 2 of the embedding-model-lookup refactor
(see ``docs/plans/embedding-model-lookup-refactor-v1.md`` §6 — APPROVED +
architect-self-reviewed; treat its specs as authoritative). It is the
schema-only dispatch of the four sub-dispatches that together complete
Phases 2+3. It does NOT touch repository code — the repo refactor that
follows this migration is dispatched separately (2+3-B/C/D). After this
migration lands alone, the production repos still query the legacy
``message_embeddings`` / ``embedding_model`` / ``embedding_dimensions``
columns that this migration drops, so ``make test`` is expected to fail
until the repo refactor clears it.

What this migration does
------------------------

1. Creates a new ``models`` lookup table keyed by an app-generated
   sequential ``model_id`` integer, with ``UNIQUE (model, dimensions)``.
   The table starts EMPTY — allocation happens lazily via
   :meth:`EmbeddingModelsRepository.getOrCreateModelId` on the first
   embed call (there is no migration-time backfill).
2. Swaps ``user_memories`` via the temp-table pattern (precedent:
   ``migration_013_remove_timestamp_defaults.py``) to drop the
   ``embedding_model`` / ``embedding_dimensions`` columns and add a
   ``model_id`` column. ``model_id`` is set to the NULL constant for
   every row — there is no LEFT JOIN to ``models`` here either. The
   same data-correctness reasoning as chat_messages (Step 3 below)
   applies: rows are marked un-embedded so the regen cron re-surfaces
   them rather than silently dropping their search.
3. Adds ``chat_messages.model_id`` via a portable ``ALTER TABLE ...
   ADD COLUMN`` (nullable, no default). The temp-table swap is
   unnecessary for a single new nullable column; rows are left
   ``model_id = NULL`` and re-embedded by the backfill cron. The
   ``message_embeddings`` BLOB vectors are dropped in Step 4, so a
   backfilled ``model_id`` would mark rows embedded with no searchable
   vector — leaving NULL forces re-embed via the cron, which is the
   only correct state when all prior vectors are gone.
4. Drops the ``message_embeddings`` table and its
   ``idx_message_embeddings_chat_model`` index. Vectors stored in the
   BLOB column cannot be regenerated from ``model_id`` alone — this is
   the explicit trade for retiring the BLOB store (plan Decision D4).
5. Drops both vec0 virtual-table families (``vec_message_embeddings_*``
   and ``vec_user_memories_*``) by enumerating them through
   ``sqlProvider.listTables(pattern)`` and filtering to the strict
   ``_<digits>`` suffix shape. vec0 DDL is not ALTER-able; full drop is
   the only portable option (plan Decision D1). The vec0 tables are
   lazily recreated on the next embed call with the new
   ``model_id``-partitioned DDL.

Rollback is honestly lossy
--------------------------

Per plan §6, the ``down()`` path restores the pre-refactor SQL shape but
NOT the data:

- ``message_embeddings`` is re-created EMPTY — the float32 BLOBs dropped
  in ``up()`` cannot be regenerated from ``model_id`` alone.
- ``user_memories.embedding_model`` / ``embedding_dimensions`` are
  restored as NULL, NULL constants via the temp-table swap-back. Since
  ``up()`` no longer populates ``model_id``, a LEFT JOIN back to
  ``models`` would miss every row anyway; the NULL constants are
  logically equivalent and avoid the unnecessary join.
- ``chat_messages`` is swapped back to the pre-``model_id`` shape.
- ``models`` is dropped.
- The ``vec_message_embeddings_*`` and ``vec_user_memories_*`` virtual
  tables are NOT re-created — they are lazily created at runtime
  regardless of schema version, and the vectors they held before
  ``up()`` ran are gone. Downgrading therefore yields a system with
  empty vector stores that repopulate via the normal backfill cron.

Schema notes (cross-RDBMS portability, per AGENTS.md)
-----------------------------------------------------

- ``models.model_id`` is ``INTEGER PRIMARY KEY NOT NULL`` with
  app-generated sequential ids (plan Decision D7 — a documented,
  intentional deviation from the AGENTS.md-default TEXT UUID: small
  sequential ints are cheaper as vec0 partition keys, the process-local
  cache makes allocation O(1), and the single-process app has no
  concurrent-writer hazard). No ``AUTOINCREMENT`` / ``SERIAL`` — the DB
  does not generate IDs.
- No ``DEFAULT CURRENT_TIMESTAMP`` — the app sets ``created_at``
  explicitly.
- ``:named`` placeholders throughout, all SQL goes through
  ``BaseSQLProvider``.
- vec0 DDL is not emitted by this migration (the lazy-create happens at
  runtime); the ``DROP TABLE IF EXISTS vec_*`` statements in Step 6 are
  SQLite vec0 virtual-table drops, which the ``vec0 DDL is EXPLICITLY
  EXEMPT`` clause in AGENTS.md covers.
"""

import logging
import re
from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration

logger = logging.getLogger(__name__)

# Strict ``_<digits>`` suffix shape for vec0 dimension-sharded tables.
# Defensive against a stray non-numeric suffix; ``listTables`` already
# narrows via a SQL LIKE pattern, this regex is the second guard.
_VEC_TABLE_NAME_PATTERN = re.compile(r"^vec_(message_embeddings|user_memories)_\d+$")


class Migration025EmbeddingModelLookup(BaseMigration):
    """Normalise embedding provenance into a ``models`` lookup table.

    Creates ``models``, swaps ``user_memories`` and ``chat_messages`` to
    carry ``model_id`` instead of the legacy ``(model, dimensions)`` /
    ``(embedding_model, embedding_dimensions)`` pairs, drops the
    ``message_embeddings`` BLOB side table, and drops both vec0
    virtual-table families. The ``down()`` path is schema-correct but
    data-lossy for vectors — see the module docstring for the rollback
    contract.

    Attributes:
        version: Migration version number (25).
        description: Human-readable description of the migration.
    """

    version: int = 25
    """The version number of this migration."""
    description: str = "Normalise embedding provenance into models lookup; drop message_embeddings BLOB store"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply migration 025 — the schema-only embedding-model-lookup refactor.

        Five ``batchExecute`` blocks (no migration-time backfill anywhere):

        1. ``CREATE IF NOT EXISTS models`` (the ``models`` lookup table
           starts EMPTY — allocation is lazy via
           :meth:`EmbeddingModelsRepository.getOrCreateModelId` on the
           first embed call).
        2. ``user_memories`` temp-table swap — sets ``model_id = NULL``
           on every row (no LEFT JOIN to ``models``). The NULL constant
           forces the regen cron to re-embed rather than silently marking
           rows embedded with no searchable vec0 row (the vec0 tables
           are dropped in Step 4).
        3. ``chat_messages ALTER TABLE ADD COLUMN model_id INTEGER``
           (nullable; rows left NULL for the same re-embed reasoning).
        4. ``DROP TABLE message_embeddings`` + its index (vectors
           irrecoverable — plan Decision D4).
        5. Drop both vec0 virtual-table families via ``listTables``
           enumeration + strict ``_<digits>`` suffix regex.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        # ----------------------------------------------------------------
        # Step 1 — Create the ``models`` lookup table (starts EMPTY;
        # allocation is lazy via getOrCreateModelId on first embed call).
        # ----------------------------------------------------------------
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS models (
                        model_id   INTEGER PRIMARY KEY NOT NULL,
                        model      TEXT NOT NULL,
                        dimensions INTEGER NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        UNIQUE (model, dimensions)
                    )
                    """),
            ]
        )

        # ----------------------------------------------------------------
        # Step 2 — Swap ``user_memories`` (temp-table pattern).
        # ----------------------------------------------------------------
        await sqlProvider.batchExecute(
            [
                # 2a. New shape — ``model_id`` replaces the provenance pair.
                ParametrizedQuery("""
                    CREATE TABLE user_memories_new (
                        chat_id    INTEGER   NOT NULL,
                        user_id    INTEGER   NOT NULL,
                        thread_id  INTEGER,
                        memory_id  TEXT      NOT NULL,
                        type       TEXT      NOT NULL,
                        content    TEXT      NOT NULL,
                        tags       TEXT      NOT NULL DEFAULT '[]',
                        permanent  INTEGER   NOT NULL DEFAULT 0,
                        source     TEXT      NOT NULL DEFAULT 'refinement',
                        model_id   INTEGER,
                        deleted_at TIMESTAMP,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL,
                        PRIMARY KEY (chat_id, user_id, memory_id)
                    )
                    """),
                # 2b. Set ``model_id = NULL`` constant (no LEFT JOIN to
                #     ``models`` — see module docstring). The NULL forces
                #     the regen cron to re-embed rather than marking rows
                #     embedded while their vec0 vectors are dropped.
                ParametrizedQuery("""
                    INSERT INTO user_memories_new (
                        chat_id, user_id, thread_id, memory_id, type,
                        content, tags, permanent, source, deleted_at,
                        model_id, created_at, updated_at
                    )
                    SELECT
                        um.chat_id, um.user_id, um.thread_id, um.memory_id, um.type,
                        um.content, um.tags, um.permanent, um.source, um.deleted_at,
                        NULL, um.created_at, um.updated_at
                    FROM user_memories um
                    """),
                ParametrizedQuery("DROP TABLE user_memories"),
                ParametrizedQuery("ALTER TABLE user_memories_new RENAME TO user_memories"),
                # 2c. Recreate the three indexes from migration_020.
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_user_memories_chat_user_thread
                        ON user_memories (chat_id, user_id, thread_id, updated_at DESC)
                    """),
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_user_memories_chat_user_permanent
                        ON user_memories (chat_id, user_id, permanent, updated_at DESC)
                    """),
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_user_memories_type
                        ON user_memories (chat_id, user_id, type)
                    """),
            ]
        )

        # ----------------------------------------------------------------
        # Step 3 — Add ``chat_messages.model_id`` (portable ADD COLUMN).
        # ----------------------------------------------------------------
        # A plain nullable ``ADD COLUMN`` is supported by SQLite, PostgreSQL,
        # and MySQL alike — the temp-table swap is overkill for a single new
        # nullable column. Rows are left ``model_id = NULL``; the backfill
        # cron (``ChatEmbeddingsRepository.getMessagesWithoutEmbeddings``)
        # re-surfaces every message for re-embedding under the chat's active
        # model. This is also MORE correct than an INSERT...SELECT backfill
        # from ``message_embeddings``: the BLOB vectors are dropped in
        # Step 4 and the vec0 tables in Step 5, so a backfilled
        # ``model_id`` would mark rows as embedded with no searchable vector
        # — ``getMessagesWithoutEmbeddings`` would never re-surface them
        # (model_id matches current) and they would silently lose search.
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("ALTER TABLE chat_messages ADD COLUMN model_id INTEGER"),
            ]
        )

        # ----------------------------------------------------------------
        # Step 4 — Drop ``message_embeddings`` and its index.
        # ----------------------------------------------------------------
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_message_embeddings_chat_model"),
                ParametrizedQuery("DROP TABLE IF EXISTS message_embeddings"),
            ]
        )

        # ----------------------------------------------------------------
        # Step 5 — Drop both vec0 families (enumerate via listTables).
        # ----------------------------------------------------------------
        await self._dropVec0Families(sqlProvider)

    async def _dropVec0Families(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop both vec0 virtual-table families via ``listTables``.

        Enumerates parent vec0 tables through the provider abstraction
        (``BaseSQLProvider.listTables(likePattern)`` already abstracts the
        per-dialect introspection query), filters to the strict
        ``_<digits>`` suffix shape via a Python regex, and DROPs each
        match. vec0 shadow tables (``vec_*_chunks``, ``vec_*_rowids``,
        ``vec_*_info``) are dropped implicitly with their parent virtual
        table on SQLite. Follows the precedent in
        ``ChatEmbeddingsRepository.deleteObsoleteModelEmbeddings`` which
        uses ``sqlProvider.listTables("vec_message_embeddings_%")`` for
        the same purpose.

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        # Go through the provider. listTables maps to sqlite_master on
        # SQLite, information_schema on PostgreSQL/MySQL. The LIKE pattern
        # is the first narrowing pass; the regex below is the second.
        messageVecTables = await sqlProvider.listTables("vec_message_embeddings_%")
        memoryVecTables = await sqlProvider.listTables("vec_user_memories_%")
        candidates = list(messageVecTables) + list(memoryVecTables)
        toDrop = [name for name in candidates if _VEC_TABLE_NAME_PATTERN.match(name)]

        if toDrop:
            dropStatements = [ParametrizedQuery(f"DROP TABLE IF EXISTS {name}") for name in toDrop]
            await sqlProvider.batchExecute(dropStatements)
            logger.info("migration_025: dropped %d vec0 tables", len(toDrop))

        # Fallback (SQLite-only — do NOT use as the primary form; prefer
        # sqlProvider.listTables above for portability). Shown for
        # concreteness only; the primary form above is what runs in
        # production. If ``listTables`` ever raises NotImplementedError on
        # the configured provider, an operator can adapt this raw form:
        #     allTables = await sqlProvider.executeFetchAll(
        #         "SELECT name FROM sqlite_master WHERE type='table'"
        #     )
        #     toDrop = [row["name"] for row in allTables if _VEC_TABLE_NAME_PATTERN.match(row["name"])]

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Best-effort rollback (schema-correct, data-lossy for vectors).

        Restores the pre-refactor SQL shape:

        - re-creates ``message_embeddings`` EMPTY (vectors cannot be
          regenerated from ``model_id`` alone — the float32 BLOBs were
          dropped in ``up()``);
        - re-creates the ``idx_message_embeddings_chat_model`` index;
        - temp-table-swaps ``chat_messages`` back to the pre-``model_id``
          shape;
        - temp-table-swaps ``user_memories`` back to the
          ``embedding_model`` / ``embedding_dimensions`` shape, setting
          both columns to NULL unconditionally (since ``up()`` no longer
          populates ``model_id``, a LEFT JOIN back to ``models`` would
          miss every row anyway — the NULL constants are logically
          equivalent and avoid the unnecessary join);
        - drops the ``models`` table.

        The ``vec_message_embeddings_*`` and ``vec_user_memories_*``
        virtual tables are NOT re-created here — they are lazily created
        at runtime regardless of schema version, and the vectors they
        held before ``up()`` ran are gone. Downgrading therefore yields a
        system with empty vector stores that will repopulate via the
        normal backfill cron. Document this for operators: ``down()`` is
        schema-correct but data-lossy for search until re-embedding
        catches up (plan Risk R1).

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        # ----------------------------------------------------------------
        # Step 1 — Re-create ``message_embeddings`` EMPTY (DDL from
        # migration_017). Vectors are irrecoverable.
        # ----------------------------------------------------------------
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS message_embeddings (
                        chat_id    INTEGER   NOT NULL,
                        message_id TEXT      NOT NULL,
                        embedding  BLOB      NOT NULL,
                        dimensions INTEGER   NOT NULL,
                        model      TEXT      NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL,
                        PRIMARY KEY (chat_id, message_id)
                    )
                    """),
                # migration_018's index — re-created empty alongside the table.
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_message_embeddings_chat_model
                    ON message_embeddings (chat_id, model)
                    """),
            ]
        )

        # ----------------------------------------------------------------
        # Step 2 — Swap ``chat_messages`` back (drop ``model_id``).
        # ----------------------------------------------------------------
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE chat_messages_new (
                        chat_id          INTEGER NOT NULL,
                        message_id       TEXT NOT NULL,
                        date             TIMESTAMP NOT NULL,
                        user_id          INTEGER NOT NULL,
                        reply_id         TEXT,
                        thread_id        INTEGER NOT NULL DEFAULT 0,
                        root_message_id  TEXT,
                        message_text     TEXT NOT NULL,
                        message_type     TEXT DEFAULT 'text' NOT NULL,
                        message_category TEXT DEFAULT 'user' NOT NULL,
                        quote_text       TEXT,
                        media_id         TEXT,
                        media_group_id   TEXT,
                        markup           TEXT DEFAULT "" NOT NULL,
                        metadata         TEXT DEFAULT "" NOT NULL,
                        created_at       TIMESTAMP NOT NULL,
                        PRIMARY KEY (chat_id, message_id)
                    )
                    """),
                ParametrizedQuery("""
                    INSERT INTO chat_messages_new (
                        chat_id, message_id, date, user_id, reply_id, thread_id,
                        root_message_id, message_text, message_type, message_category,
                        quote_text, media_id, media_group_id, markup, metadata, created_at
                    )
                    SELECT
                        chat_id, message_id, date, user_id, reply_id, thread_id,
                        root_message_id, message_text, message_type, message_category,
                        quote_text, media_id, media_group_id, markup, metadata, created_at
                    FROM chat_messages
                    """),
                ParametrizedQuery("DROP TABLE chat_messages"),
                ParametrizedQuery("ALTER TABLE chat_messages_new RENAME TO chat_messages"),
            ]
        )

        # ----------------------------------------------------------------
        # Step 3 — Swap ``user_memories`` back: restore the provenance
        # pair as NULL, NULL constants (no LEFT JOIN to ``models`` —
        # ``up()`` no longer populates ``model_id``, so the join would
        # miss every row anyway). Must run BEFORE the ``models`` DROP below.
        # ----------------------------------------------------------------
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE user_memories_new (
                        chat_id              INTEGER   NOT NULL,
                        user_id              INTEGER   NOT NULL,
                        thread_id            INTEGER,
                        memory_id            TEXT      NOT NULL,
                        type                 TEXT      NOT NULL,
                        content              TEXT      NOT NULL,
                        tags                 TEXT      NOT NULL DEFAULT '[]',
                        permanent            INTEGER   NOT NULL DEFAULT 0,
                        source               TEXT      NOT NULL DEFAULT 'refinement',
                        deleted_at           TIMESTAMP,
                        embedding_model      TEXT,
                        embedding_dimensions INTEGER,
                        created_at           TIMESTAMP NOT NULL,
                        updated_at           TIMESTAMP NOT NULL,
                        PRIMARY KEY (chat_id, user_id, memory_id)
                    )
                    """),
                ParametrizedQuery("""
                    INSERT INTO user_memories_new (
                        chat_id, user_id, thread_id, memory_id, type, content, tags,
                        permanent, source, deleted_at, embedding_model, embedding_dimensions,
                        created_at, updated_at
                    )
                    SELECT
                        um.chat_id, um.user_id, um.thread_id, um.memory_id, um.type,
                        um.content, um.tags, um.permanent, um.source, um.deleted_at,
                        NULL, NULL, um.created_at, um.updated_at
                    FROM user_memories um
                    """),
                ParametrizedQuery("DROP TABLE user_memories"),
                ParametrizedQuery("ALTER TABLE user_memories_new RENAME TO user_memories"),
                # Restore the three indexes from migration_020.
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_user_memories_chat_user_thread
                        ON user_memories (chat_id, user_id, thread_id, updated_at DESC)
                    """),
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_user_memories_chat_user_permanent
                        ON user_memories (chat_id, user_id, permanent, updated_at DESC)
                    """),
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_user_memories_type
                        ON user_memories (chat_id, user_id, type)
                    """),
            ]
        )

        # ----------------------------------------------------------------
        # Step 4 — Drop ``models``. vec0 tables are NOT re-created (see
        # the method docstring — they are lazily created at runtime).
        # ----------------------------------------------------------------
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP TABLE IF EXISTS models"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration025EmbeddingModelLookup
