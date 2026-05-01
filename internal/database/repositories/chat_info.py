"""Repository for managing chat information and topic data.

This module provides the ChatInfoRepository class for storing and retrieving
chat metadata including chat type, title, username, and forum status, as well
as managing forum topic information.
"""

import logging
from typing import List, Optional

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import ChatInfoDict, ChatTopicInfoDict
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
            await sqlProvider.execute(
                """
                INSERT INTO chat_info
                    (chat_id, type, title, username, is_forum)
                VALUES
                    (:chatId, :type, :title, :username, :isForum)
                ON CONFLICT DO UPDATE SET
                    type = :type,
                    title = :title,
                    username = :username,
                    is_forum = :isForum,
                    updated_at = CURRENT_TIMESTAMP
            """,
                {
                    "chatId": chatId,
                    "type": type,
                    "title": title,
                    "username": username,
                    "isForum": isForum,
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
            await sqlProvider.execute(
                """
                INSERT INTO chat_topics
                    (chat_id, topic_id, icon_color, icon_custom_emoji_id, name, updated_at)
                VALUES
                    (:chatId, :topicId, :iconColor, :customEmojiId, :topicName, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id, topic_id) DO UPDATE SET
                    icon_color = excluded.icon_color,
                    icon_custom_emoji_id = excluded.icon_custom_emoji_id,
                    name = excluded.name,
                    updated_at = CURRENT_TIMESTAMP
            """,
                {
                    "chatId": chatId,
                    "topicId": topicId,
                    "iconColor": iconColor,
                    "customEmojiId": customEmojiId,
                    "topicName": topicName,
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
