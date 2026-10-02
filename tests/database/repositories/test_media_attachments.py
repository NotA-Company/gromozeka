"""Tests for MediaAttachmentsRepository.

Integration tests exercising :class:`MediaAttachmentsRepository` against a
real in-memory SQLite database (all migrations applied via the
``testDatabase`` fixture).  Covers basic add / read operations.
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
