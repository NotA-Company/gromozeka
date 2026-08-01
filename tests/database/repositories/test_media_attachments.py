"""Tests for MediaAttachmentsRepository.

Integration tests exercising :class:`MediaAttachmentsRepository` against a
real in-memory SQLite database (all migrations applied via the
``testDatabase`` fixture).  Covers the ``setStatusVerified`` compare-and-set
helper as well as basic add / read operations that the new method depends on.
"""

from internal.database import Database
from internal.database.models import MediaStatus
from internal.models import MessageType


class TestMediaAttachmentsRepository:
    """Integration tests for the media_attachments repository.

    Each test writes through the public repository API on top of the shared
    ``testDatabase`` fixture (a fresh in-memory SQLite database with all
    migrations applied) and reads back through it to verify observable state.
    """

    async def testSetStatusVerifiedReturnsRowOnMatchingTransition(self, testDatabase: Database) -> None:
        """NEW -> PENDING returns the updated row.

        Inserts a row at status NEW, calls setStatusVerified with
        expected=NEW and target=PENDING, and asserts the returned row has
        status PENDING.  Re-reads via getMediaAttachment to confirm
        persistence.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments

        await repo.addMediaAttachment(
            fileUniqueId="file-001",
            fileId="fid-001",
            mediaType=MessageType.IMAGE,
            status=MediaStatus.NEW,
        )

        result = await repo.setStatusVerified("file-001", expected=MediaStatus.NEW, target=MediaStatus.PENDING)

        assert result is not None
        assert result["status"] == MediaStatus.PENDING

        row = await repo.getMediaAttachment("file-001")
        assert row is not None
        assert row["status"] == MediaStatus.PENDING

    async def testSetStatusVerifiedReturnsNoneOnStatusMismatch(self, testDatabase: Database) -> None:
        """expected=DONE on a DONE row with target=FAILED does not match.

        The row already has status DONE, so the WHERE clause
        ``status = :expected (PENDING)`` matches zero rows.  Returns None
        and the row remains at DONE.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments

        await repo.addMediaAttachment(
            fileUniqueId="file-002",
            fileId="fid-002",
            mediaType=MessageType.IMAGE,
            status=MediaStatus.DONE,
        )

        result = await repo.setStatusVerified("file-002", expected=MediaStatus.PENDING, target=MediaStatus.FAILED)

        assert result is None

        row = await repo.getMediaAttachment("file-002")
        assert row is not None
        assert row["status"] == MediaStatus.DONE

    async def testSetStatusVerifiedReturnsNoneWhenRowMissing(self, testDatabase: Database) -> None:
        """A non-existent mediaId yields None without raising.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments

        result = await repo.setStatusVerified("nonexistent", expected=MediaStatus.NEW, target=MediaStatus.PENDING)

        assert result is None

    async def testSetStatusVerifiedWritesDescriptionOnTerminalDone(self, testDatabase: Database) -> None:
        """PENDING -> DONE with description stores the transcript text.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments

        await repo.addMediaAttachment(
            fileUniqueId="file-003",
            fileId="fid-003",
            mediaType=MessageType.VOICE,
            status=MediaStatus.PENDING,
        )

        result = await repo.setStatusVerified(
            "file-003",
            expected=MediaStatus.PENDING,
            target=MediaStatus.DONE,
            description="hello world",
        )

        assert result is not None
        assert result["status"] == MediaStatus.DONE
        assert result["description"] == "hello world"

        row = await repo.getMediaAttachment("file-003")
        assert row is not None
        assert row["status"] == MediaStatus.DONE
        assert row["description"] == "hello world"

    async def testSetStatusVerifiedClearsDescriptionOnTerminalFailed(self, testDatabase: Database) -> None:
        """PENDING -> FAILED with description=None clears any existing description.

        Inserts a row at PENDING with a non-null description, then
        transitions to FAILED with description=None.  Asserts description is
        None after the transition.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments

        await repo.addMediaAttachment(
            fileUniqueId="file-004",
            fileId="fid-004",
            mediaType=MessageType.VOICE,
            status=MediaStatus.PENDING,
            description="prior text",
        )

        result = await repo.setStatusVerified(
            "file-004",
            expected=MediaStatus.PENDING,
            target=MediaStatus.FAILED,
            description=None,
        )

        assert result is not None
        assert result["status"] == MediaStatus.FAILED
        assert result["description"] is None

        row = await repo.getMediaAttachment("file-004")
        assert row is not None
        assert row["status"] == MediaStatus.FAILED
        assert row["description"] is None

    async def testSetStatusVerifiedReturnsNoneOnFalsePositiveTerminal(self, testDatabase: Database) -> None:
        """expected=PENDING on a DONE row with target=DONE returns None (false-positive guard).

        Regression test for the non-atomic compare-and-set bug: the old
        two-statement implementation (UPDATE then re-read SELECT) would
        match zero rows in the UPDATE (status is DONE, not PENDING) but
        then find the row via the re-read ``WHERE status = :target``
        (DONE), falsely returning it as if the transition applied.  The
        true-CAS ``UPDATE ... RETURNING`` returns zero rows when the
        WHERE does not match, so the method correctly returns ``None``.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments

        await repo.addMediaAttachment(
            fileUniqueId="file-fp",
            fileId="fid-fp",
            mediaType=MessageType.VOICE,
            status=MediaStatus.DONE,
            description="original transcript",
        )

        result = await repo.setStatusVerified(
            "file-fp",
            expected=MediaStatus.PENDING,
            target=MediaStatus.DONE,
            description="should not overwrite",
        )

        assert result is None

        row = await repo.getMediaAttachment("file-fp")
        assert row is not None
        assert row["status"] == MediaStatus.DONE
        assert row["description"] == "original transcript"

    async def testAddMediaAttachment_returnsRowViaGet(self, testDatabase: Database) -> None:
        """Add and get round-trips correctly.

        Regression guard: existing addMediaAttachment + getMediaAttachment
        still work correctly alongside the new setStatusVerified method.

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
