"""Add the unified ``user_memories`` table and backfill it from legacy stores.

This migration introduces ``user_memories`` — the single source of truth
for durable per-(chat, user, thread) facts, preferences, events,
relationships, and high-level bio notes about a user (see
``docs/archive/plans/user-memories-v1.md``). It unifies and retires two legacy
stores:

- ``user_data`` (key-value facts) → permanent cross-thread
  ``type='fact'`` memories (Backfill A). The ``user_data`` **table** is
  kept for rollback safety; only the tools that wrote it are retired.
- ``chat_users.metadata.memoryRefinement[str(threadId)]`` (the rolling
  per-thread bio JSON blob) → permanent thread-scoped ``type='bio'``
  memories (Backfill B). The blob itself is not deleted here — the
  refinement rewrite stops writing it and stale reads are no longer
  performed (the ``applyUserMetadata``/``userSummary`` path was removed
  in Phase 4b); the blob is simply left unread.

Both backfills run as Python loops inside ``up()`` because the
``memory_id`` is an app-generated UUID (AGENTS.md: "Generate it in
Python before insert; never delegate ID generation to the DB").

Schema notes (cross-RDBMS portability, per AGENTS.md):
- Composite natural PRIMARY KEY ``(chat_id, user_id, memory_id)`` — no
  ``AUTOINCREMENT`` / ``SERIAL``.
- No ``DEFAULT CURRENT_TIMESTAMP`` — the app sets ``created_at`` /
  ``updated_at`` explicitly.
- ``tags`` stored as JSON TEXT; ``permanent`` stored as INTEGER 0/1.
- ``embedding_model`` / ``embedding_dimensions`` are nullable (NULL =
  not yet embedded); the vec0 runtime table (``vec_user_memories_{dim}``)
  is created lazily on first write (Phase 1b), NOT by this migration.
"""

import json
import logging
import uuid
from typing import Type

import lib.utils as libUtils
from lib.db.providers import BaseSQLProvider, ParametrizedQuery

from ..base import BaseMigration

logger = logging.getLogger(__name__)


class Migration020UserMemories(BaseMigration):
    """Add the ``user_memories`` table and backfill it from legacy stores.

    Creates the authoritative ``user_memories`` table (with three
    supporting indexes) and migrates existing data from ``user_data``
    (Backfill A) and the rolling-bio JSON blob in ``chat_users.metadata``
    (Backfill B). ``down()`` drops only ``user_memories`` — ``user_data``
    is left intact for rollback safety.

    Attributes:
        version: Migration version number (20).
        description: Human-readable description of the migration.
    """

    version: int = 20
    """The version number of this migration."""
    description: str = "Add user_memories table with backfills from user_data and rolling-bio"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create ``user_memories`` and backfill it from legacy stores.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS user_memories (
                        chat_id    INTEGER   NOT NULL,
                        user_id    INTEGER   NOT NULL,
                        thread_id  INTEGER,
                        memory_id  TEXT      NOT NULL,
                        type       TEXT      NOT NULL,
                        content    TEXT      NOT NULL,
                        tags       TEXT      NOT NULL DEFAULT '[]',
                        permanent  INTEGER   NOT NULL DEFAULT 0,
                        source     TEXT      NOT NULL DEFAULT 'refinement',
                        embedding_model      TEXT,     -- For re-embedding process
                        embedding_dimensions INTEGER,  -- For re-embedding process
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL,
                        PRIMARY KEY (chat_id, user_id, memory_id)
                    )
                """),
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

        await self._backfillUserData(sqlProvider)
        await self._backfillRollingBio(sqlProvider)

    async def _backfillUserData(self, sqlProvider: BaseSQLProvider) -> None:
        """Backfill A — migrate ``user_data`` rows into permanent cross-thread facts.

        Each legacy ``(user_id, chat_id, key, data)`` row becomes a
        permanent ``type='fact'`` memory with ``thread_id=NULL``
        (cross-thread — ``user_data`` has no thread concept), content
        shaped ``"{key}: {data}"``, empty tags, ``source='migration'``,
        and NULL embedding columns. Original ``created_at`` /
        ``updated_at`` are preserved.

        Idempotent: a sentinel probe (``source='migration' AND
        type='fact'``) skips the backfill when it has already run. The
        migration framework does NOT wrap ``up()`` in a single
        transaction nor bump the version after a partial failure, so a
        crash mid-backfill + restart would otherwise re-run the loop and
        insert duplicate rows (each with a fresh UUID).

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        alreadyDone = await sqlProvider.executeFetchOne(
            "SELECT 1 FROM user_memories WHERE source = 'migration' AND type = :type LIMIT 1",
            {"type": "fact"},
        )
        if alreadyDone is not None:
            logger.info("user_memories: user_data backfill already applied, skipping")
            return

        rows = await sqlProvider.executeFetchAll(
            "SELECT user_id, chat_id, key, data, created_at, updated_at FROM user_data",
            {},
        )
        if not rows:
            return

        insertSql = """
            INSERT INTO user_memories
                (chat_id, user_id, thread_id, memory_id, type, content, tags,
                 permanent, source, embedding_model, embedding_dimensions,
                 created_at, updated_at)
            VALUES
                (:chatId, :userId, NULL, :memoryId, 'fact', :content, '[]',
                 1, 'migration', NULL, NULL, :createdAt, :updatedAt)
        """
        for row in rows:
            params: dict[str, object] = {
                "chatId": row["chat_id"],
                "userId": row["user_id"],
                "memoryId": uuid.uuid4().hex,
                "content": f"{row['key']}: {row['data']}",
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
            await sqlProvider.execute(insertSql, params)
        logger.info("user_memories: backfilled %d user_data rows", len(rows))

    async def _backfillRollingBio(self, sqlProvider: BaseSQLProvider) -> None:
        """Backfill B — migrate rolling-bio JSON into permanent thread-scoped bios.

        Each ``chat_users.metadata.memoryRefinement[str(threadId)]`` entry
        with a non-empty ``summary`` becomes a permanent ``type='bio'``
        memory scoped to the original thread (``thread_id=<thread>``),
        with ``tags='["migrated_bio"]'`` and ``source='migration'``. The
        summary text is preserved verbatim in ``content``. ``created_at``
        / ``updated_at`` are set to the current time (the blob carries no
        usable timestamp).

        Idempotent: a sentinel probe (``source='migration' AND
        type='bio'``) skips the backfill when it has already run. The
        migration framework does NOT wrap ``up()`` in a single
        transaction nor bump the version after a partial failure, so a
        crash mid-backfill + restart would otherwise re-run the loop and
        insert duplicate rows (each with a fresh UUID).

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        alreadyDone = await sqlProvider.executeFetchOne(
            "SELECT 1 FROM user_memories WHERE source = 'migration' AND type = :type LIMIT 1",
            {"type": "bio"},
        )
        if alreadyDone is not None:
            logger.info("user_memories: rolling-bio backfill already applied, skipping")
            return

        rows = await sqlProvider.executeFetchAll(
            "SELECT chat_id, user_id, metadata FROM chat_users WHERE metadata LIKE :pattern",
            {"pattern": '%"memoryRefinement"%'},
        )
        if not rows:
            return

        insertSql = """
            INSERT INTO user_memories
                (chat_id, user_id, thread_id, memory_id, type, content, tags,
                 permanent, source, embedding_model, embedding_dimensions,
                 created_at, updated_at)
            VALUES
                (:chatId, :userId, :threadId, :memoryId, 'bio', :content, '["migrated_bio"]',
                 1, 'migration', NULL, NULL, :createdAt, :updatedAt)
        """
        now = libUtils.now()
        inserted = 0
        for row in rows:
            rawMetadata = row["metadata"]
            if not rawMetadata:
                continue
            try:
                metadata = json.loads(rawMetadata)
            except (ValueError, TypeError):
                logger.warning(
                    "user_memories: skipping unparseable metadata for chat %s user %s",
                    row["chat_id"],
                    row["user_id"],
                )
                continue
            refinement = metadata.get("memoryRefinement")
            if not isinstance(refinement, dict) or not refinement:
                continue
            for threadIdStr, entry in refinement.items():
                summary = (entry or {}).get("summary") if isinstance(entry, dict) else None
                if not summary:
                    continue
                try:
                    threadId = int(threadIdStr)
                except (ValueError, TypeError):
                    logger.warning(
                        "user_memories: skipping non-integer thread key %r for chat %s user %s",
                        threadIdStr,
                        row["chat_id"],
                        row["user_id"],
                    )
                    continue
                params: dict[str, object] = {
                    "chatId": row["chat_id"],
                    "userId": row["user_id"],
                    "threadId": threadId,
                    "memoryId": uuid.uuid4().hex,
                    "content": summary,
                    "createdAt": now,
                    "updatedAt": now,
                }
                await sqlProvider.execute(insertSql, params)
                inserted += 1
        if inserted:
            logger.info("user_memories: backfilled %d rolling-bio entries", inserted)

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop the ``user_memories`` table.

        Does NOT touch ``user_data`` (kept for rollback safety) or
        ``chat_users.metadata`` (the rolling-bio blob is left intact; stale
        reads are no longer performed (the ``applyUserMetadata``/``userSummary``
        path was removed in Phase 4b); the blob is simply left unread).

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP TABLE IF EXISTS user_memories"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration020UserMemories
