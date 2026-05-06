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
