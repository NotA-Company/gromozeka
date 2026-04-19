"""TODO: write docstring"""

import datetime
import logging
from collections.abc import Sequence
from typing import Any, List, Optional

from internal.models import MessageIdType, MessageType

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import ChatMessageDict, MessageCategory
from ..providers import ParametrizedQuery
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ChatMessagesRepository(BaseRepository):
    """TODO: write docstring"""

    __slots__ = ()

    def __init__(self, manager: DatabaseManager):
        super().__init__(manager)

    ###
    # Chat messages manipulation functions
    ###
    async def saveChatMessage(
        self,
        date: datetime.datetime,
        chatId: int,
        userId: int,
        messageId: MessageIdType,
        replyId: Optional[MessageIdType] = None,
        threadId: Optional[int] = None,
        messageText: str = "",
        messageType: MessageType = MessageType.TEXT,
        messageCategory: MessageCategory = MessageCategory.UNSPECIFIED,
        rootMessageId: Optional[MessageIdType] = None,
        quoteText: Optional[str] = None,
        mediaId: Optional[str] = None,
        markup: str = "",
        metadata: str = "",
        mediaGroupId: Optional[str] = None,
    ) -> bool:
        """
        Save a chat message with detailed information.

        Args:
            date: Message timestamp
            chatId: Chat identifier (used for source routing)
            userId: User identifier
            messageId: Message identifier
            replyId: Optional reply message ID
            threadId: Optional thread ID
            messageText: Message text content
            messageType: Type of message
            messageCategory: Message category
            rootMessageId: Optional root message ID for threads
            quoteText: Optional quoted text
            mediaId: Optional media attachment ID

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
            TODO: Update docstrings
        """
        messageId = str(messageId)
        if replyId is not None:
            replyId = str(replyId)
        if rootMessageId is not None:
            rootMessageId = str(rootMessageId)

        if threadId is None:
            threadId = dbUtils.DEFAULT_THREAD_ID
        try:
            sqlPrivider = await self.manager.getProvider(chatId=chatId, readonly=False)
            today = date.replace(hour=0, minute=0, second=0, microsecond=0)
            await sqlPrivider.batchExecute(
                [
                    ParametrizedQuery(
                        """
                    INSERT INTO chat_messages
                    (date, chat_id, user_id, message_id,
                        reply_id, thread_id, message_text, message_type,
                        message_category, root_message_id, quote_text,
                        media_id, markup, metadata, media_group_id
                        )
                    VALUES
                    (:date, :chatId, :userId, :messageId,
                        :replyId, :threadId, :messageText, :messageType,
                        :messageCategory, :rootMessageId, :quoteText,
                        :mediaId, :markup, :metadata, :mediaGroupId
                        )
                """,
                        {
                            "date": date,
                            "chatId": chatId,
                            "userId": userId,
                            "messageId": messageId,
                            "replyId": replyId,
                            "threadId": threadId,
                            "messageText": messageText,
                            "messageType": messageType,
                            "messageCategory": str(messageCategory),
                            "rootMessageId": rootMessageId,
                            "quoteText": quoteText,
                            "mediaId": mediaId,
                            "markup": markup,
                            "metadata": metadata,
                            "mediaGroupId": mediaGroupId,
                        },
                    ),
                    ParametrizedQuery(
                        """
                    UPDATE chat_users
                    SET messages_count = messages_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE chat_id = ? AND user_id = ?
                """,
                        (chatId, userId),
                    ),
                    ParametrizedQuery(
                        """
                    INSERT INTO chat_stats
                    (chat_id, date, messages_count, updated_at)
                    VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (chat_id, date) DO UPDATE SET
                        messages_count = messages_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                """,
                        (chatId, today),
                    ),
                    ParametrizedQuery(
                        """
                    INSERT INTO chat_user_stats
                    (chat_id, user_id, date, messages_count, updated_at)
                    VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (chat_id, user_id, date) DO UPDATE SET
                        messages_count = messages_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                """,
                        (chatId, userId, today),
                    ),
                ]
            )

            return True
        except Exception as e:
            logger.error(f"Failed to save chat message from user {userId} in chat {chatId}: {e}")
            return False

    async def getChatMessagesSince(
        self,
        chatId: int,
        sinceDateTime: Optional[datetime.datetime] = None,
        tillDateTime: Optional[datetime.datetime] = None,
        threadId: Optional[int] = None,
        limit: Optional[int] = None,
        messageCategory: Optional[Sequence[MessageCategory]] = None,
        *,
        dataSource: Optional[str] = None,
    ) -> List[ChatMessageDict]:
        """
        Get chat messages from a specific chat newer than the given date.

        Args:
            chatId: Chat identifier
            sinceDateTime: Optional start date for message filtering
            tillDateTime: Optional end date for message filtering
            threadId: Optional thread identifier for filtering
            limit: Optional maximum number of messages to return
            messageCategory: Optional list of message categories to filter
            dataSource: Optional data source name for explicit routing

        Returns:
            List of ChatMessageDict objects matching the criteria
        """
        logger.debug(
            f"Getting chat messages for chat {chatId}:{threadId} "
            f"date: [{sinceDateTime},{tillDateTime}], limit: {limit}, "
            f"messageCategory: {messageCategory}, dataSource: {dataSource}"
        )
        try:
            params = {
                "chatId": chatId,
                "sinceDateTime": sinceDateTime,
                "tillDateTime": tillDateTime,
                "threadId": threadId,
                "messageCategory": None if messageCategory is None else True,
            }

            placeholders = []
            if messageCategory is not None:
                for i, category in enumerate(messageCategory):
                    placeholders.append(f":messageCategory{i}")
                    params[f"messageCategory{i}"] = category

            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            query = f"""
                SELECT c.*, u.username, u.full_name  FROM chat_messages c
                JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                WHERE
                    c.chat_id = :chatId
                    AND (:sinceDateTime   IS NULL OR c.date > :sinceDateTime)
                    AND (:tillDateTime    IS NULL OR c.date < :tillDateTime)
                    AND (:threadId        IS NULL OR c.thread_id = :threadId)
                    AND (:messageCategory IS NULL OR message_category IN ({", ".join(placeholders)}))
                ORDER BY c.date DESC, c.message_id DESC
            """
            if limit is not None:
                query += f" LIMIT {int(limit)}"

            rows = await sqlProvider.executeFetchAll(
                query,
                params,
            )
            return [dbUtils.sqlToTypedDict(row, ChatMessageDict) for row in rows]
        except Exception as e:
            logger.error(
                f"Failed to get chat messages for chat {chatId} since {sinceDateTime} (threadId={threadId}): {e}"
            )
            return []

    async def getChatMessageByMessageId(
        self, chatId: int, messageId: MessageIdType, *, dataSource: Optional[str] = None
    ) -> Optional[ChatMessageDict]:
        """
        Get a specific chat message by message_id, chat_id, and optional thread_id.

        Args:
            chatId: Chat identifier
            messageId: Message identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            ChatMessageDict or None if not found
        """
        logger.debug(f"Getting chat message for chat {chatId}, message_id {messageId}")
        messageId = str(messageId)
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)

            row = await sqlProvider.executeFetchOne(
                """
                SELECT c.*, u.username, u.full_name FROM chat_messages c
                JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                WHERE
                    c.chat_id = :chatId
                    AND c.message_id = :messageId
                LIMIT 1
            """,
                {"chatId": chatId, "messageId": messageId},
            )
            return dbUtils.sqlToTypedDict(row, ChatMessageDict) if row else None
        except Exception as e:
            logger.error(f"Failed to get chat message for chat {chatId}, message_id {messageId}: {e}")
            return None

    async def getChatMessagesByRootId(
        self,
        chatId: int,
        rootMessageId: MessageIdType,
        threadId: Optional[int] = None,
        *,
        dataSource: Optional[str] = None,
    ) -> List[ChatMessageDict]:
        """Get all chat messages in a conversation thread by root message ID.

        Args:
            chatId: Chat identifier
            rootMessageId: Root message ID to find thread messages for
            threadId: Optional thread ID to filter by
            dataSource: Optional data source identifier for multi-source database routing

        Returns:
            List of chat message dictionaries in the thread
        """
        logger.debug(f"Getting chat messages for chat {chatId}, thread {threadId}, root_message_id {rootMessageId}")
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT c.*, u.username, u.full_name FROM chat_messages c
                JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                WHERE
                    c.chat_id = :chatId
                    AND c.root_message_id = :rootMessageId
                    AND ((:threadId IS NULL) OR (c.thread_id = :threadId))
                ORDER BY c.date ASC
            """,
                {
                    "chatId": chatId,
                    "rootMessageId": rootMessageId,
                    "threadId": threadId,
                },
            )
            return [dbUtils.sqlToTypedDict(row, ChatMessageDict) for row in rows]
        except Exception as e:
            logger.error(
                f"Failed to get chat messages for chat {chatId}, thread {threadId}, "
                f"root_message_id {rootMessageId}: {e}"
            )
            return []

    async def getChatMessagesByUser(
        self, chatId: int, userId: int, limit: int = 100, *, dataSource: Optional[str] = None
    ) -> List[ChatMessageDict]:
        """
        Get all chat messages by user ID.

        Args:
            chatId: Chat identifier
            userId: User identifier
            limit: Maximum number of messages to return (default: 100)
            dataSource: Optional data source name for explicit routing

        Returns:
            List of ChatMessageDict
        """
        logger.debug(f"Getting chat messages for chat {chatId}, user {userId}")
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT c.*, u.username, u.full_name FROM chat_messages c
                JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                WHERE
                    c.chat_id = :chatId
                    AND c.user_id = :userId
                ORDER BY c.date DESC
                LIMIT :limit
            """,
                {
                    "chatId": chatId,
                    "userId": userId,
                    "limit": limit,
                },
            )
            return [dbUtils.sqlToTypedDict(row, ChatMessageDict) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get chat messages for chat {chatId}, user {userId}: {e}")
            return []

    async def getFirstChatMessageByMediaGroupId(
        self,
        chatId: int,
        mediaGroupId: str,
        threadId: Optional[int] = None,
        *,
        dataSource: Optional[str] = None,
    ) -> Optional[ChatMessageDict]:
        """
        Get the first (earliest) chat message with given media group ID.

        Args:
            chatId: Chat identifier
            mediaGroupId: Media group identifier
            threadId: Optional thread identifier for filtering
            dataSource: Optional data source name for explicit routing

        Returns:
            ChatMessageDict or None if not found
        """
        # logger.debug(
        #     f"Getting first chat message for chat {chatId}, thread {threadId}, media_group_id {mediaGroupId}"
        # )
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            row = await sqlProvider.executeFetchOne(
                """
                SELECT c.*, u.username, u.full_name FROM chat_messages c
                JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                WHERE
                    c.chat_id = :chatId
                    AND (:threadId IS NULL OR c.thread_id = :threadId)
                    AND c.media_group_id = :mediaGroupId
                ORDER BY c.date ASC
                LIMIT 1
            """,
                {
                    "chatId": chatId,
                    "threadId": threadId,
                    "mediaGroupId": mediaGroupId,
                },
            )
            return dbUtils.sqlToTypedDict(row, ChatMessageDict) if row else None
        except Exception as e:
            logger.error(
                f"Failed to get first chat message for chat {chatId}, "
                f"thread {threadId}, media_group_id {mediaGroupId}: {e}"
            )
            return None

    async def updateChatMessageCategory(
        self,
        chatId: int,
        messageId: MessageIdType,
        messageCategory: MessageCategory,
    ) -> bool:
        """Update the category of a chat message."""
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                UPDATE chat_messages
                SET message_category = :category
                WHERE
                    chat_id = :chatId
                    AND message_id = :messageId
            """,
                {
                    "chatId": chatId,
                    "messageId": messageId,
                    "category": messageCategory,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update category for message {messageId} in chat {chatId}: {e}")
            return False

    async def updateChatMessageMetadata(
        self,
        chatId: int,
        messageId: MessageIdType,
        metadata: str | Any,
    ) -> bool:
        """Update the metadata of a chat message."""
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                UPDATE chat_messages
                SET metadata = :metadata
                WHERE
                    chat_id = :chatId
                    AND message_id = :messageId
            """,
                {
                    "chatId": chatId,
                    "messageId": messageId,
                    "metadata": metadata,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update metadata for message {messageId} in chat {chatId}: {e}")
            return False
