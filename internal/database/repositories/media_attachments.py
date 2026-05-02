"""Repository for managing media attachments and media groups in the database.

This module provides methods to create, update, and retrieve media attachments,
as well as manage media group relationships. Media attachments can include images,
videos, documents, and other file types with associated metadata.
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
    """

    __slots__ = ()

    def __init__(self, manager: DatabaseManager):
        super().__init__(manager)

    ###
    # Media Attachments manipulation functions
    ###

    async def ensureMediaInGroup(self, *, mediaId: str, mediaGroupId: str) -> bool:
        """
        Ensure that a media attachment is in a group.

        Args:
            mediaId: Media attachment ID
            mediaGroupId: Media group ID

        Returns:
            bool: True if successful, False otherwise

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
        metadata: str | dict = "{}",
        status: MediaStatus = MediaStatus.NEW,
        localUrl: Optional[str] = None,
        prompt: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """
        Add a media attachment to the database.

        Args:
            fileUniqueId: Unique file identifier
            fileId: File identifier
            fileSize: Optional file size
            mediaType: Type of media
            mimeType: Optional MIME type
            metadata: JSON metadata
            status: Media status
            localUrl: Optional local URL
            prompt: Optional prompt
            description: Optional description

        Returns:
            bool: True if successful, False otherwise

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
        metadata: Optional[str | dict] = None,
        mimeType: Optional[str] = None,
        localUrl: Optional[str] = None,
        description: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> bool:
        """
        Update a media attachment in the database.

        Args:
            mediaId: Media identifier
            fileSize: Optional file size
            status: Optional media status
            metadata: Optional JSON metadata
            mimeType: Optional MIME type
            localUrl: Optional local URL
            description: Optional description
            prompt: Optional prompt

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            query = ""
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

        Args:
            mediaId: Media attachment unique identifier
            dataSource: Optional data source name for multi-source routing

        Returns:
            MediaAttachmentDict if found, None otherwise
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

        Args:
            mediaGroupId: Media group identifier
            dataSource: Optional data source name for multi-source routing

        Returns:
            List of MediaAttachmentDict objects, empty list if none found
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
        """
        Get the timestamp of the most recently added media in a group.

        This method is useful for determining when a media group is complete
        by checking if enough time has passed since the last media was added.

        Args:
            mediaGroupId: Media group ID to query
            dataSource: Optional data source name for multi-source routing

        Returns:
            datetime of the most recent media addition, or None if group not found
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
                ok, ret = dbUtils.sqlToCustomType(row["last_updated"], datetime.datetime)
                if not ok:
                    logger.error(f"Failed to convert last_updated to datetime: {row['last_updated']}")
                return ret
            return None
        except Exception as e:
            logger.error(f"Failed to get media group last updated timestamp: {e}")
            logger.exception(e)
            return None
