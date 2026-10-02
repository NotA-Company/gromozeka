"""Tests for ``migration_022_drop_user_data`` (drops the obsolete table).

Verifies that ``up()`` drops ``user_data`` and ``down()`` re-creates an
**empty** ``user_data`` table (structural reversibility only -- dropped
rows cannot be recovered).  The re-created DDL must be valid, so the test
inserts a row against it to confirm.

``up()`` is idempotent (``DROP TABLE IF EXISTS``).

Approach: the shared ``testDatabase`` fixture auto-migrates to the latest
version.  Each test rolls back to the pre-022 state (version 21) via
``rollbackTo(targetVersion=21)``: ``user_data`` exists, re-created empty by
022's ``down()`` during the rollback.  The test then exercises ``up()`` /
``down()`` directly.
"""

import lib.utils as libUtils
from internal.database import Database
from internal.database.migrations import MigrationManager
from internal.database.migrations.versions.migration_022_drop_user_data import Migration022DropUserData
from lib.db.providers.base import BaseSQLProvider

CHAT_ID = 1
USER_ID = 100


async def _tableExists(provider: BaseSQLProvider, tableName: str) -> bool:
    """Check whether a table exists in the default source.

    Args:
        provider: SQL provider for the default data source.
        tableName: Name of the table to check.

    Returns:
        ``True`` if the table exists, ``False`` otherwise.
    """
    row = await provider.executeFetchOne(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = :name",
        {"name": tableName},
    )
    return row is not None


async def _rollbackToPre022(provider: BaseSQLProvider) -> None:
    """Roll back to version 21 to reach the pre-022 state.

    ``rollbackTo(targetVersion=21)`` runs ``down()`` for 022 and every
    migration above it. The per-migration effects are: 025's ``down()``
    (restores the pre-refactor embedding schema), 024's ``down()`` (drops
    the bayes_tokens index -- no-op on data), 023's ``down()`` (reverse key
    rename -- no-op on an empty DB) and 022's ``down()`` (re-creates an
    **empty** ``user_data`` table). After this, ``user_data`` exists
    (empty) and is ready to be dropped by ``up()``.

    Args:
        provider: Writable SQL provider for the default data source.

    Returns:
        None
    """
    rollbackManager = MigrationManager()
    rollbackManager.loadMigrationsFromVersions()
    await rollbackManager.rollbackTo(targetVersion=21, sqlProvider=provider)


async def _insertUserData(provider: BaseSQLProvider, chatId: int, userId: int, key: str, data: str) -> None:
    """Insert a single ``user_data`` row.

    Args:
        provider: Writable SQL provider for the default data source.
        chatId: Chat id to associate the data with.
        userId: User id to associate the data with.
        key: Setting key string.
        data: Setting value string.

    Returns:
        None
    """
    now = libUtils.now()
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


async def test_up_dropsUserDataTable(testDatabase: Database) -> None:
    """``up()`` drops the ``user_data`` table.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre022(provider)

    # user_data exists (re-created empty by 022's down() during rollback).
    assert await _tableExists(provider, "user_data"), "user_data must exist before up()"

    # Seed a row to make the drop meaningful.
    await _insertUserData(provider, CHAT_ID, USER_ID, "city", "Berlin")

    migration = Migration022DropUserData()
    await migration.up(provider)

    assert not await _tableExists(provider, "user_data"), "up() must drop user_data"


async def test_down_recreatesEmptyUserDataTable(testDatabase: Database) -> None:
    """``down()`` re-creates an empty ``user_data`` table with valid DDL.

    The re-created table must accept INSERTs -- this validates that the DDL
    in ``down()`` is correct and usable (structural reversibility).

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre022(provider)

    migration = Migration022DropUserData()
    await migration.up(provider)
    assert not await _tableExists(provider, "user_data"), "up() must drop user_data first"

    await migration.down(provider)

    # Table exists and is empty.
    assert await _tableExists(provider, "user_data"), "down() must re-create user_data"
    countRow = await provider.executeFetchOne("SELECT COUNT(*) AS cnt FROM user_data")
    assert countRow is not None and int(countRow["cnt"]) == 0, "re-created table must be empty"

    # The re-created DDL must be valid -- INSERT must work against it.
    await _insertUserData(provider, CHAT_ID, USER_ID, "city", "Berlin")
    inserted = await provider.executeFetchOne(
        "SELECT user_id, chat_id, key, data FROM user_data WHERE key = :key",
        {"key": "city"},
    )
    assert inserted is not None, "INSERT into re-created table must succeed"
    assert inserted["data"] == "Berlin"


async def test_up_isIdempotent(testDatabase: Database) -> None:
    """``up()`` is idempotent -- ``DROP TABLE IF EXISTS`` is safe to call twice.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre022(provider)

    migration = Migration022DropUserData()
    await migration.up(provider)
    assert not await _tableExists(provider, "user_data")

    # Second up() must not raise (IF EXISTS guard).
    await migration.up(provider)
    assert not await _tableExists(provider, "user_data"), "second up() must leave user_data dropped"
