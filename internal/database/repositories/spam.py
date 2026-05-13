"""Repository for managing spam and ham message storage and retrieval.

This module provides the SpamRepository class which handles database operations
for storing and retrieving spam and ham messages, including their classification
scores, confidence levels, and reasons. The repository supports multi-source
database routing based on chat IDs, allowing for flexible data distribution
across different database instances.

Example:
    >>> from internal.database.manager import DatabaseManager
    >>> from internal.database.repositories.spam import SpamRepository
    >>>
    >>> manager = DatabaseManager(config)
    >>> spam_repo = SpamRepository(manager)
    >>>
    >>> # Add a spam message
    >>> await spam_repo.addSpamMessage(
    ...     chatId=123456789,
    ...     userId=987654321,
    ...     messageId=1,
    ...     messageText="Spam content",
    ...     spamReason=SpamReason.KEYWORD,
    ...     score=0.95,
    ...     confidence=0.9
    ... )
    >>>
    >>> # Retrieve spam messages
    >>> messages = await spam_repo.getSpamMessages(limit=10)
"""

import logging
from typing import List, Optional

from internal.models import MessageId

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import SpamMessageDict, SpamReason
from .base import BaseRepository

logger = logging.getLogger(__name__)


class SpamRepository(BaseRepository):
    """Repository for managing spam and ham message database operations.

    Provides methods to add, retrieve, and delete spam and ham messages
    with support for multi-source database routing based on chat IDs. This
    repository extends BaseRepository and leverages the DatabaseManager for
    provider routing and connection management.

    Attributes:
        manager: DatabaseManager instance for database operations and provider routing

    Note:
        All write operations are routed based on chatId mapping and cannot write to
        readonly sources. Read operations can optionally specify a dataSource for
        explicit routing or rely on chatId-based routing.
    """

    __slots__ = ()

    def __init__(self, manager: DatabaseManager):
        """Initialize the SpamRepository.

        Args:
            manager: DatabaseManager instance for database operations and provider routing
        """
        super().__init__(manager)

    ###
    # SPAM/Ham Processing functions
    ###

    async def addSpamMessage(
        self,
        chatId: int,
        userId: int,
        messageId: MessageId,
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
            score: Spam score (typically 0.0 to 1.0)
            confidence: Confidence level of the classification (typically 0.0 to 1.0)

        Returns:
            bool: True if successful, False otherwise

        Raises:
            Exception: If database operation fails (caught and logged, returns False)

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO spam_messages
                    (chat_id, user_id, message_id, text, reason, score, confidence,
                     created_at, updated_at)
                VALUES
                    (:chatId, :userId, :messageId, :messageText, :spamReason, :score,
                     :confidence, :createdAt, :updatedAt)
            """,
                {
                    "chatId": chatId,
                    "userId": userId,
                    "messageId": messageId,
                    "messageText": messageText,
                    "spamReason": spamReason.value,
                    "score": score,
                    "confidence": confidence,
                    "createdAt": dbUtils.getCurrentTimestamp(),
                    "updatedAt": dbUtils.getCurrentTimestamp(),
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
        messageId: MessageId,
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
            score: Ham score (typically 0.0 to 1.0)
            confidence: Confidence level of the classification (typically 0.0 to 1.0)

        Returns:
            bool: True if successful, False otherwise

        Raises:
            Exception: If database operation fails (caught and logged, returns False)

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO ham_messages
                    (chat_id, user_id, message_id, text, reason, score, confidence,
                     created_at, updated_at)
                VALUES
                    (:chatId, :userId, :messageId, :messageText, :spamReason, :score,
                     :confidence, :createdAt, :updatedAt)
            """,
                {
                    "chatId": chatId,
                    "userId": userId,
                    "messageId": messageId,
                    "messageText": messageText,
                    "spamReason": spamReason.value,
                    "score": score,
                    "confidence": confidence,
                    "createdAt": dbUtils.getCurrentTimestamp(),
                    "updatedAt": dbUtils.getCurrentTimestamp(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add ham message: {e}")
            return False

    async def getSpamMessagesByText(self, text: str, *, dataSource: Optional[str] = None) -> List[SpamMessageDict]:
        """
        Get spam messages by text.

        Args:
            text: Message text to search for (case-insensitive comparison)
            dataSource: Optional data source name for explicit routing

        Returns:
            List of SpamMessageDict matching the text, empty list on error

        Raises:
            Exception: If database operation fails (caught and logged, returns empty list)
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
            caseInsensitiveComparison = sqlProvider.getCaseInsensitiveComparison("text", "text")
            rows = await sqlProvider.executeFetchAll(
                f"""
                SELECT * FROM spam_messages
                WHERE
                    {caseInsensitiveComparison}
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
        """
        Get spam messages.

        Args:
            limit: Maximum number of messages to retrieve (default: 1000)
            dataSource: Optional data source name for explicit routing

        Returns:
            List of SpamMessageDict, empty list on error

        Raises:
            Exception: If database operation fails (caught and logged, returns empty list)
        """
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

        Raises:
            Exception: If database operation fails (caught and logged, returns False)

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
            chatId: Chat identifier (used for source routing)
            userId: User identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            List of SpamMessageDict, empty list on error

        Raises:
            Exception: If database operation fails (caught and logged, returns empty list)
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
