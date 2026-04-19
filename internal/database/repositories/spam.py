"""TODO: write docstring"""

import logging
from typing import List, Optional

from internal.models import MessageIdType

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import SpamMessageDict, SpamReason
from .base import BaseRepository

logger = logging.getLogger(__name__)


class SpamRepository(BaseRepository):
    """TODO: write docstring"""

    __slots__ = ()

    def __init__(self, manager: DatabaseManager):
        super().__init__(manager)

    ###
    # SPAM/Ham Processing functions
    ###

    async def addSpamMessage(
        self,
        chatId: int,
        userId: int,
        messageId: MessageIdType,
        messageText: str,
        spamReason: SpamReason,
        score: float,
        confidence: float,
    ) -> bool:
        """
        Add spam message to the database.

        Args:
            chatId: Chat identifier (used for source routing)
            userId: User identifier
            messageId: Message identifier
            messageText: Message text
            spamReason: Reason for spam classification
            score: Spam score

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        messageId = str(messageId)
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO spam_messages
                    (chat_id, user_id, message_id, text, reason, score, confidence)
                VALUES
                    (:chatId, :userId, :messageId, :messageText, :spamReason, :score, :confidence)
            """,
                {
                    "chatId": chatId,
                    "userId": userId,
                    "messageId": messageId,
                    "messageText": messageText,
                    "spamReason": spamReason.value,
                    "score": score,
                    "confidence": confidence,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add spam message: {e}")
            return False

    async def addHamMessage(
        self,
        chatId: int,
        userId: int,
        messageId: MessageIdType,
        messageText: str,
        spamReason: SpamReason,
        score: float,
        confidence: float,
    ) -> bool:
        """
        Add ham message to the database.

        Args:
            chatId: Chat identifier (used for source routing)
            userId: User identifier
            messageId: Message identifier
            messageText: Message text
            spamReason: Reason for ham classification
            score: Ham score

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        messageId = str(messageId)
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO ham_messages
                    (chat_id, user_id, message_id, text, reason, score, confidence)
                VALUES
                    (:chatId, :userId, :messageId, :messageText, :spamReason, :score, :confidence)
            """,
                {
                    "chatId": chatId,
                    "userId": userId,
                    "messageId": messageId,
                    "messageText": messageText,
                    "spamReason": spamReason.value,
                    "score": score,
                    "confidence": confidence,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add ham message: {e}")
            return False

    async def getSpamMessagesByText(self, text: str, *, dataSource: Optional[str] = None) -> List[SpamMessageDict]:
        """Get spam messages by text."""
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT * FROM spam_messages
                WHERE
                    text = :text
            """,
                {
                    "text": text,
                },
            )
            return [dbUtils.sqlToTypedDict(row, SpamMessageDict) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get spam messages: {e}")
            return []

    async def getSpamMessages(self, limit: int = 1000, *, dataSource: Optional[str] = None) -> List[SpamMessageDict]:
        """Get spam messages."""
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT * FROM spam_messages
                LIMIT :limit
            """,
                {
                    "limit": limit,
                },
            )
            return [dbUtils.sqlToTypedDict(row, SpamMessageDict) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get spam messages: {e}")
            return []

    async def deleteSpamMessagesByUserId(self, chatId: int, userId: int) -> bool:
        """
        Delete spam messages by user id.

        Args:
            chatId: Chat identifier (used for source routing)
            userId: User identifier

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                DELETE FROM spam_messages
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId
            """,
                {
                    "chatId": chatId,
                    "userId": userId,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete spam messages: {e}")
            return False

    async def getSpamMessagesByUserId(
        self, chatId: int, userId: int, *, dataSource: Optional[str] = None
    ) -> List[SpamMessageDict]:
        """
        Get spam messages by user id.

        Args:
            chatId: Chat identifier
            userId: User identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            List of SpamMessageDict
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT * FROM spam_messages
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId
            """,
                {
                    "chatId": chatId,
                    "userId": userId,
                },
            )
            return [dbUtils.sqlToTypedDict(row, SpamMessageDict) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get spam messages: {e}")
            return []
