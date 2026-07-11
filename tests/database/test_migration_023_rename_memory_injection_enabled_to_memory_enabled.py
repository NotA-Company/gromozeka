"""Tests for ``migration_023_rename_memory_injection_enabled_to_memory_enabled``.

Verifies the value-preserving rename of a persisted ``chat_settings`` key to
``"memory-enabled"`` (the ``OLD_KEY`` / ``NEW_KEY`` constants in the migration
module hold the exact before/after strings), accompanying the ``MEMORY_ENABLED``
enum rename.

Approach: the shared ``testDatabase`` fixture auto-migrates to the latest
version (so ``chat_settings`` exists, empty). The test rolls back migration 023
(one step — it is the newest) to reach the pre-rename state, seeds a row with
the old key plus a couple of sibling rows with unrelated keys, then exercises
``up()`` / ``down()`` directly and asserts:

- The old-key row's ``key`` is renamed; its ``value`` is preserved verbatim.
- Sibling rows for other keys are untouched.
- ``down()`` reverts the rename.
- ``up()`` is idempotent — running it twice does not error and leaves the key
  at ``"memory-enabled"``.
"""

import lib.utils as libUtils
from internal.database import Database
from internal.database.migrations import MigrationManager
from internal.database.migrations.versions.migration_023_rename_memory_injection_enabled_to_memory_enabled import (
    NEW_KEY,
    OLD_KEY,
    Migration023RenameMemoryInjectionEnabledToMemoryEnabled,
)
from internal.database.providers.base import BaseSQLProvider, QueryResultFetchOne

CHAT_ID = 1


async def _insertChatSetting(provider: BaseSQLProvider, chatId: int, key: str, value: str) -> None:
    """Insert a single ``chat_settings`` row with ``created_at`` / ``updated_at`` set.

    Args:
        provider: Writable SQL provider for the default data source.
        chatId: Chat id to associate the setting with.
        key: Setting key string.
        value: Setting value string.

    Returns:
        None
    """
    now = libUtils.now()
    await provider.execute(
        """
        INSERT INTO chat_settings (chat_id, key, value, created_at, updated_at)
        VALUES (:chatId, :key, :value, :createdAt, :updatedAt)
        """,
        {"chatId": chatId, "key": key, "value": value, "createdAt": now, "updatedAt": now},
    )


async def _fetchSetting(provider: BaseSQLProvider, chatId: int, key: str) -> QueryResultFetchOne:
    """Fetch a single ``chat_settings`` row by ``(chatId, key)``.

    Args:
        provider: SQL provider for the default data source.
        chatId: Chat id of the setting.
        key: Setting key string.

    Returns:
        The matching row dict, or ``None`` when no such row exists.
    """
    return await provider.executeFetchOne(
        "SELECT chat_id, key, value FROM chat_settings WHERE chat_id = :chatId AND key = :key",
        {"chatId": chatId, "key": key},
    )


async def test_migration_023_renamesKeyPreservingValue(testDatabase: Database) -> None:
    """``up()`` renames the key and preserves the value; sibling rows untouched.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)

    # --- Roll back migration 023 (the newest) to reach the pre-rename state.
    # One step: 023's down() is the reverse rename, a no-op on an empty DB.
    rollbackManager = MigrationManager()
    rollbackManager.loadMigrationsFromVersions()
    await rollbackManager.rollback(steps=1, sqlProvider=provider)

    # --- Seed: the target row under the OLD key, plus two sibling rows for
    # unrelated keys that must be left exactly as they were.
    targetValue = "1"
    await _insertChatSetting(provider, CHAT_ID, OLD_KEY, targetValue)
    await _insertChatSetting(provider, CHAT_ID, "spam-protection-enabled", "1")
    await _insertChatSetting(provider, CHAT_ID, "memory-enabled-tag-mode", "x")

    # Sanity: the target row exists under the OLD key, and NEW_KEY is absent.
    preTarget = await _fetchSetting(provider, CHAT_ID, OLD_KEY)
    assert preTarget is not None and preTarget["value"] == targetValue
    assert await _fetchSetting(provider, CHAT_ID, NEW_KEY) is None

    # --- Run up() directly.
    migration = Migration023RenameMemoryInjectionEnabledToMemoryEnabled()
    await migration.up(provider)

    # Target row renamed; value preserved; OLD key gone; NEW key present.
    assert await _fetchSetting(provider, CHAT_ID, OLD_KEY) is None, "old key must be gone after up()"
    renamed = await _fetchSetting(provider, CHAT_ID, NEW_KEY)
    assert renamed is not None, "new key must exist after up()"
    assert renamed["chat_id"] == CHAT_ID
    assert renamed["value"] == targetValue, "value must be preserved verbatim by the rename"

    # Sibling rows untouched.
    siblingA = await _fetchSetting(provider, CHAT_ID, "spam-protection-enabled")
    assert siblingA is not None and siblingA["value"] == "1", "unrelated key must be untouched"
    siblingB = await _fetchSetting(provider, CHAT_ID, "memory-enabled-tag-mode")
    assert (
        siblingB is not None and siblingB["value"] == "x"
    ), "unrelated key that merely contains the new-key substring must be untouched"


async def test_migration_023_downRevertsRename(testDatabase: Database) -> None:
    """``down()`` is the exact inverse — renames ``memory-enabled`` back to the old key.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)

    rollbackManager = MigrationManager()
    rollbackManager.loadMigrationsFromVersions()
    await rollbackManager.rollback(steps=1, sqlProvider=provider)

    targetValue = "0"
    await _insertChatSetting(provider, CHAT_ID, OLD_KEY, targetValue)

    migration = Migration023RenameMemoryInjectionEnabledToMemoryEnabled()
    await migration.up(provider)
    assert await _fetchSetting(provider, CHAT_ID, NEW_KEY) is not None

    # --- down() reverts.
    await migration.down(provider)

    assert await _fetchSetting(provider, CHAT_ID, NEW_KEY) is None, "new key must be gone after down()"
    reverted = await _fetchSetting(provider, CHAT_ID, OLD_KEY)
    assert (
        reverted is not None and reverted["value"] == targetValue
    ), "old key must be restored with its original value after down()"


async def test_migration_023_upIsIdempotent(testDatabase: Database) -> None:
    """Running ``up()`` twice neither errors nor changes the result.

    After the first ``up()`` every matching row is renamed, so the second
    ``up()`` matches zero rows and is a no-op.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)

    rollbackManager = MigrationManager()
    rollbackManager.loadMigrationsFromVersions()
    await rollbackManager.rollback(steps=1, sqlProvider=provider)

    targetValue = "1"
    await _insertChatSetting(provider, CHAT_ID, OLD_KEY, targetValue)

    migration = Migration023RenameMemoryInjectionEnabledToMemoryEnabled()

    # First up(): performs the rename.
    await migration.up(provider)
    firstRun = await _fetchSetting(provider, CHAT_ID, NEW_KEY)
    assert firstRun is not None and firstRun["value"] == targetValue

    # Second up(): must not raise and must not alter the row.
    await migration.up(provider)
    secondRun = await _fetchSetting(provider, CHAT_ID, NEW_KEY)
    assert (
        secondRun is not None and secondRun["value"] == targetValue
    ), "second up() must leave the renamed row unchanged"
    assert await _fetchSetting(provider, CHAT_ID, OLD_KEY) is None, "old key must still be absent after second up()"

    # No spurious duplicate rows: exactly one row for this chat.
    rowCount = await provider.executeFetchOne(
        "SELECT COUNT(*) AS cnt FROM chat_settings WHERE chat_id = :chatId",
        {"chatId": CHAT_ID},
    )
    assert rowCount is not None and int(rowCount["cnt"]) == 1, "idempotent up() must not create duplicate rows"
