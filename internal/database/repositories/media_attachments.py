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
from typing import Any, Dict, List, Optional, Set, Tuple

from internal.models import MessageType
from lib.db import utils as dbUtils
from lib.db.manager import DatabaseManager

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
            On a database failure the error is logged (ERROR) by the repository and
            False is returned; the exception is not propagated to the caller.

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
            On a database failure the error is logged (ERROR) by the repository and
            False is returned; the exception is not propagated to the caller.

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
        visionUrl: Optional[str] = None,
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
            visionUrl: Optional StorageService URL of the normalized vision
                image to update (native-vision feature).

        Returns:
            bool: True if the media attachment was updated successfully, False otherwise.
            On a database failure the error is logged (ERROR) by the repository and
            False is returned; the exception is not propagated to the caller.

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
            if visionUrl is not None:
                query += "vision_url = :visionUrl, "
                values["visionUrl"] = visionUrl
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
            MediaAttachmentDict if found, None otherwise. On a database failure the
            error is logged (ERROR) by the repository and None is returned; the
            exception is not propagated to the caller.
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
            List of MediaAttachmentDict objects, empty list if none found. On a
            database failure the error is logged (ERROR) by the repository and an
            empty list is returned; the exception is not propagated to the caller.
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
            On a database failure the error is logged (ERROR) by the repository and
            None is returned; the exception is not propagated to the caller.
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

    async def getExpiredVisionAttachmentsWithRetention(
        self, cutoff: datetime.datetime, *, dataSource: Optional[str] = None
    ) -> Optional[Tuple[List[MediaAttachmentDict], Set[str]]]:
        """Get expired vision rows AND their retained keys from ONE consistent snapshot.

        Single-statement sweep input for the vision TTL garbage collector.
        In one database evaluation point (an atomic snapshot on SQLite, an
        MVCC-consistent read on PostgreSQL/MySQL) the statement selects
        every row past the retention cutoff that still references a vision
        object and, per row, whether that row's ``vision_url`` is shared by
        at least one live row (``updated_at >= cutoff``):

        ```sql
        SELECT e.*,
               EXISTS(
                   SELECT 1 FROM media_attachments l
                   WHERE l.vision_url = e.vision_url AND l.updated_at >= :cutoff
               ) AS retained
        FROM media_attachments e
        WHERE e.vision_url IS NOT NULL AND e.updated_at < :cutoff
        ```

        The ``updated_at`` column doubles as the receipt-freshness/LRU
        signal: it is refreshed by every update (including the bare touch
        on the vision reuse path), so a row older than the cutoff has not
        been re-received within the retention window.

        Single-statement consistency is the shipped property: expiry and
        retention are decided at ONE database evaluation point, so no
        interleaved write can make the two decisions inconsistent — a
        mid-sweep re-receipt can no longer strip a live row's shared-key
        protection (the destructive race belonged only to the intermediate,
        uncommitted two-query shape, not to the committed baseline).

        Args:
            cutoff: Expiration boundary (aware UTC); rows with ``updated_at``
                strictly before it are expired, rows at or after it count as
                live sharers.
            dataSource: Optional data source name for multi-source routing.

        Returns:
            Three-valued contract — the caller MUST distinguish all three:

            - Populated tuple: ``(expiredRows, retainedKeys)`` from ONE
              consistent snapshot. *expiredRows* is the sweep input (rows
              with ``vision_url IS NOT NULL AND updated_at < cutoff``, as
              MediaAttachmentDict objects — the internal ``retained`` flag
              is stripped); *retainedKeys* contains exactly the expired
              rows' keys that at least one live row shares — the keys the
              GC must NOT delete; every other expired key is safe to delete.
            - ``([], set())``: the query succeeded and genuinely nothing is
              expired.
            - ``None``: the query itself FAILED (error logged (ERROR) by
              the repository; the exception is not propagated).

            This method is the sanctioned exception to this repository's
            empty-sentinel-on-error convention because its only caller is
            a DESTRUCTIVE garbage collector that deletes every stored file
            whose key is absent from the retained set: mistaking a failed
            lookup for "nothing is expired / retained" would authorize
            deleting files that live rows may still reference. Failure must
            therefore be observable as ``None``, never collapsed into
            emptiness.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT e.*,
                       EXISTS(
                           SELECT 1 FROM media_attachments l
                           WHERE l.vision_url = e.vision_url AND l.updated_at >= :cutoff
                       ) AS retained
                FROM media_attachments e
                WHERE e.vision_url IS NOT NULL AND e.updated_at < :cutoff
            """,
                {"cutoff": cutoff},
            )

            expiredRows: List[MediaAttachmentDict] = []
            retainedKeys: Set[str] = set()
            for row in rows:
                if row["retained"]:
                    retainedKeys.add(row["vision_url"])
                # Strip the synthetic retained flag: the typed dicts carry
                # only real media_attachments columns.
                expiredRows.append(
                    dbUtils.sqlToTypedDict(
                        {key: value for key, value in row.items() if key != "retained"},
                        MediaAttachmentDict,
                    )
                )
            return (expiredRows, retainedKeys)
        except Exception as e:
            logger.error(f"Failed to get expired vision attachments with retention: {e}")
            return None

    async def clearVisionUrl(self, mediaId: str, *, dataSource: Optional[str] = None) -> bool:
        """Clear the vision_url of a media attachment (vision TTL garbage collection).

        Sets ``vision_url`` to NULL and refreshes ``updated_at`` in a single
        UPDATE — the ride-along ``updated_at`` refresh is consistent with
        every update in this repository and marks the row as freshly
        examined by the GC pass.

        Args:
            mediaId: Media attachment unique identifier (file_unique_id).
            dataSource: Optional data source name for multi-source routing.

        Returns:
            bool: True if the update executed successfully, False otherwise.
            A mediaId matching no row is not an error (True, same semantics
            as updateMediaAttachment). On a database failure the error is
            logged (ERROR) by the repository and False is returned; the
            exception is not propagated to the caller.

        Note:
            Writes to the routed source with ``readonly=False`` (default
            source when no *dataSource* is given). Cannot write to readonly
            sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=False)
            await sqlProvider.execute(
                """
                UPDATE media_attachments
                SET
                    vision_url = NULL,
                    updated_at = :updatedAt
                WHERE
                    file_unique_id = :mediaId
            """,
                {
                    "mediaId": mediaId,
                    "updatedAt": dbUtils.getCurrentTimestamp(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to clear media attachment vision_url: {e}")
            return False
