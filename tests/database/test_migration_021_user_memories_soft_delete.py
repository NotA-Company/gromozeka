"""Tests for ``migration_021_user_memories_soft_delete`` (adds ``deleted_at``).

Verifies the nullable ``deleted_at TIMESTAMP`` column is added to
``user_memories`` for soft-delete semantics.  ``down()`` is intentionally a
no-op -- portable ``DROP COLUMN`` is unavailable across SQLite /
PostgreSQL / MySQL, and a nullable additive column is safe to leave on
rollback.

Approach: the shared ``testDatabase`` fixture auto-migrates to the latest
version.  Because migration 021's ``down()`` is a no-op, simply rolling
back 021 does not remove the column -- the test must reach the pre-020
state (roll back 5 steps: 024, 023, 022, 021, 020) and re-create
``user_memories`` via ``Migration020UserMemories().up()`` (the backfills
are no-ops on the empty legacy tables left by the rollback).  This
produces a ``user_memories`` table WITHOUT ``deleted_at`` -- the pre-021
state.

``up()`` is not idempotent at the SQL level (``ALTER TABLE ... ADD
COLUMN`` has no ``IF NOT EXISTS`` and errors on a duplicate column name);
the migration framework prevents re-application via version tracking.
``down()`` is idempotent (it is a logging-only no-op).
"""

import uuid

import lib.utils as libUtils
from internal.database import Database
from internal.database.migrations import MigrationManager
from internal.database.migrations.versions.migration_020_user_memories import Migration020UserMemories
from internal.database.migrations.versions.migration_021_user_memories_soft_delete import (
    Migration021UserMemoriesSoftDelete,
)
from internal.database.providers.base import BaseSQLProvider

CHAT_ID = 1
USER_ID = 100


async def _rollbackToPre020AndCreateUserMemories(provider: BaseSQLProvider) -> None:
    """Roll back to version 19 and re-create ``user_memories`` without ``deleted_at``.

    Rolling back 5 steps (024, 023, 022, 021, 020) drops ``user_memories`` and
    re-creates an empty ``user_data`` table (via 022's ``down()``).  Then
    ``Migration020UserMemories().up()`` re-creates ``user_memories`` in its
    pre-021 shape (no ``deleted_at`` column).  The backfills are no-ops
    because the legacy tables are empty.

    Args:
        provider: Writable SQL provider for the default data source.

    Returns:
        None
    """
    rollbackManager = MigrationManager()
    rollbackManager.loadMigrationsFromVersions()
    await rollbackManager.rollback(steps=5, sqlProvider=provider)
    await Migration020UserMemories().up(provider)


async def _insertUserMemory(provider: BaseSQLProvider, chatId: int, userId: int, content: str) -> None:
    """Insert a single ``user_memories`` row in the pre-021 shape (no ``deleted_at``).

    Args:
        provider: Writable SQL provider for the default data source.
        chatId: Chat id to associate the memory with.
        userId: User id to associate the memory with.
        content: Memory content string.

    Returns:
        None
    """
    now = libUtils.now()
    await provider.execute(
        """
        INSERT INTO user_memories
            (chat_id, user_id, thread_id, memory_id, type, content, tags,
             permanent, source, embedding_model, embedding_dimensions,
             created_at, updated_at)
        VALUES
            (:chatId, :userId, NULL, :memoryId, 'fact', :content, '[]',
             1, 'manual', NULL, NULL, :createdAt, :updatedAt)
        """,
        {
            "chatId": chatId,
            "userId": userId,
            "memoryId": uuid.uuid4().hex,
            "content": content,
            "createdAt": now,
            "updatedAt": now,
        },
    )


async def test_up_addsNullableDeletedAtColumn(testDatabase: Database) -> None:
    """``up()`` adds a nullable ``deleted_at`` column; existing rows get NULL.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre020AndCreateUserMemories(provider)

    # Seed a row BEFORE the column exists (pre-021 state).
    await _insertUserMemory(provider, CHAT_ID, USER_ID, "city: Berlin")

    migration = Migration021UserMemoriesSoftDelete()
    await migration.up(provider)

    # The column exists and the pre-existing row has NULL.
    row = await provider.executeFetchOne(
        "SELECT deleted_at FROM user_memories WHERE chat_id = :chatId AND user_id = :userId",
        {"chatId": CHAT_ID, "userId": USER_ID},
    )
    assert row is not None, "seeded row must survive the ALTER TABLE"
    assert row["deleted_at"] is None, "existing rows must have NULL deleted_at after up()"


async def test_down_leavesColumnInPlace(testDatabase: Database) -> None:
    """``down()`` is a no-op -- the nullable additive column is left in place.

    Portable ``DROP COLUMN`` is unavailable across SQLite / PostgreSQL /
    MySQL, so the migration intentionally does nothing in ``down()``.
    Calling ``down()`` must not raise and must leave the ``deleted_at``
    column present.  Calling it twice is equally safe (idempotent no-op).

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre020AndCreateUserMemories(provider)

    migration = Migration021UserMemoriesSoftDelete()
    await migration.up(provider)

    # down() is a no-op -- must not raise, must leave the column.
    await migration.down(provider)
    await migration.down(provider)  # idempotent -- safe to call twice.

    # Explicitly verify the column is still present.
    columns = await provider.executeFetchAll("PRAGMA table_info(user_memories)")
    columnNames = {col["name"] for col in columns}
    assert "deleted_at" in columnNames, "down() must leave deleted_at column in place"
