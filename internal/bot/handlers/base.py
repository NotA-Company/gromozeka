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
from enum import Enum
import json
import logging
import re

from typing import Any, Dict, List, Optional, Sequence

import magic

from telegram import Chat, Message, User, Update
from telegram.ext import ExtBot, ContextTypes
from telegram._files._basemedium import _BaseMedium
from telegram._utils.types import ReplyMarkup

from internal.services.cache import CacheService
from internal.services.cache.types import UserDataType, UserDataValueType
from internal.services.queue.service import QueueService, makeEmptyAsyncTask
from lib.ai.models import (
    ModelImageMessage,
    ModelMessage,
    ModelResultStatus,
)
from lib.ai.manager import LLMManager
from lib.markdown import markdown_to_markdownv2
import lib.utils as utils

from ...config.manager import ConfigManager

from ...database.wrapper import DatabaseWrapper
from ...database.models import ChatInfoDict, ChatUserDict, MediaStatus, MessageCategory

from ..models import (
    ChatSettingsKey,
    ChatSettingsValue,
    CommandHandlerInfo,
    CommandHandlerMixin,
    CallbackDataDict,
    EnsuredMessage,
    MentionCheckResult,
    MessageType,
    MediaProcessingInfo,
    UserMetadataDict,
)
from .. import constants


logger = logging.getLogger(__name__)


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

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
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

        # TODO: Put all botOwners and chatDefaults to some service to not duplicate it for each handler class
        # Init different defaults
        self.botOwners = [username.lower() for username in self.config.get("bot_owners", [])]

        botDefaults: Dict[ChatSettingsKey, ChatSettingsValue] = {
            k: ChatSettingsValue(v) for k, v in self.config.get("defaults", {}).items() if k in ChatSettingsKey
        }

        self.chatDefaults: Dict[ChatSettingsKey, ChatSettingsValue] = {
            k: ChatSettingsValue("") for k in ChatSettingsKey
        }

        self.chatDefaults.update({k: v for k, v in botDefaults.items() if k in ChatSettingsKey})

        # Init cache
        self.cache = CacheService.getInstance()

        self.queueService = QueueService.getInstance()

        self._bot: Optional[ExtBot] = None

    def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
        """
        Get all command handlers auto-discovered via decorators, dood!

        Returns:
            Sequence of [`CommandHandlerInfo`](internal/bot/models/command_handlers.py) objects containing
            handler metadata (command names, descriptions, handler functions)
        """
        return super().getCommandHandlers()

    def injectBot(self, bot: ExtBot) -> None:
        """
        Inject the bot instance for use in handlers, dood!

        This method must be called before handlers can send messages or
        perform bot-specific operations.

        Args:
            bot: Telegram bot instance from python-telegram-bot library
        """
        self._bot = bot

    ###
    # Chat settings Managenent
    ###

    def getChatSettings(
        self, chatId: Optional[int], returnDefault: bool = True
    ) -> Dict[ChatSettingsKey, ChatSettingsValue]:
        """
        Get chat settings with optional default fallback, dood!

        Retrieves settings from cache, merging with defaults if requested.
        If chatId is None, returns only default settings.

        Args:
            chatId: Telegram chat ID, or None for defaults only
            returnDefault: If True, merge with default settings; if False, return only custom settings

        Returns:
            Dictionary mapping [`ChatSettingsKey`](internal/bot/models/chat_settings.py)
                            to [`ChatSettingsValue`](internal/bot/models/chat_settings.py)
        """
        if chatId is None:
            return self.chatDefaults.copy()

        chatSettings = self.cache.getChatSettings(chatId)

        if returnDefault:
            return {**self.chatDefaults, **chatSettings}

        return chatSettings

    def setChatSetting(self, chatId: int, key: ChatSettingsKey, value: ChatSettingsValue) -> None:
        """
        Set a specific chat setting, dood!

        Updates the setting in cache, which will be persisted to database.

        Args:
            chatId: Telegram chat ID
            key: Setting key from [`ChatSettingsKey`](internal/bot/models/chat_settings.py) enum
            value: Setting value as [`ChatSettingsValue`](internal/bot/models/chat_settings.py)
        """
        # TODO: Should I add deprecation warning?
        self.cache.setChatSetting(chatId, key, value)

    def unsetChatSetting(self, chatId: int, key: ChatSettingsKey) -> None:
        """
        Remove a specific chat setting, reverting to default, dood!

        Args:
            chatId: Telegram chat ID
            key: Setting key from [`ChatSettingsKey`](internal/bot/models/chat_settings.py) enum to remove
        """
        self.cache.unsetChatSetting(chatId=chatId, key=key)

    ###
    # User Data Management
    ###

    def getUserData(self, chatId: int, userId: int) -> UserDataType:
        """
        Get user-specific data for a chat, dood!

        Retrieves user data stored in cache or database.

        Args:
            chatId: Telegram chat ID
            userId: Telegram user ID

        Returns:
            Dictionary of user data as [`UserDataType`](internal/services/cache/types.py)
        """
        return self.cache.getChatUserData(chatId=chatId, userId=userId)

    def setUserData(
        self, chatId: int, userId: int, key: str, value: UserDataValueType, append: bool = False
    ) -> UserDataValueType:
        """
        Set or append user-specific data for a chat, dood!

        If append is True and existing value is a list, appends to it.
        Otherwise, replaces the value.

        Args:
            chatId: Telegram chat ID
            userId: Telegram user ID
            key: Data key (string identifier)
            value: Data value (string, list, or dict)
            append: If True, append to existing list value instead of replacing

        Returns:
            The final value stored (after append if applicable)
        """
        userData = self.getUserData(chatId, userId)

        newValue = value
        if key in userData and append:
            # TODO: Properly work with dicts
            _data = userData[key]
            if isinstance(newValue, list):
                newValue = [str(v).strip() for v in newValue]
            else:
                newValue = [str(newValue).strip()]

            if isinstance(_data, list):
                userData[key] = _data + newValue
            else:
                userData[key] = [str(_data)] + newValue

            newValue = userData[key]

        self.cache.setChatUserData(chatId=chatId, userId=userId, key=key, value=newValue)
        return newValue

    def unsetUserData(self, chatId: int, userId: int, key: str) -> None:
        """
        Remove a specific user data key, dood!

        Args:
            chatId: Telegram chat ID
            userId: Telegram user ID
            key: Data key to remove
        """
        self.cache.unsetChatUserData(chatId=chatId, userId=userId, key=key)

    def clearUserData(self, chatId: int, userId: int) -> None:
        """
        Clear all user data for a specific user in a chat, dood!

        Args:
            chatId: Telegram chat ID
            userId: Telegram user ID
        """
        self.cache.clearChatUserData(chatId=chatId, userId=userId)

    def _updateEMessageUserData(self, ensuredMessage: EnsuredMessage) -> None:
        """
        Update an [`EnsuredMessage`](internal/bot/models/ensured_message.py) with current user data, dood!

        Internal helper method to inject user data into message objects.

        Args:
            ensuredMessage: Message object to update with user data
        """
        ensuredMessage.setUserData(self.getUserData(ensuredMessage.chat.id, ensuredMessage.user.id))

    def checkEMMentionsMe(self, ensuredMessage: EnsuredMessage) -> MentionCheckResult:
        """
        Check if a message mentions the bot, dood!

        Checks for bot username mention or custom nicknames configured in chat settings.

        Args:
            ensuredMessage: Message to check for mentions

        Returns:
            [`MentionCheckResult`](internal/bot/models/ensured_message.py) indicating if bot was mentioned
        """
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)

        username: Optional[str] = None
        if self._bot:
            username = "@" + self._bot.username

        return ensuredMessage.checkHasMention(
            username=username,
            customMentions=chatSettings[ChatSettingsKey.BOT_NICKNAMES].toList(),
        )

    ###
    # Different helpers
    ###

    async def isAdmin(self, user: User, chat: Optional[Chat] = None, allowBotOwners: bool = True) -> bool:
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
        # If chat is None, then we are checking if it's bot owner
        username = user.username
        if username is None:
            return False
        username = username.lower()

        if allowBotOwners and username in self.botOwners:
            return True

        if chat is not None:
            for admin in await chat.get_administrators():
                # logger.debug(f"Got admin for chat {chat.id}: {admin}")
                if admin.user.username and username == admin.user.username.lower():
                    return True

        return False

    async def sendMessage(
        self,
        replyToMessage: EnsuredMessage,
        messageText: Optional[str] = None,
        addMessagePrefix: str = "",
        photoData: Optional[bytes] = None,
        photoCaption: Optional[str] = None,
        sendMessageKWargs: Optional[Dict[str, Any]] = None,
        tryMarkdownV2: bool = True,
        tryParseInputJSON: Optional[bool] = None,  # False - do not try, True - try, None - try to detect
        sendErrorIfAny: bool = True,
        skipLogs: bool = False,
        mediaPrompt: Optional[str] = None,
        messageCategory: MessageCategory = MessageCategory.BOT,
        replyMarkup: Optional[ReplyMarkup] = None,
    ) -> Optional[Message]:
        """
        Send a text or photo message as a reply, dood!

        Handles message formatting (MarkdownV2), JSON parsing, photo sending,
        and automatic message saving to database. Supports both text and photo messages.

        Args:
            replyToMessage: Message to reply to
            messageText: Text content (required if photoData is None)
            addMessagePrefix: Prefix to add before message text
            photoData: Photo bytes (required if messageText is None)
            photoCaption: Caption for photo messages
            sendMessageKWargs: Additional kwargs for telegram send methods
            tryMarkdownV2: If True, attempt to parse and send as MarkdownV2
            tryParseInputJSON: Whether to parse JSON responses (None=auto-detect)
            sendErrorIfAny: If True, send error message on failure
            skipLogs: If True, skip debug logging
            mediaPrompt: Optional prompt for media processing
            messageCategory: Category for database storage (from [`MessageCategory`](internal/database/models.py))
            replyMarkup: Optional reply markup (keyboard/buttons)

        Returns:
            Sent Message object, or None if sending failed

        Raises:
            ValueError: If neither messageText nor photoData provided, or invalid chat type
        """

        if photoData is None and messageText is None:
            logger.error("No message text or photo data provided")
            raise ValueError("No message text or photo data provided")

        replyMessage: Optional[Message] = None
        message = replyToMessage.getBaseMessage()
        chatType = replyToMessage.chat.type
        isPrivate = chatType == Chat.PRIVATE
        isGroupChat = chatType in [Chat.GROUP, Chat.SUPERGROUP]

        if not isPrivate and not isGroupChat:
            logger.error("Cannot send message to chat type {}".format(chatType))
            raise ValueError("Cannot send message to chat type {}".format(chatType))

        if sendMessageKWargs is None:
            sendMessageKWargs = {}

        replyKwargs = sendMessageKWargs.copy()
        replyKwargs.update(
            {
                "reply_to_message_id": replyToMessage.messageId,
                "message_thread_id": replyToMessage.threadId,
                "reply_markup": replyMarkup,
            }
        )

        try:
            if photoData is not None:
                # Send photo
                replyKwargs.update(
                    {
                        "photo": photoData,
                    }
                )

                if tryMarkdownV2 and photoCaption is not None:
                    try:
                        messageTextParsed = markdown_to_markdownv2(addMessagePrefix + photoCaption)
                        # logger.debug(f"Sending MarkdownV2: {replyText}")
                        replyMessage = await message.reply_photo(
                            caption=messageTextParsed,
                            parse_mode="MarkdownV2",
                            **replyKwargs,
                        )
                    except Exception as e:
                        logger.error(f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}")
                        # Probably error in markdown formatting, fallback to raw text

                if replyMessage is None:
                    _photoCaption = photoCaption if photoCaption is not None else ""
                    replyMessage = await message.reply_photo(caption=addMessagePrefix + _photoCaption, **replyKwargs)

            elif messageText is not None:
                # Send text

                # If response is json, parse it
                if tryParseInputJSON is None:
                    tryParseInputJSON = re.match(r"^\s*`*\s*{", messageText) is not None
                    if tryParseInputJSON:
                        logger.debug(f"JSONPreParser: message '{messageText}' looks like JSON, tring parse it")

                if tryParseInputJSON:
                    try:
                        jsonReply = json.loads(messageText.strip("` \n\r"))
                        if "text" in jsonReply:
                            messageText = str(jsonReply["text"]).strip()
                        elif "message" in jsonReply:
                            messageText = str(jsonReply["message"]).strip()
                        elif "media_description" in jsonReply:
                            messageText = str(jsonReply["media_description"]).strip()
                        else:
                            logger.warning(f"No text field found in json reply, fallback to text: {jsonReply}")
                            raise ValueError("No text field found in json reply")
                    except Exception as e:
                        logger.debug(f"Error while parsing LLM reply, assume it's text: {type(e).__name__}#{e}")

                if not skipLogs:
                    logger.debug(f"Sending reply to {replyToMessage}")
                # Try to send Message as MarkdownV2 first
                if tryMarkdownV2:
                    try:
                        messageTextParsed = markdown_to_markdownv2(addMessagePrefix + messageText)
                        # logger.debug(f"Sending MarkdownV2: {replyText}")
                        replyMessage = await message.reply_text(
                            text=messageTextParsed,
                            parse_mode="MarkdownV2",
                            **replyKwargs,
                        )
                    except Exception as e:
                        logger.error(f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}")
                        # Probably error in markdown formatting, fallback to raw text

                if replyMessage is None:
                    replyMessage = await message.reply_text(text=addMessagePrefix + messageText, **replyKwargs)

            try:
                if replyMessage is None:
                    raise ValueError("No reply message")

                if not skipLogs:
                    logger.debug(f"Sent message: {replyMessage}")

                # Save message
                ensuredReplyMessage = EnsuredMessage.fromMessage(replyMessage)
                if addMessagePrefix:
                    replyText = ensuredReplyMessage.messageText
                    if replyText.startswith(addMessagePrefix):
                        replyText = replyText[len(addMessagePrefix) :]
                        ensuredReplyMessage.messageText = replyText
                if replyMessage.photo:
                    media = await self.processImage(ensuredReplyMessage, mediaPrompt)
                    ensuredReplyMessage.setMediaProcessingInfo(media)

                if isGroupChat or isPrivate:
                    self.saveChatMessage(ensuredReplyMessage, messageCategory=messageCategory)
                else:
                    raise ValueError("Unknown chat type")

            except Exception as e:
                logger.error(f"Error while saving chat message: {type(e).__name__}#{e}")
                logger.exception(e)
                # Message was sent, so return True anyway
                return replyMessage

        except Exception as e:
            logger.error(f"Error while sending message: {type(e).__name__}#{e}")
            logger.exception(e)
            if sendErrorIfAny:
                await message.reply_text(
                    f"Error while sending message: {type(e).__name__}#{e}",
                    reply_to_message_id=replyToMessage.messageId,
                )
            return None

        return replyMessage

    def getChatInfo(self, chatId: int) -> Optional[ChatInfoDict]:
        """
        Get chat information from cache or database, dood!

        Args:
            chatId: Telegram chat ID

        Returns:
            Chat info dictionary as [`ChatInfoDict`](internal/database/models.py), or None if not found
        """
        return self.cache.getChatInfo(chatId)

    def updateChatInfo(self, chat: Chat) -> None:
        """
        Update chat information in cache and database, dood!

        Only updates if chat info has changed (title, username, forum status, or type).
        Uses cache to avoid unnecessary database writes.

        Args:
            chat: Telegram Chat object with current information
        """
        chatId = chat.id
        storedChatInfo = self.getChatInfo(chatId=chatId)

        if (
            storedChatInfo is None
            or chat.title != storedChatInfo.get("title", None)
            or chat.username != storedChatInfo.get("username", None)
            or chat.is_forum != storedChatInfo.get("is_forum", None)
            or chat.type != storedChatInfo.get("type", None)
        ):
            self.cache.setChatInfo(
                chat.id,
                {
                    "chat_id": chat.id,
                    "title": chat.title,
                    "username": chat.username,
                    "is_forum": chat.is_forum or False,
                    "type": chat.type,
                    "created_at": datetime.datetime.now(),
                    "updated_at": datetime.datetime.now(),
                },
            )

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
            force: If True, update even if already in cache
        """
        _topicId = topicId if topicId is not None else 0
        storedTopicInfo = self.cache.getChatTopicInfo(chatId=chatId, topicId=_topicId)

        if not force and storedTopicInfo:
            # No need to rewrite topic info
            return

        if (
            storedTopicInfo is None
            or iconColor != storedTopicInfo["icon_color"]
            or customEmojiId != storedTopicInfo["icon_custom_emoji_id"]
            or name != storedTopicInfo["name"]
        ):
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

    def saveChatMessage(self, message: EnsuredMessage, messageCategory: MessageCategory) -> bool:
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
        chat = message.chat
        sender = message.sender

        if message.messageType == MessageType.UNKNOWN:
            logger.error(f"Unsupported message type: {message.messageType}")
            return False

        messageText = message.messageText

        replyId = message.replyId
        rootMessageId = message.messageId
        if message.isReply and replyId:
            parentMsg = self.db.getChatMessageByMessageId(
                chatId=chat.id,
                messageId=replyId,
            )
            if parentMsg:
                rootMessageId = parentMsg["root_message_id"]

        self.updateChatInfo(chat)

        # TODO: Actually topic name and emoji could be changed after that
        # but currently we have no way to know it (except of see
        # https://docs.python-telegram-bot.org/en/stable/telegram.forumtopicedited.html )
        # Think about it later
        if message.isTopicMessage:
            repliedMessage = message.getBaseMessage().reply_to_message
            if repliedMessage and repliedMessage.forum_topic_created:
                self.updateTopicInfo(
                    chatId=message.chat.id,
                    topicId=message.threadId,
                    iconColor=repliedMessage.forum_topic_created.icon_color,
                    customEmojiId=repliedMessage.forum_topic_created.icon_custom_emoji_id,
                    name=repliedMessage.forum_topic_created.name,
                )
        else:
            self.updateTopicInfo(chatId=message.chat.id, topicId=message.threadId)

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
            messageText=messageText,
            messageType=message.messageType,
            messageCategory=messageCategory,
            rootMessageId=rootMessageId,
            quoteText=message.quoteText,
            mediaId=message.mediaId,
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

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)

        try:
            llmModel = chatSettings[ChatSettingsKey.IMAGE_PARSING_MODEL].toModel(self.llmManager)
            logger.debug(f"Prompting Image {ensuredMessage.mediaId} LLM for image with prompt: {messages[:1]}")
            llmRet = await llmModel.generateText(messages)
            logger.debug(f"Image LLM Response: {llmRet}")

            if llmRet.status != ModelResultStatus.FINAL:
                raise RuntimeError(f"Image LLM Response status is not FINAL: {llmRet.status}")

            description = llmRet.resultText
            self.db.updateMediaAttachment(
                fileUniqueId=fileUniqueId,
                status=MediaStatus.DONE,
                description=description,
            )
            return True

        except Exception as e:
            logger.error(f"Failed to parse image: {e}")
            self.db.updateMediaAttachment(
                fileUniqueId=fileUniqueId,
                status=MediaStatus.FAILED,
            )
            return False

        # ret['content'] = llmRet.resultText

    async def _processMedia(
        self,
        ensuredMessage: EnsuredMessage,
        media: _BaseMedium,
        metadata: Dict[str, Any],
        mediaForLLM: Optional[_BaseMedium] = None,
        prompt: Optional[str] = None,
    ) -> MediaProcessingInfo:
        """
        Process media attachment from message (image/sticker), dood!

        Handles media download, database storage, MIME type detection,
        and optional LLM-based image parsing. Creates background task
        for async image analysis.

        Currently supports only image/* MIME types for LLM parsing.

        Args:
            ensuredMessage: Message containing the media
            media: Media object to process (best quality)
            metadata: Media metadata dictionary (dimensions, etc.)
            mediaForLLM: Optional different media size for LLM (e.g., smaller)
            prompt: Optional custom prompt for image parsing

        Returns:
            [`MediaProcessingInfo`](internal/bot/models/media.py) with processing task and metadata

        Raises:
            ValueError: If media type is TEXT or UNKNOWN
            RuntimeError: If bot not initialized or media type mismatch in database
        """
        # Currently we support only image/ media.
        # If we'll want to support other types, then need to
        # find all "image/" entries in this function and fix
        mediaStatus = MediaStatus.NEW
        localUrl: Optional[str] = None
        mimeType: Optional[str] = None
        mediaType = ensuredMessage.messageType
        if mediaForLLM is None:
            mediaForLLM = media

        if mediaType in [MessageType.TEXT, MessageType.UNKNOWN]:
            raise ValueError(f"Media type {mediaType} is not supported")

        logger.debug(f"Processing media: {media}")
        ret = MediaProcessingInfo(
            id=media.file_unique_id,
            task=None,
            type=mediaType,
        )

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
                                f"{mediaType}#{ret.id} `updated_at` is not a datetime: "
                                f"{type(mediaDate).__name__}({mediaDate})"
                            )
                            mediaDate = datetime.datetime.fromisoformat(mediaDate)

                        if utils.getAgeInSecs(mediaDate) > constants.PROCESSING_TIMEOUT:
                            logger.warning(
                                f"{mediaType}#{ret.id} already in database but in status "
                                f"{mediaAttachment['status']} and is too old ({mediaDate}), reprocessing it"
                            )
                        else:
                            ret.task = makeEmptyAsyncTask()
                            return ret
                    except Exception as e:
                        logger.error("{mediaType}#{ret.id} Error during checking age:")
                        logger.exception(e)

                case _:
                    mimeType = str(mediaAttachment["mime_type"])
                    if mimeType.lower().startswith("image/"):
                        logger.debug(
                            f"{mediaType}#{ret.id} in wrong status: {mediaAttachment['status']}. Reprocessing it"
                        )
                    else:
                        logger.debug(f"{mediaType}#{ret.id} is {mimeType}, skipping it")
                        ret.task = makeEmptyAsyncTask()
                        return ret

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        mediaData: Optional[bytes] = None

        if chatSettings[ChatSettingsKey.SAVE_IMAGES].toBool():
            # TODO do
            pass

        if chatSettings[ChatSettingsKey.PARSE_IMAGES].toBool():
            mediaStatus = MediaStatus.PENDING
        else:
            mediaStatus = MediaStatus.DONE

        if hasMediaAttachment:
            self.db.updateMediaAttachment(
                fileUniqueId=ret.id,
                status=mediaStatus,
                metadata=utils.jsonDumps(metadata),
                mimeType=mimeType,
                localUrl=localUrl,
                prompt=prompt,
            )
        else:
            self.db.addMediaAttachment(
                fileUniqueId=ret.id,
                fileId=media.file_id,
                fileSize=media.file_size,
                mediaType=mediaType,
                mimeType=mimeType,
                metadata=utils.jsonDumps(metadata),
                status=mediaStatus,
                localUrl=localUrl,
                prompt=prompt,
                description=None,
            )

        # Need to parse image content with LLM
        if chatSettings[ChatSettingsKey.PARSE_IMAGES].toBool():
            # Do not redownload file if it was downloaded already
            if mediaData is None or mediaForLLM != media:
                if self._bot is None:
                    raise RuntimeError("Bot is not initialized")
                file = await self._bot.get_file(mediaForLLM.file_id)
                logger.debug(f"{mediaType}#{ret.id} File info: {file}")
                mediaData = bytes(await file.download_as_bytearray())

            mimeType = magic.from_buffer(mediaData, mime=True)
            logger.debug(f"{mediaType}#{ret.id} Mimetype: {mimeType}")

            self.db.updateMediaAttachment(
                fileUniqueId=ret.id,
                mimeType=mimeType,
            )

            if mimeType.lower().startswith("image/"):
                logger.debug(f"{mediaType}#{ret.id} is an image")
            else:
                logger.warning(f"{mediaType}#{ret.id} is not an image, skipping parsing")
                ret.task = makeEmptyAsyncTask()
                self.db.updateMediaAttachment(
                    fileUniqueId=ret.id,
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

    async def processSticker(self, ensuredMessage: EnsuredMessage) -> MediaProcessingInfo:
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
        sticker = ensuredMessage.getBaseMessage().sticker
        if sticker is None:
            raise ValueError("Sticker not found")

        # Sticker(..., emoji='😨', file_id='C...E', file_size=51444, file_unique_id='A...Q',
        # height=512, is_animated=True, is_video=False, set_name='SharkBoss',
        # thumbnail=PhotoSize(...), type=<StickerType.REGULAR>, width=512)

        metadata = {
            "width": sticker.width,
            "height": sticker.height,
            "emoji": sticker.emoji,
            "set_name": sticker.set_name,
            "is_animated": sticker.is_animated,
            "is_video": sticker.is_video,
            "is_premium": sticker.premium_animation is not None,
        }

        return await self._processMedia(ensuredMessage, media=sticker, metadata=metadata)

    async def processImage(self, ensuredMessage: EnsuredMessage, prompt: Optional[str] = None) -> MediaProcessingInfo:
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

        bestPhotoSize = ensuredMessage.getBaseMessage().photo[-1]
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)

        llmPhotoSize = bestPhotoSize
        optimalImageSize = chatSettings[ChatSettingsKey.OPTIMAL_IMAGE_SIZE].toInt()
        if optimalImageSize > 0:
            # Iterate over all photo sizes and find the best one (i.e. smallest, but, larger than optimalImageSize)
            for pSize in ensuredMessage.getBaseMessage().photo:
                if pSize.width > optimalImageSize or pSize.height > optimalImageSize:
                    llmPhotoSize = pSize
                    break

        metadata = {
            # Store metadata for best size
            "width": bestPhotoSize.width,
            "height": bestPhotoSize.height,
        }

        return await self._processMedia(
            ensuredMessage,
            media=bestPhotoSize,
            mediaForLLM=llmPhotoSize,
            metadata=metadata,
            prompt=prompt,
        )

    ###
    # Base methods for processing Telegram events
    ###

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """
        Handle regular text messages, dood!

        Base implementation that skips processing. Override in subclasses
        to implement specific message handling logic.

        Args:
            update: Telegram update object
            context: Handler context from python-telegram-bot
            ensuredMessage: Wrapped message object, or None if not applicable

        Returns:
            [`HandlerResultStatus`](internal/bot/handlers/base.py:56) indicating processing result
        """
        # By default, skip processing
        return HandlerResultStatus.SKIPPED

    async def buttonHandler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        data: CallbackDataDict,
    ) -> HandlerResultStatus:
        """
        Handle inline button callbacks, dood!

        Base implementation that skips processing. Override in subclasses
        to implement specific button handling logic.

        Args:
            update: Telegram update object
            context: Handler context from python-telegram-bot
            data: Parsed callback data as [`CallbackDataDict`](internal/bot/models/command_handlers.py)

        Returns:
            [`HandlerResultStatus`](internal/bot/handlers/base.py:56) indicating processing result
        """
        # By default, skip processing
        return HandlerResultStatus.SKIPPED
