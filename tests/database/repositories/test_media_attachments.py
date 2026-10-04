"""Tests for MediaAttachmentsRepository.

Integration tests exercising :class:`MediaAttachmentsRepository` against a
real in-memory SQLite database (all migrations applied via the
``testDatabase`` fixture).  Covers basic add / read operations.
"""

import datetime
from typing import Optional
from unittest.mock import AsyncMock, patch

from internal.database import Database
from internal.database.models import MediaStatus
from internal.models import MessageType
from lib.db.manager import DatabaseManager


class TestMediaAttachmentsRepository:
    """Integration tests for the media_attachments repository.

    Each test writes through the public repository API on top of the shared
    ``testDatabase`` fixture (a fresh in-memory SQLite database with all
    migrations applied) and reads back through it to verify observable state.
    """

    async def testAddMediaAttachment_returnsRowViaGet(self, testDatabase: Database) -> None:
        """Add and get round-trips correctly.

        Regression guard: existing addMediaAttachment + getMediaAttachment
        round-trip correctly.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments

        ok = await repo.addMediaAttachment(
            fileUniqueId="file-005",
            fileId="fid-005",
            fileSize=1024,
            mediaType=MessageType.IMAGE,
            mimeType="image/png",
            status=MediaStatus.NEW,
            description="a photo",
        )

        assert ok is True

        row = await repo.getMediaAttachment("file-005")
        assert row is not None
        assert row["file_unique_id"] == "file-005"
        assert row["file_id"] == "fid-005"
        assert row["file_size"] == 1024
        assert row["media_type"] == MessageType.IMAGE
        assert row["status"] == MediaStatus.NEW
        assert row["description"] == "a photo"

    ###
    # Vision TTL-GC support (Phase A)
    ###

    async def _seedAttachmentWithVisionUrl(
        self, testDatabase: Database, mediaId: str, visionUrl: Optional[str]
    ) -> None:
        """Seed one media row (with an optional vision_url) through the repo API.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
            mediaId: Media attachment unique identifier to seed.
            visionUrl: Vision storage key to set, or None to leave it NULL.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments
        assert await repo.addMediaAttachment(fileUniqueId=mediaId, fileId=f"fid-{mediaId}") is True
        if visionUrl is not None:
            assert await repo.updateMediaAttachment(mediaId, visionUrl=visionUrl) is True

    async def _backdateUpdatedAt(self, testDatabase: Database, mediaId: str, ts: datetime.datetime) -> None:
        """Backdate a row's ``updated_at`` via the canonical raw-SQL test pattern.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
            mediaId: Media attachment unique identifier to backdate.
            ts: Timestamp (aware UTC) to write.

        Returns:
            None
        """
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "UPDATE media_attachments SET updated_at = :ts WHERE file_unique_id = :id",
            {"ts": ts.isoformat(), "id": mediaId},
        )

    async def testGetExpiredVisionAttachments_returnsOnlyOldRowsWithVisionUrl(self, testDatabase: Database) -> None:
        """Expired query returns exactly old rows that still reference a vision object.

        Seeds three rows — an old row with a vision_url (must be returned),
        a fresh row with a vision_url (still within the retention window),
        and an old row with a NULL vision_url (nothing to collect). Only
        the first matches ``vision_url IS NOT NULL AND updated_at < cutoff``.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments
        await self._seedAttachmentWithVisionUrl(testDatabase, "old-vision", "abcd1234.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "fresh-vision", "efgh5678.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "old-null", None)

        oldTs = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        await self._backdateUpdatedAt(testDatabase, "old-vision", oldTs)
        await self._backdateUpdatedAt(testDatabase, "old-null", oldTs)

        cutoff = datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc)
        expired = await repo.getExpiredVisionAttachments(cutoff)

        assert len(expired) == 1
        assert expired[0]["file_unique_id"] == "old-vision"
        assert expired[0]["vision_url"] == "abcd1234.jpeg"

    async def testGetLiveVisionUrls_returnsOnlyFreshKeys(self, testDatabase: Database) -> None:
        """Live-vision-keys query returns exactly the keys referenced by fresh rows.

        Same seeds and cutoff as the expired-query test: only the fresh row
        counts as live, so exactly its content-addressed key is returned
        (the dedup guard for the TTL-GC delete decision).

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments
        await self._seedAttachmentWithVisionUrl(testDatabase, "old-vision", "abcd1234.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "fresh-vision", "efgh5678.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "old-null", None)

        oldTs = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        await self._backdateUpdatedAt(testDatabase, "old-vision", oldTs)
        await self._backdateUpdatedAt(testDatabase, "old-null", oldTs)

        cutoff = datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc)
        liveUrls = await repo.getLiveVisionUrls(cutoff)

        assert isinstance(liveUrls, set)
        assert all(isinstance(url, str) for url in liveUrls)
        assert liveUrls == {"efgh5678.jpeg"}

    async def testGetLiveVisionUrls_emptySetWhenNoLiveRows(self, testDatabase: Database) -> None:
        """Live-vision-keys query returns an empty set when no row is live.

        A single fully-expired row (old + vision_url) leaves nothing live
        at a cutoff after its ``updated_at``.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments
        await self._seedAttachmentWithVisionUrl(testDatabase, "old-vision", "abcd1234.jpeg")

        oldTs = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        await self._backdateUpdatedAt(testDatabase, "old-vision", oldTs)

        cutoff = datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc)
        assert await repo.getLiveVisionUrls(cutoff) == set()

    async def testGetLiveVisionUrls_dbFailure_returnsNone(self, testDatabase: Database) -> None:
        """A failed live-vision-keys query returns None, NOT an empty set.

        The repository's empty-sentinel-on-error convention is deliberately
        broken for this one method (the sanctioned exception): its only
        caller is a DESTRUCTIVE garbage collector that deletes every stored
        file absent from the returned set, so a query failure must be
        observable as ``None`` — mistaking it for "genuinely nothing live"
        would authorize deleting files live rows may still reference.

        The failure is simulated the canonical way for ``__slots__``
        repositories: a CLASS-level patch on ``DatabaseManager.getProvider``
        (instance patching is impossible with ``__slots__``); a raising
        ``AsyncMock`` stands in for provider acquisition.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments
        await self._seedAttachmentWithVisionUrl(testDatabase, "live-row", "abcd1234.jpeg")

        with patch.object(
            DatabaseManager, "getProvider", new_callable=AsyncMock, side_effect=Exception("provider unavailable")
        ):
            liveUrls = await repo.getLiveVisionUrls(datetime.datetime(2021, 1, 1, tzinfo=datetime.timezone.utc))

        assert liveUrls is None

    async def testClearVisionUrl_nullsUrlAndRefreshesUpdatedAt(self, testDatabase: Database) -> None:
        """clearVisionUrl nulls vision_url and refreshes updated_at in one UPDATE.

        The row is backdated first so the refresh is observable: after the
        clear, ``vision_url`` is NULL and ``updated_at`` is strictly newer
        than the backdated value (the ride-along refresh every update in
        this repository performs).

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments
        await self._seedAttachmentWithVisionUrl(testDatabase, "to-clear", "abcd1234.jpeg")

        oldTs = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        await self._backdateUpdatedAt(testDatabase, "to-clear", oldTs)

        assert await repo.clearVisionUrl("to-clear") is True

        row = await repo.getMediaAttachment("to-clear")
        assert row is not None
        assert row["vision_url"] is None
        assert isinstance(row["updated_at"], datetime.datetime)
        assert row["updated_at"] > oldTs

    async def testClearVisionUrl_missingRowFollowsUpdateSemantics(self, testDatabase: Database) -> None:
        """clearVisionUrl on a missing mediaId matches updateMediaAttachment semantics.

        An UPDATE matching zero rows is not an error in this repository:
        like updateMediaAttachment (unconditional True after execute), the
        method returns True and must not raise.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments
        assert await repo.clearVisionUrl("no-such-row") is True

    async def testUpdateMediaAttachment_bareTouchRefreshesOnlyUpdatedAt(self, testDatabase: Database) -> None:
        """A fieldless updateMediaAttachment call refreshes ONLY updated_at.

        Pins the bare-touch mechanism the vision reuse path and the
        upcoming TTL-GC rely on: the SET clause always includes
        ``updated_at`` even when no field kwarg is passed, and every other
        column keeps its previous value.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments
        assert await repo.addMediaAttachment(
            fileUniqueId="touch-me",
            fileId="fid-touch",
            fileSize=2048,
            mimeType="image/png",
            description="unchanged",
        )
        assert await repo.updateMediaAttachment("touch-me", visionUrl="abcd1234.jpeg")

        before = await repo.getMediaAttachment("touch-me")
        assert before is not None

        oldTs = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        await self._backdateUpdatedAt(testDatabase, "touch-me", oldTs)

        assert await repo.updateMediaAttachment("touch-me") is True

        after = await repo.getMediaAttachment("touch-me")
        assert after is not None
        assert isinstance(after["updated_at"], datetime.datetime)
        assert after["updated_at"] > oldTs
        assert {k: v for k, v in after.items() if k != "updated_at"} == {
            k: v for k, v in before.items() if k != "updated_at"
        }
