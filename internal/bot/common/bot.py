"""Multi-platform bot implementation for Telegram and Max Messenger.

This module provides a unified bot interface supporting both Telegram and Max Messenger
platforms with message handling, media processing, and administrative operations.

The main class, TheBot, abstracts platform-specific differences and provides a consistent
API for bot operations across different messaging platforms.
"""

import asyncio
import hashlib
import logging
import random
import time
from collections.abc import Awaitable, Callable, MutableSet, Sequence
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple, TypeVar, Union

import magic
import telegram
import telegram.error
import telegram.ext

import lib.max_bot as libMax
import lib.max_bot.exceptions as maxExceptions
import lib.max_bot.models as maxModels
from internal.bot.common.models import CallbackButton, TypingAction
from internal.bot.common.typing_manager import TypingManager
from internal.bot.constants import (
    BOT_ID_CACHE_TTL_SECONDS,
    BOT_ID_FAILURE_GRACE_SECONDS,
    BOT_USERNAME_CACHE_TTL_SECONDS,
    BOT_USERNAME_FAILURE_GRACE_SECONDS,
    TELEGRAM_RETRY_AFTER_CAP_SECONDS,
    TELEGRAM_SEND_MAX_ATTEMPTS,
    TELEGRAM_SEND_RETRY_DELAY_BASE,
    TELEGRAM_SEND_RETRY_JITTER,
)
from internal.bot.models import BotProvider, ChatType, EnsuredMessage, MessageRecipient, MessageSender
from internal.database.models import ChatBotStatus, ChatInfoDict
from internal.models import MessageId, MessageType
from internal.services.cache import CacheService
from lib import utils
from lib.markdown.parser import markdownToMarkdownV2

logger = logging.getLogger(__name__)


_TelegramSendReturnT = TypeVar("_TelegramSendReturnT")
"""TypeVar for the return type of :meth:`TheBot._retryTelegramSend`."""


class TheBot:
    """Multi-platform bot client supporting Telegram and Max Messenger.

    Provides unified interface for bot operations across different messaging platforms
    including message sending, media handling, user management, and administrative functions.

    Attributes:
        botProvider: Platform type (BotProvider.TELEGRAM or BotProvider.MAX)
        config: Configuration dictionary containing bot settings
        maxBot: Max Messenger bot client instance (None if not using Max)
        tgBot: Telegram bot client instance (None if not using Telegram)
        botOwnersUsername: Set of bot owner usernames (lowercase, without @)
        botOwnersId: Set of bot owner user IDs
        cache: Cache service instance for storing temporary data

    Args:
        botProvider: Platform type (BotProvider.TELEGRAM or BotProvider.MAX)
        config: Bot configuration dictionary containing bot settings and owner information
        maxBot: Max Messenger bot client instance (required if botProvider is MAX)
        tgBot: Telegram bot client instance (required if botProvider is TELEGRAM)

    Raises:
        ValueError: If required bot client is not provided for the specified platform
    """

    # TODO Add __slots__

    def __init__(
        self,
        botProvider: BotProvider,
        config: Dict[str, Any],
        *,
        maxBot: Optional[libMax.MaxBotClient] = None,
        tgBot: Optional[telegram.ext.ExtBot] = None,
    ) -> None:
        """Initialize bot instance with platform-specific client.

        Args:
            botProvider: Platform type (BotProvider.TELEGRAM or BotProvider.MAX)
            config: Configuration dictionary containing bot settings and owner information
            maxBot: Max Messenger bot client (required if botProvider is MAX)
            tgBot: Telegram bot client (required if botProvider is TELEGRAM)

        Raises:
            ValueError: If required bot client is not provided for the specified platform,
                       or if bot owner configuration contains invalid values
        """

        self.botProvider: BotProvider = botProvider
        self.config = config

        # Init proper botInstance
        self.maxBot: Optional[libMax.MaxBotClient] = None
        self.tgBot: Optional[telegram.ext.ExtBot] = None
        if self.botProvider == BotProvider.TELEGRAM:
            self.tgBot = tgBot
            if self.tgBot is None:
                raise ValueError("tgBot need to be providen if botProvider is Telegram")
        elif self.botProvider == BotProvider.MAX:
            self.maxBot = maxBot
            if self.maxBot is None:
                raise ValueError("maxBot need to be providen if botProvider is Telegram")
        else:
            raise ValueError(f"Unexpected botProvider: {self.botProvider}")

        self.botOwnersUsername: MutableSet[str] = set[str]()
        self.botOwnersId: MutableSet[int] = set[int]()
        for val in self.config.get("bot_owners", []):
            if isinstance(val, int):
                self.botOwnersId.add(val)
            elif isinstance(val, str):
                self.botOwnersUsername.add(val.lower())
                if val and val[0] in "-0123456789":
                    try:
                        intVal = int(val)
                        self.botOwnersId.add(intVal)
                    except ValueError:
                        pass
            else:
                raise ValueError(f"Unexpected type of botowner value '{val}': {type(val).__name__}")

        logger.debug(f"Bot Owners: byId: {self.botOwnersId}, byUsername: {self.botOwnersUsername}")
        self.cache = CacheService.getInstance()

        # Cache for bot identity (stable for process lifetime, with TTL)
        self._botId: Optional[int] = None
        self._botIdCachedAt: float = 0.0
        self._botUserName: Optional[str] = None
        self._botUserNameCachedAt: float = 0.0

        ###

    # Different helpers
    ###

    async def getBotId(self) -> int:
        """Get bot's unique ID.

        The bot ID is cached for BOT_ID_CACHE_TTL_SECONDS (3600 seconds) to avoid
        repeated platform API calls. After the TTL expires, the ID is re-resolved
        from the platform, enabling recovery from temporary glitches (e.g., bot
        re-creation on the platform).

        For Max, the refresh bypasses the client-level cache (getMyInfo with
        useCache=False), so TheBot's TTL is the only caching layer; one uncached
        request per TTL window.

        On refresh failure, if a stale cached value exists and the cache age is
        less than (TTL + GRACE), the stale value is returned instead of raising.
        This provides graceful degradation for transient platform issues.
        Failures are never cached.

        Returns:
            Bot's unique ID from the active platform

        Raises:
            RuntimeError: If no active bot client; or if refresh fails and no
                stale cache is available (no cache, or cache older than TTL+GRACE).
        """
        now = time.monotonic()
        cacheAge = now - self._botIdCachedAt
        hasCachedValue = self._botIdCachedAt > 0

        # Return cached value if it exists and hasn't expired
        if hasCachedValue and cacheAge < BOT_ID_CACHE_TTL_SECONDS:
            # hasCachedValue > 0 guarantees _botId was set on a prior successful resolution
            assert self._botId is not None
            return self._botId

        # Try a refresh
        try:
            # Resolve from platform API
            botId: Optional[int] = None
            if self.tgBot:
                botId = self.tgBot.id
            elif self.maxBot:
                botId = (await self.maxBot.getMyInfo(useCache=False)).user_id
            else:
                raise RuntimeError("No Active bot found")

            # Cache only on successful resolution
            self._botId = botId
            self._botIdCachedAt = now
            return botId
        except Exception:
            # If we have a cached value within grace window, return it
            if hasCachedValue and cacheAge < (BOT_ID_CACHE_TTL_SECONDS + BOT_ID_FAILURE_GRACE_SECONDS):
                logger.exception("Bot ID refresh failed, returning stale value")
                # hasCachedValue > 0 guarantees _botId was set on a prior successful resolution
                assert self._botId is not None
                # Return stale value within grace window
                return self._botId

            # No cache or cache too old — raise the original exception
            raise

    async def getBotUserName(self) -> Optional[str]:
        """Get bot's username.

        The bot username is cached for BOT_USERNAME_CACHE_TTL_SECONDS (3600 seconds) to avoid
        repeated platform API calls. After the TTL expires, the username is re-resolved
        from the platform, enabling recovery from temporary glitches (e.g., bot
        re-creation or username change on the platform).

        For Max, the refresh bypasses the client-level cache (getMyInfo with
        useCache=False), so TheBot's TTL is the only caching layer; one uncached
        request per TTL window.

        On refresh failure, if a stale cached value exists and the cache age is
        less than (TTL + GRACE), the stale value is returned instead of raising.
        This provides graceful degradation for transient platform issues.
        Failures are never cached.

        Returns:
            Bot's username from the active platform, or None if not set

        Raises:
            RuntimeError: If no active bot client; or if refresh fails and no
                stale cache is available (no cache, or cache older than TTL+GRACE).
        """
        now = time.monotonic()
        cacheAge = now - self._botUserNameCachedAt
        hasCachedValue = self._botUserNameCachedAt > 0

        # Return cached value if it exists and hasn't expired
        if hasCachedValue and cacheAge < BOT_USERNAME_CACHE_TTL_SECONDS:
            return self._botUserName

        # Try a refresh
        try:
            # Resolve from platform API
            botUserName: Optional[str] = None
            if self.tgBot:
                botUserName = self.tgBot.username
            elif self.maxBot:
                botUserName = (await self.maxBot.getMyInfo(useCache=False)).username
            else:
                raise RuntimeError("No Active bot found")

            # Cache only on successful resolution
            self._botUserName = botUserName
            self._botUserNameCachedAt = now
            return botUserName
        except Exception:
            # If we have a cached value within grace window, return it
            if hasCachedValue and cacheAge < (BOT_USERNAME_CACHE_TTL_SECONDS + BOT_USERNAME_FAILURE_GRACE_SECONDS):
                logger.exception("Bot username refresh failed, returning stale value")
                # Return stale value within grace window
                return self._botUserName

            # No cache or cache too old — raise the original exception
            raise

    def isBotOwner(self, user: MessageSender) -> bool:
        """Check if a user is a bot owner.

        Args:
            user: Telegram user to check

        Returns:
            True if user is bot owner, False otherwise
        """
        return user.username in self.botOwnersUsername or user.id in self.botOwnersId

    async def getChatAdmins(self, chat: MessageRecipient) -> Dict[int, Tuple[str, str]]:
        """Retrieve chat administrators as a mapping of user IDs to display names.

        Checks the cache first; fetches from the appropriate platform API if not cached,
        then stores the result in cache before returning.

        When the bot is no longer in the chat or has no access (e.g., kicked/blocked on
        Telegram or NotFoundError on Max), logs a warning, marks the chat as inaccessible,
        and returns an empty dict without caching the failure. This allows the caller
        (e.g., isAdmin) to treat the result as "no admins in this chat" and gracefully
        exclude it from lists.

        Args:
            chat: The target chat to fetch administrators for.

        Returns:
            Dict mapping admin user IDs (int) to their username + display names (Tuple[str, str]).
            Returns an empty dict if the bot has no access to the chat.

        Raises:
            RuntimeError: If the configured bot provider is neither Telegram nor Max.
        """
        # Short-circuit: if the chat is marked INACCESSIBLE, skip the platform API call.
        # isChatInaccessible is cache-aside (cheap on a cache hit, may read DB on miss).
        # Returns the same {} the failure path would, so callers degrade identically.
        # Recovery flips the status back to ACTIVE.
        if await self.cache.isChatInaccessible(chat.id):
            return {}

        # If chat is passed, check if user is admin of given chat
        chatAdmins: Optional[Dict[int, Tuple[str, str]]] = self.cache.getChatAdmins(chat.id)
        if chatAdmins is not None:
            return chatAdmins

        chatAdmins = {}  # userID -> username
        if self.botProvider == BotProvider.TELEGRAM and self.tgBot is not None:
            try:
                for admin in await self.tgBot.get_chat_administrators(chat_id=chat.id):
                    adminUsername = admin.user.username or ""
                    if adminUsername:
                        adminUsername = "@" + adminUsername
                    chatAdmins[admin.user.id] = (adminUsername, admin.user.full_name)
            except telegram.error.Forbidden as exc:
                # Bot was kicked/blocked or has no access to the chat
                logger.warning(f"getChatAdmins: cannot fetch admins for chat {chat.id} (Telegram): {exc}")
                await self.cache.markChatInaccessible(chat.id)
                return {}
            except telegram.error.BadRequest as exc:
                # Conservative: only treat as inaccessible if clearly about access.
                # A miss safely re-raises - if Telegram's wording changes, we want real errors surfaced.
                excMsg = str(exc)
                if "chat not found" in excMsg.lower():
                    logger.warning(f"getChatAdmins: cannot fetch admins for chat {chat.id} (Telegram): {exc}")
                    await self.cache.markChatInaccessible(chat.id)
                    return {}
                # Re-raise other BadRequest errors - they're likely real API usage errors
                raise

        elif self.botProvider == BotProvider.MAX and self.maxBot is not None:
            try:
                maxChatAdmins = (await self.maxBot.getAdmins(chatId=chat.id)).members
                for admin in maxChatAdmins:
                    adminFullName = admin.first_name
                    if admin.last_name:
                        adminFullName += " " + admin.last_name
                    adminUsername = admin.username or ""
                    if adminUsername:
                        adminUsername = "@" + adminUsername

                    chatAdmins[admin.user_id] = (adminUsername, adminFullName)
            except maxExceptions.NotFoundError as exc:
                # Bot not in chat or chat not found
                logger.warning(f"getChatAdmins: cannot fetch admins for chat {chat.id} (Max): {exc}")
                await self.cache.markChatInaccessible(chat.id)
                return {}

        else:
            raise RuntimeError(f"Unexpected platform: {self.botProvider}")

        self.cache.setChatAdmins(chat.id, chatAdmins)
        return chatAdmins

    async def isAdmin(
        self, user: MessageSender, chat: Optional[MessageRecipient] = None, allowBotOwners: bool = True
    ) -> bool:
        """
        Check if a user is an admin or bot owner

        If chat is None, only checks bot owner status.
        If chat is provided, checks both bot owners and chat administrators.

        Args:
            user: Telegram user to check
            chat: Optional chat to check admin status in
            allowBotOwners: If True, bot owners are always considered admins

        Returns:
            True if user is admin/owner, False otherwise
        """
        # If chat is None, then we are checking if it's bot owner only

        username = user.username
        if username:
            username = username.lower().lstrip("@")

        if allowBotOwners and self.isBotOwner(user):
            # User is bot owner and bot owners are allowed
            return True

        if chat is None:
            # No chat - can't be admin
            return False

        if chat.chatType == ChatType.PRIVATE:
            return True

        # If userId is the same as chatID, then it's Private chat or Anonymous Admin
        if self.botProvider == BotProvider.TELEGRAM and user.id == chat.id:
            return True

        # If chat is passed, check if user is admin of given chat
        chatAdmins = await self.getChatAdmins(chat=chat)
        return user.id in chatAdmins

    def _keyboardToTelegram(self, keyboard: Sequence[Sequence[CallbackButton]]) -> telegram.InlineKeyboardMarkup:
        """Convert generic keyboard format to Telegram inline keyboard markup.

        Args:
            keyboard: 2D sequence of CallbackButton objects representing keyboard layout

        Returns:
            Telegram InlineKeyboardMarkup object ready for use in Telegram API calls
        """
        return telegram.InlineKeyboardMarkup([[btn.toTelegram() for btn in row] for row in keyboard])

    def _keyboardToMax(self, keyboard: Sequence[Sequence[CallbackButton]]) -> maxModels.InlineKeyboardAttachmentRequest:
        """Convert generic keyboard format to Max inline keyboard attachment request.

        Args:
            keyboard: 2D sequence of CallbackButton objects representing keyboard layout

        Returns:
            Max InlineKeyboardAttachmentRequest object ready for use in Max API calls
        """
        return maxModels.InlineKeyboardAttachmentRequest(
            payload=maxModels.Keyboard(buttons=[[btn.toMax() for btn in row] for row in keyboard])
        )

    async def editMessage(
        self,
        messageId: MessageId,
        chatId: int,
        *,
        text: Optional[str] = None,
        inlineKeyboard: Optional[Sequence[Sequence[CallbackButton]]] = None,
        useMarkdown: bool = True,
    ) -> bool:
        """Edit existing message text or inline keyboard.

        Args:
            messageId: ID of message to edit
            chatId: Chat ID where message is located
            text: New message text (None to edit only keyboard)
            inlineKeyboard: New inline keyboard layout
            useMarkdown: Whether to parse text as Markdown

        Returns:
            True if edit was successful, False otherwise
        """

        if self.botProvider == BotProvider.TELEGRAM and self.tgBot is not None:
            ret = None
            if text is None:
                ret = await self._retryTelegramSend(
                    self.tgBot.edit_message_reply_markup,
                    chat_id=chatId,
                    message_id=messageId.asInt(),
                    reply_markup=self._keyboardToTelegram(inlineKeyboard) if inlineKeyboard is not None else None,
                )
            else:
                kwargs = {}
                if useMarkdown:
                    kwargs["parse_mode"] = telegram.constants.ParseMode.MARKDOWN_V2
                    text = markdownToMarkdownV2(text)
                ret = await self._retryTelegramSend(
                    self.tgBot.edit_message_text,
                    text=text,
                    chat_id=chatId,
                    message_id=messageId.asInt(),
                    reply_markup=self._keyboardToTelegram(inlineKeyboard) if inlineKeyboard is not None else None,
                    **kwargs,
                )
            return bool(ret)
        elif self.botProvider == BotProvider.MAX and self.maxBot is not None:
            await self.maxBot.editMessage(
                messageId=str(messageId),
                text=text,
                attachments=None if inlineKeyboard is not None else [],
                inlineKeyboard=self._keyboardToMax(inlineKeyboard) if inlineKeyboard is not None else None,
                format=maxModels.TextFormat.MARKDOWN if useMarkdown else None,
            )
        else:
            logger.error(f"Can not edit message in platform {self.botProvider}")
        return False

    async def sendMessage(
        self,
        replyToMessage: Optional[EnsuredMessage],
        messageText: Optional[str] = None,
        *,
        addMessagePrefix: str = "",
        photoData: Optional[bytes] = None,
        sendMessageKWargs: Optional[Dict[str, Any]] = None,
        tryMarkdownV2: bool = True,
        sendErrorIfAny: bool = True,
        skipLogs: bool = False,
        inlineKeyboard: Optional[Sequence[Sequence[CallbackButton]]] = None,
        typingManager: Optional[TypingManager] = None,
        splitIfTooLong: bool = True,
        chatId: Optional[int] = None,
        threadId: Optional[int] = None,
        notify: Optional[bool] = None,
        attachmentList: Optional[Sequence[Tuple[bytes, MessageType, Optional[str]]]] = None,
    ) -> List[EnsuredMessage]:
        """Send message as reply with text and/or photo.

        Args:
            replyToMessage: Message to reply to (Or None if it is not answer to a message)
            messageText: Text content (required if photoData is None)
            addMessagePrefix: Prefix to add before message text
            photoData: Photo bytes (required if messageText is None)
            sendMessageKWargs: Additional platform-specific parameters
            tryMarkdownV2: Whether to parse text as MarkdownV2
            sendErrorIfAny: Whether to send error message on failure
            skipLogs: Whether to skip debug logging
            inlineKeyboard: Inline keyboard layout
            typingManager: Manager for typing indicators
            splitIfTooLong: Whether to split long messages
            chatId: Chat ID to send message to (only useful if `replyToMessage` is None)
            threadId: Thread ID to send message to (only useful if `replyToMessage` is None)

        Returns:
            List of sent message objects

        Raises:
            ValueError: If neither messageText nor photoData provided
            RuntimeError: If no active bot client is configured
        """
        match self.botProvider:
            case BotProvider.TELEGRAM:
                inlineKeyboardTg = self._keyboardToTelegram(inlineKeyboard) if inlineKeyboard is not None else None
                # TODO: Refactoring needed
                return await self._sendTelegramMessage(
                    replyToMessage=replyToMessage,
                    messageText=messageText,
                    addMessagePrefix=addMessagePrefix,
                    photoData=photoData,
                    sendMessageKWargs=sendMessageKWargs,
                    tryMarkdownV2=tryMarkdownV2,
                    sendErrorIfAny=sendErrorIfAny,
                    skipLogs=skipLogs,
                    inlineKeyboard=inlineKeyboardTg,
                    typingManager=typingManager,
                    splitIfTooLong=splitIfTooLong,
                    chatId=chatId,
                    threadId=threadId,
                    notify=notify,
                    attachmentList=attachmentList,
                )

            case BotProvider.MAX:
                inlineKeyboardMax = self._keyboardToMax(inlineKeyboard) if inlineKeyboard is not None else None

                return await self._sendMaxMessage(
                    replyToMessage=replyToMessage,
                    messageText=messageText,
                    addMessagePrefix=addMessagePrefix,
                    photoData=photoData,
                    sendMessageKWargs=sendMessageKWargs,
                    tryMarkdownV2=tryMarkdownV2,
                    sendErrorIfAny=sendErrorIfAny,
                    skipLogs=skipLogs,
                    inlineKeyboard=inlineKeyboardMax,
                    typingManager=typingManager,
                    splitIfTooLong=splitIfTooLong,
                    chatId=chatId,
                    threadId=threadId,
                    notify=notify,
                    attachmentList=attachmentList,
                )
            case _:
                raise RuntimeError(f"Unexpected bot provider: {self.botProvider}")

    async def _sendMaxMessage(
        self,
        replyToMessage: Optional[EnsuredMessage],
        messageText: Optional[str] = None,
        *,
        addMessagePrefix: str = "",
        photoData: Optional[bytes] = None,
        sendMessageKWargs: Optional[Dict[str, Any]] = None,
        tryMarkdownV2: bool = True,
        sendErrorIfAny: bool = True,
        skipLogs: bool = False,
        inlineKeyboard: Optional[maxModels.InlineKeyboardAttachmentRequest] = None,
        typingManager: Optional[TypingManager] = None,
        splitIfTooLong: bool = True,
        chatId: Optional[int] = None,
        threadId: Optional[int] = None,
        notify: Optional[bool] = None,
        attachmentList: Optional[Sequence[Tuple[bytes, MessageType, Optional[str]]]] = None,
    ) -> List[EnsuredMessage]:
        """Send message via Max Messenger platform.

        Handles sending text messages, photos, and attachments through Max Messenger API.
        Supports Markdown formatting, inline keyboards, and automatic message splitting
        for long messages. Photo data is automatically converted to attachment format.

        Args:
            replyToMessage: Message to reply to (provides chatId and replyToMessageId)
            messageText: Text content to send (required if no attachments)
            addMessagePrefix: Prefix to add before message text
            photoData: Photo bytes to send (converted to attachment automatically)
            sendMessageKWargs: Additional Max-specific parameters for send_message
            tryMarkdownV2: Whether to parse text as Markdown
            sendErrorIfAny: Whether to send error message to chat on failure
            skipLogs: Whether to skip debug logging
            inlineKeyboard: Max inline keyboard attachment request
            typingManager: Manager for typing indicators (stopped before sending)
            splitIfTooLong: Whether to split long messages into multiple parts
            chatId: Chat ID to send message to (required if replyToMessage is None)
            threadId: Thread ID (unused in Max, kept for interface compatibility)
            notify: Whether to send notification (None uses platform default)
            attachmentList: List of (data, type, filename) tuples for attachments

        Returns:
            List of sent EnsuredMessage objects (empty list on failure)

        Raises:
            RuntimeError: If Max bot client is not configured
            ValueError: If neither messageText nor attachments provided,
                       or if chatId is not provided when replyToMessage is None,
                       or if chat type is not PRIVATE or GROUP
        """
        if self.maxBot is None:
            raise RuntimeError("Max bot is Undefined")

        if photoData is not None:
            if attachmentList is None:
                attachmentList = []
            else:
                attachmentList = list(attachmentList)
            attachmentList.append((photoData, MessageType.IMAGE, None))

        replyToMessageId: Optional[MessageId] = None
        chatType: ChatType = ChatType.PRIVATE
        if replyToMessage is not None:
            chatId = replyToMessage.recipient.id
            # threadId = replyToMessage.threadId  # threadId is unused in Max
            replyToMessageId = replyToMessage.messageId
            chatType = replyToMessage.recipient.chatType
        else:
            if chatId is None:
                raise ValueError("ChatId or replyToMessage is required")
            chatType = ChatType.PRIVATE if chatId > 0 else ChatType.GROUP

        if photoData is None and messageText is None:
            logger.error("No message text or photo data provided")
            raise ValueError("No message text or photo data provided")

        replyMessageList: List[maxModels.Message] = []
        ensuredReplyList: List[EnsuredMessage] = []

        if typingManager is not None:
            await typingManager.stopTask()

        if chatType not in [ChatType.PRIVATE, ChatType.GROUP]:
            logger.error("Cannot send message to chat type {}".format(chatType))
            raise ValueError("Cannot send message to chat type {}".format(chatType))

        if sendMessageKWargs is None:
            sendMessageKWargs = {}

        replyKwargs = sendMessageKWargs.copy()
        replyKwargs.update(
            {
                "chatId": chatId,
                "replyTo": replyToMessageId.asStr() if replyToMessageId is not None else None,
                "format": maxModels.TextFormat.MARKDOWN if tryMarkdownV2 else None,
                "notify": notify,
            }
        )
        attachments: Optional[List[maxModels.AttachmentRequest]] = []

        try:
            if attachmentList:
                for mediaData, mediaType, fileName in attachmentList:
                    mimeType = magic.from_buffer(mediaData, mime=True)
                    if fileName is None:
                        digest = hashlib.sha256(mediaData).hexdigest()
                        ext = mimeType.split("/")[1]
                        fileName = f"{mediaType}-{digest}.{ext}"
                    ret = await self.maxBot.uploadFile(
                        filename=fileName,
                        data=mediaData,
                        mimeType=mimeType,
                        uploadType=mediaType.toMaxUploadType(),
                    )
                    attachments.append(ret.toAttachmentRequest())

            if messageText is not None or attachments:
                # Send Message
                if not attachments:
                    attachments = None
                if messageText is None:
                    messageText = ""

                if not skipLogs:
                    logger.debug(f"Sending reply to {replyToMessage}")

                # Must be only one file attachment in message (code: proto.payload)
                # So we send all except last attachment as separate messages in case of non-media attachments
                if attachments:
                    maxAttachmentsCount = 1
                    newAttachments: List[maxModels.AttachmentRequest] = []
                    while len(attachments) > maxAttachmentsCount:
                        firstAttachment = attachments[0]
                        attachments = attachments[1:]

                        if firstAttachment.type in [
                            maxModels.AttachmentType.IMAGE,
                            maxModels.AttachmentType.VIDEO,
                            maxModels.AttachmentType.AUDIO,
                        ]:
                            # If there is at leas one media attachment, do not allow other
                            # (i.e. not media) attachments in last message
                            maxAttachmentsCount = 0
                            newAttachments.append(firstAttachment)
                            continue

                        ret = await self.maxBot.sendMessage(
                            attachments=[firstAttachment],
                            **replyKwargs,
                        )
                        replyMessageList.append(ret.message)

                    attachments = newAttachments + attachments

                messageTextList: List[str] = [messageText]
                maxMessageLength = libMax.MAX_MESSAGE_LENGTH - len(addMessagePrefix)
                if splitIfTooLong and len(messageText) > maxMessageLength:
                    messageTextList = [
                        messageText[i : i + maxMessageLength] for i in range(0, len(messageText), maxMessageLength)
                    ]
                for _messageText in messageTextList:
                    ret = await self.maxBot.sendMessage(
                        text=addMessagePrefix + _messageText,
                        attachments=attachments,
                        inlineKeyboard=inlineKeyboard,
                        **replyKwargs,
                    )
                    attachments = None  # Send attachments with first message only
                    inlineKeyboard = None
                    replyMessageList.append(ret.message)

            try:
                if not replyMessageList:
                    raise ValueError("No reply messages")

                if not skipLogs:
                    logger.debug(f"Sent messages: {[utils.jsonDumps(msg) for msg in replyMessageList]}")

                # Save message
                for replyMessage in replyMessageList:
                    ensuredReplyMessage = EnsuredMessage.fromMaxMessage(replyMessage)
                    ensuredReplyList.append(ensuredReplyMessage)

            except Exception as e:
                logger.error(f"Error while saving chat message: {type(e).__name__}#{e}")
                logger.exception(e)
                # Message was sent, so return it
                return ensuredReplyList

        except Exception as e:
            logger.error(f"Error while sending message: {type(e).__name__}#{e}")
            logger.exception(e)
            if sendErrorIfAny:
                try:
                    await self.maxBot.sendMessage(
                        text=f"Error while sending message: {type(e).__name__}#{e}",
                        chatId=chatId,
                        replyTo=replyToMessageId.asStr() if replyToMessageId is not None else None,
                    )
                except Exception as error_e:
                    logger.error(f"Failed to send error message: {type(error_e).__name__}#{error_e}")
            return ensuredReplyList

        return ensuredReplyList

    async def _retryTelegramSend(
        self,
        sendCallable: Callable[..., Awaitable[_TelegramSendReturnT]],
        **kwargs: Any,
    ) -> _TelegramSendReturnT:
        """Retry a Telegram Bot API send/edit call on transient errors.

        Retries on ``telegram.error.TimedOut``, other ``telegram.error.NetworkError``
        (excluding ``BadRequest``), and ``telegram.error.RetryAfter``. Non-retryable
        exceptions (``BadRequest``, ``Forbidden``, ``Conflict``, ``ChatMigrated``,
        etc.) propagate immediately on the first attempt.

        ``BadRequest`` subclasses ``NetworkError`` but is semantically a 400
        (client error), so it is excluded from retry and re-raised.

        Args:
            sendCallable: The bound ``self.tgBot.send_*`` / ``edit_message_*``
                coroutine factory. Called as ``await sendCallable(**kwargs)``.
            **kwargs: Keyword arguments forwarded verbatim to ``sendCallable``.

        Returns:
            Whatever ``sendCallable`` returns on a successful attempt
            (typically ``telegram.Message`` or ``Sequence[telegram.Message]``).

        Raises:
            The last transient exception if all attempts are exhausted; the
            original non-retryable exception immediately if one is raised.
        """
        for attempt in range(TELEGRAM_SEND_MAX_ATTEMPTS):
            try:
                return await sendCallable(**kwargs)
            except telegram.error.BadRequest:
                # BadRequest is a client error (400), never retry
                raise
            except telegram.error.RetryAfter as e:
                if attempt == TELEGRAM_SEND_MAX_ATTEMPTS - 1:
                    # Last attempt exhausted, re-raise
                    raise
                # Read the property exactly once: each access may emit a
                # PTBDeprecationWarning while PTB_TIMEDELTA is unset (int mode).
                retryAfterValue: Union[int, timedelta] = e.retry_after
                # Honor retry_after, capped to prevent absurdly long sleeps
                if isinstance(retryAfterValue, timedelta):
                    delaySeconds = retryAfterValue.total_seconds()
                else:
                    delaySeconds = float(retryAfterValue)
                delaySeconds = min(delaySeconds, TELEGRAM_RETRY_AFTER_CAP_SECONDS)
                logger.warning(
                    f"Telegram send (attempt {attempt + 1}/{TELEGRAM_SEND_MAX_ATTEMPTS}), "
                    f"honoring retry_after={retryAfterValue}, sleeping {delaySeconds:.1f}s: "
                    f"{type(e).__name__}#{e}"
                )
                await asyncio.sleep(delaySeconds)
            except telegram.error.NetworkError as e:
                if attempt == TELEGRAM_SEND_MAX_ATTEMPTS - 1:
                    # Last attempt exhausted, re-raise
                    raise
                # Exponential backoff with jitter
                delay = TELEGRAM_SEND_RETRY_DELAY_BASE * (2**attempt) + random.uniform(0, TELEGRAM_SEND_RETRY_JITTER)
                logger.warning(
                    f"Telegram send (attempt {attempt + 1}/{TELEGRAM_SEND_MAX_ATTEMPTS}), "
                    f"retrying in {delay:.2f}s: {type(e).__name__}#{e}"
                )
                await asyncio.sleep(delay)
        # This line is unreachable — the loop always returns or raises on the last iteration
        raise RuntimeError("_retryTelegramSend: exhausted retry loop without return")  # pragma: no cover

    async def _sendTelegramMessage(
        self,
        replyToMessage: Optional[EnsuredMessage],
        messageText: Optional[str] = None,
        *,
        addMessagePrefix: str = "",
        photoData: Optional[bytes] = None,
        sendMessageKWargs: Optional[Dict[str, Any]] = None,
        tryMarkdownV2: bool = True,
        sendErrorIfAny: bool = True,
        skipLogs: bool = False,
        inlineKeyboard: Optional[telegram.InlineKeyboardMarkup] = None,
        typingManager: Optional[TypingManager] = None,
        splitIfTooLong: bool = True,
        chatId: Optional[int] = None,
        threadId: Optional[int] = None,
        notify: Optional[bool] = None,
        attachmentList: Optional[Sequence[Tuple[bytes, MessageType, Optional[str]]]] = None,
    ) -> List[EnsuredMessage]:
        """Send message via Telegram platform.

        Args:
            replyToMessage: Message to reply to
            messageText: Text content (required if photoData is None)
            addMessagePrefix: Prefix to add before message text
            photoData: Photo bytes (required if messageText is None)
            sendMessageKWargs: Additional Telegram-specific parameters
            tryMarkdownV2: Whether to parse text as MarkdownV2
            sendErrorIfAny: Whether to send error message on failure
            skipLogs: Whether to skip debug logging
            inlineKeyboard: Telegram inline keyboard markup
            typingManager: Manager for typing indicators
            splitIfTooLong: Whether to split long messages

        Returns:
            List of sent message objects

        Raises:
            ValueError: If neither messageText nor photoData provided
            RuntimeError: If Telegram bot client is not configured
        """

        if photoData is None and messageText is None and attachmentList is None:
            logger.error("No message text or media data provided")
            raise ValueError("No message text or media data provided")

        if photoData is not None and attachmentList is not None:
            attachmentList = list(attachmentList)
            attachmentList.append((photoData, MessageType.IMAGE, None))
            photoData = None

        replyMessageList: List[telegram.Message] = []
        ensuredReplyList: List[EnsuredMessage] = []

        replyToMessageId: Optional[MessageId] = None
        chatType: ChatType = ChatType.PRIVATE
        if replyToMessage is not None:
            chatId = replyToMessage.recipient.id
            # threadId = replyToMessage.threadId  # threadId is unused in Max
            replyToMessageId = replyToMessage.messageId
            chatType = replyToMessage.recipient.chatType
        else:
            if chatId is None:
                raise ValueError("ChatId or replyToMessage is required")
            chatType = ChatType.PRIVATE if chatId > 0 else ChatType.GROUP

        # message = replyToMessage.toTelegramMessage()
        # message.set_bot(self.tgBot)
        if self.tgBot is None:
            raise RuntimeError("Telegram bot client is not configured")

        if typingManager is not None:
            await typingManager.stopTask()

        if chatType not in [ChatType.PRIVATE, ChatType.GROUP]:
            logger.error("Cannot send message to chat type {}".format(chatType))
            raise ValueError("Cannot send message to chat type {}".format(chatType))

        if sendMessageKWargs is None:
            sendMessageKWargs = {}

        replyKwargs = sendMessageKWargs.copy()
        replyKwargs.update(
            {
                "reply_to_message_id": replyToMessageId.asInt() if replyToMessageId is not None else None,
                "message_thread_id": threadId,
                "chat_id": chatId,
            }
        )
        if inlineKeyboard is not None:
            replyKwargs["reply_markup"] = inlineKeyboard
        if notify is not None:
            replyKwargs["disable_notification"] = not notify

        try:
            if photoData is not None:
                # Send photo
                replyKwargs.update(
                    {
                        "photo": photoData,
                    }
                )

                replyMessage: Optional[telegram.Message] = None
                if tryMarkdownV2 and messageText is not None:
                    try:
                        messageTextParsed = markdownToMarkdownV2(addMessagePrefix + messageText)
                    except Exception as e:
                        # Markdown conversion failed (formatter bug, bad input, etc.) —
                        # broad catch is intentional: the markdown pipeline is best-effort
                        # and must never prevent sending the message at all.
                        logger.error(f"Error formatting markdown: {type(e).__name__}#{e}")
                        messageTextParsed = None
                    else:
                        try:
                            # logger.debug(f"Sending MarkdownV2: {replyText}")
                            # TODO: One day start using self.tgBot
                            replyMessage = await self._retryTelegramSend(
                                self.tgBot.send_photo,
                                caption=messageTextParsed,
                                parse_mode=telegram.constants.ParseMode.MARKDOWN_V2,
                                **replyKwargs,
                            )
                        except telegram.error.BadRequest as e:
                            # Telegram rejected the markdown — fallback to raw text.
                            # Transient errors (TimedOut/NetworkError/RetryAfter) have
                            # already been retried inside _retryTelegramSend and bubble
                            # past this except to the outer handler.
                            logger.error(f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}")

                if replyMessage is None:
                    _messageText = messageText if messageText is not None else ""
                    replyMessage = await self._retryTelegramSend(
                        self.tgBot.send_photo,
                        caption=addMessagePrefix + _messageText,
                        **replyKwargs,
                    )
                if replyMessage is not None:
                    replyMessageList.append(replyMessage)

            elif attachmentList is not None:
                # Send attachments
                media: List[
                    Union[
                        telegram.InputMediaAudio,
                        telegram.InputMediaDocument,
                        telegram.InputMediaPhoto,
                        telegram.InputMediaVideo,
                    ]
                ] = []
                for mediaData, mediaType, fileName in attachmentList:
                    if fileName is None:
                        mimeType = magic.from_buffer(mediaData, mime=True)
                        digest = hashlib.sha256(mediaData).hexdigest()
                        ext = mimeType.split("/")[1]
                        fileName = f"{mediaType}-{digest}.{ext}"
                    match mediaType:
                        case MessageType.IMAGE | MessageType.STICKER:
                            media.append(telegram.InputMediaPhoto(mediaData, filename=fileName))
                        case MessageType.ANIMATION | MessageType.VIDEO | MessageType.VIDEO_NOTE:
                            media.append(telegram.InputMediaVideo(mediaData, filename=fileName))
                        case MessageType.AUDIO | MessageType.VOICE:
                            media.append(telegram.InputMediaAudio(mediaData, filename=fileName))
                        case _:
                            media.append(telegram.InputMediaDocument(mediaData, filename=fileName))

                replyMessages: Optional[Sequence[telegram.Message]] = None
                if tryMarkdownV2 and messageText is not None:
                    try:
                        messageTextParsed = markdownToMarkdownV2(addMessagePrefix + messageText)
                        # logger.debug(f"Sending MarkdownV2: {replyText}")
                        # TODO: One day start using self.tgBot
                        replyMessages = await self.tgBot.send_media_group(
                            media=media,
                            caption=messageTextParsed,
                            parse_mode=telegram.constants.ParseMode.MARKDOWN_V2,
                            **replyKwargs,
                        )
                    except Exception as e:
                        logger.error(f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}")
                        # Probably error in markdown formatting, fallback to raw text

                if replyMessages is None:
                    _messageText = messageText if messageText is not None else ""
                    replyMessages = await self.tgBot.send_media_group(
                        media=media,
                        caption=addMessagePrefix + _messageText,
                        **replyKwargs,
                    )
                if replyMessages is not None:
                    replyMessageList.extend(replyMessages)

            elif messageText is not None:
                # Send text

                if not skipLogs:
                    logger.debug(f"Sending reply to {replyToMessage}")

                messageTextList: List[str] = [messageText]
                maxMessageLength = telegram.constants.MessageLimit.MAX_TEXT_LENGTH - len(addMessagePrefix)
                if splitIfTooLong and len(messageText) > maxMessageLength:
                    messageTextList = [
                        messageText[i : i + maxMessageLength] for i in range(0, len(messageText), maxMessageLength)
                    ]
                for _messageText in messageTextList:
                    replyMessage: Optional[telegram.Message] = None
                    # Try to send Message as MarkdownV2 first
                    if tryMarkdownV2:
                        try:
                            messageTextParsed = markdownToMarkdownV2(addMessagePrefix + _messageText)
                        except Exception as e:
                            # Markdown conversion failed (formatter bug, bad input, etc.) —
                            # broad catch is intentional: the markdown pipeline is best-effort
                            # and must never prevent sending the message at all.
                            logger.error(f"Error formatting markdown: {type(e).__name__}#{e}")
                            messageTextParsed = None
                        else:
                            try:
                                # logger.debug(f"Sending MarkdownV2: {replyText}")
                                replyMessage = await self._retryTelegramSend(
                                    self.tgBot.send_message,
                                    text=messageTextParsed,
                                    parse_mode=telegram.constants.ParseMode.MARKDOWN_V2,
                                    **replyKwargs,
                                )
                            except telegram.error.BadRequest as e:
                                # Telegram rejected the markdown — fallback to raw text.
                                # Transient errors (TimedOut/NetworkError/RetryAfter) have
                                # already been retried inside _retryTelegramSend and bubble
                                # past this except to the outer handler.
                                logger.error(f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}")

                    if replyMessage is None:
                        replyMessage = await self._retryTelegramSend(
                            self.tgBot.send_message,
                            text=addMessagePrefix + _messageText,
                            **replyKwargs,
                        )

                    if replyMessage is not None:
                        replyMessageList.append(replyMessage)

            try:
                if not replyMessageList:
                    raise ValueError("No reply messages")

                if not skipLogs:
                    logger.debug(f"Sent messages: {[utils.dumpTelegramMessage(msg) for msg in replyMessageList]}")

                # Save message
                for replyMessage in replyMessageList:
                    ensuredReplyMessage = EnsuredMessage.fromTelegramMessage(replyMessage)
                    ensuredReplyList.append(ensuredReplyMessage)

            except Exception as e:
                logger.error(f"Error while saving chat message: {type(e).__name__}#{e}")
                logger.exception(e)
                # Message was sent, so return True anyway
                return ensuredReplyList

        except Exception as e:
            logger.error(f"Error while sending message: {type(e).__name__}#{e}")
            logger.exception(e)
            if sendErrorIfAny:
                try:
                    await self.tgBot.send_message(
                        chat_id=chatId,
                        text=f"Error while sending message: {type(e).__name__}#{e}",
                        reply_to_message_id=replyToMessageId.asInt() if replyToMessageId is not None else None,
                        message_thread_id=threadId,
                    )
                except Exception as error_e:
                    logger.error(f"Failed to send error message: {type(error_e).__name__}#{error_e}")
            return ensuredReplyList

        return ensuredReplyList

    async def deleteMessage(self, ensuredMessage: EnsuredMessage) -> bool:
        """Delete a message from the chat.

        Args:
            ensuredMessage: The message to delete, containing recipient and message ID

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        return await self.deleteMessagesById(ensuredMessage.recipient.id, [ensuredMessage.messageId])

    async def deleteMessagesById(self, chatId: int, messageIds: List[MessageId]) -> bool:
        """Delete multiple messages by their IDs in the specified chat.

        Args:
            chatId: The ID of the chat where messages should be deleted
            messageIds: List of message IDs to delete (int for Telegram, str for Max)

        Returns:
            bool: True if deletion was successful, False otherwise
        """

        if self.botProvider == BotProvider.TELEGRAM and self.tgBot is not None:
            return await self.tgBot.delete_messages(
                chat_id=chatId,
                message_ids=[v.asInt() for v in messageIds],
            )
        elif self.botProvider == BotProvider.MAX and self.maxBot is not None:
            return await self.maxBot.deleteMessages([messageId.asStr() for messageId in messageIds])

        logger.error(f"Can not delete {messageIds} in platform {self.botProvider}")
        return False

    async def forwardMessages(
        self,
        fromChatId: int,
        messageIds: List[MessageId],
        toChatId: int,
        *,
        threadId: Optional[int] = None,
        notify: Optional[bool] = None,
    ) -> List[MessageId]:
        """Forward (copy) messages from one chat into another.

        Telegram wraps PTB's ``copy_messages`` (handles single messages and
        media groups alike in one call); Max has no bulk-forward API, so each
        source id is forwarded individually via its own ``sendMessage`` call
        with a ``forwardFrom`` link. The returned IDs identify the newly
        created messages in the destination chat.

        Args:
            fromChatId: ID of the chat to copy messages from.
            messageIds: IDs of the source messages (a single message as a
                one-element list, or all IDs of a media group). An empty list
                short-circuits and returns ``[]``.
            toChatId: ID of the chat to copy messages into.
            threadId: Optional Telegram forum thread ID (ignored on Max).
            notify: Whether to send a notification for the copied messages.
                ``None`` uses the platform default.

        Returns:
            List of MessageIds of the newly created messages in the destination
            chat — one entry per source message on both platforms (Telegram
            returns them from a single ``copy_messages`` call, Max from one
            ``sendMessage`` call per id). Returns an empty list when
            ``messageIds`` is empty.

        Raises:
            RuntimeError: If the configured bot provider is neither Telegram nor
                Max, or the matching bot client is not configured.
        """
        if not messageIds:
            return []

        if self.botProvider == BotProvider.TELEGRAM and self.tgBot is not None:
            forwardKwargs = {
                "chat_id": toChatId,
                "from_chat_id": fromChatId,
                "message_ids": [m.asInt() for m in messageIds],
            }
            if threadId is not None:
                forwardKwargs["message_thread_id"] = threadId
            if notify is not None:
                forwardKwargs["disable_notification"] = not notify
            try:
                result = await self.tgBot.copy_messages(**forwardKwargs)
            except Exception:
                logger.exception(f"Failed to forward messages {messageIds} from chat {fromChatId} to chat {toChatId}")
                raise
            # copy_messages returns tuple[telegram.MessageId, ...]; extract the
            # int id and wrap in our MessageId.
            return [MessageId(mid.message_id) for mid in result]

        if self.botProvider == BotProvider.MAX and self.maxBot is not None:
            # Max has no bulk-forward API, so each source id is forwarded
            # individually via its own forwardFrom link.
            results: List[MessageId] = []
            for messageId in messageIds:
                try:
                    result = await self.maxBot.sendMessage(
                        chatId=toChatId,
                        forwardFrom=messageId.asStr(),
                        notify=notify,
                    )
                except Exception:
                    logger.exception(f"Failed to forward message {messageId} from chat {fromChatId} to chat {toChatId}")
                    raise
                results.append(MessageId(result.message.body.mid))
            return results

        raise RuntimeError(f"Unexpected bot provider: {self.botProvider}")

    async def sendChatAction(self, ensuredMessage: EnsuredMessage, typingAction: TypingAction) -> bool:
        """Send chat action (typing indicator) to show bot activity.

        Sends a typing action or other status indicator to inform users that the bot
        is processing their request. Different platforms support different action types.

        Args:
            ensuredMessage: Message containing chat information (recipient and threadId)
            typingAction: Type of action to send (e.g., typing, uploading_photo)

        Returns:
            True if action was sent successfully, False otherwise

        Raises:
            ValueError: If platform is not supported (neither Telegram nor Max)
        """
        if self.botProvider == BotProvider.TELEGRAM and self.tgBot is not None:
            return await self.tgBot.send_chat_action(
                chat_id=ensuredMessage.recipient.id,
                action=typingAction.toTelegram(),
                message_thread_id=ensuredMessage.threadId,
            )
        elif self.botProvider == BotProvider.MAX and self.maxBot is not None:
            return await self.maxBot.sendAction(
                chatId=ensuredMessage.recipient.id,
                action=typingAction.toMax(),
            )
        else:
            raise ValueError(f"Unexpected platform: {self.botProvider}")

    async def downloadAttachment(self, mediaId: str, fileId: str) -> Optional[bytes]:
        """Download file attachment from Max/Telegram platform.

        Args:
            mediaId: Unique identifier for the media in the database
            fileId:
                For Max:
                    URL of the file to download from Max Messenger
                For Telegram:
                    Telegram file_id to download

        Returns:
            File content as bytes, or None if download fails or platform mismatch
        """

        if self.botProvider == BotProvider.MAX and self.maxBot is not None:
            return await self.maxBot.downloadAttachmentPayload(fileId)
        elif self.botProvider == BotProvider.TELEGRAM and self.tgBot is not None:
            fileInfo = await self.tgBot.get_file(fileId)
            logger.debug(f"{mediaId}#{fileId} File info: {fileInfo}")
            return bytes(await fileInfo.download_as_bytearray())
        else:
            raise ValueError(f"Unexpected platform: {self.botProvider}")

    async def banUserInChat(self, *, chatId: int, userId: int) -> bool:
        """Ban user from chat.

        Args:
            chatId: ID of chat to ban user from
            userId: ID of user to ban

        Returns:
            True if ban was successful, False otherwise

        Raises:
            ValueError: If platform is not supported
        """
        if self.botProvider == BotProvider.TELEGRAM and self.tgBot is not None:
            if userId < 0:
                return await self.tgBot.ban_chat_sender_chat(
                    chat_id=chatId,
                    sender_chat_id=userId,
                )
            else:
                return await self.tgBot.ban_chat_member(
                    chat_id=chatId,
                    user_id=userId,
                    revoke_messages=True,
                )
        elif self.botProvider == BotProvider.MAX and self.maxBot is not None:
            return await self.maxBot.removeMember(chatId=chatId, userId=userId, block=True)
        else:
            raise ValueError(f"Unexpected platform: {self.botProvider}")

    async def unbanUserInChat(self, *, chatId: int, userId: int) -> bool:
        """Unban user from chat.

        Args:
            chatId: ID of chat to unban user from
            userId: ID of user to unban

        Returns:
            True if unban was successful, False otherwise

        Raises:
            ValueError: If platform is not supported
        """
        if self.botProvider == BotProvider.TELEGRAM and self.tgBot is not None:
            if userId > 0:
                return await self.tgBot.unban_chat_member(chat_id=chatId, user_id=userId, only_if_banned=True)
            else:
                return await self.tgBot.unban_chat_sender_chat(chat_id=chatId, sender_chat_id=userId)
        elif self.botProvider == BotProvider.MAX and self.maxBot is not None:
            logger.warning("There is no unban action in Max messenger...")
            return False
        else:
            raise ValueError(f"Unexpected platform: {self.botProvider}")

    async def getChatInfo(self, message: EnsuredMessage) -> ChatInfoDict:
        """
        Get chat information from the message.

        Extracts chat information from the provided message, handling different bot
        platforms (Telegram and MAX) appropriately. For Telegram messages, extracts
        directly from the base message. For MAX messages, retrieves chat information
        from the MAX bot API.

        Args:
            message: The message to extract chat information from as
                      [`EnsuredMessage`](internal/bot/models/ensured_message.py)

        Returns:
            Chat information dictionary as [`ChatInfoDict`](internal/database/models.py)

        Raises:
            ValueError: If the base message is not a telegram.Message when using
                          Telegram provider, or if an unexpected platform is encountered
        """
        if self.botProvider == BotProvider.TELEGRAM and self.tgBot is not None:
            baseMessage = message.getBaseMessage()
            if not isinstance(baseMessage, telegram.Message):
                raise ValueError("Base message is not a telegram.Message")
            chat = baseMessage.chat

            now = utils.now()
            return {
                "chat_id": chat.id,
                "title": chat.title,
                "username": chat.username,
                "is_forum": chat.is_forum or False,
                "type": message.recipient.chatType,
                "created_at": now,
                "updated_at": now,
                "bot_status": ChatBotStatus.ACTIVE,
            }

        elif self.botProvider == BotProvider.MAX and self.maxBot is not None:
            maxChatInfo = await self.maxBot.getChat(message.recipient.id)
            chatUsername = maxChatInfo.link
            if maxChatInfo.dialog_with_user is not None:
                chatUsername = maxChatInfo.dialog_with_user.username
                if not chatUsername:
                    chatUsername = maxChatInfo.dialog_with_user.first_name
                    if maxChatInfo.dialog_with_user.last_name:
                        chatUsername += " " + maxChatInfo.dialog_with_user.last_name

            now = utils.now()
            return {
                "chat_id": maxChatInfo.chat_id,
                "title": maxChatInfo.title,
                "username": chatUsername,
                "is_forum": False,
                "type": message.recipient.chatType,
                "created_at": now,
                "updated_at": now,
                "bot_status": ChatBotStatus.ACTIVE,
            }

        else:
            raise ValueError(f"Unexpected platform: {self.botProvider}")
