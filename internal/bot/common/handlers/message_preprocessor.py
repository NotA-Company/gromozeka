"""Message preprocessing handler for bot messages.

This module contains the MessagePreprocessorHandler class which processes
incoming messages before they are handled by other handlers. It validates
chat settings, processes different media types (images, stickers), and
saves messages to the database. This handler acts as the first stage in
the message processing pipeline, ensuring all messages are properly
normalized and persisted before being passed to other handlers.
"""

import logging
from typing import Dict, List, Optional, Tuple

import telegram

from internal.bot.common.models import UpdateObjectType
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    CompactMemoryIdsDict,
    EnsuredMessage,
    LLMMessageFormat,
    MessageRecipient,
    MessageSender,
)
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import MessageCategory
from internal.database.utils import DEFAULT_THREAD_ID
from internal.models import MessageId

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class MessagePreprocessorHandler(BaseBotHandler):
    """Preprocesses incoming bot messages before further handling.

    This handler validates chat settings, processes media content (images and
    stickers), and persists messages to the database. It acts as the first
    stage in the message processing pipeline, ensuring all messages are
    properly normalized and persisted before being passed to other handlers.

    Attributes:
        botProvider: The bot platform provider (Telegram or Max).
        db: Database manager instance for persistence operations.
        logger: Logger instance for this handler.
        _searchEnabled: Cached value of ``[search-history].enabled`` at
            handler construction time. Read once in :meth:`__init__` so
            every message dispatch avoids a `ConfigManager` round-trip;
            a config-flip requires a bot restart.
    """

    def __init__(self, *, configManager: ConfigManager, database: Database, botProvider: BotProvider) -> None:
        """Initialize the preprocessor and cache the ``[search-history].enabled`` flag.

        The handler is a hot path — every incoming message flows through
        :meth:`newMessageHandler`. Reading ``[search-history].enabled`` from
        the config manager on every message would do a nested-dict lookup
        per dispatch, so the boolean is captured once at construction
        and stored on ``self._searchEnabled``. A future config flip
        therefore requires a bot restart to take effect, which matches
        the behaviour of every other feature gate in the bot (e.g.
        :class:`ChatSearchHandler`).

        Args:
            configManager: Configuration manager providing bot settings.
            database: Database wrapper for persistence operations.
            botProvider: The bot platform provider (Telegram or Max).
        """
        super().__init__(configManager=configManager, database=database, botProvider=botProvider)
        self._searchEnabled: bool = bool(self.configManager.getSearchHistoryConfig().get("enabled", False))

    async def injectMemories(
        self,
        ensuredMessage: EnsuredMessage,
        embeddingModel: Optional[str],
        queryEmbedding: Optional[List[float]] = None,
    ) -> None:
        """Inject user memories into the ensured message.

        Loads permanent memories (always injected) plus an ephemeral cohort
        chosen by ``queryEmbedding``: when ``None`` the latest memories are
        fetched (newest-updated-first fallback), when a vector is supplied
        :meth:`UserMemoriesRepository.searchMemories` ranks them by cosine
        similarity against ``queryEmbedding`` using ``embeddingModel``.

        Args:
            ensuredMessage: The ensured message to inject memories into.
            embeddingModel: The embedding model name used to produce
                ``queryEmbedding`` (forwarded to ``searchMemories`` for
                per-model vec0 scoping). Ignored when ``queryEmbedding is None``.
            queryEmbedding: A single query embedding vector. ``None`` selects
                ``getLatestMemories`` (newest-first fallback); a non-``None``
                vector selects ``searchMemories(queryEmbedding=...)`` (vec0
                semantic ranking). ``None`` is the path taken when memory
                injection is enabled but no embedding was generated (latest
                retrieval fallback, empty message text, or an embedding failure).
        """

        permanentMemories = await self.cache.getChatUserPermanentMemories(
            ensuredMessage.recipient.id,
            ensuredMessage.sender.id,
            ensuredMessage.threadId or DEFAULT_THREAD_ID,
        )
        shortTermMemories = []
        shortTermScores: Dict[str, float] = {}
        if queryEmbedding is None:
            shortTermMemories = await self.db.userMemories.getLatestMemories(
                chatId=ensuredMessage.recipient.id,
                userId=ensuredMessage.sender.id,
                threadId=ensuredMessage.threadId or DEFAULT_THREAD_ID,
            )
        else:
            shortTermMemories = await self.db.userMemories.searchMemories(
                chatId=ensuredMessage.recipient.id,
                userId=ensuredMessage.sender.id,
                threadId=ensuredMessage.threadId or DEFAULT_THREAD_ID,
                queryEmbedding=queryEmbedding,
                embeddingModel=embeddingModel,
                permanent=False,
            )
            # In semantic mode, extract the scores for later merging.
            # Only include entries with a valid memory_id and a score.
            shortTermScores = {m["memory_id"]: m["score"] for m in shortTermMemories if "score" in m}

        # Write compact memory IDs to metadata["memories"] for persistence and
        # lazy resolution. formatForLLM resolves these IDs to content via
        # cache.getMemoriesByIds at render time — the by-id cache is populated
        # lazily (cache-aside) on that first read, not warmed here. Entries
        # without a usable id are silently dropped (walrus + truthy guard;
        # ``id`` is NotRequired on SingleMemoryDict).
        memoryDict: CompactMemoryIdsDict = {
            "permanentIds": [mid for m in permanentMemories if (mid := m.get("id"))],
            "shortTermIds": [m["memory_id"] for m in shortTermMemories if m["memory_id"]],
        }
        # Only include shortTermScores when we have data (semantic mode only).
        if shortTermScores:
            memoryDict["shortTermScores"] = shortTermScores
        ensuredMessage.metadata["memories"] = memoryDict

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Preprocess incoming messages by processing media and saving to database.

        This method handles the first stage of message processing. It processes
        media attachments (images, stickers, documents) differently based on the
        bot platform (Telegram or Max), determines the message category (user
        or channel), and persists the message to the database.

        Args:
            ensuredMessage: Normalized message object to preprocess.
            updateObj: Original update object from the platform.

        Returns:
            HandlerResultStatus.NEXT if preprocessing successful, ERROR if save failed.

        Raises:
            Exception: If media processing or database operations fail.
        """
        messageCategory: MessageCategory = MessageCategory.USER
        # Telegram has different messages for each media\document
        # While Each Max Message can contain multiple attachments of different types
        match self.botProvider:
            case BotProvider.TELEGRAM:
                media = await self.processTelegramMedia(ensuredMessage)
                if media is not None:
                    ensuredMessage.addMediaProcessingInfo(media, setMediaId=True)
                baseMessage = ensuredMessage.getBaseMessage()
                # If it's an automatic forward from linked channel,
                #  then mark message as channel message, so we can do something in future
                #  (For example forward somewhere)
                if isinstance(baseMessage, telegram.Message) and baseMessage.is_automatic_forward:
                    messageCategory = MessageCategory.CHANNEL
            case BotProvider.MAX:
                for media in await self.processMaxMedia(ensuredMessage):
                    ensuredMessage.addMediaProcessingInfo(media, setMediaId=False)
            case _:
                logger.error(f"Unsupported bot provider: {self.botProvider}")

        if not await self.saveChatMessage(ensuredMessage, messageCategory=messageCategory):
            logger.error("Failed to save chat message")
            return HandlerResultStatus.ERROR

        # After the message is durably saved, generate embeddings + injectMemories if needed
        # (memories require embeddings as well).
        chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)

        chatSearchEnabled = self._searchEnabled and chatSettings[ChatSettingsKey.EMBEDDINGS_ENABLED].toBool()
        memoriesEnabled = chatSettings[ChatSettingsKey.MEMORY_ENABLED].toBool()
        embeddingsEnabled = chatSettings[ChatSettingsKey.EMBEDDINGS_ENABLED].toBool()
        # Semantic ("relevant") memory retrieval is used when MEMORY_ENABLED and
        # EMBEDDINGS_ENABLED are both on; otherwise memory injection falls back to latest.
        chatMemoriesEmbeddingsEnabled = memoriesEnabled and embeddingsEnabled
        memoryInjected = False

        if chatSearchEnabled or chatMemoriesEmbeddingsEnabled:
            messageText: str = await ensuredMessage.formatForLLM(
                self.db, format=LLMMessageFormat.TEXT, useSingleMedia=False, cache=None
            )
            embeddings: Optional[Tuple[str, List[float]]] = None

            # Empty/whitespace message text must never be embedded: a garbage
            # vector pollutes both chat-search recall and memory semantic search.
            # Skip the embedding block so execution falls through to the
            # latest-retrieval fallback below — an empty-text message still gets
            # memory injection, just not a (meaningless) embedding.
            if messageText.strip():
                embeddings = await self.llmService.generateEmbedding(
                    messageText,
                    chatId=ensuredMessage.recipient.id,
                    chatSettings=chatSettings,
                )

            if embeddings is not None:
                if chatSearchEnabled:
                    await self.db.chatEmbeddings.saveMessageEmbedding(
                        chatId=ensuredMessage.recipient.id,
                        messageId=ensuredMessage.messageId,
                        embedding=embeddings[1],
                        model=embeddings[0],
                        date=ensuredMessage.date.isoformat() if ensuredMessage.date is not None else None,
                    )

                if chatMemoriesEmbeddingsEnabled:
                    await self.injectMemories(ensuredMessage, embeddings[0], queryEmbedding=embeddings[1])
                    memoryInjected = True

        # If memory injection was needed, but didn't happen
        # (because of it uses 'latest' or because of some issue)
        if memoriesEnabled and not memoryInjected:
            await self.injectMemories(ensuredMessage, None, queryEmbedding=None)
            memoryInjected = True

        if memoryInjected:
            await self.db.chatMessages.updateChatMessageMetadata(
                chatId=ensuredMessage.recipient.id,
                messageId=ensuredMessage.messageId,
                metadata=ensuredMessage.metadata,
            )

        return HandlerResultStatus.NEXT

    async def newChatMemberHandler(
        self,
        targetChat: MessageRecipient,
        messageId: Optional[MessageId],
        newMember: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """Handle new chat member events and optionally delete join messages.

        This method updates the chat user information in the database, marks
        the user as having joined (not left), and optionally deletes the join
        notification message based on chat settings.

        Args:
            targetChat: Chat where the new member joined.
            messageId: Optional message ID of the join notification.
            newMember: User who joined the chat.
            updateObj: Original update object from the platform.

        Returns:
            HandlerResultStatus.FINAL if join message deleted, NEXT otherwise.

        Raises:
            Exception: If database operations or message deletion fails.
        """
        await self.cache.updateChatUser(
            chatId=targetChat.id,
            userId=newMember.id,
            username=newMember.username,
            fullName=newMember.name,
        )
        await self.setUserMetadata(
            chatId=targetChat.id,
            userId=newMember.id,
            metadata={
                "leftChat": False,
            },
            isUpdate=True,
        )

        chatSettings = await self.getChatSettings(targetChat.id)
        if messageId is not None and chatSettings[ChatSettingsKey.DELETE_JOIN_MESSAGES].toBool():
            logger.info(f"Deleting join message#{messageId} of {newMember} in chat {targetChat.id}")
            await self.deleteMessagesById(targetChat.id, [messageId])
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.NEXT

    async def leftChatMemberHandler(
        self,
        targetChat: MessageRecipient,
        messageId: Optional[MessageId],
        leftMember: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """Handle left chat member events and optionally delete left messages.

        This method updates the chat user information in the database, marks
        the user as having left the chat, and optionally deletes the leave
        notification message based on chat settings.

        Args:
            targetChat: The chat where the member left.
            messageId: Optional message ID associated with the leave event.
            leftMember: The member who left the chat.
            updateObj: The raw update object from the bot platform.

        Returns:
            HandlerResultStatus.FINAL if left message deleted, NEXT otherwise.

        Raises:
            Exception: If database operations or message deletion fails.
        """
        await self.cache.updateChatUser(
            chatId=targetChat.id,
            userId=leftMember.id,
            username=leftMember.username,
            fullName=leftMember.name,
        )
        await self.setUserMetadata(
            chatId=targetChat.id,
            userId=leftMember.id,
            metadata={
                "leftChat": True,
            },
            isUpdate=True,
        )

        chatSettings = await self.getChatSettings(targetChat.id)
        if messageId is not None and chatSettings[ChatSettingsKey.DELETE_LEFT_MESSAGES].toBool():
            logger.info(f"Deleting left message#{messageId} of {leftMember} in chat {targetChat.id}")
            await self.deleteMessagesById(targetChat.id, [messageId])
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.NEXT
