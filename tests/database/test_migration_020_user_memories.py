"""Tests for ``migration_020_user_memories`` (table creation + both backfills).

Verifies the unified ``user_memories`` table is created and backfilled
from the two legacy stores it retires:

- Backfill A — ``user_data`` rows -> permanent cross-thread ``type='fact'``
  memories with ``content="{key}: {data}"``.
- Backfill B — ``chat_users.metadata.memoryRefinement[str(threadId)]``
  rolling-bio blobs -> permanent thread-scoped ``type='bio'`` memories
  tagged ``["migrated_bio"]``.  Entries with an empty ``summary`` are
  skipped.

The original monolith (``test_migration_020_up_downAndBackfills``) is split
into one-concern-per-test functions following the pattern in
``test_migration_023_rename_memory_injection_enabled_to_memory_enabled.py``.
Every assertion from the monolith is preserved across the split.

Approach: the shared ``testDatabase`` fixture auto-migrates to the latest
version (so ``user_memories`` exists, empty).  Each test rolls back to the
pre-020 state (version 19) via ``rollbackTo(targetVersion=19)`` -- this
runs ``down()`` for every migration above 020 (020 included), seeds the
legacy stores, then exercises ``up()`` / ``down()`` directly. Targeting a
fixed version (rather than ``rollback(steps=N)``) keeps the baseline
stable when new migrations are added above 020.

Idempotency note: migration 020's backfill helpers use a COUNT+diff guard
(not a pure sentinel probe) so a crash mid-backfill resumes the remaining
rows on re-run.  The idempotency test asserts that a second ``up()`` on
the same seeded data produces no duplicate rows under this guard.
"""

import json

import lib.utils as libUtils
from internal.database import Database
from internal.database.migrations import MigrationManager
from internal.database.migrations.versions.migration_020_user_memories import Migration020UserMemories
from lib.db.providers.base import BaseSQLProvider

CHAT_ID = 1
USER_ID = 100


async def _tableNames(provider: BaseSQLProvider) -> set[str]:
    """Return the set of table names visible to ``provider``.

    Args:
        provider: SQL provider for the default data source.

    Returns:
        The set of table names in the default source.
    """
    rows = await provider.executeFetchAll("SELECT name FROM sqlite_master WHERE type='table'")
    return {row["name"] for row in rows}


async def _rollbackToPre020(provider: BaseSQLProvider) -> None:
    """Roll back to version 19 to reach the pre-020 state.

    ``rollbackTo(targetVersion=19)`` runs ``down()`` for every migration at
    or below the current version with version > 19 -- i.e. 020 and
    everything above it (currently 021/022/023/024/025, plus any later
    migrations). The per-migration effects are:

    - 025's ``down()``: restores the pre-refactor embedding schema
      (``message_embeddings`` re-created empty, ``user_memories`` /
      ``chat_messages`` swapped back, ``models`` dropped).
    - 024's ``down()``: drops the bayes_tokens index (no-op on data).
    - 023's ``down()``: reverse key rename (no-op on an empty DB).
    - 022's ``down()``: re-creates an **empty** ``user_data`` table.
    - 021's ``down()``: no-op (nullable additive column left in place).
    - 020's ``down()``: drops ``user_memories``.

    After this, ``user_memories`` does not exist, ``user_data`` exists
    (empty), and ``chat_users`` is untouched.

    Args:
        provider: Writable SQL provider for the default data source.

    Returns:
        None
    """
    rollbackManager = MigrationManager()
    rollbackManager.loadMigrationsFromVersions()
    await rollbackManager.rollbackTo(targetVersion=19, sqlProvider=provider)


async def _seedLegacyStores(provider: BaseSQLProvider) -> None:
    """Seed the two legacy stores that migration 020 backfills from.

    - ``user_data``: two key-value facts (``city: Berlin``, ``job: nurse``)
      for ``USER_ID`` in ``CHAT_ID``.
    - ``chat_users``: a rolling-bio blob under
      ``metadata.memoryRefinement`` with two thread entries -- thread 5
      (non-empty summary) and thread 9 (empty summary, must be skipped
      by the backfill).

    Args:
        provider: Writable SQL provider for the default data source.

    Returns:
        None
    """
    now = libUtils.now()

    # user_data: two key-value facts for one user.
    userDataRows = [
        (USER_ID, CHAT_ID, "city", "Berlin"),
        (USER_ID, CHAT_ID, "job", "nurse"),
    ]
    for userId, chatId, key, data in userDataRows:
        await provider.execute(
            """
            INSERT INTO user_data (user_id, chat_id, key, data, created_at, updated_at)
            VALUES (:userId, :chatId, :key, :data, :createdAt, :updatedAt)
            """,
            {
                "userId": userId,
                "chatId": chatId,
                "key": key,
                "data": data,
                "createdAt": now,
                "updatedAt": now,
            },
        )

    # chat_users: a rolling-bio blob under metadata.memoryRefinement for thread 5,
    # plus an empty-summary entry that the backfill must skip.
    rollingBioMetadata = json.dumps(
        {
            "memoryRefinement": {
                "5": {
                    "summary": "User likes jazz and lives in Berlin.",
                    "lastProcessedMessageId": 42,
                    "lastProcessedMessageDate": "2026-01-01T00:00:00+00:00",
                },
                "9": {
                    "summary": "",
                    "lastProcessedMessageId": 7,
                    "lastProcessedMessageDate": "2026-01-02T00:00:00+00:00",
                },
            }
        }
    )
    await provider.execute(
        """
        INSERT INTO chat_users
            (chat_id, user_id, username, full_name, messages_count, metadata,
             created_at, updated_at)
        VALUES
            (:chatId, :userId, :username, :fullName, 0, :metadata,
             :createdAt, :updatedAt)
        """,
        {
            "chatId": CHAT_ID,
            "userId": USER_ID,
            "username": "@tester",
            "fullName": "Test User",
            "metadata": rollingBioMetadata,
            "createdAt": now,
            "updatedAt": now,
        },
    )


async def test_down_dropsUserMemoriesKeepsLegacyTables(testDatabase: Database) -> None:
    """``down()`` drops ``user_memories`` while ``user_data`` and ``chat_users`` survive.

    Exercises ``down()`` in two contexts: (a) during the rollback to the
    pre-020 state (``user_memories`` is empty), and (b) after ``up()`` has
    backfilled rows into ``user_memories``.  In both cases the legacy
    tables and their data must be left intact.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)

    # --- Roll back to the pre-020 state -- this exercises down() on each
    # migration above 019 (including 020's own down()).
    await _rollbackToPre020(provider)

    preStateTables = await _tableNames(provider)
    assert "user_memories" not in preStateTables, "down() should have dropped user_memories"
    assert "user_data" in preStateTables, "user_data must survive rollback"
    assert "chat_users" in preStateTables, "chat_users must survive rollback"

    # --- Seed legacy stores, run up() to create + backfill user_memories,
    # then run down() again to confirm the drop leaves legacy data intact.
    await _seedLegacyStores(provider)

    migration = Migration020UserMemories()
    await migration.up(provider)
    await migration.down(provider)

    postStateTables = await _tableNames(provider)
    assert "user_memories" not in postStateTables, "down() must drop user_memories"

    survivingUserData = await provider.executeFetchAll("SELECT * FROM user_data")
    assert len(survivingUserData) == 2, "user_data must be untouched by down()"

    survivingChatUsers = await provider.executeFetchAll("SELECT * FROM chat_users")
    assert len(survivingChatUsers) == 1, "chat_users must be untouched by down()"


async def test_up_backfillsUserDataToFacts(testDatabase: Database) -> None:
    """``up()`` backfills ``user_data`` rows into permanent cross-thread fact memories.

    Each legacy ``(user_id, chat_id, key, data)`` row becomes a permanent
    ``type='fact'`` memory with ``thread_id=NULL``, content
    ``"{key}: {data}"``, empty tags, ``source='migration'``, and NULL
    embedding columns.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre020(provider)
    await _seedLegacyStores(provider)

    migration = Migration020UserMemories()
    await migration.up(provider)

    factRows = await provider.executeFetchAll(
        "SELECT chat_id, user_id, thread_id, memory_id, type, content, tags, "
        "permanent, source, embedding_model, embedding_dimensions "
        "FROM user_memories WHERE type = 'fact' ORDER BY content"
    )
    assert len(factRows) == 2, f"expected 2 fact rows, got {len(factRows)}"
    for row in factRows:
        assert row["chat_id"] == CHAT_ID
        assert row["user_id"] == USER_ID
        assert row["thread_id"] is None, "user_data backfill must be cross-thread (thread_id NULL)"
        assert row["type"] == "fact"
        assert row["tags"] == "[]", "user_data backfill must have empty tags"
        assert row["permanent"] == 1, "user_data backfill must be permanent"
        assert row["source"] == "migration"
        assert row["embedding_model"] is None
        assert row["embedding_dimensions"] is None
        assert row["memory_id"], "memory_id must be populated"
    factContents = {row["content"] for row in factRows}
    assert factContents == {"city: Berlin", "job: nurse"}, factContents


async def test_up_backfillsRollingBioToBioMemories(testDatabase: Database) -> None:
    """``up()`` backfills rolling-bio JSON into permanent thread-scoped bio memories.

    Each ``chat_users.metadata.memoryRefinement[str(threadId)]`` entry with
    a non-empty ``summary`` becomes a permanent ``type='bio'`` memory scoped
    to the original thread, with ``tags='["migrated_bio"]'`` and
    ``source='migration'``.  The summary text is preserved verbatim.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre020(provider)
    await _seedLegacyStores(provider)

    migration = Migration020UserMemories()
    await migration.up(provider)

    bioRows = await provider.executeFetchAll(
        "SELECT chat_id, user_id, thread_id, memory_id, type, content, tags, "
        "permanent, source, embedding_model, embedding_dimensions "
        "FROM user_memories WHERE type = 'bio'"
    )
    # The empty-summary thread-9 entry must be skipped -> only one bio row.
    assert len(bioRows) == 1, f"expected 1 bio row (empty summary skipped), got {len(bioRows)}"
    bio = bioRows[0]
    assert bio["chat_id"] == CHAT_ID
    assert bio["user_id"] == USER_ID
    assert bio["thread_id"] == 5, "bio backfill must keep its original thread scope (NOT NULL)"
    assert bio["type"] == "bio"
    assert bio["content"] == "User likes jazz and lives in Berlin."
    assert bio["tags"] == '["migrated_bio"]'
    assert bio["permanent"] == 1
    assert bio["source"] == "migration"
    assert bio["embedding_model"] is None
    assert bio["embedding_dimensions"] is None
    assert bio["memory_id"]


async def test_up_skipsEmptySummaryEntries(testDatabase: Database) -> None:
    """``up()`` skips rolling-bio entries whose ``summary`` is empty.

    The seeded ``chat_users`` row has two ``memoryRefinement`` entries:
    thread 5 (non-empty summary) and thread 9 (empty summary).  Only the
    non-empty entry should produce a bio memory.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre020(provider)
    await _seedLegacyStores(provider)

    migration = Migration020UserMemories()
    await migration.up(provider)

    bioCountRow = await provider.executeFetchOne("SELECT COUNT(*) AS cnt FROM user_memories WHERE type = 'bio'")
    assert bioCountRow is not None, "COUNT(*) must always return a row"
    assert int(bioCountRow["cnt"]) == 1, "empty-summary entry must be skipped (1 bio row, not 2)"


async def test_up_isIdempotent(testDatabase: Database) -> None:
    """A second ``up()`` on the same seeded data produces no duplicate rows.

    Migration 020's backfill helpers use a COUNT+diff guard (not a pure
    sentinel probe) so a crash mid-backfill resumes the remaining rows.
    On a completed backfill, the guard detects that all source rows are
    already migrated and inserts nothing -- a second ``up()`` is a no-op.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre020(provider)
    await _seedLegacyStores(provider)

    migration = Migration020UserMemories()
    await migration.up(provider)

    # Second up() -- the count+diff guards must make this a no-op.
    await migration.up(provider)

    factCountRow = await provider.executeFetchOne("SELECT COUNT(*) AS cnt FROM user_memories WHERE type = 'fact'")
    bioCountRow = await provider.executeFetchOne("SELECT COUNT(*) AS cnt FROM user_memories WHERE type = 'bio'")
    assert factCountRow is not None, "COUNT(*) must always return a row"
    assert bioCountRow is not None, "COUNT(*) must always return a row"
    assert int(factCountRow["cnt"]) == 2, "second up() must not duplicate fact rows"
    assert int(bioCountRow["cnt"]) == 1, "second up() must not duplicate bio rows"
