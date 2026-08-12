"""Repository for managing chat information and topic data.

This module provides the ChatInfoRepository class for storing and retrieving
chat metadata including chat type, title, username, and forum status, as well
as managing forum topic information.
"""

import logging
from typing import Dict, List, Optional

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import ChatBotStatus, ChatInfoDict, ChatTopicInfoDict
from ..providers.base import ExcludedValue
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ChatInfoRepository(BaseRepository):
    """Repository for managing chat information and topic data.

    Provides methods to store and retrieve chat metadata including type, title,
    username, and forum status, as well as managing forum topic information
    such as icon colors, custom emojis, and topic names.
    """

    __slots__ = ()
    """Empty slots tuple to prevent dynamic attribute creation."""

    def __init__(self, manager: DatabaseManager):
        """Initialize the ChatInfoRepository.

        Args:
            manager: DatabaseManager instance for database operations
        """
        super().__init__(manager)

    ###
    # Chat Info manipulation
    ###
    async def updateChatInfo(
        self,
        chatId: int,
        type: str,
        title: Optional[str] = None,
        username: Optional[str] = None,
        isForum: Optional[bool] = False,
    ) -> bool:
        """Add or update chat information in the database.

        Args:
            chatId: Chat identifier
            type: Chat type (e.g., 'private', 'group', 'supergroup', 'channel')
            title: Optional chat title
            username: Optional chat username
            isForum: Whether the chat is a forum (default: False)

        Returns:
            bool: True if successful, False otherwise

        Note:
            Uses UPSERT logic - inserts new record or updates existing one.
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        if isForum is None:
            isForum = False
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId)
            currentTimestamp = dbUtils.getCurrentTimestamp()
            await sqlProvider.upsert(
                table="chat_info",
                values={
                    "chat_id": chatId,
                    "type": type,
                    "title": title,
                    "username": username,
                    "is_forum": isForum,
                    "created_at": currentTimestamp,
                    "updated_at": currentTimestamp,
                },
                conflictColumns=["chat_id"],
                updateExpressions={
                    "type": ExcludedValue(),
                    "title": ExcludedValue(),
                    "username": ExcludedValue(),
                    "is_forum": ExcludedValue(),
                    "updated_at": ExcludedValue(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add chat info: {e}")
            logger.exception(e)
            return False

    async def getChatInfo(self, chatId: int, *, dataSource: Optional[str] = None) -> Optional[ChatInfoDict]:
        """
        Get chat info from the database.

        Args:
            chatId: Chat identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            ChatInfoDict or None if not found
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            row = await sqlProvider.executeFetchOne(
                """
                SELECT * FROM chat_info
                WHERE
                    chat_id = :chatId
            """,
                {
                    "chatId": chatId,
                },
            )
            # logger.debug(f"Chat#{chatId} info: {row}")
            return dbUtils.sqlToTypedDict(row, ChatInfoDict) if row else None
        except Exception as e:
            logger.error(f"Failed to get chat info: {e}")
            return None

    async def updateChatTopicInfo(
        self,
        chatId: int,
        topicId: int,
        iconColor: Optional[int] = None,
        customEmojiId: Optional[str] = None,
        topicName: Optional[str] = None,
    ) -> bool:
        """
        Store or update chat topic information.

        Args:
            chatId: Chat identifier (used for source routing)
            topicId: Topic identifier
            iconColor: Optional icon color
            customEmojiId: Optional custom emoji ID
            topicName: Optional topic name

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        if topicName is None:
            topicName = "Default"
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            currentTimestamp = dbUtils.getCurrentTimestamp()
            await sqlProvider.upsert(
                table="chat_topics",
                values={
                    "chat_id": chatId,
                    "topic_id": topicId,
                    "icon_color": iconColor,
                    "icon_custom_emoji_id": customEmojiId,
                    "name": topicName,
                    "created_at": currentTimestamp,
                    "updated_at": currentTimestamp,
                },
                conflictColumns=["chat_id", "topic_id"],
                updateExpressions={
                    "icon_color": ExcludedValue(),
                    "icon_custom_emoji_id": ExcludedValue(),
                    "name": ExcludedValue(),
                    "updated_at": ExcludedValue(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update chat topic {topicId} in chat {chatId}: {e}")
            return False

    async def getChatTopics(self, chatId: int, *, dataSource: Optional[str] = None) -> List[ChatTopicInfoDict]:
        """
        Get chat topics.

        Args:
            chatId: Chat identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            List of ChatTopicInfoDict
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT * FROM chat_topics
                WHERE
                    chat_id = :chatId
            """,
                {
                    "chatId": chatId,
                },
            )
            return [dbUtils.sqlToTypedDict(row, ChatTopicInfoDict) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get chat topics: {e}")
            return []

    async def setChatBotStatus(self, chatId: int, status: ChatBotStatus) -> bool:
        """Conditionally set ``chat_info.bot_status`` for ``chatId``.

        Uses a conditional UPDATE (``WHERE bot_status != :status``) so the common case of
        setting the current value is a no-op write and the method is safe to call on every
        probe. Routed by ``chatId``. Cannot write to readonly sources.

        Args:
            chatId: Chat identifier.
            status: Target :class:`ChatBotStatus`.

        Returns:
            True if the chat exists and now has the target status, False if the chat
            does not exist. Under concurrent writes, multiple callers may both return
            True even if only one actually changed the value — the DB converges to the
            last writer. Callers must not gate critical logic on "this caller specifically
            changed it."
        """
        sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
        # Conditional UPDATE: only write when status differs (idempotent, race-convergent)
        await sqlProvider.execute(
            """
            UPDATE chat_info
            SET bot_status = :status
            WHERE chat_id = :chatId AND bot_status != :status
            """,
            {
                "chatId": chatId,
                "status": status.value,
            },
        )
        # Recover the signal: check the resulting state
        row = await sqlProvider.executeFetchOne(
            """
            SELECT bot_status FROM chat_info WHERE chat_id = :chatId
            """,
            {"chatId": chatId},
        )
        # row is None → chat doesn't exist; else True if now at target (always true after
        # successful UPDATE + conditional, or was already target)
        return row is not None

    async def getInactiveChatIds(self) -> List[Dict[str, int]]:
        """Return ``[{chat_id: int}, ...]`` for every chat currently ``INACCESSIBLE``.

        Used by ``CacheService.injectDatabase`` to seed the in-memory known-inaccessible
        set at startup so the preprocessor recovery hook (§5.1) works immediately after a
        restart. Read-only; aggregates across sources like the other chat-listing reads.

        Returns:
            List of dicts with ``chat_id`` keys for every chat with ``bot_status =
            ChatBotStatus.INACCESSIBLE``. Aggregates from all sources in multi-source mode.
        """
        allResults: List[Dict[str, int]] = []
        seen: set[int] = set()  # Deduplicate by chatId

        sourcesList = list(self.manager._providers.keys())

        for sourceName in sourcesList:
            try:
                sqlProvider = await self.manager.getProvider(dataSource=sourceName, readonly=True)
                rows = await sqlProvider.executeFetchAll(
                    """
                    SELECT chat_id FROM chat_info
                    WHERE bot_status = :inaccessibleStatus
                    """,
                    {
                        "inaccessibleStatus": ChatBotStatus.INACCESSIBLE.value,
                    },
                )
                for row in rows:
                    chatId = int(row["chat_id"])
                    if chatId not in seen:
                        seen.add(chatId)
                        allResults.append({"chat_id": chatId})
            except Exception as e:
                logger.warning(f"Failed to get inactive chat IDs from source '{sourceName}': {e}")
                continue

        logger.debug(f"Found {len(allResults)} inactive chats across all sources")
        return allResults
