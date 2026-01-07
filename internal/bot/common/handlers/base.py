"""
Base handler module for Gromozeka Telegram bot, dood!

This module provides the foundational [`BaseBotHandler`](internal/bot/handlers/base.py:66) class that all bot handlers
inherit from. It includes core functionality for message handling, chat settings management,
user data management, media processing, and database operations, dood!

The module defines:
- [`HandlerResultStatus`](internal/bot/handlers/base.py:56): Enum for handler processing results
- [`BaseBotHandler`](internal/bot/handlers/base.py:66): Base class with common handler functionality

Key Features:
- Chat settings and user data management with caching
- Media processing (images, stickers) with LLM integration
- Message sending with MarkdownV2 support
- Database operations for chats, users, and messages
- Admin permission checking
- Command handler discovery via decorators
"""

import asyncio
import datetime
import hashlib
import json
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

import magic
import telegram
import telegram._files._basemedium as telegramBasemedium

import lib.max_bot.models as maxModels
import lib.utils as utils
from internal.bot import constants
from internal.bot.common.bot import TheBot
from internal.bot.common.models import CallbackButton, TypingAction, UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatTier,
    ChatType,
    CommandHandlerInfoV2,
    CommandHandlerMixin,
    EnsuredMessage,
    FormatEntity,
    LLMMessageFormat,
    MediaProcessingInfo,
    MentionCheckResult,
    MessageRecipient,
    MessageSender,
    MessageType,
    OutputFormat,
    UserMetadataDict,
)
from internal.config.manager import ConfigManager
from internal.database.models import ChatInfoDict, ChatUserDict, MediaStatus, MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.models import MessageIdType
from internal.services.cache import CacheService
from internal.services.llm import LLMService
from internal.services.queue_service import QueueService, makeEmptyAsyncTask
from internal.services.storage import StorageService
from lib.ai import (
    LLMManager,
    ModelImageMessage,
    ModelMessage,
    ModelResultStatus,
)

logger = logging.getLogger(__name__)

__all__ = ["HandlerResultStatus", "BaseBotHandler"]


class HandlerResultStatus(Enum):
    """
    Enum representing the result status of handler processing, dood!

    This enum is used to control the flow of message processing through
    multiple handlers in the handler chain.

    Attributes:
        FINAL: Processing completed successfully, no further handlers needed
        SKIPPED: Handler skipped processing (not applicable to this message)
        NEXT: Processing completed, continue to next handler in chain
        ERROR: Processing error occurred but can continue to next handler
        FATAL: Fatal error occurred, stop all processing immediately
    """

    FINAL = "final"  # Processed and no need further processing
    SKIPPED = "skipped"  # Skipped processing
    NEXT = "next"  # Processed, need to process further
    ERROR = "error"  # Processing error (can be processed further)
    FATAL = "fatal"  # Fatal error, need to stop processing

    def isFinalState(self) -> bool:
        return self in (HandlerResultStatus.FINAL, HandlerResultStatus.FATAL)

    def needLogs(self) -> bool:
        return self not in (HandlerResultStatus.SKIPPED,)


class BaseBotHandler(CommandHandlerMixin):
    """
    Base handler class providing core functionality for all bot handlers, dood!

    This class serves as the foundation for all specialized bot handlers, providing
    common functionality for message handling, chat management, user data storage,
    media processing, and database operations.

    The class integrates with:
    - [`ConfigManager`](internal/config/manager.py): For bot configuration
    - [`DatabaseWrapper`](internal/database/wrapper.py): For data persistence
    - [`LLMManager`](lib/ai/manager.py): For AI model interactions
    - [`CacheService`](internal/services/cache/service.py): For performance optimization
    - [`QueueService`](internal/services/queue/service.py): For background task management

    Attributes:
        configManager: Configuration manager instance
        config: Bot configuration dictionary
        db: Database wrapper for data operations
        llmManager: LLM manager for AI model access
        botOwners: List of bot owner usernames (lowercase)
        chatDefaults: Default settings for all chats
        cache: Cache service instance
        queueService: Queue service for background tasks
    """

    def __init__(
        self,
        configManager: ConfigManager,
        database: DatabaseWrapper,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ):
        """
        Initialize the base handler with required services, dood!

        Args:
            configManager: Configuration manager providing bot settings
            database: Database wrapper for data persistence
            llmManager: LLM manager for AI model operations
        """
        # Initialize the mixin (discovers handlers)
        super().__init__()

        self.configManager = configManager
        self.config = configManager.getBotConfig()
        self.db = database
        self.llmManager = llmManager
        self.botProvider = botProvider

        self.cache = CacheService.getInstance()
        self.queueService = QueueService.getInstance()
        self.storage = StorageService.getInstance()
        self.llmService = LLMService.getInstance()

        # self._tgBot: Optional[telegramExt.ExtBot] = None
        # self._maxBot: Optional[libMax.MaxBotClient] = None
        self._bot: Optional[TheBot] = None

    def getCommandHandlersV2(self) -> Sequence[CommandHandlerInfoV2]:
        """
        Get all command handlers auto-discovered via decorators, dood!

        Returns:
            Sequence of [`CommandHandlerInfo`](internal/bot/models/command_handlers.py) objects containing
            handler metadata (command names, descriptions, handler functions)
        """
        return super().getCommandHandlersV2()

    def injectBot(self, bot: TheBot) -> None:
        """
        Inject the bot instance into the handler for bot operations.

        Args:
            bot: The bot instance to inject for message handling and API operations

        Returns:
            None
        """
        self._bot = bot

    ###
    # Chat settings Managenent
    ###

    def getChatSettings(
        self,
        chatId: Optional[int],
        *,
        returnDefault: bool = True,
        chatType: Optional[ChatType] = None,
        chatTier: Optional[ChatTier] = None,
    ) -> Dict[ChatSettingsKey, ChatSettingsValue]:
        """
        TODO: rewrite docstring
        Get chat settings with optional default fallback, dood!

        Retrieves settings from cache, merging with defaults if requested.
        If chatId is None, returns only default settings.

        Args:
            chatId: Telegram chat ID, or None for defaults only
            returnDefault: If True, merge with default settings; if False, return only custom settings
            chatType: Chat type to get defaults for (usefull only if chatId is None)

        Returns:
            Dictionary mapping [`ChatSettingsKey`](internal/bot/models/chat_settings.py)
                            to [`ChatSettingsValue`](internal/bot/models/chat_settings.py)
        """
        if chatId is not None and returnDefault:
            chatSettings = self.cache.getCachedChatSettings(chatId)
            if chatSettings is not None:
                return chatSettings

        defaultSettings: Dict[ChatSettingsKey, ChatSettingsValue] = {}
        if chatId is None and chatType is None:
            raise ValueError("Either chatId or chatType should be not None")

        # TODO: Currently we support only Private and Groups
        # In case of Channels support, we need to think something
        if chatId is not None:
            chatType = ChatType.PRIVATE if chatId > 0 else ChatType.GROUP
        if chatType != ChatType.PRIVATE:
            chatType = ChatType.GROUP

        if returnDefault:
            defaultSettings = self.cache.getDefaultChatSettings(None)
            defaultSettings.update(self.cache.getDefaultChatSettings(chatType))

        if chatId is None:
            chatSettings: Optional[Dict[ChatSettingsKey, ChatSettingsValue]] = {}
        else:
            chatSettings = self.cache.getChatSettings(chatId)

        if chatTier is None:
            chatTier = self.getChatTier(chatSettings)

        if chatTier is None and ChatSettingsKey.BASE_TIER in defaultSettings:
            chatTier = ChatTier.fromStr(defaultSettings[ChatSettingsKey.BASE_TIER].toStr())

        tierSettings = self.cache.getDefaultChatSettings(f"tier-{chatTier}")
        if returnDefault:
            defaultSettings.update(tierSettings)

        if chatId is None:
            return defaultSettings

        # TODO: Add ability to revert some settings to default
        #  if they are not allowed to be changed on given tier
        chatSettings = {**defaultSettings, **chatSettings}

        if returnDefault:
            # Update cached settings only if we added defaults as well
            self.cache.cacheChatSettings(chatId, chatSettings)
        return chatSettings

    def setChatSetting(
        self, chatId: int, key: ChatSettingsKey, value: ChatSettingsValue, *, user: MessageSender
    ) -> None:
        """
        Set a specific chat setting, dood!

        Updates the setting in cache, which will be persisted to database.

        Args:
            chatId: Telegram chat ID
            key: Setting key from [`ChatSettingsKey`](internal/bot/models/chat_settings.py) enum
            value: Setting value as [`ChatSettingsValue`](internal/bot/models/chat_settings.py)

        Note:
            This method directly updates the cache. Consider whether this setting
            should be validated before being applied.
        """
        self.cache.setChatSetting(chatId, key, value, userId=user.id)

    def unsetChatSetting(self, chatId: int, key: ChatSettingsKey) -> None:
        """
        Remove a specific chat setting, reverting to default, dood!

        Args:
            chatId: Telegram chat ID
            key: Setting key from [`ChatSettingsKey`](internal/bot/models/chat_settings.py) enum to remove
        """
        self.cache.unsetChatSetting(chatId=chatId, key=key)

    def getChatTier(self, chatSettings: Dict[ChatSettingsKey, ChatSettingsValue]) -> Optional[ChatTier]:
        """
        Determine chat tier based on settings, checking paid tier first.

        Args:
            chatSettings: Dictionary containing chat settings with tier configuration.

        Returns:
            ChatTier if paid tier is active or base tier is set, None otherwise.
        """
        if ChatSettingsKey.PAID_TIER in chatSettings and ChatSettingsKey.PAID_TIER_UNTILL_TS in chatSettings:
            paidUntil = chatSettings[ChatSettingsKey.PAID_TIER_UNTILL_TS].toFloat()
            if paidUntil >= time.time():
                return ChatTier.fromStr(chatSettings[ChatSettingsKey.PAID_TIER].toStr())

        if ChatSettingsKey.BASE_TIER in chatSettings:
            return ChatTier.fromStr(chatSettings[ChatSettingsKey.BASE_TIER].toStr())

        return None

    ###
    # User Data Management
    ###

    def _updateEMessageUserData(self, ensuredMessage: EnsuredMessage) -> None:
        """
        Update an [`EnsuredMessage`](internal/bot/models/ensured_message.py) with current user data, dood!

        Internal helper method to inject user data into message objects.

        Args:
            ensuredMessage: Message object to update with user data
        """
        ensuredMessage.setUserData(
            self.cache.getChatUserData(chatId=ensuredMessage.recipient.id, userId=ensuredMessage.sender.id)
        )

    async def checkEMMentionsMe(self, ensuredMessage: EnsuredMessage) -> MentionCheckResult:
        """
        Check if a message mentions the bot, dood!

        Checks for bot username mention or custom nicknames configured in chat settings.

        Args:
            ensuredMessage: Message to check for mentions

        Returns:
            [`MentionCheckResult`](internal/bot/models/ensured_message.py) indicating if bot was mentioned
        """
        chatSettings = self.getChatSettings(ensuredMessage.recipient.id)

        username: Optional[str] = await self.getBotUserName()
        if username is not None:
            username = "@" + username.lower().lstrip("@")

        return ensuredMessage.checkHasMention(
            username=username,
            customMentions=chatSettings[ChatSettingsKey.BOT_NICKNAMES].toList(),
        )

    ###
    # Different helpers
    ###

    async def getBotId(self) -> int:
        if self._bot is None:
            raise ValueError("Bot is not initialized")
        return await self._bot.getBotId()

    async def getBotUserName(self) -> Optional[str]:
        if self._bot is None:
            raise ValueError("Bot is not initialized")
        return await self._bot.getBotUserName()

    async def isAdmin(
        self, user: MessageSender, chat: Optional[MessageRecipient] = None, allowBotOwners: bool = True
    ) -> bool:
        """
        Check if a user is an admin or bot owner, dood!

        If chat is None, only checks bot owner status.
        If chat is provided, checks both bot owners and chat administrators.

        Args:
            user: Telegram user to check
            chat: Optional chat to check admin status in
            allowBotOwners: If True, bot owners are always considered admins

        Returns:
            True if user is admin/owner, False otherwise
        """
        if self._bot is None:
            raise ValueError("Bot is not initialized")

        return await self._bot.isAdmin(user=user, chat=chat, allowBotOwners=allowBotOwners)

    async def editMessage(
        self,
        messageId: MessageIdType,
        chatId: int,
        *,
        text: Optional[str] = None,
        inlineKeyboard: Optional[Sequence[Sequence[CallbackButton]]] = None,
        useMarkdown: bool = True,
    ) -> bool:
        if self._bot is None:
            raise ValueError("Bot is not initialized")
        return await self._bot.editMessage(
            messageId=messageId,
            chatId=chatId,
            text=text,
            inlineKeyboard=inlineKeyboard,
            useMarkdown=useMarkdown,
        )

    async def sendMessage(
        self,
        replyToMessage: Optional[EnsuredMessage],
        messageText: Optional[str] = None,
        *,
        addMessagePrefix: str = "",
        photoData: Optional[bytes] = None,
        sendMessageKWargs: Optional[Dict[str, Any]] = None,
        tryMarkdownV2: bool = True,
        tryParseInputJSON: Optional[bool] = None,  # False - do not try, True - try, None - try to detect
        sendErrorIfAny: bool = True,
        skipLogs: bool = False,
        mediaPrompt: Optional[str] = None,
        messageCategory: MessageCategory = MessageCategory.BOT,
        inlineKeyboard: Optional[Sequence[Sequence[CallbackButton]]] = None,
        typingManager: Optional[TypingManager] = None,
        splitIfTooLong: bool = True,
        chatId: Optional[int] = None,
        threadId: Optional[int] = None,
        notify: Optional[bool] = None,
        attachmentList: Optional[Sequence[Tuple[bytes, MessageType]]] = None,
    ) -> List[EnsuredMessage]:
        if self._bot is None:
            raise ValueError("Bot is not initialized")
        ret = await self._bot.sendMessage(
            replyToMessage=replyToMessage,
            messageText=messageText,
            addMessagePrefix=addMessagePrefix,
            photoData=photoData,
            sendMessageKWargs=sendMessageKWargs,
            tryMarkdownV2=tryMarkdownV2,
            sendErrorIfAny=sendErrorIfAny,
            skipLogs=skipLogs,
            inlineKeyboard=inlineKeyboard,
            typingManager=typingManager,
            splitIfTooLong=splitIfTooLong,
            chatId=chatId,
            threadId=threadId,
            notify=notify,
            attachmentList=attachmentList,
        )

        for ensuredReplyMessage in ret:
            if addMessagePrefix:
                replyText = ensuredReplyMessage.messageText
                if replyText.startswith(addMessagePrefix):
                    replyText = replyText[len(addMessagePrefix) :]
                    ensuredReplyMessage.messageText = replyText
            replyMessage = ensuredReplyMessage.getBaseMessage()
            if isinstance(replyMessage, telegram.Message):
                media = await self.processTelegramMedia(ensuredReplyMessage, mediaPrompt)
                if media is not None:
                    ensuredReplyMessage.addMediaProcessingInfo(media)
            elif isinstance(replyMessage, maxModels.Message) and replyMessage.body.attachments:
                mediaList = await self.processMaxMedia(ensuredReplyMessage, mediaPrompt)
                for media in mediaList:
                    ensuredReplyMessage.addMediaProcessingInfo(media)

            await self.saveChatMessage(ensuredReplyMessage, messageCategory=messageCategory)

        return ret

    async def deleteMessage(self, ensuredMessage: EnsuredMessage) -> bool:
        """Delete a message from the chat.

        Args:
            ensuredMessage: The message to delete, containing recipient and message ID

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        if self._bot is None:
            raise ValueError("Bot is not initialized")
        return await self._bot.deleteMessage(ensuredMessage)

    async def deleteMessagesById(self, chatId: int, messageIds: List[MessageIdType]) -> bool:
        """Delete multiple messages by their IDs in the specified chat.

        Args:
            chatId: The ID of the chat where messages should be deleted
            messageIds: List of message IDs to delete (int for Telegram, str for Max)

        Returns:
            bool: True if deletion was successful, False otherwise
        """

        if self._bot is None:
            raise ValueError("Bot is not initialized")
        return await self._bot.deleteMessagesById(chatId=chatId, messageIds=messageIds)

    ###
    # Chat Management
    ###

    async def getThreadByMessageForLLM(
        self,
        ensuredMessage: EnsuredMessage,
        condenseThread: bool = True,
    ) -> Sequence[ModelMessage]:

        dbMessage = self.db.getChatMessageByMessageId(ensuredMessage.recipient.id, ensuredMessage.messageId)
        if dbMessage is None:
            return []

        chatId = dbMessage["chat_id"]
        chatSettings = self.getChatSettings(chatId, chatType=ensuredMessage.recipient.chatType)
        llmMFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

        outputFormat = OutputFormat.MARKDOWN
        match self.botProvider:
            case BotProvider.TELEGRAM:
                outputFormat = OutputFormat.MARKDOWN_TG
            case BotProvider.MAX:
                outputFormat = OutputFormat.MARKDOWN_MAX

        # TODO: Think, should we add system prompt or not? Dunno
        ret: List[ModelMessage] = [
            ModelMessage(
                role="system",
                content=chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr()
                + "\n"
                + chatSettings[ChatSettingsKey.CHAT_PROMPT_SUFFIX].toStr(),
            ),
        ]

        if dbMessage["root_message_id"] is None:
            eMessage = EnsuredMessage.fromDBChatMessage(dbMessage, self.db)
            self._updateEMessageUserData(eMessage)
            return ret + [
                await eMessage.toModelMessage(
                    self.db,
                    format=llmMFormat,
                    outputFormat=outputFormat,
                    role="user" if dbMessage["message_category"] == "user" else "assistant",
                )
            ]

        dbMessageList = self.db.getChatMessagesByRootId(
            dbMessage["chat_id"],
            rootMessageId=dbMessage["root_message_id"],
            threadId=dbMessage["thread_id"],
        )

        if not dbMessageList:
            logger.error(f"No messages found for root message ID {dbMessage['root_message_id']}")
            return []

        # While condensing, keep the first and last message
        keepFirstN = 1
        keepLastN = 1

        eRootMessage = EnsuredMessage.fromDBChatMessage(dbMessageList[0], self.db)
        self._updateEMessageUserData(eRootMessage)
        condenseCache = eRootMessage.metadata.get("condensedThread", [])
        if condenseCache and condenseThread:
            # First - add skipped messages to result.
            # It should be ony starting message
            for i in range(min(keepFirstN, len(dbMessageList))):
                eMessage = EnsuredMessage.fromDBChatMessage(dbMessageList[i], self.db)
                self._updateEMessageUserData(eMessage)
                ret.append(
                    await eMessage.toModelMessage(
                        self.db,
                        format=llmMFormat,
                        outputFormat=outputFormat,
                        role="user" if dbMessageList[i]["message_category"] == "user" else "assistant",
                    )
                )

            # For each summary:
            # Add summary message to result
            # And skip summaried messages
            for condensedMessage in condenseCache:
                # If we'll decide to condenseContext, skip summary message from condensing
                keepFirstN += 1
                ret.append(ModelMessage(role="user", content=condensedMessage["text"]))
                lastDT = datetime.datetime.fromtimestamp(condensedMessage["tillTS"])
                skippedMessages = 0
                for dbMessage in dbMessageList:
                    skippedMessages += 1
                    if dbMessage["message_id"] == condensedMessage["tillMessageId"] or dbMessage["date"] > lastDT:
                        break
                dbMessageList = dbMessageList[skippedMessages:]

        for dbMessage in dbMessageList:
            eMessage = EnsuredMessage.fromDBChatMessage(dbMessage, self.db)
            self._updateEMessageUserData(eMessage)
            ret.append(
                await eMessage.toModelMessage(
                    self.db,
                    format=llmMFormat,
                    outputFormat=outputFormat,
                    role="user" if dbMessage["message_category"] == "user" else "assistant",
                )
            )

        if not condenseThread:
            return ret

        # Condense thread if needed
        llmModel = chatSettings[ChatSettingsKey.CHAT_MODEL].toModel(self.llmManager)
        # If we need condencind, assume that we sould use no more than 50% of the context size
        maxTokens = int(llmModel.contextSize * 0.5)

        currentTokens = llmModel.getEstimateTokensCount([v.toDict() for v in ret])
        if currentTokens < maxTokens:
            return ret

        condensedRet = await self.llmService.condenseContext(
            ret,
            model=llmModel,
            keepFirstN=keepFirstN,
            keepLastN=keepLastN,
            maxTokens=maxTokens,
            condensingModel=chatSettings[ChatSettingsKey.CONDENSING_MODEL].toModel(self.llmManager),
            condensingPrompt=chatSettings[ChatSettingsKey.CONDENSING_PROMPT].toStr(),
        )

        # -1 is last element, so -keepLastN to skip skipped elements to get last condensed message
        lastCondensedMessage = dbMessageList[-1 - keepLastN]
        # +1 because of system prompt

        # logger.debug("CONDENSING DEBUG")
        # logger.debug(f"ret   = {condensedRet}")
        # logger.debug(f"cache = {condenseCache}")
        # logger.debug(f"lastM = {lastCondensedMessage}")

        currentTokens = llmModel.getEstimateTokensCount([v.toDict() for v in condensedRet])
        if currentTokens > maxTokens:
            # If there are too many condensed entries in cache, condense them as well
            keepFirstN = 1
            condensedRet = await self.llmService.condenseContext(
                condensedRet,
                model=llmModel,
                keepFirstN=keepFirstN,
                keepLastN=keepLastN,
                maxTokens=maxTokens,
                condensingModel=chatSettings[ChatSettingsKey.CONDENSING_MODEL].toModel(self.llmManager),
                condensingPrompt=chatSettings[ChatSettingsKey.CONDENSING_PROMPT].toStr(),
            )
            # We'll need to rewrite cache, so empty it here
            condenseCache = []

        for i in range(keepFirstN + 1, len(condensedRet) - keepLastN):
            condenseCache.append(
                {
                    "text": condensedRet[i].content,
                    "tillMessageId": lastCondensedMessage["message_id"],
                    "tillTS": lastCondensedMessage["date"].timestamp(),
                }
            )

        # logger.debug(f"cache2 = {condenseCache}")
        eRootMessage.metadata["condensedThread"] = condenseCache
        self.db.updateChatMessageMetadata(
            chatId=eRootMessage.recipient.id,
            messageId=eRootMessage.messageId,
            metadata=eRootMessage.metadata,
        )

        return condensedRet

    def getChatInfo(self, chatId: int) -> Optional[ChatInfoDict]:
        """
        Get chat information from cache or database, dood!

        Args:
            chatId: Telegram chat ID

        Returns:
            Chat info dictionary as [`ChatInfoDict`](internal/database/models.py), or None if not found
        """
        return self.cache.getChatInfo(chatId)

    async def updateChatInfo(self, message: EnsuredMessage) -> None:
        """
        Updates chat information and topic details based on the message received.

        Fetches and caches chat info if it's older than 12 hours. Also updates topic
        information for Telegram forum topics or sets default topic for other providers.

        Args:
            message: The message containing chat and topic information to update
        """
        if self._bot is None:
            raise ValueError("Bot is not initialized")

        chatId = message.recipient.id
        storedChatInfo = self.getChatInfo(chatId=chatId)
        needChange = True
        now = datetime.datetime.now()
        if storedChatInfo is not None:
            timeDiff = now - storedChatInfo["updated_at"]
            needChange = timeDiff.total_seconds() > 60 * 60 * 12

        if needChange:
            chatInfo = await self._bot.getChatInfo(message)
            self.cache.setChatInfo(chatId, chatInfo)

        # Update topics info as well
        if self.botProvider == BotProvider.TELEGRAM:
            try:
                # TODO: Actually topic name and emoji could be changed after that
                # but currently we have no way to know it (except of see
                # https://docs.python-telegram-bot.org/en/stable/telegram.forumtopicedited.html )
                # Think about it later
                if message.isTopicMessage:
                    baseMessage = message.getBaseMessage()
                    if not isinstance(baseMessage, telegram.Message):
                        raise ValueError("Base message is not a telegram.Message")
                    repliedMessage = baseMessage.reply_to_message
                    if repliedMessage and repliedMessage.forum_topic_created:
                        self.updateTopicInfo(
                            chatId=message.recipient.id,
                            topicId=message.threadId,
                            iconColor=repliedMessage.forum_topic_created.icon_color,
                            customEmojiId=repliedMessage.forum_topic_created.icon_custom_emoji_id,
                            name=repliedMessage.forum_topic_created.name,
                        )
                else:
                    self.updateTopicInfo(chatId=message.recipient.id, topicId=message.threadId)
            except Exception as e:
                logger.error(f"Error updating chat info: {e}")
        elif self.botProvider == BotProvider.MAX:
            # No topics in Max, but for consistency assume there is one default topic
            self.updateTopicInfo(chatId=message.recipient.id, topicId=message.threadId)

        else:
            logger.error(f"Updating chat info for {self.botProvider} is not implemented yet")

    def updateTopicInfo(
        self,
        chatId: int,
        topicId: Optional[int],
        iconColor: Optional[int] = None,
        customEmojiId: Optional[str] = None,
        name: Optional[str] = None,
        force: bool = False,
    ) -> None:
        """
        Update forum topic information in cache and database, dood!

        Only updates if topic info has changed or force is True.
        Uses cache to avoid unnecessary database writes.

        Args:
            chatId: Telegram chat ID
            topicId: Forum topic ID (None or 0 for general topic)
            iconColor: Topic icon color code
            customEmojiId: Custom emoji ID for topic icon
            name: Topic name
            force: If True, update even if already in DB
        """
        _topicId = topicId if topicId is not None else 0
        storedTopicInfo = self.cache.getChatTopicInfo(chatId=chatId, topicId=_topicId)

        if not force and storedTopicInfo:
            # No need to rewrite topic info as for Telegram
            #  we always get initial topic info, not current one
            return

        self.cache.setChatTopicInfo(
            chatId=chatId,
            topicId=_topicId,
            info={
                "chat_id": chatId,
                "topic_id": _topicId,
                "icon_color": iconColor,
                "icon_custom_emoji_id": customEmojiId,
                "name": name,
                "created_at": datetime.datetime.now(),
                "updated_at": datetime.datetime.now(),
            },
        )

    async def saveChatMessage(self, message: EnsuredMessage, messageCategory: MessageCategory) -> bool:
        """
        Save a chat message to the database with full context, dood!

        Handles message threading, reply chains, chat/topic info updates,
        and user information updates. Automatically determines root message
        for reply chains.

        Args:
            message: Message to save as [`EnsuredMessage`](internal/bot/models/ensured_message.py)
            messageCategory: Message category from [`MessageCategory`](internal/database/models.py) enum

        Returns:
            True if saved successfully, False if message type unsupported
        """
        chat = message.recipient
        sender = message.sender

        if message.messageType == MessageType.UNKNOWN:
            logger.error(f"Unsupported message type: {message.messageType}")
            return False

        replyId = message.replyId
        rootMessageId = message.messageId
        if message.isReply and replyId:
            parentMsg = self.db.getChatMessageByMessageId(
                chatId=chat.id,
                messageId=replyId,
            )
            if parentMsg:
                rootMessageId = parentMsg["root_message_id"]

        await self.updateChatInfo(message)

        self.db.updateChatUser(
            chatId=chat.id,
            userId=sender.id,
            username=sender.username,
            fullName=sender.name,
        )

        self.db.saveChatMessage(
            date=message.date,
            chatId=chat.id,
            userId=sender.id,
            messageId=message.messageId,
            replyId=replyId,
            threadId=message.threadId,
            messageText=message.messageText,
            messageType=message.messageType,
            messageCategory=messageCategory,
            rootMessageId=rootMessageId,
            quoteText=message.quoteText,
            mediaId=message.mediaId,
            markup=utils.jsonDumps(FormatEntity.toDictList(message.formatEntities)),
            metadata=utils.jsonDumps(message.metadata),
            mediaGroupId=message.mediaGroupId,
        )

        return True

    def parseUserMetadata(self, userInfo: Optional[ChatUserDict]) -> UserMetadataDict:
        """
        Parse user metadata from database record, dood!

        Args:
            userInfo: User info dictionary from database as [`ChatUserDict`](internal/database/models.py)

        Returns:
            Parsed metadata dictionary as [`UserMetadataDict`](internal/bot/models/user_metadata.py)
        """
        if userInfo is None:
            return {}

        metadataStr = userInfo["metadata"]
        if metadataStr:
            return json.loads(metadataStr)
        return {}

    def setUserMetadata(self, chatId: int, userId: int, metadata: UserMetadataDict, isUpdate: bool = False) -> None:
        """
        Set or update user metadata in database, dood!

        Args:
            chatId: Telegram chat ID
            userId: Telegram user ID
            metadata: Metadata dictionary as [`UserMetadataDict`](internal/bot/models/user_metadata.py)
            isUpdate: If True, merge with existing metadata; if False, replace completely
        """
        if isUpdate:
            userInfo = self.db.getChatUser(chatId=chatId, userId=userId)
            metadata = {**self.parseUserMetadata(userInfo), **metadata}

        metadataStr = utils.jsonDumps(metadata)
        self.db.updateUserMetadata(chatId=chatId, userId=userId, metadata=metadataStr)

    async def startTyping(
        self,
        ensuredMessage: EnsuredMessage,
        *,
        action: TypingAction = TypingAction.TYPING,
        # 5 minutes looks like reasonable default
        maxTimeout: int = 300,
        # If we'll not send typing action for abount 5 seconds, it will wanish, so need to refresh it
        repeatInterval: int = 4,
    ) -> TypingManager:
        """
        Start continuous typing action, dood!

        Creates and configures a TypingManager that sends typing actions at regular
        intervals until stopped. This is useful for long-running operations to show
        the user that the bot is still working.

        Args:
            ensuredMessage: Message object to send typing action for
            action: Chat action to send (default: TYPING)
            maxTimeout: Maximum time in seconds to keep typing (default: 300 seconds)
            repeatInterval: Interval in seconds between typing actions (default: 4 seconds)

        Returns:
            TypingManager instance to control the typing action
        """
        typingManager = TypingManager(
            action=action,
            maxTimeout=maxTimeout,
            repeatInterval=repeatInterval,
        )

        # logger.debug(f"startContinousTyping(,{action},{maxTimeout},{repeatInterval}) started...")

        async def sendChatAction():
            if self._bot is None:
                raise ValueError("Bot is not initialized")
            return await self._bot.sendChatAction(ensuredMessage, typingManager.action)

        async def _sendTyping() -> None:
            typingManager.iteration = 0

            while typingManager.isRunning():
                # logger.debug(f"_sendTyping(,{action}), iteration: {iteration}...")
                if await typingManager.tick() == 0:
                    await typingManager.sendTypingAction()

            if typingManager.isTimeout():
                logger.warning(
                    f"startTyping({ensuredMessage}) reached timeout ({typingManager.maxTimeout}), exiting..."
                )

        await typingManager.startTask(asyncio.create_task(_sendTyping()), sendChatAction, True)
        return typingManager

    def getChatTitle(
        self,
        chatInfo: ChatInfoDict,
        *,
        useMarkdown: bool = True,
        addChatId: bool = True,
        addChatType: bool = True,
    ) -> str:
        """
        Get chat title for the given chat info, dood!

        Args:
            chatInfo: Chat info object
            useMarkdown: Whether to use markdown markup (Default: True)
            addChatId: Whether to add chat ID (Default: True)
            addChatType: Whether yo add chat type (private, group, etc...) (Default: True)

        Returns:
            Chat title string
        """
        chatTitle: str = f"#{chatInfo['chat_id']}"
        if chatInfo["title"]:
            chatTitle = chatInfo["title"]
        elif chatInfo["username"]:
            chatTitle = chatInfo["username"]
        if useMarkdown:
            chatTitle = f"**{chatTitle}**"

        if chatInfo["type"] == ChatType.PRIVATE:
            chatTitle = f"{constants.PRIVATE_ICON} {chatTitle}"
        else:
            chatTitle = f"{constants.CHAT_ICON} {chatTitle}"
            # TODO: Different icons for other types?

        if addChatType:
            chatTitle = f"{chatTitle} ({chatInfo['type']})"

        if addChatId:
            if useMarkdown:
                chatTitle = f"#`{chatInfo['chat_id']}`, {chatTitle}"
            else:
                chatTitle = f"#{chatInfo['chat_id']} {chatTitle}"
        return chatTitle

    ###
    # Processing media
    ###

    async def _parseImage(
        self,
        ensuredMessage: EnsuredMessage,
        fileUniqueId: str,
        messages: List[ModelMessage],
    ) -> bool:
        """
        Parse image content using LLM to generate description, dood!

        Internal method that sends image to configured LLM model for analysis.
        Updates database with generated description or failure status.

        Args:
            ensuredMessage: Message containing the image
            fileUniqueId: Unique file identifier for database lookup
            messages: List of [`ModelMessage`](lib/ai/models.py) objects for LLM (system prompt + image)

        Returns:
            True if parsing succeeded, False if failed
        """

        chatSettings = self.getChatSettings(ensuredMessage.recipient.id)

        try:
            imageParsingLLM = chatSettings[ChatSettingsKey.IMAGE_PARSING_MODEL].toModel(self.llmManager)
            imageParsingFallbackLLM = chatSettings[ChatSettingsKey.IMAGE_PARSING_FALLBACK_MODEL].toModel(
                self.llmManager
            )
            logger.debug(f"Prompting Image {ensuredMessage.mediaId} LLM for image with prompt: {messages[:1]}")
            llmRet = await imageParsingLLM.generateTextWithFallBack(messages, imageParsingFallbackLLM)
            logger.debug(f"Image LLM Response: {llmRet}")

            if llmRet.status != ModelResultStatus.FINAL:
                raise RuntimeError(f"Image LLM Response status is not FINAL: {llmRet.status}")

            description = llmRet.resultText
            self.db.updateMediaAttachment(
                mediaId=fileUniqueId,
                status=MediaStatus.DONE,
                description=description,
            )
            return True

        except Exception as e:
            logger.error(f"Failed to parse image: {e}")
            self.db.updateMediaAttachment(
                mediaId=fileUniqueId,
                status=MediaStatus.FAILED,
            )
            return False

        # ret['content'] = llmRet.resultText

    async def processTelegramSticker(
        self, ensuredMessage: EnsuredMessage, prompt: Optional[str] = None
    ) -> MediaProcessingInfo:
        """
        Process a sticker attachment from message, dood!

        Extracts sticker metadata (dimensions, emoji, animation status)
        and processes it through the media pipeline.

        Args:
            ensuredMessage: Message containing the sticker

        Returns:
            [`MediaProcessingInfo`](internal/bot/models/media.py) with processing task and metadata

        Raises:
            ValueError: If message doesn't contain a sticker
        """
        if self.botProvider != BotProvider.TELEGRAM:
            raise RuntimeError("Stickers are supported in Telegram only")
        baseMessage = ensuredMessage.getBaseMessage()
        if not isinstance(baseMessage, telegram.Message):
            raise RuntimeError(f"Base message is not Message, but {type(baseMessage)}")

        sticker = baseMessage.sticker
        if sticker is None:
            raise ValueError("Sticker not found")

        # Sticker(..., emoji='😨', file_id='C...E', file_size=51444, file_unique_id='A...Q',
        # height=512, is_animated=True, is_video=False, set_name='SharkBoss',
        # thumbnail=PhotoSize(...), type=<StickerType.REGULAR>, width=512)

        metadata = {
            "type": sticker.type,
            "emoji": sticker.emoji,
            "width": sticker.width,
            "height": sticker.height,
            "set_name": sticker.set_name,
            "is_animated": sticker.is_animated,
            "is_video": sticker.is_video,
            "is_premium": sticker.premium_animation is not None,
            "file_size": sticker.file_size,
        }

        return await self._processMediaV2(
            ensuredMessage=ensuredMessage,
            mediaType=MessageType.STICKER,
            mediaId=sticker.file_unique_id,
            fileId=sticker.file_id,
            metadata=metadata,
            prompt=prompt,
        )

    async def processTelegramImage(
        self, ensuredMessage: EnsuredMessage, prompt: Optional[str] = None
    ) -> MediaProcessingInfo:
        """
        Process a photo attachment from message, dood!

        Selects optimal photo size based on chat settings and processes
        through the media pipeline. May use smaller size for LLM to reduce costs.

        Args:
            ensuredMessage: Message containing the photo
            prompt: Optional custom prompt for image parsing

        Returns:
            [`MediaProcessingInfo`](internal/bot/models/media.py) with processing task and metadata
        """
        if self.botProvider != BotProvider.TELEGRAM:
            raise RuntimeError("Stickers are supported in Telegram only")
        baseMessage = ensuredMessage.getBaseMessage()
        if not isinstance(baseMessage, telegram.Message):
            raise RuntimeError(f"Base message is not Message, but {type(baseMessage)}")

        bestPhotoSize = baseMessage.photo[-1]

        metadata = {
            # Store metadata for best size
            "width": bestPhotoSize.width,
            "height": bestPhotoSize.height,
            "file_size": bestPhotoSize.file_size,
        }

        return await self._processMediaV2(
            ensuredMessage=ensuredMessage,
            mediaType=MessageType.IMAGE,
            mediaId=bestPhotoSize.file_unique_id,
            fileId=bestPhotoSize.file_id,
            metadata=metadata,
            prompt=prompt,
        )

    async def _processTelegramMedia(
        self,
        ensuredMessage: EnsuredMessage,
        *,
        mediaType: MessageType,
        media: telegramBasemedium._BaseMedium,
        prompt: Optional[str] = None,
    ) -> MediaProcessingInfo:
        """
        Process Telegram media attachments (images, videos, stickers, etc.), dood!

        Extracts media information from Telegram's _BaseMedium objects and initiates
        asynchronous processing through the internal media pipeline. This method is
        specifically designed for Telegram bot provider and will raise an error if
        called from other providers.

        Args:
            ensuredMessage: Wrapped message containing the base Telegram message
            mediaType: Type of media being processed (IMAGE, VIDEO, STICKER, etc.)
            media: Telegram media object (_BaseMedium) containing file information
            prompt: Optional text prompt/caption associated with the media

        Returns:
            MediaProcessingInfo: Object containing media ID, type, and async processing task

        Raises:
            RuntimeError: If bot provider is not Telegram or base message is invalid
        """
        if self.botProvider != BotProvider.TELEGRAM:
            raise RuntimeError("Stickers are supported in Telegram only")
        baseMessage = ensuredMessage.getBaseMessage()
        if not isinstance(baseMessage, telegram.Message):
            raise RuntimeError(f"Base message is not Message, but {type(baseMessage)}")

        return await self._processMediaV2(
            ensuredMessage=ensuredMessage,
            mediaType=mediaType,
            mediaId=media.file_unique_id,
            fileId=media.file_id,
            metadata=media.to_dict(recursive=True),
            prompt=prompt,
        )

    async def processTelegramMedia(
        self, ensuredMessage: EnsuredMessage, prompt: Optional[str] = None
    ) -> Optional[MediaProcessingInfo]:
        baseMessage = ensuredMessage.getBaseMessage()
        if not isinstance(baseMessage, telegram.Message):
            raise RuntimeError(f"Base message is not Message, but {type(baseMessage)}")
        match ensuredMessage.messageType:
            case MessageType.TEXT:
                # No Media
                return None
            case MessageType.IMAGE:
                return await self.processTelegramImage(ensuredMessage, prompt=prompt)
            case MessageType.STICKER:
                return await self.processTelegramSticker(ensuredMessage, prompt=prompt)
            case MessageType.ANIMATION:
                if baseMessage.animation is None:
                    logger.error(f"Animation mising in Telegram message {baseMessage}")
                    return None
                return await self._processTelegramMedia(
                    ensuredMessage,
                    mediaType=ensuredMessage.messageType,
                    media=baseMessage.animation,
                    prompt=prompt,
                )
            case MessageType.VIDEO:
                if baseMessage.video is None:
                    logger.error(f"Video mising in Telegram message {baseMessage}")
                    return None
                return await self._processTelegramMedia(
                    ensuredMessage,
                    mediaType=ensuredMessage.messageType,
                    media=baseMessage.video,
                    prompt=prompt,
                )
            case MessageType.VIDEO_NOTE:
                if baseMessage.video_note is None:
                    logger.error(f"VideoNote mising in Telegram message {baseMessage}")
                    return None
                return await self._processTelegramMedia(
                    ensuredMessage,
                    mediaType=ensuredMessage.messageType,
                    media=baseMessage.video_note,
                    prompt=prompt,
                )
            case MessageType.AUDIO:
                if baseMessage.audio is None:
                    logger.error("Audio mising in Telegram message")
                    return None
                return await self._processTelegramMedia(
                    ensuredMessage,
                    mediaType=ensuredMessage.messageType,
                    media=baseMessage.audio,
                    prompt=prompt,
                )
            case MessageType.VOICE:
                if baseMessage.voice is None:
                    logger.error("Voice mising in Telegram message")
                    return None
                return await self._processTelegramMedia(
                    ensuredMessage,
                    mediaType=ensuredMessage.messageType,
                    media=baseMessage.voice,
                    prompt=prompt,
                )
            case MessageType.DOCUMENT:
                if baseMessage.document is None:
                    logger.error("Document mising in Telegram message")
                    return None
                return await self._processTelegramMedia(
                    ensuredMessage,
                    mediaType=ensuredMessage.messageType,
                    media=baseMessage.document,
                    prompt=prompt,
                )
            case _:
                # TODO: add support for downloading other types of attachments
                # For unsupported message types, just log a warning and process caption like text message
                logger.warning(f"Unsupported message type: {ensuredMessage.messageType}")
                return None

    async def processMaxMedia(
        self, ensuredMessage: EnsuredMessage, prompt: Optional[str] = None
    ) -> List[MediaProcessingInfo]:
        baseMessage = ensuredMessage.getBaseMessage()
        ret: List[MediaProcessingInfo] = []
        if not isinstance(baseMessage, maxModels.Message):
            logger.error(f"Invalid message type: {type(baseMessage)}")
            return ret

        if not baseMessage.body.attachments:
            # No attachments, skip
            return ret

        for attachment in baseMessage.body.attachments:
            if attachment.type == maxModels.AttachmentType.IMAGE and isinstance(attachment, maxModels.PhotoAttachment):
                url = attachment.payload.url
                mediaId = f"{attachment.type}:{attachment.payload.photo_id}"
                ret.append(
                    await self._processMediaV2(
                        ensuredMessage=ensuredMessage,
                        mediaType=MessageType.IMAGE,
                        mediaId=mediaId,
                        fileId=url,
                        prompt=prompt,
                        metadata=attachment.to_dict(recursive=True),
                    )
                )

            elif attachment.type == maxModels.AttachmentType.STICKER and isinstance(
                attachment, maxModels.StickerAttachment
            ):
                url = attachment.payload.url
                mediaId = f"{attachment.type}:{attachment.payload.code}"

                if url.startswith("https://st.mycdn.me/static/messages/res/images/stub/") and url.endswith(".png"):
                    # https://st.mycdn.me/static/messages/res/images/stub/sticker_31856a27@2x.png
                    # It is not real sticker image, just stub for all(?) animated stickers.
                    # We should'nt process it as it will put wrong data into context
                    logger.info(f"Sticker {attachment} looks like animated sticker")
                    if self.db.getMediaAttachment(mediaId=mediaId) is None:
                        logger.debug("Putting fake db entry for it...")
                        self.db.addMediaAttachment(
                            fileUniqueId=mediaId,
                            fileId=url,
                            mediaType=MessageType.STICKER,
                            metadata=utils.jsonDumps(attachment.to_dict(recursive=True)),
                            status=MediaStatus.DONE,
                            description="Animated sticker",
                        )

                ret.append(
                    await self._processMediaV2(
                        ensuredMessage=ensuredMessage,
                        mediaType=MessageType.STICKER,
                        mediaId=mediaId,
                        fileId=url,
                        prompt=prompt,
                        metadata=attachment.to_dict(recursive=True),
                    )
                )
            elif attachment.type == maxModels.AttachmentType.VIDEO and isinstance(
                attachment, maxModels.VideoAttachment
            ):
                url = attachment.payload.url
                mediaId = f"{attachment.type}:{attachment.payload.token}"
                ret.append(
                    await self._processMediaV2(
                        ensuredMessage=ensuredMessage,
                        mediaType=MessageType.VIDEO,
                        mediaId=mediaId,
                        fileId=url,
                        prompt=prompt,
                        metadata=attachment.to_dict(recursive=True),
                    )
                )
            elif attachment.type == maxModels.AttachmentType.AUDIO and isinstance(
                attachment, maxModels.AudioAttachment
            ):
                url = attachment.payload.url
                mediaId = f"{attachment.type}:{attachment.payload.token}"
                ret.append(
                    await self._processMediaV2(
                        ensuredMessage=ensuredMessage,
                        mediaType=MessageType.AUDIO,
                        mediaId=mediaId,
                        fileId=url,
                        prompt=prompt,
                        metadata=attachment.to_dict(recursive=True),
                    )
                )
            elif attachment.type == maxModels.AttachmentType.FILE and isinstance(attachment, maxModels.FileAttachment):
                url = attachment.payload.url
                mediaId = f"{attachment.type}:{attachment.payload.token}"
                ret.append(
                    await self._processMediaV2(
                        ensuredMessage=ensuredMessage,
                        mediaType=MessageType.DOCUMENT,
                        mediaId=mediaId,
                        fileId=url,
                        prompt=prompt,
                        metadata=attachment.to_dict(recursive=True),
                    )
                )
            else:
                logger.warning(f"Unsupported attachment type: {attachment.type}:{type(attachment).__name__}")

        return ret

    async def _processMediaV2(
        self,
        *,
        ensuredMessage: EnsuredMessage,
        mediaType: MessageType,
        mediaId: str,
        fileId: str,
        metadata: Optional[Dict[str, Any]] = None,
        prompt: Optional[str] = None,
    ) -> MediaProcessingInfo:
        """
        Process media attachments from messages, handling database storage and optional LLM parsing.

        Args:
            ensuredMessage: The validated message object containing media information
            mediaType: Type of media (image, video, audio, etc.)
            mediaId: Unique identifier for the media attachment
            fileId: Platform-specific file identifier for downloading
            dataGetter: Async function to retrieve media data by mediaId and fileId
            metadata: Optional dictionary with additional media information
            prompt: Optional prompt text for media processing

        Returns:
            MediaProcessingInfo: Object containing media processing status and async task
        """

        if ensuredMessage.mediaGroupId is None:
            logger.error(f"MediaGroupId is None for message {ensuredMessage}")
            raise ValueError("MediaGroupId is None")

        ret = MediaProcessingInfo(
            id=mediaId,
            task=None,
            type=mediaType,
        )
        localUrl: Optional[str] = None  # To be filled with downloaded media URL
        mimeType: Optional[str] = None  # To be filled with downloaded media MIME type

        logger.debug(f"Processing media {ret.type}#{ret.id} with fileId:{fileId}...")

        # We are ensuring it here to properly handle case, when this media already in database
        # But for different message
        self.db.ensureMediaInGroup(mediaId=ret.id, mediaGroupId=ensuredMessage.mediaGroupId)

        # First check if we have the photo in the database already
        mediaAttachment = self.db.getMediaAttachment(ret.id)
        hasMediaAttachment = mediaAttachment is not None
        if mediaAttachment is not None:
            logger.debug(f"Media#{ret.id} already in database")
            if mediaAttachment["media_type"] != mediaType:
                raise RuntimeError(
                    f"Media#{ret.id} already present in database and it is not an "
                    f"{mediaType} but {mediaAttachment['media_type']}"
                )

            # Only skip processing if Media in DB is in right status
            match MediaStatus(mediaAttachment["status"]):
                case MediaStatus.DONE:
                    ret.task = makeEmptyAsyncTask()
                    return ret

                case MediaStatus.PENDING:
                    try:
                        mediaDate = mediaAttachment["updated_at"]
                        if not isinstance(mediaDate, datetime.datetime):
                            logger.error(
                                f"{ret.type}#{ret.id} `updated_at` is not a datetime: "
                                f"{type(mediaDate).__name__}({mediaDate})"
                            )
                            mediaDate = datetime.datetime.fromisoformat(mediaDate)

                        if utils.getAgeInSecs(mediaDate) > constants.PROCESSING_TIMEOUT:
                            logger.warning(
                                f"{ret.type}#{ret.id} already in database but in status "
                                f"{mediaAttachment['status']} and is too old ({mediaDate}), reprocessing it"
                            )
                        else:
                            ret.task = makeEmptyAsyncTask()
                            return ret
                    except Exception as e:
                        logger.error("{ret.type}#{ret.id} Error during checking age:")
                        logger.exception(e)

                case _:
                    mimeType = str(mediaAttachment["mime_type"])
                    # NOTE: Currently we can process only images
                    if mimeType.lower().startswith("image/"):
                        logger.debug(
                            f"{ret.type}#{ret.id} in wrong status: {mediaAttachment['status']}. Reprocessing it"
                        )
                    else:
                        logger.debug(f"{ret.type}#{ret.id} is {mimeType}, skipping it")
                        ret.task = makeEmptyAsyncTask()
                        return ret

        chatSettings = self.getChatSettings(ensuredMessage.recipient.id)
        mediaData: Optional[bytes] = None
        if chatSettings[ChatSettingsKey.SAVE_ATTACHMENTS].toBool():
            if self._bot is None:
                raise ValueError("Bot is not initialized")
            mediaData = await self._bot.downloadAttachment(mediaId, fileId)
            if mediaData is not None:
                localUrl = await self.storeAttachment(
                    data=mediaData,
                    prefix=chatSettings[ChatSettingsKey.SAVE_PREFIX].toStr(),
                    mediaType=mediaType,
                )

        if chatSettings[ChatSettingsKey.PARSE_ATTACHMENTS].toBool() and mediaType in [
            MessageType.IMAGE,
            MessageType.STICKER,
        ]:
            # Currently we can process only images
            mediaStatus = MediaStatus.PENDING
        else:
            mediaStatus = MediaStatus.DONE

        if hasMediaAttachment:
            self.db.updateMediaAttachment(
                mediaId=ret.id,
                status=mediaStatus,
                metadata=utils.jsonDumps(metadata),
                mimeType=mimeType,
                localUrl=localUrl,
                prompt=prompt,
            )
        else:
            self.db.addMediaAttachment(
                fileUniqueId=ret.id,
                fileId=fileId,
                mediaType=mediaType,
                mimeType=mimeType,
                metadata=utils.jsonDumps(metadata),
                status=mediaStatus,
                localUrl=localUrl,
                prompt=prompt,
                fileSize=None,
                description=None,
            )

        # Need to parse image content with LLM
        if chatSettings[ChatSettingsKey.PARSE_ATTACHMENTS].toBool():
            # Do not redownload file if it was downloaded already
            if mediaData is None:
                if self._bot is None:
                    raise ValueError("Bot is not initialized")
                mediaData = await self._bot.downloadAttachment(mediaId, fileId)

            if mediaData is None:
                logger.error(f"{ret.type}#{ret.id} is None, cannot parse it")
                self.db.updateMediaAttachment(
                    mediaId=ret.id,
                    status=MediaStatus.FAILED,
                )
                ret.task = makeEmptyAsyncTask()
                return ret

            mimeType = magic.from_buffer(mediaData, mime=True)
            logger.debug(f"{ret.type}#{ret.id} Mimetype: {mimeType}")

            self.db.updateMediaAttachment(
                mediaId=ret.id,
                mimeType=mimeType,
                fileSize=len(mediaData),
            )

            if mimeType.lower().startswith("image/"):
                logger.debug(f"{ret.type}#{ret.id} is an image")
            else:
                logger.warning(f"{ret.type}#{ret.id} is not an image, skipping parsing")
                ret.task = makeEmptyAsyncTask()
                self.db.updateMediaAttachment(
                    mediaId=ret.id,
                    status=MediaStatus.NEW,
                )
                return ret

            imagePrompt = chatSettings[ChatSettingsKey.PARSE_IMAGE_PROMPT].toStr()
            messages = [
                ModelMessage(
                    role="system",
                    content=imagePrompt,
                ),
                ModelImageMessage(
                    role="user",
                    content=ensuredMessage.messageText,
                    image=bytearray(mediaData),
                ),
            ]

            logger.debug(f"{mediaType}#{ret.id}: Asynchronously parsing image")
            parseTask = asyncio.create_task(self._parseImage(ensuredMessage, ret.id, messages))
            # logger.debug(f"{mediaType}#{ret.id} After Start")
            ret.task = parseTask
            await self.queueService.addBackgroundTask(parseTask)
            # logger.debug(f"{mediaType}#{ret.id} After Queued")

        if ret.task is None:
            ret.task = makeEmptyAsyncTask()

        return ret

    async def storeAttachment(self, data: bytes, prefix: str, mediaType: str) -> Optional[str]:
        """
        Store an attachment in the storage service with deduplication.

        This method stores binary attachment data in the configured storage backend
        (filesystem, S3, etc.) using a content-addressed key. It automatically
        deduplicates attachments by using SHA512 hash of the content as part of the key.

        The key format is: {prefix}{mediaType}-{sha512}.{mimeType}

        Args:
            data: The binary attachment data to store
            prefix: A prefix for the storage key (e.g., "attachments/")
            mediaType: The media type identifier (e.g., "image", "document")

        Returns:
            The storage key if successful, None if an error occurred

        Note:
            The method only stores the attachment if it doesn't already exist,
            preventing duplicate storage based on content hash.
        """
        try:
            mimeType = magic.from_buffer(data, mime=True).split("/")[-1]
            sha512 = hashlib.sha512(data).hexdigest()
            key = f"{prefix}{mediaType}-{sha512}.{mimeType}"
            # Store the attachment in the storage only if it doesn't exist
            # As we getting SHA512 hash of the attachment,
            # we can check if it exists in the storage with hight probability
            if not self.storage.exists(key):
                self.storage.store(key, data)
            return key
        except Exception as e:
            logger.error(f"Error storing attachment: {e}")
            logger.exception(e)
            return None

    ###
    # Base methods for processing Telegram events
    ###

    async def newMessageHandler(
        self,
        ensuredMessage: EnsuredMessage,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        # By default, skip processing
        return HandlerResultStatus.SKIPPED

    async def newChatMemberHandler(
        self,
        targetChat: MessageRecipient,
        messageId: Optional[MessageIdType],
        newMember: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """
        Handle new chat member event, dood!

        Base implementation that returns SKIPPED. Subclasses can override
        to implement custom behavior when a new member joins a chat.

        Args:
            targetChat: The chat where the member joined
            messageId: Optional message ID associated with the join event
            newMember: The new member who joined the chat
            updateObj: The raw update object from the bot platform

        Returns:
            HandlerResultStatus indicating processing result (default: SKIPPED)
        """
        # By default, skip processing
        return HandlerResultStatus.SKIPPED

    async def leftChatMemberHandler(
        self,
        targetChat: MessageRecipient,
        messageId: Optional[MessageIdType],
        leftMember: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """
        Handle left chat member event, dood!

        Base implementation that returns SKIPPED. Subclasses can override
        to implement custom behavior when a new member joins a chat.

        Args:
            targetChat: The chat where the member joined
            messageId: Optional message ID associated with the join event
            leftMember: The member who left the chat
            updateObj: The raw update object from the bot platform

        Returns:
            HandlerResultStatus indicating processing result (default: SKIPPED)
        """
        # By default, skip processing
        return HandlerResultStatus.SKIPPED

    async def callbackHandler(
        self,
        ensuredMessage: EnsuredMessage,
        data: utils.PayloadDict,
        user: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        # By default, skip processing
        return HandlerResultStatus.SKIPPED
