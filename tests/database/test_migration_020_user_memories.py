"""Tests for ``migration_020_user_memories`` (table creation + both backfills).

Verifies the unified ``user_memories`` table is created and backfilled
from the two legacy stores it retires:

- Backfill A — ``user_data`` rows → permanent cross-thread ``type='fact'``
  memories with ``content="{key}: {data}"``.
- Backfill B — ``chat_users.metadata.memoryRefinement[str(threadId)]``
  rolling-bio blobs → permanent thread-scoped ``type='bio'`` memories
  tagged ``["migrated_bio"]``.

Approach: the shared ``testDatabase`` fixture auto-migrates to the latest
version (so ``user_memories`` exists empty). The test rolls back
migration 020 (which exercises ``down()`` and confirms ``user_data`` +
``chat_users`` survive), seeds the legacy tables, then runs ``up()``
directly to exercise the full create + backfill path, and finally
``down()`` again to confirm the drop leaves ``user_data`` intact.
"""

import json

import lib.utils as libUtils
from internal.database import Database
from internal.database.migrations import MigrationManager
from internal.database.migrations.versions.migration_020_user_memories import Migration020UserMemories

CHAT_ID = 1
USER_ID = 100


async def _tableNames(db: Database) -> set[str]:
    """Return the set of table names in the default source."""
    provider = await db.manager.getProvider(readonly=True)
    rows = await provider.executeFetchAll("SELECT name FROM sqlite_master WHERE type='table'")
    return {row["name"] for row in rows}


async def test_migration_020_up_downAndBackfills(testDatabase: Database) -> None:
    """up() creates the table and backfills; down() drops only user_memories.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)

    # --- Roll back migration 020 to reach the pre-020 state.
    # This also exercises down(): user_memories must be dropped while
    # user_data + chat_users survive. Four steps are rolled back because
    # migrations 023 (chat_settings key rename), 022 (drop user_data), and
    # 021 (user_memories.deleted_at) sit above 020: step 1 is 023's down()
    # (no-op data rename on an empty DB), step 2 is 022's down() (re-creates
    # empty user_data), step 3 is 021's no-op down(), step 4 is 020's down()
    # that drops the table.
    rollbackManager = MigrationManager()
    rollbackManager.loadMigrationsFromVersions()
    await rollbackManager.rollback(steps=4, sqlProvider=provider)

    preStateTables = await _tableNames(testDatabase)
    assert "user_memories" not in preStateTables, "down() should have dropped user_memories"
    assert "user_data" in preStateTables, "user_data must survive rollback"
    assert "chat_users" in preStateTables, "chat_users must survive rollback"

    # --- Seed legacy stores.
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

    # --- Run up() directly (table does not exist yet → full create + backfill).
    migration = Migration020UserMemories()
    await migration.up(provider)

    # --- Assert Backfill A: user_data → permanent cross-thread facts.
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

    # --- Assert Backfill B: rolling-bio → permanent thread-scoped bio.
    bioRows = await provider.executeFetchAll(
        "SELECT chat_id, user_id, thread_id, memory_id, type, content, tags, "
        "permanent, source, embedding_model, embedding_dimensions "
        "FROM user_memories WHERE type = 'bio'"
    )
    # The empty-summary thread-9 entry must be skipped → only one bio row.
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

    # --- Idempotency: a second up() on the same seeded data must NOT
    # double the backfilled rows. The migration framework neither wraps
    # up() in a single transaction nor bumps the version after a partial
    # failure, so a restart re-runs up() — the sentinel guards in each
    # backfill helper make the re-run a no-op here. This assertion would
    # FAIL before the sentinels existed (each re-run inserts fresh UUIDs).
    await migration.up(provider)

    factCountRow = await provider.executeFetchOne("SELECT COUNT(*) AS cnt FROM user_memories WHERE type = 'fact'")
    bioCountRow = await provider.executeFetchOne("SELECT COUNT(*) AS cnt FROM user_memories WHERE type = 'bio'")
    assert factCountRow is not None, "COUNT(*) must always return a row"
    assert bioCountRow is not None, "COUNT(*) must always return a row"
    assert int(factCountRow["cnt"]) == 2, "second up() must not duplicate fact rows"
    assert int(bioCountRow["cnt"]) == 1, "second up() must not duplicate bio rows"

    # --- Run down() directly: user_memories dropped, user_data + chat_users intact.
    await migration.down(provider)

    postStateTables = await _tableNames(testDatabase)
    assert "user_memories" not in postStateTables, "down() must drop user_memories"

    survivingUserData = await provider.executeFetchAll("SELECT * FROM user_data")
    assert len(survivingUserData) == 2, "user_data must be untouched by down()"

    survivingChatUsers = await provider.executeFetchAll("SELECT * FROM chat_users")
    assert len(survivingChatUsers) == 1, "chat_users must be untouched by down()"
