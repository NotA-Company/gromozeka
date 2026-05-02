"""Repository for managing chat summarization cache operations.

This module provides the ChatSummarizationRepository class which handles
caching of chat message summaries to avoid redundant summarization operations.
It supports storing and retrieving summaries based on chat ID, topic ID,
message ID ranges, and the summarization prompt used.
"""

import hashlib
import logging
from typing import Optional

from internal.models import MessageIdType

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import ChatSummarizationCacheDict
from ..providers.base import ExcludedValue
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ChatSummarizationRepository(BaseRepository):
    """Repository for managing chat summarization cache.

    Provides methods to cache and retrieve chat message summaries based on
    chat ID, topic ID, message ID ranges, and summarization prompts.
    Uses SHA512 hashing to generate unique cache keys.

    Attributes:
        __slots__: Empty tuple - no additional instance attributes beyond base class
    """

    __slots__ = ()

    def __init__(self, manager: DatabaseManager):
        """Initialize the chat summarization repository.

        Args:
            manager: DatabaseManager instance for database operations
        """
        super().__init__(manager)

    ###
    # Chat Summarization
    ###
    def _makeChatSummarizationCSID(
        self,
        chatId: int,
        topicId: Optional[int],
        firstMessageId: MessageIdType,
        lastMessageId: MessageIdType,
        prompt: str,
    ) -> str:
        """
        Make CSID for chat summarization cache using SHA512 hash.

        Args:
            chatId: Chat identifier
            topicId: Optional topic identifier
            firstMessageId: First message ID in the range
            lastMessageId: Last message ID in the range
            prompt: Summarization prompt text

        Returns:
            SHA512 hash string of the cache key components
        """
        cacheKeyString = f"{chatId}:{topicId}_{firstMessageId}:{lastMessageId}-{prompt}"
        return hashlib.sha512(cacheKeyString.encode("utf-8")).hexdigest()

    async def addChatSummarization(
        self,
        chatId: int,
        topicId: Optional[int],
        firstMessageId: MessageIdType,
        lastMessageId: MessageIdType,
        prompt: str,
        summary: str,
    ) -> bool:
        """
        Store chat summarization into cache.

        Args:
            chatId: Chat identifier (used for source routing)
            topicId: Optional topic identifier
            firstMessageId: First message ID in range
            lastMessageId: Last message ID in range
            prompt: Summarization prompt
            summary: Generated summary

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        csid = self._makeChatSummarizationCSID(chatId, topicId, firstMessageId, lastMessageId, prompt)

        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            currentTimestamp = dbUtils.getCurrentTimestamp()
            await sqlProvider.upsert(
                table="chat_summarization_cache",
                values={
                    "csid": csid,
                    "chat_id": chatId,
                    "topic_id": topicId,
                    "first_message_id": firstMessageId,
                    "last_message_id": lastMessageId,
                    "prompt": prompt,
                    "summary": summary,
                    "created_at": currentTimestamp,
                    "updated_at": currentTimestamp,
                },
                conflictColumns=["csid"],
                updateExpressions={
                    "summary": ExcludedValue(),
                    "updated_at": ExcludedValue(),
                },
            )
            logger.debug(f"Added/updated chat summarization cache: csid={csid}")
            return True
        except Exception as e:
            logger.error(f"Failed to add chat summarization cache: {e}")
            return False

    async def getChatSummarization(
        self,
        chatId: int,
        topicId: Optional[int],
        firstMessageId: MessageIdType,
        lastMessageId: MessageIdType,
        prompt: str,
        *,
        dataSource: Optional[str] = None,
    ) -> Optional[ChatSummarizationCacheDict]:
        """Fetch chat summarization from cache.

        Args:
            chatId: Chat identifier
            topicId: Optional topic identifier
            firstMessageId: First message ID in range
            lastMessageId: Last message ID in range
            prompt: Summarization prompt
            dataSource: Optional data source name to query

        Returns:
            ChatSummarizationCacheDict if found, None otherwise
        """
        try:
            csid = self._makeChatSummarizationCSID(chatId, topicId, firstMessageId, lastMessageId, prompt)
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            row = await sqlProvider.executeFetchOne(
                """
                SELECT * FROM chat_summarization_cache
                WHERE
                    csid = :csid
                """,
                {"csid": csid},
            )

            return dbUtils.sqlToTypedDict(row, ChatSummarizationCacheDict) if row else None

        except Exception as e:
            logger.error(f"Failed to get chat summarization cache: {e}")
            return None
