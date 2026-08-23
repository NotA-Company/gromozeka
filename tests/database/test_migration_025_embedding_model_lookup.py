"""Tests for ``migration_025_embedding_model_lookup`` (plan §6 — Phase 2).

Verifies the schema refactor that normalises embedding provenance into a
single ``models`` lookup table:

- Step 1 — ``models`` table created with ``UNIQUE (model, dimensions)``.
  The table starts EMPTY — allocation is lazy via
  ``EmbeddingModelsRepository.getOrCreateModelId`` on the first embed
  call (there is no migration-time backfill).
- Step 2 — ``user_memories`` swapped to the ``model_id`` shape. Every
  row gets ``model_id = NULL`` (NULL constant — no LEFT JOIN to
  ``models``); the regen cron re-surfaces them for re-embedding.
- Step 3 — ``chat_messages`` gains ``model_id`` via portable ``ALTER
  TABLE ... ADD COLUMN`` (nullable; no backfill — rows left NULL for
  the embed cron to re-surface).
- Step 4 — ``message_embeddings`` + its index dropped.
- Step 5 — both vec0 families enumerated via ``listTables`` and dropped.

Approach: the shared ``testDatabase`` fixture auto-migrates to the latest
version (so the post-025 schema is in place, empty). Each test rolls back
to the pre-025 state (version 24) via ``rollbackTo(targetVersion=24)``
(runs 025's ``down()``: ``message_embeddings`` re-created empty,
``user_memories`` in its ``embedding_model`` / ``embedding_dimensions``
shape, ``models`` gone), seeds the legacy stores, then exercises ``up()``
/ ``down()`` directly.
"""

import uuid

import lib.utils as libUtils
from internal.database import Database
from internal.database.migrations import MigrationManager
from internal.database.migrations.versions.migration_025_embedding_model_lookup import (
    Migration025EmbeddingModelLookup,
)
from lib.db.providers.base import BaseSQLProvider, ParametrizedQuery

CHAT_ID = 1
USER_ID = 100

# Two distinct (model, dimensions) pairs used across the seeded rows.
MODEL_SMALL = "text-embedding-3-small"
DIMS_SMALL = 384
MODEL_LARGE = "text-embedding-3-large"
DIMS_LARGE = 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


async def _tableNames(provider: BaseSQLProvider) -> set[str]:
    """Return the set of table names visible to ``provider``.

    Args:
        provider: SQL provider for the default data source.

    Returns:
        The set of table names in the default source.
    """
    rows = await provider.executeFetchAll("SELECT name FROM sqlite_master WHERE type='table'")
    return {row["name"] for row in rows}


async def _columnNames(provider: BaseSQLProvider, tableName: str) -> set[str]:
    """Return the set of column names on ``tableName``.

    Args:
        provider: SQL provider for the default data source.
        tableName: Name of the table to introspect.

    Returns:
        Set of column names.
    """
    rows = await provider.executeFetchAll(f"PRAGMA table_info({tableName})")
    return {row["name"] for row in rows}


async def _rollbackToPre025(provider: BaseSQLProvider) -> None:
    """Roll back to version 24 to reach the pre-025 state.

    ``rollbackTo(targetVersion=24)`` runs ``down()`` for 025 and every
    migration above it: 025's ``down()`` re-creates ``message_embeddings``
    empty, swaps ``chat_messages`` and ``user_memories`` back to their
    pre-``model_id`` shapes, and drops ``models``. After this, the schema
    is in the pre-refactor shape and legacy stores can be seeded.

    Args:
        provider: Writable SQL provider for the default data source.

    Returns:
        None
    """
    rollbackManager = MigrationManager()
    rollbackManager.loadMigrationsFromVersions()
    await rollbackManager.rollbackTo(targetVersion=24, sqlProvider=provider)


async def _seedChatMessage(provider: BaseSQLProvider, chatId: int, messageId: str) -> None:
    """Insert a single ``chat_messages`` row in the pre-025 shape (no ``model_id``).

    Args:
        provider: Writable SQL provider for the default data source.
        chatId: Chat id to associate the message with.
        messageId: Message id string.

    Returns:
        None
    """
    now = libUtils.now()
    await provider.execute(
        """
        INSERT INTO chat_messages
            (chat_id, message_id, date, user_id, reply_id, thread_id,
             root_message_id, message_text, message_type, message_category,
             quote_text, media_id, media_group_id, markup, metadata, created_at)
        VALUES
            (:chatId, :messageId, :date, :userId, NULL, 0,
             NULL, :messageText, 'text', 'user',
             NULL, NULL, NULL, '', '', :createdAt)
        """,
        {
            "chatId": chatId,
            "messageId": messageId,
            "date": now,
            "userId": USER_ID,
            "messageText": f"body of {messageId}",
            "createdAt": now,
        },
    )


async def _seedMessageEmbedding(
    provider: BaseSQLProvider,
    chatId: int,
    messageId: str,
    model: str,
    dimensions: int,
) -> None:
    """Insert a single ``message_embeddings`` row (pre-025 BLOB store).

    Args:
        provider: Writable SQL provider for the default data source.
        chatId: Chat id of the embedding's message.
        messageId: Message id of the embedding's message.
        model: Embedding model name string.
        dimensions: Vector dimensionality.

    Returns:
        None
    """
    now = libUtils.now()
    await provider.execute(
        """
        INSERT INTO message_embeddings
            (chat_id, message_id, embedding, dimensions, model, created_at, updated_at)
        VALUES
            (:chatId, :messageId, :embedding, :dimensions, :model, :createdAt, :updatedAt)
        """,
        {
            "chatId": chatId,
            "messageId": messageId,
            # BLOB content is irrelevant for the backfill — we only test
            # the model_id mapping. A 4-byte placeholder is fine.
            "embedding": b"\x00\x00\x00\x00",
            "dimensions": dimensions,
            "model": model,
            "createdAt": now,
            "updatedAt": now,
        },
    )


async def _seedUserMemory(
    provider: BaseSQLProvider,
    chatId: int,
    userId: int,
    *,
    content: str,
    embeddingModel: str | None,
    embeddingDimensions: int | None,
) -> None:
    """Insert a single ``user_memories`` row in the pre-025 shape.

    Uses the post-021 schema (``deleted_at`` column exists, nullable).

    Args:
        provider: Writable SQL provider for the default data source.
        chatId: Chat id to associate the memory with.
        userId: User id to associate the memory with.
        content: Memory content string.
        embeddingModel: Embedding model name (``None`` = never embedded).
        embeddingDimensions: Vector dimensionality (``None`` = never embedded).

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
             1, 'manual', :embeddingModel, :embeddingDimensions,
             :createdAt, :updatedAt)
        """,
        {
            "chatId": chatId,
            "userId": userId,
            "memoryId": uuid.uuid4().hex,
            "content": content,
            "embeddingModel": embeddingModel,
            "embeddingDimensions": embeddingDimensions,
            "createdAt": now,
            "updatedAt": now,
        },
    )


async def _createFakeVecTable(provider: BaseSQLProvider, tableName: str) -> None:
    """Create a fake vec0-named table (regular SQL, not a virtual table).

    The migration's enumerate-and-drop logic in Step 5 matches table
    NAMES via a regex — it does not inspect whether the table is an
    actual vec0 virtual table. A regular table with a vec0-shaped name
    is therefore a faithful stand-in for testing the drop logic.

    Args:
        provider: Writable SQL provider for the default data source.
        tableName: Name of the fake vec0 table to create.

    Returns:
        None
    """
    await provider.execute(f"CREATE TABLE {tableName} (id INTEGER PRIMARY KEY)")


# ---------------------------------------------------------------------------
# Tests — schema correctness (Steps 1, 3, 4, 5)
# ---------------------------------------------------------------------------


async def test_up_createsModelsWithUniqueConstraint(testDatabase: Database) -> None:
    """``up()`` creates the ``models`` table with the expected columns + UNIQUE.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre025(provider)
    assert not await _tableExists(provider, "models"), "precondition: models absent pre-025"

    migration = Migration025EmbeddingModelLookup()
    await migration.up(provider)

    assert await _tableExists(provider, "models"), "up() must create models"
    assert await _columnNames(provider, "models") == {
        "model_id",
        "model",
        "dimensions",
        "created_at",
    }

    # UNIQUE (model, dimensions) — insert the same pair twice must raise.
    now = libUtils.now()
    await provider.execute(
        "INSERT INTO models (model_id, model, dimensions, created_at) " "VALUES (1, :model, :dims, :now)",
        {"model": MODEL_SMALL, "dims": DIMS_SMALL, "now": now},
    )
    secondInsertBlocked = False
    try:
        await provider.execute(
            "INSERT INTO models (model_id, model, dimensions, created_at) " "VALUES (2, :model, :dims, :now)",
            {"model": MODEL_SMALL, "dims": DIMS_SMALL, "now": now},
        )
    except Exception:
        secondInsertBlocked = True
    assert secondInsertBlocked, "UNIQUE (model, dimensions) must block duplicate pairs"


async def test_up_swapsUserMemoriesToModelIdShape(testDatabase: Database) -> None:
    """``up()`` swaps ``user_memories`` to the ``model_id`` shape (drops provenance pair).

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre025(provider)

    migration = Migration025EmbeddingModelLookup()
    await migration.up(provider)

    columns = await _columnNames(provider, "user_memories")
    assert "model_id" in columns, "user_memories must gain model_id"
    assert "embedding_model" not in columns, "embedding_model must be dropped"
    assert "embedding_dimensions" not in columns, "embedding_dimensions must be dropped"

    # Indexes from migration_020 must be present on the swapped table.
    indexRows = await provider.executeFetchAll(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='user_memories'"
    )
    indexNames = {row["name"] for row in indexRows}
    assert "idx_user_memories_chat_user_thread" in indexNames
    assert "idx_user_memories_chat_user_permanent" in indexNames
    assert "idx_user_memories_type" in indexNames


async def test_up_swapsChatMessagesToModelIdShape(testDatabase: Database) -> None:
    """``up()`` swaps ``chat_messages`` to the ``model_id`` shape (appends column).

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre025(provider)

    migration = Migration025EmbeddingModelLookup()
    await migration.up(provider)

    columns = await _columnNames(provider, "chat_messages")
    assert "model_id" in columns, "chat_messages must gain model_id"
    # Pre-existing columns are preserved (spot-check the full set).
    assert columns == {
        "chat_id",
        "message_id",
        "date",
        "user_id",
        "reply_id",
        "thread_id",
        "root_message_id",
        "message_text",
        "message_type",
        "message_category",
        "quote_text",
        "media_id",
        "media_group_id",
        "markup",
        "metadata",
        "created_at",
        "model_id",
    }


async def test_up_dropsMessageEmbeddingsAndIndex(testDatabase: Database) -> None:
    """``up()`` drops the ``message_embeddings`` table and its index from migration_018.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre025(provider)
    assert await _tableExists(provider, "message_embeddings"), "precondition: pre-025 has it"

    migration = Migration025EmbeddingModelLookup()
    await migration.up(provider)

    assert not await _tableExists(provider, "message_embeddings"), "up() must drop message_embeddings"
    indexRow = await provider.executeFetchOne(
        "SELECT name FROM sqlite_master WHERE type='index' AND name = 'idx_message_embeddings_chat_model'"
    )
    assert indexRow is None, "up() must drop idx_message_embeddings_chat_model"


# ---------------------------------------------------------------------------
# Tests — chat_messages.model_id (Step 3, no backfill)
# ---------------------------------------------------------------------------


async def test_up_leavesChatMessagesModelIdNullNoBackfill(testDatabase: Database) -> None:
    """``up()`` leaves ``chat_messages.model_id = NULL`` for every row (ADD COLUMN, no backfill).

    Step 3 uses a portable ``ALTER TABLE chat_messages ADD COLUMN model_id INTEGER``
    rather than the temp-table swap + INSERT...SELECT backfill. The column is
    nullable with no default, so every existing row is left ``model_id = NULL``;
    the backfill cron (``ChatEmbeddingsRepository.getMessagesWithoutEmbeddings``)
    re-surfaces every message for re-embedding under the chat's active model.

    This is intentionally NOT a backfill: the ``message_embeddings`` BLOB
    vectors are dropped in Step 4 and the vec0 tables in Step 5, so a backfilled
    ``model_id`` would mark rows as embedded with no searchable vector — they
    would never be re-surfaced (model_id matches current) and would silently
    lose search. Leaving ``NULL`` forces every message back through the embed
    cron, which is the only correct state when all prior vectors are gone.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre025(provider)

    # m1: embedded with SMALL. m2: embedded with LARGE. m3: no embedding row.
    # The message_embeddings rows exist but are NOT consulted for the
    # chat_messages.model_id column (no backfill — model_id is set to NULL).
    await _seedChatMessage(provider, CHAT_ID, "m1")
    await _seedChatMessage(provider, CHAT_ID, "m2")
    await _seedChatMessage(provider, CHAT_ID, "m3")
    await _seedMessageEmbedding(provider, CHAT_ID, "m1", MODEL_SMALL, DIMS_SMALL)
    await _seedMessageEmbedding(provider, CHAT_ID, "m2", MODEL_LARGE, DIMS_LARGE)

    migration = Migration025EmbeddingModelLookup()
    await migration.up(provider)

    # Every chat_messages row has model_id = NULL (ADD COLUMN, no backfill).
    rows = await provider.executeFetchAll(
        "SELECT message_id AS messageId, model_id AS modelId "
        "FROM chat_messages WHERE chat_id = :chatId ORDER BY message_id",
        {"chatId": CHAT_ID},
    )
    byId = {row["messageId"]: row for row in rows}
    assert byId["m1"]["modelId"] is None, "m1 must be NULL — no backfill (vectors are dropped)"
    assert byId["m2"]["modelId"] is None, "m2 must be NULL — no backfill (vectors are dropped)"
    assert byId["m3"]["modelId"] is None, "m3 must be NULL — never embedded"


# ---------------------------------------------------------------------------
# Tests — idempotent re-entry (CREATE IF NOT EXISTS models)
# ---------------------------------------------------------------------------


async def test_up_succeedsWhenModelsPartiallyPopulated(testDatabase: Database) -> None:
    """A full ``up()`` succeeds when ``models`` already exists with rows.

    Simulates a realistic crash-mid-up scenario: Step 1 ran (``models``
    was created), some rows were inserted into ``models`` by a prior
    runtime allocation, then the process crashed before the remaining
    steps completed. On restart, ``up()`` re-enters from the top —
    Step 1 is a ``CREATE IF NOT EXISTS`` no-op, the remaining steps
    proceed normally (none of them touch ``models``). The full migration
    must succeed and leave the schema in the post-025 shape.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre025(provider)

    await _seedMessageEmbedding(provider, CHAT_ID, "m1", MODEL_SMALL, DIMS_SMALL)
    await _seedMessageEmbedding(provider, CHAT_ID, "m2", MODEL_LARGE, DIMS_LARGE)

    # Manually run Step 1 + insert ONE pair to simulate a partial prior
    # run (``models`` was created and one pair was allocated at runtime
    # before the process crashed mid-migration).
    await provider.batchExecute(
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
    now = libUtils.now()
    await provider.execute(
        "INSERT INTO models (model_id, model, dimensions, created_at) " "VALUES (1, :model, :dims, :now)",
        {"model": MODEL_SMALL, "dims": DIMS_SMALL, "now": now},
    )

    migration = Migration025EmbeddingModelLookup()
    # Full up() must succeed — Step 1's CREATE IF NOT EXISTS is a no-op
    # on the pre-created ``models`` table; the remaining steps proceed
    # normally (none of them insert into ``models``).
    await migration.up(provider)

    # The post-025 schema shape is in place (spot-check).
    assert not await _tableExists(provider, "message_embeddings")
    userColumns = await _columnNames(provider, "user_memories")
    assert "model_id" in userColumns
    assert "embedding_model" not in userColumns


# ---------------------------------------------------------------------------
# Tests — vec0 enumerate-and-drop (Step 5)
# ---------------------------------------------------------------------------


async def test_up_dropsVec0FamiliesMatchingStrictSuffix(testDatabase: Database) -> None:
    """``up()`` drops vec0 tables whose names match the strict ``_<digits>`` suffix.

    Non-matching vec0-shaped names (``_foo`` suffix, or a different
    family prefix) must be left alone.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre025(provider)

    # Two real-shape vec0 names — must be dropped.
    await _createFakeVecTable(provider, "vec_message_embeddings_384")
    await _createFakeVecTable(provider, "vec_user_memories_1024")
    # Decoys — must survive.
    await _createFakeVecTable(provider, "vec_message_embeddings_foo")  # non-numeric suffix
    await _createFakeVecTable(provider, "vec_other_123")  # wrong family prefix

    migration = Migration025EmbeddingModelLookup()
    await migration.up(provider)

    tables = await _tableNames(provider)
    assert "vec_message_embeddings_384" not in tables, "numeric-suffix vec0 table must be dropped"
    assert "vec_user_memories_1024" not in tables, "numeric-suffix vec0 table must be dropped"
    assert "vec_message_embeddings_foo" in tables, "non-numeric suffix must be skipped"
    assert "vec_other_123" in tables, "wrong-family vec0 name must be skipped"


async def test_up_dropsAllShardsInAFamily(testDatabase: Database) -> None:
    """``up()`` drops every dimension-sharded table in both families.

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre025(provider)

    await _createFakeVecTable(provider, "vec_message_embeddings_384")
    await _createFakeVecTable(provider, "vec_message_embeddings_1024")
    await _createFakeVecTable(provider, "vec_message_embeddings_3072")
    await _createFakeVecTable(provider, "vec_user_memories_384")
    await _createFakeVecTable(provider, "vec_user_memories_1024")

    migration = Migration025EmbeddingModelLookup()
    await migration.up(provider)

    tables = await _tableNames(provider)
    for name in (
        "vec_message_embeddings_384",
        "vec_message_embeddings_1024",
        "vec_message_embeddings_3072",
        "vec_user_memories_384",
        "vec_user_memories_1024",
    ):
        assert name not in tables, f"{name} must be dropped"


# ---------------------------------------------------------------------------
# Tests — down() rollback
# ---------------------------------------------------------------------------


async def test_down_restoresPreRefactorSchema(testDatabase: Database) -> None:
    """``down()`` restores the pre-refactor SQL shape (data-lossy for vectors).

    After ``up()`` then ``down()``:

    - ``message_embeddings`` exists again (empty — vectors are lost).
    - ``chat_messages`` has NO ``model_id``.
    - ``user_memories`` has ``embedding_model`` / ``embedding_dimensions`` again.
    - ``models`` does NOT exist.
    - vec0 tables are NOT re-created (documented lossiness).

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre025(provider)

    # Seed before up() so the down() swap has rows to carry back.
    await _seedChatMessage(provider, CHAT_ID, "m1")
    await _seedMessageEmbedding(provider, CHAT_ID, "m1", MODEL_SMALL, DIMS_SMALL)
    await _seedUserMemory(
        provider,
        CHAT_ID,
        USER_ID,
        content="embedded",
        embeddingModel=MODEL_SMALL,
        embeddingDimensions=DIMS_SMALL,
    )

    migration = Migration025EmbeddingModelLookup()
    await migration.up(provider)
    await migration.down(provider)

    # message_embeddings re-created (empty — BLOBs irrecoverable).
    assert await _tableExists(provider, "message_embeddings"), "down() re-creates message_embeddings"
    meCount = await provider.executeFetchOne("SELECT COUNT(*) AS cnt FROM message_embeddings")
    assert meCount is not None and int(meCount["cnt"]) == 0, "re-created table must be empty"

    # chat_messages: model_id gone, pre-existing columns preserved.
    chatColumns = await _columnNames(provider, "chat_messages")
    assert "model_id" not in chatColumns, "down() must drop chat_messages.model_id"
    assert "message_text" in chatColumns, "down() must preserve pre-existing columns"
    # Data survives the swap.
    chatRow = await provider.executeFetchOne(
        "SELECT message_text FROM chat_messages WHERE chat_id = :chatId AND message_id = 'm1'",
        {"chatId": CHAT_ID},
    )
    assert chatRow is not None and chatRow["message_text"] == "body of m1"

    # user_memories: provenance pair restored as NULL, NULL constants
    # (no LEFT JOIN to models — up() no longer populates model_id, so
    # the join would miss every row anyway).
    userColumns = await _columnNames(provider, "user_memories")
    assert "embedding_model" in userColumns, "down() must restore embedding_model"
    assert "embedding_dimensions" in userColumns, "down() must restore embedding_dimensions"
    userRow = await provider.executeFetchOne(
        "SELECT content, embedding_model, embedding_dimensions FROM user_memories "
        "WHERE chat_id = :chatId AND user_id = :userId",
        {"chatId": CHAT_ID, "userId": USER_ID},
    )
    assert userRow is not None, "down() must preserve user_memories rows"
    assert userRow["content"] == "embedded"
    assert (
        userRow["embedding_model"] is None
    ), "embedding_model must be NULL — down() sets NULL, NULL unconditionally (see module docstring)"
    assert userRow["embedding_dimensions"] is None

    # models dropped.
    assert not await _tableExists(provider, "models"), "down() must drop models"


async def test_down_doesNotRecreateVec0Tables(testDatabase: Database) -> None:
    """``down()`` does NOT re-create vec0 families (documented lossiness).

    Args:
        testDatabase: Fresh in-memory database (all migrations applied).

    Returns:
        None
    """
    provider = await testDatabase.manager.getProvider(chatId=CHAT_ID, readonly=False)
    await _rollbackToPre025(provider)
    await _createFakeVecTable(provider, "vec_message_embeddings_384")
    await _createFakeVecTable(provider, "vec_user_memories_1024")

    migration = Migration025EmbeddingModelLookup()
    await migration.up(provider)
    await migration.down(provider)

    tables = await _tableNames(provider)
    assert (
        "vec_message_embeddings_384" not in tables
    ), "down() must NOT re-create vec0 tables (lazily created at runtime)"
    assert "vec_user_memories_1024" not in tables
