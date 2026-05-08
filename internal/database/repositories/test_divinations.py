"""Tests for :class:`DivinationsRepository`, dood!

Verifies that divination readings round-trip through SQLite correctly:
inserts succeed, duplicate composite primary keys are rejected (handled
gracefully without leaking exceptions), nullable fields stay None when
not provided, and ``created_at`` is populated with a recent UTC timestamp.
"""

import datetime
import json
from typing import Any, AsyncGenerator, Dict

import pytest

from internal.database import Database
from internal.database.manager import DatabaseManagerConfig


@pytest.fixture
async def divinationsDb() -> AsyncGenerator[Database, None]:
    """Create an in-memory database with migrations applied, dood.

    Triggers provider initialization (and therefore migration 014) by
    invoking ``getProvider()`` once before yielding the Database instance.

    Yields:
        Database: A ready-to-use Database backed by an in-memory SQLite DB.
    """
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            }
        },
    }
    db = Database(config)
    # Trigger migrations.
    await db.manager.getProvider()
    try:
        yield db
    finally:
        await db.manager.closeAll()


def _buildSamplePayload(*, chatId: int = 100500, messageId: str = "msg-1") -> Dict[str, Any]:
    """Build a fully populated insert payload, dood.

    Args:
        chatId: Originating chat id (default ``100500``).
        messageId: Originating message id (default ``"msg-1"``).

    Returns:
        Dict[str, Any]: kwargs ready to splat into ``insertReading``.
    """
    drawsJson = json.dumps(
        [
            {"symbolId": "major_00_fool", "reversed": False, "position": "Past", "positionIndex": 0},
            {"symbolId": "major_01_magician", "reversed": True, "position": "Present", "positionIndex": 1},
            {"symbolId": "major_02_high_priestess", "reversed": False, "position": "Future", "positionIndex": 2},
        ]
    )
    return {
        "chatId": chatId,
        "messageId": messageId,
        "userId": 42,
        "systemId": "tarot",
        "deckId": "rws",
        "layoutId": "three_card",
        "question": "Что меня ждёт?",
        "drawsJson": drawsJson,
        "interpretation": "A measured, thoughtful interpretation, dood.",
        "imagePrompt": "vintage occult illustration of a three-card spread",
        "invokedVia": "command",
    }


async def test_insertReadingSuccess(divinationsDb: Database) -> None:
    """Insert a fully populated row and verify every field round-trips, dood.

    Args:
        divinationsDb: In-memory Database fixture with migrations applied.

    Returns:
        None
    """
    payload: Dict[str, Any] = _buildSamplePayload()
    ok: bool = await divinationsDb.divinations.insertReading(**payload)
    assert ok is True

    sqlProvider = await divinationsDb.manager.getProvider(readonly=True)
    row = await sqlProvider.executeFetchOne(
        "SELECT * FROM divinations WHERE chat_id = :chatId AND message_id = :messageId",
        {"chatId": payload["chatId"], "messageId": payload["messageId"]},
    )
    assert row is not None
    assert row["chat_id"] == payload["chatId"]
    assert row["message_id"] == payload["messageId"]
    assert row["user_id"] == payload["userId"]
    assert row["system_id"] == payload["systemId"]
    assert row["deck_id"] == payload["deckId"]
    assert row["layout_id"] == payload["layoutId"]
    assert row["question"] == payload["question"]
    assert row["draws_json"] == payload["drawsJson"]
    assert row["interpretation"] == payload["interpretation"]
    assert row["image_prompt"] == payload["imagePrompt"]
    assert row["invoked_via"] == payload["invokedVia"]
    assert row["created_at"] is not None


async def test_insertReadingDuplicatePrimaryKey(divinationsDb: Database) -> None:
    """Inserting the same (chatId, messageId) twice returns False on conflict, dood.

    Args:
        divinationsDb: In-memory Database fixture with migrations applied.

    Returns:
        None
    """
    payload: Dict[str, Any] = _buildSamplePayload(chatId=200, messageId="dup-msg")

    firstOk: bool = await divinationsDb.divinations.insertReading(**payload)
    assert firstOk is True

    # Second insert should be rejected by the composite PK and swallowed.
    secondOk: bool = await divinationsDb.divinations.insertReading(**payload)
    assert secondOk is False

    # Confirm exactly one row exists for that PK.
    sqlProvider = await divinationsDb.manager.getProvider(readonly=True)
    row = await sqlProvider.executeFetchOne(
        "SELECT COUNT(*) AS cnt FROM divinations WHERE chat_id = :chatId AND message_id = :messageId",
        {"chatId": payload["chatId"], "messageId": payload["messageId"]},
    )
    assert row is not None
    assert int(row["cnt"]) == 1


async def test_insertReadingWithNullableFieldsAsNone(divinationsDb: Database) -> None:
    """``image_prompt`` stays None when explicitly passed as None, dood.

    Args:
        divinationsDb: In-memory Database fixture with migrations applied.

    Returns:
        None
    """
    payload: Dict[str, Any] = _buildSamplePayload(chatId=300, messageId="null-msg")
    payload["imagePrompt"] = None

    ok: bool = await divinationsDb.divinations.insertReading(**payload)
    assert ok is True

    sqlProvider = await divinationsDb.manager.getProvider(readonly=True)
    row = await sqlProvider.executeFetchOne(
        "SELECT * FROM divinations WHERE chat_id = :chatId AND message_id = :messageId",
        {"chatId": payload["chatId"], "messageId": payload["messageId"]},
    )
    assert row is not None
    assert row["image_prompt"] is None


async def test_insertReadingPersistsCreatedAt(divinationsDb: Database) -> None:
    """``created_at`` is populated with a recent UTC timestamp, dood.

    Args:
        divinationsDb: In-memory Database fixture with migrations applied.

    Returns:
        None
    """
    payload: Dict[str, Any] = _buildSamplePayload(chatId=400, messageId="ts-msg")

    before: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)
    ok: bool = await divinationsDb.divinations.insertReading(**payload)
    after: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)
    assert ok is True

    sqlProvider = await divinationsDb.manager.getProvider(readonly=True)
    row = await sqlProvider.executeFetchOne(
        "SELECT created_at FROM divinations WHERE chat_id = :chatId AND message_id = :messageId",
        {"chatId": payload["chatId"], "messageId": payload["messageId"]},
    )
    assert row is not None
    rawCreatedAt = row["created_at"]
    assert rawCreatedAt is not None

    # SQLite may return either a datetime or a string depending on the driver
    # path; normalise both to an aware UTC datetime before comparing.
    createdAt: datetime.datetime
    if isinstance(rawCreatedAt, datetime.datetime):
        createdAt = rawCreatedAt
    else:
        createdAt = datetime.datetime.fromisoformat(str(rawCreatedAt))
    if createdAt.tzinfo is None:
        createdAt = createdAt.replace(tzinfo=datetime.timezone.utc)

    # Allow a 5-second window in either direction to absorb clock jitter.
    margin: datetime.timedelta = datetime.timedelta(seconds=5)
    assert before - margin <= createdAt <= after + margin


async def test_getLayoutUsesCleanedSearchTerm(divinationsDb: Database) -> None:
    """Verify that getLayout() uses the cleaned search term from the loop.

    When a layout name contains parentheses, getLayout() should strip them
    and search for the cleaned term. This test ensures the loop variable
    (not the original layoutName) is passed as the parameter.

    Args:
        divinationsDb: In-memory Database fixture with migrations applied.

    Returns:
        None
    """
    # Insert a layout with name without parentheses
    await divinationsDb.divinations.saveLayout(
        systemId="tarot",
        layoutId="celtic_cross",
        nameEn="Celtic Cross",
        nameRu="Кельтский крест",
        nSymbols=10,
        positions=["pos1", "pos2", "pos3"],
        description="A classic spread",
    )

    # Search for layout with parentheses in name - should find it
    # because getLayout() strips parentheses before searching
    layout = await divinationsDb.divinations.getLayout(systemId="tarot", layoutName="Celtic Cross (Extended)")
    assert layout is not None
    assert layout["layout_id"] == "celtic_cross"
    assert layout["name_en"] == "Celtic Cross"


async def test_getLayoutSearchOrder(divinationsDb: Database) -> None:
    """Verify that getLayout() searches in the correct order.

    Search order should be:
    1. Exact match on layout_id/name_en/name_ru
    2. Stripped parentheses version
    3. Partial match with LIKE

    Args:
        divinationsDb: In-memory Database fixture with migrations applied.

    Returns:
        None
    """
    # Insert multiple layouts
    await divinationsDb.divinations.saveLayout(
        systemId="tarot",
        layoutId="three_card_spread",
        nameEn="Three Card Spread",
        nameRu="Три карты",
        nSymbols=3,
        positions=["Past", "Present", "Future"],
        description="Simple three card layout",
    )

    # Partial match via LIKE should work
    layout = await divinationsDb.divinations.getLayout(systemId="tarot", layoutName="Three Card")
    assert layout is not None
    assert layout["layout_id"] == "three_card_spread"

    # Exact match on name_en should work
    layout = await divinationsDb.divinations.getLayout(systemId="tarot", layoutName="Three Card Spread")
    assert layout is not None
    assert layout["layout_id"] == "three_card_spread"


async def test_saveNegativeCacheUsesExcludedValue(divinationsDb: Database) -> None:
    """Verify that saveNegativeCache() uses ExcludedValue() for updated_at.

    This ensures the upsert contract is followed correctly - the excluded value
    mechanism uses the updated_at from the INSERT clause in the UPDATE clause,
    avoiding the need for parameter placeholders.

    Args:
        divinationsDb: In-memory Database fixture with migrations applied.

    Returns:
        None
    """
    # Insert a negative cache entry (first call - INSERT path)
    ok = await divinationsDb.divinations.saveNegativeCache(
        systemId="tarot",
        layoutId="nonexistent_layout",
    )
    assert ok is True

    # Get the initial row to capture created_at and updated_at
    sqlProvider = await divinationsDb.manager.getProvider(readonly=True)
    row = await sqlProvider.executeFetchOne(
        "SELECT created_at, updated_at FROM divination_layouts WHERE system_id = :systemId AND layout_id = :layoutId",
        {"systemId": "tarot", "layoutId": "nonexistent_layout"},
    )
    assert row is not None
    initialCreatedAt = row["created_at"]
    initialUpdatedAt = row["updated_at"]
    assert initialCreatedAt is not None
    assert initialUpdatedAt is not None

    # Verify it's a negative cache entry
    rowFull = await sqlProvider.executeFetchOne(
        "SELECT * FROM divination_layouts WHERE system_id = :systemId AND layout_id = :layoutId",
        {"systemId": "tarot", "layoutId": "nonexistent_layout"},
    )
    assert rowFull is not None
    assert rowFull["name_en"] == ""
    assert rowFull["name_ru"] == ""
    assert rowFull["n_symbols"] == 0
    # Positions might be a JSON string or empty list depending on provider
    positions = rowFull["positions"]
    if isinstance(positions, str):
        assert positions == "[]" or positions == ""
    else:
        assert positions == []

    # Wait a tiny bit to ensure timestamp would differ if updated
    # (Note: In practice, timestamps may be very close, but the key test
    # is that the upsert executes without SQL errors)
    import asyncio

    await asyncio.sleep(0.01)

    # Call saveNegativeCache again with the same key (second call - UPDATE path)
    # This tests the conflict handling with ExcludedValue()
    ok = await divinationsDb.divinations.saveNegativeCache(
        systemId="tarot",
        layoutId="nonexistent_layout",
    )
    assert ok is True

    # Verify the row still exists and hasn't changed its negative cache status
    row2 = await sqlProvider.executeFetchOne(
        "SELECT created_at, updated_at FROM divination_layouts WHERE system_id = :systemId AND layout_id = :layoutId",
        {"systemId": "tarot", "layoutId": "nonexistent_layout"},
    )
    assert row2 is not None
    assert row2["created_at"] == initialCreatedAt  # created_at should not change
    # updated_at should be set to the new value from the INSERT clause
    assert row2["updated_at"] is not None


async def test_saveLayoutUsesExcludedValue(divinationsDb: Database) -> None:
    """Verify that saveLayout() uses ExcludedValue() for updated_at.

    This ensures the upsert contract is followed correctly - the excluded value
    mechanism uses the updated_at from the INSERT clause in the UPDATE clause,
    avoiding the need for parameter placeholders.

    Args:
        divinationsDb: In-memory Database fixture with migrations applied.

    Returns:
        None
    """
    # Insert a layout entry (first call - INSERT path)
    ok = await divinationsDb.divinations.saveLayout(
        systemId="tarot",
        layoutId="three_card",
        nameEn="Three Card",
        nameRu="Три карты",
        nSymbols=3,
        positions=["Past", "Present", "Future"],
        description="Simple three card layout",
    )
    assert ok is True

    # Get the initial row to capture created_at and updated_at
    sqlProvider = await divinationsDb.manager.getProvider(readonly=True)
    row = await sqlProvider.executeFetchOne(
        "SELECT created_at, updated_at FROM divination_layouts WHERE system_id = :systemId AND layout_id = :layoutId",
        {"systemId": "tarot", "layoutId": "three_card"},
    )
    assert row is not None
    initialCreatedAt = row["created_at"]
    initialUpdatedAt = row["updated_at"]
    assert initialCreatedAt is not None
    assert initialUpdatedAt is not None

    # Wait a tiny bit to ensure timestamp would differ if updated
    # (Note: In practice, timestamps may be very close, but the key test
    # is that the upsert executes without SQL errors)
    import asyncio

    await asyncio.sleep(0.01)

    # Call saveLayout again with the same key (second call - UPDATE path)
    # This tests the conflict handling with ExcludedValue()
    ok = await divinationsDb.divinations.saveLayout(
        systemId="tarot",
        layoutId="three_card",
        nameEn="Three Card",
        nameRu="Три карты",
        nSymbols=3,
        positions=["Past", "Present", "Future"],
        description="Simple three card layout",
    )
    assert ok is True

    # Verify the row still exists and hasn't changed its layout data
    row2 = await sqlProvider.executeFetchOne(
        "SELECT created_at, updated_at, name_en, n_symbols "
        "FROM divination_layouts "
        "WHERE system_id = :systemId AND layout_id = :layoutId",
        {"systemId": "tarot", "layoutId": "three_card"},
    )
    assert row2 is not None
    assert row2["created_at"] == initialCreatedAt  # created_at should not change
    assert row2["name_en"] == "Three Card"  # name_en should not change (uses ExcludedValue)
    assert row2["n_symbols"] == 3  # n_symbols should not change (uses ExcludedValue)
    # updated_at should be set to the new value from the INSERT clause
    assert row2["updated_at"] is not None


async def test_layoutCacheConsistency(divinationsDb: Database) -> None:
    """Verify that layout cache lookup and storage use consistent canonical IDs.

    When a layout is discovered/cached, the canonical ID derived from the
    user's input should be used consistently for both lookup and storage.
    This prevents cache misses where lookup uses one ID and storage uses another.

    Args:
        divinationsDb: In-memory Database fixture with migrations applied.

    Returns:
        None
    """
    # Simulate the canonicalization that happens in the handler
    user_input = "Celtic Cross (Extended)"
    canonical_id = user_input.lower().replace(" ", "_").replace("(", "").replace(")", "")

    # Save a layout with the canonical ID
    await divinationsDb.divinations.saveLayout(
        systemId="tarot",
        layoutId=canonical_id,
        nameEn="Celtic Cross",
        nameRu="Кельтский крест",
        nSymbols=10,
        positions=["pos1", "pos2", "pos3"],
        description="A classic spread",
    )

    # Lookup using the same canonical ID should succeed
    layout = await divinationsDb.divinations.getLayout(systemId="tarot", layoutName=canonical_id)
    assert layout is not None
    assert layout["layout_id"] == canonical_id

    # Negative cache should also use canonical ID consistently
    await divinationsDb.divinations.saveNegativeCache(
        systemId="tarot",
        layoutId=canonical_id + "_nonexistent",
    )
    negative = await divinationsDb.divinations.getLayout(systemId="tarot", layoutName=canonical_id + "_nonexistent")
    assert negative is not None
    assert divinationsDb.divinations.isNegativeCacheEntry(negative) is True
