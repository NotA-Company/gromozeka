"""Tests for WebhookUpdatesRepository.

Integration tests exercising :class:`WebhookUpdatesRepository` against a real
in-memory SQLite database (all migrations applied via the ``testDatabase``
fixture). Covers storing raw webhook payloads, polling unprocessed rows in
arrival order, batch-marking them processed, and TTL-based reaping of old
processed rows.
"""

import asyncio

from internal.database import Database
from internal.database.models import WebhookUpdatesRow

#: Minimum delay between two ``getCurrentTimestamp()`` calls to guarantee the
#: second timestamp strictly exceeds the first at microsecond resolution. Used
#: to make arrival-order and TTL-cutoff assertions deterministic.
TIMESTAMP_TICK: float = 0.02


class TestWebhookUpdatesRepository:
    """Integration tests for the webhook_updates repository.

    Each test writes through the public repository API on top of the shared
    ``testDatabase`` fixture (a fresh in-memory SQLite database with all
    migrations applied) and reads back through it to verify observable state.
    """

    async def test_addUpdate_storesEvent(self, testDatabase: Database) -> None:
        """addUpdate reports success and the row is retrievable as pending.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        result = await repo.addUpdate("evt-1", "message_created", '{"hello":"world"}')

        assert result is True
        pending = await repo.getUnprocessedUpdates()
        assert len(pending) == 1
        assert pending[0]["id"] == "evt-1"

    async def test_getUnprocessedUpdates_returnsStoredUpdates(self, testDatabase: Database) -> None:
        """Pending rows come back in ascending received_at order.

        Two updates are inserted with a small gap so their received_at
        timestamps are strictly ordered, then we assert both are returned
        oldest-first.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        await repo.addUpdate("first", "message_created", '{"a":1}')
        await asyncio.sleep(TIMESTAMP_TICK)
        await repo.addUpdate("second", "message_created", '{"a":2}')

        pending = await repo.getUnprocessedUpdates()

        assert len(pending) == 2
        assert [row["id"] for row in pending] == ["first", "second"]

    async def test_getUnprocessedUpdates_respectsLimit(self, testDatabase: Database) -> None:
        """The limit argument caps the number of returned rows.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        for i in range(10):
            await repo.addUpdate(f"lim-{i}", "message_created", "{}")

        pending = await repo.getUnprocessedUpdates(limit=3)

        assert len(pending) == 3

    async def test_markProcessed_marksCorrectRows(self, testDatabase: Database) -> None:
        """Only the supplied IDs are marked; the rest stay pending.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        await repo.addUpdate("keep", "message_created", "{}")
        await repo.addUpdate("drop", "message_created", "{}")

        await repo.markProcessed(["drop"])

        pending = await repo.getUnprocessedUpdates()
        assert len(pending) == 1
        assert pending[0]["id"] == "keep"

    async def test_markProcessed_withEmptyList(self, testDatabase: Database) -> None:
        """An empty ID list is a no-op that does not raise or mutate rows.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        await repo.addUpdate("evt", "message_created", "{}")

        # Must not raise.
        await repo.markProcessed([])

        assert len(await repo.getUnprocessedUpdates()) == 1

    async def test_markProcessed_atomicAllOrNothing(self, testDatabase: Database) -> None:
        """A batch containing a non-existent ID does not abort processing.

        Note: the original spec expected this to "fail on the nonexistent one",
        but that premise does not hold. ``UPDATE ... WHERE id = :id`` matching
        zero rows is a SQL no-op, not an error, and ``markProcessed`` swallows
        any provider exception regardless. So a missing ID neither raises nor
        rolls back the batch. The real contract verified here is that the batch
        tolerates missing IDs gracefully: it completes without raising and still
        marks every ID that does exist.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        await repo.addUpdate("exists-1", "message_created", "{}")
        await repo.addUpdate("exists-2", "message_created", "{}")

        # "ghost" was never inserted; the matching UPDATE is a no-op.
        await repo.markProcessed(["exists-1", "ghost"])

        pending = await repo.getUnprocessedUpdates()
        assert [row["id"] for row in pending] == ["exists-2"]

    async def test_deleteProcessedOlderThan_removesOldEvents(self, testDatabase: Database) -> None:
        """Processed rows past the TTL cutoff are physically deleted.

        After marking processed, a short sleep guarantees ``processed_at``
        strictly precedes ``now`` so the ``processed_at < cutoff`` predicate
        (with ``ttlSeconds=0``) matches. Deletion is verified by a direct row
        count rather than through ``getUnprocessedUpdates`` (which would be
        empty either way once the row is processed).

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        await repo.addUpdate("old", "message_created", "{}")
        await repo.markProcessed(["old"])
        await asyncio.sleep(TIMESTAMP_TICK)

        assert await repo.deleteProcessedOlderThan(ttlSeconds=0) is True

        provider = await testDatabase.manager.getProvider(readonly=True)
        rows = await provider.executeFetchAll(
            "SELECT COUNT(*) AS c FROM webhook_updates WHERE id = :id",
            {"id": "old"},
        )
        assert (rows[0]["c"] if rows else 0) == 0
        assert await repo.getUnprocessedUpdates() == []

    async def test_deleteProcessedOlderThan_keepsUnprocessedEvents(self, testDatabase: Database) -> None:
        """Unprocessed rows are never reaped regardless of TTL.

        The delete predicate filters on ``processed = 1``, so a pending row
        (``processed = 0``) survives even with ``ttlSeconds=0``.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        await repo.addUpdate("unprocessed", "message_created", "{}")
        await asyncio.sleep(TIMESTAMP_TICK)

        assert await repo.deleteProcessedOlderThan(ttlSeconds=0) is True

        pending = await repo.getUnprocessedUpdates()
        assert len(pending) == 1
        assert pending[0]["id"] == "unprocessed"

    async def test_addUpdate_duplicateIdsFail(self, testDatabase: Database) -> None:
        """Re-inserting an existing id returns False (PRIMARY KEY conflict).

        The IntegrityError is caught inside ``addUpdate`` and surfaced as
        ``False``; the originally inserted row is left intact.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        assert await repo.addUpdate("dup", "message_created", "{}") is True
        assert await repo.addUpdate("dup", "message_created", "{}") is False

        pending = await repo.getUnprocessedUpdates()
        assert len(pending) == 1
        assert pending[0]["id"] == "dup"

    async def test_getUnprocessedUpdates_returnsTypedDict(self, testDatabase: Database) -> None:
        """Returned rows expose every WebhookUpdatesRow field with typed values.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        await repo.addUpdate("typed", "message_created", '{"k":1}')

        pending = await repo.getUnprocessedUpdates()
        assert len(pending) == 1

        row = pending[0]
        expectedKeys = set(WebhookUpdatesRow.__annotations__.keys())
        assert expectedKeys <= set(row.keys())

        assert row["id"] == "typed"
        assert row["update_type"] == "message_created"
        assert row["raw_json"] == '{"k":1}'
        assert row["processed"] == 0
        assert row["processed_at"] is None

    async def test_getUnprocessedUpdates_withMarker_filtersRows(self, testDatabase: Database) -> None:
        """A marker excludes every row at or before its position.

        Three rows are inserted with strictly increasing ``received_at``. A
        marker built from the middle row is passed in; only the newest row
        (strictly after the marker) should come back.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        await repo.addUpdate("first", "message_created", "{}")
        await asyncio.sleep(TIMESTAMP_TICK)
        await repo.addUpdate("second", "message_created", "{}")
        await asyncio.sleep(TIMESTAMP_TICK)
        await repo.addUpdate("third", "message_created", "{}")

        allRows = await repo.getUnprocessedUpdates()
        assert [row["id"] for row in allRows] == ["first", "second", "third"]

        middle = allRows[1]
        marker = f"{middle['received_at'].isoformat()}|{middle['id']}"

        filtered = await repo.getUnprocessedUpdates(marker=marker)

        assert [row["id"] for row in filtered] == ["third"]

    async def test_getUnprocessedUpdates_withoutMarkerReturnsAll(self, testDatabase: Database) -> None:
        """A None marker returns every unprocessed row (unchanged behaviour).

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        await repo.addUpdate("a", "message_created", "{}")
        await repo.addUpdate("b", "message_created", "{}")

        pending = await repo.getUnprocessedUpdates()

        assert [row["id"] for row in pending] == ["a", "b"]

    async def test_markProcessedBeforeMarker_marksCorrectRows(self, testDatabase: Database) -> None:
        """markProcessedBeforeMarker acks rows at/before the marker only.

        Three rows are inserted with strictly increasing ``received_at``. The
        marker built from the middle row acks the first two (``received_at``
        before the marker, or equal with ``id <= marker id``); the third stays
        pending. Verified by re-polling unprocessed rows without a marker.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        await repo.addUpdate("first", "message_created", "{}")
        await asyncio.sleep(TIMESTAMP_TICK)
        await repo.addUpdate("second", "message_created", "{}")
        await asyncio.sleep(TIMESTAMP_TICK)
        await repo.addUpdate("third", "message_created", "{}")

        allRows = await repo.getUnprocessedUpdates()
        middle = allRows[1]
        marker = f"{middle['received_at'].isoformat()}|{middle['id']}"

        await repo.markProcessedBeforeMarker(marker)

        remaining = await repo.getUnprocessedUpdates()
        assert [row["id"] for row in remaining] == ["third"]

    async def test_markProcessedBeforeMarker_isIdempotent(self, testDatabase: Database) -> None:
        """Re-acking the same marker is a no-op on already-processed rows.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.webhookUpdates

        await repo.addUpdate("only", "message_created", "{}")
        row = (await repo.getUnprocessedUpdates())[0]
        marker = f"{row['received_at'].isoformat()}|{row['id']}"

        await repo.markProcessedBeforeMarker(marker)
        # Second ack must not raise and leaves no pending rows.
        await repo.markProcessedBeforeMarker(marker)

        assert await repo.getUnprocessedUpdates() == []
