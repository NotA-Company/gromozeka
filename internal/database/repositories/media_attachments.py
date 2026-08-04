"""Repository for managing media attachments and media groups in the database.

This module provides methods to create, update, and retrieve media attachments,
as well as manage media group relationships. Media attachments can include images,
videos, documents, and other file types with associated metadata.

Key Classes:
    MediaAttachmentsRepository: Main repository class for media attachments operations.

Example:
    >>> manager = DatabaseManager()
    >>> repo = MediaAttachmentsRepository(manager)
    >>> await repo.addMediaAttachment(
    ...     fileUniqueId="unique123",
    ...     fileId="file456",
    ...     mediaType=MessageType.IMAGE
    ... )
"""

import datetime
import logging
from typing import Any, Dict, List, Optional

from internal.models import MessageType

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import MediaAttachmentDict, MediaStatus
from .base import BaseRepository

logger = logging.getLogger(__name__)


class MediaAttachmentsRepository(BaseRepository):
    """Repository for managing media attachments and media groups.

    Provides CRUD operations for media attachments including adding new attachments,
    updating metadata and status, and retrieving attachments by ID or group.
    Also manages media group relationships for grouping related media items.

    Attributes:
        manager: DatabaseManager instance for database operations.

    Example:
        >>> manager = DatabaseManager()
        >>> repo = MediaAttachmentsRepository(manager)
        >>> await repo.addMediaAttachment(
        ...     fileUniqueId="unique123",
        ...     fileId="file456",
        ...     mediaType=MessageType.IMAGE
        ... )
    """

    __slots__ = ()

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the media attachments repository.

        Args:
            manager: DatabaseManager instance for database operations.
        """
        super().__init__(manager)

    ###
    # Media Attachments manipulation functions
    ###

    async def ensureMediaInGroup(self, *, mediaId: str, mediaGroupId: str) -> bool:
        """Ensure that a media attachment is in a group.

        This method creates a relationship between a media attachment and a media group
        if it doesn't already exist. If the relationship exists, no changes are made.

        Args:
            mediaId: Media attachment unique identifier (file_unique_id).
            mediaGroupId: Media group identifier.

        Returns:
            bool: True if the relationship was ensured successfully, False otherwise.

        Raises:
            Exception: If database operation fails.

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=False)
            await sqlProvider.upsert(
                table="media_groups",
                values={
                    "media_group_id": mediaGroupId,
                    "media_id": mediaId,
                    "created_at": dbUtils.getCurrentTimestamp(),
                },
                conflictColumns=["media_group_id", "media_id"],
                updateExpressions={},  # ON CONFLICT DO NOTHING
            )
            return True
        except Exception as e:
            logger.error(f"Failed to ensure media in group: {e}")
            return False

    async def addMediaAttachment(
        self,
        *,
        fileUniqueId: str,
        fileId: str,
        fileSize: Optional[int] = None,
        mediaType: MessageType = MessageType.IMAGE,
        mimeType: Optional[str] = None,
        metadata: str | Dict[str, Any] = "{}",
        status: MediaStatus = MediaStatus.NEW,
        localUrl: Optional[str] = None,
        prompt: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Add a media attachment to the database.

        Creates a new media attachment record with the provided metadata.
        The attachment can be an image, video, document, or other media type.

        Args:
            fileUniqueId: Unique file identifier from the messaging platform.
            fileId: File identifier from the messaging platform.
            fileSize: Optional file size in bytes.
            mediaType: Type of media (e.g., IMAGE, VIDEO, DOCUMENT).
            mimeType: Optional MIME type of the file.
            metadata: JSON metadata as string or dict. Defaults to empty dict.
            status: Media status (e.g., NEW, DOWNLOADED, FAILED). Defaults to NEW.
            localUrl: Optional local URL where the file is stored.
            prompt: Optional prompt associated with the media.
            description: Optional description of the media content.

        Returns:
            bool: True if the media attachment was added successfully, False otherwise.

        Raises:
            Exception: If database operation fails.

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO media_attachments
                    (file_unique_id, file_id, file_size,
                            media_type, metadata, status,
                            mime_type, local_url, prompt,
                            description, created_at, updated_at
                            )
                VALUES
                    (:fileUniqueId, :fileId, :fileSize,
                            :mediaType, :metadata, :status,
                            :mimeType, :localUrl, :prompt,
                            :description, :createdAt, :updatedAt)
            """,
                {
                    "fileUniqueId": fileUniqueId,
                    "fileId": fileId,
                    "fileSize": fileSize,
                    "mediaType": mediaType,
                    "metadata": metadata,
                    "status": status,
                    "mimeType": mimeType,
                    "localUrl": localUrl,
                    "prompt": prompt,
                    "description": description,
                    "createdAt": dbUtils.getCurrentTimestamp(),
                    "updatedAt": dbUtils.getCurrentTimestamp(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add media attachment: {e}")
            return False

    async def updateMediaAttachment(
        self,
        mediaId: str,
        *,
        fileSize: Optional[int] = None,
        status: Optional[MediaStatus] = None,
        metadata: Optional[str | Dict[str, Any]] = None,
        mimeType: Optional[str] = None,
        localUrl: Optional[str] = None,
        description: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> bool:
        """Update a media attachment in the database.

        Updates specified fields of a media attachment. Only fields that are
        provided (not None) will be updated. The updated_at timestamp is
        automatically refreshed.

        Args:
            mediaId: Media attachment unique identifier (file_unique_id).
            fileSize: Optional file size in bytes to update.
            status: Optional media status to update.
            metadata: Optional JSON metadata to update.
            mimeType: Optional MIME type to update.
            localUrl: Optional local URL to update.
            description: Optional description to update.
            prompt: Optional prompt to update.

        Returns:
            bool: True if the media attachment was updated successfully, False otherwise.

        Raises:
            Exception: If database operation fails.

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            query: str = ""
            values: Dict[str, Any] = {"fileUniqueId": mediaId}

            if status is not None:
                query += "status = :status, "
                values["status"] = status
            if metadata is not None:
                query += "metadata = :metadata, "
                values["metadata"] = metadata
            if mimeType is not None:
                query += "mime_type = :mimeType, "
                values["mimeType"] = mimeType
            if localUrl is not None:
                query += "local_url = :localUrl, "
                values["localUrl"] = localUrl
            if description is not None:
                query += "description = :description, "
                values["description"] = description
            if prompt is not None:
                query += "prompt = :prompt, "
                values["prompt"] = prompt
            if fileSize is not None:
                query += "file_size = :fileSize, "
                values["fileSize"] = fileSize

            sqlProvider = await self.manager.getProvider(readonly=False)
            await sqlProvider.execute(
                f"""
                UPDATE media_attachments
                SET
                    {query}
                    updated_at = :updatedAt
                WHERE
                    file_unique_id = :fileUniqueId
            """,
                {
                    **values,
                    "updatedAt": dbUtils.getCurrentTimestamp(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update media attachment: {e}")
            return False

    async def getMediaAttachment(
        self, mediaId: str, *, dataSource: Optional[str] = None
    ) -> Optional[MediaAttachmentDict]:
        """Get a media attachment from the database.

        Retrieves a single media attachment by its unique identifier.

        Args:
            mediaId: Media attachment unique identifier (file_unique_id).
            dataSource: Optional data source name for multi-source routing.

        Returns:
            MediaAttachmentDict if found, None otherwise.

        Raises:
            Exception: If database operation fails.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
            row = await sqlProvider.executeFetchOne(
                """
                SELECT * FROM media_attachments
                WHERE file_unique_id = :mediaId
            """,
                {
                    "mediaId": mediaId,
                },
            )

            return dbUtils.sqlToTypedDict(row, MediaAttachmentDict) if row else None
        except Exception as e:
            logger.error(f"Failed to get media attachment: {e}")
            return None

    async def getMediaAttachmentsByGroupId(
        self, mediaGroupId: str, *, dataSource: Optional[str] = None
    ) -> List[MediaAttachmentDict]:
        """Get all media attachments belonging to a media group.

        Retrieves all media attachments that are associated with a specific media group.
        This is useful for handling media groups like photo albums or video collections.

        Args:
            mediaGroupId: Media group identifier.
            dataSource: Optional data source name for multi-source routing.

        Returns:
            List of MediaAttachmentDict objects, empty list if none found.

        Raises:
            Exception: If database operation fails.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT ma.* FROM media_groups mg
                JOIN media_attachments ma ON mg.media_id = ma.file_unique_id
                WHERE mg.media_group_id = :mediaGroupId
            """,
                {"mediaGroupId": mediaGroupId},
            )

            return [dbUtils.sqlToTypedDict(row, MediaAttachmentDict) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get media attachments by group ID: {e}")
            return []

    async def getMediaGroupLastUpdatedAt(
        self, mediaGroupId: str, *, dataSource: Optional[str] = None
    ) -> Optional[datetime.datetime]:
        """Get the timestamp of the most recently added media in a group.

        This method is useful for determining when a media group is complete
        by checking if enough time has passed since the last media was added.
        Media groups are typically complete when no new media has been added
        for a certain period of time.

        Args:
            mediaGroupId: Media group identifier to query.
            dataSource: Optional data source name for multi-source routing.

        Returns:
            datetime of the most recent media addition, or None if group not found.

        Raises:
            Exception: If database operation fails.
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=True, dataSource=dataSource)
            row = await sqlProvider.executeFetchOne(
                """
                SELECT MAX(created_at) as last_updated
                FROM media_groups
                WHERE media_group_id = :mediaGroupId
                """,
                {"mediaGroupId": mediaGroupId},
            )

            if row and row["last_updated"]:
                ok: bool
                ret: Optional[datetime.datetime]
                ok, ret = dbUtils.sqlToCustomType(row["last_updated"], datetime.datetime)
                if not ok:
                    logger.error(f"Failed to convert last_updated to datetime: {row['last_updated']}")
                return ret
            return None
        except Exception as e:
            logger.error(f"Failed to get media group last updated timestamp: {e}")
            logger.exception(e)
            return None
