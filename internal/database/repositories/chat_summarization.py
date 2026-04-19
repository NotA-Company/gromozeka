"""TODO: write docstring"""

import hashlib
import logging
from typing import Optional

from internal.models import MessageIdType

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import ChatSummarizationCacheDict
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ChatSummarizationRepository(BaseRepository):
    """TODO: write docstring"""

    __slots__ = ()

    def __init__(self, manager: DatabaseManager):
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
            await sqlProvider.execute(
                """
                INSERT INTO chat_summarization_cache
                    (csid, chat_id, topic_id, first_message_id, last_message_id,
                        prompt, summary, created_at, updated_at)
                VALUES (:csid, :chatId, :topicId, :firstMessageId, :lastMessageId,
                        :prompt, :summary, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(csid) DO UPDATE SET
                    summary = excluded.summary,
                    updated_at = CURRENT_TIMESTAMP
                """,
                {
                    "csid": csid,
                    "chatId": chatId,
                    "topicId": topicId,
                    "firstMessageId": firstMessageId,
                    "lastMessageId": lastMessageId,
                    "prompt": prompt,
                    "summary": summary,
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
        """Fetch chat summarization from cache by chatId, topicId, firstMessageId, lastMessageId and prompt"""
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
