"""Multi-platform bot implementation for Telegram and Max Messenger.

Provides unified bot interface supporting both Telegram and Max Messenger platforms
with message handling, media processing, and administrative operations.
"""

import logging
from collections.abc import Sequence
from typing import Any, Dict, List, Optional

import magic
import telegram
import telegram.ext

import lib.max_bot as libMax
import lib.max_bot.models as maxModels
from internal.bot.common.models import CallbackButton, TypingAction
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import BotProvider, ChatType, EnsuredMessage, MessageRecipient, MessageSender
from internal.models import MessageIdType
from internal.services.cache import CacheService
from lib import utils
from lib.markdown.parser import markdownToMarkdownV2

logger = logging.getLogger(__name__)


class TheBot:
    """Multi-platform bot client supporting Telegram and Max Messenger.

    Provides unified interface for bot operations across different messaging platforms
    including message sending, media handling, user management, and administrative functions.

    Args:
        botProvider: Platform type (Telegram or Max)
        config: Bot configuration dictionary
        maxBot: Max Messenger bot client instance (required if botProvider is MAX)
        tgBot: Telegram bot client instance (required if botProvider is TELEGRAM)
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
            config: Configuration dictionary containing bot settings
            maxBot: Max Messenger bot client (required if botProvider is MAX)
            tgBot: Telegram bot client (required if botProvider is TELEGRAM)

        Raises:
            ValueError: If required bot client is not provided for the specified platform
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

        self.botOwnersUsername: List[str] = []
        self.botOwnersId: List[int] = []
        for val in self.config.get("bot_owners", []):
            if isinstance(val, int):
                self.botOwnersId.append(val)
            elif isinstance(val, str):
                self.botOwnersUsername.append(val.lower())
                if val and val[0] in "-0123456789":
                    try:
                        intVal = int(val)
                        self.botOwnersId.append(intVal)
                    except ValueError:
                        pass
            else:
                raise ValueError(f"Unexpected type of botowner value '{val}': {type(val).__name__}")

        logger.debug(f"Bot Owners: byId: {self.botOwnersId}, byUsername: {self.botOwnersUsername}")
        self.cache = CacheService.getInstance()

        ###

    # Different helpers
    ###

    async def getBotId(self) -> int:
        """Get bot's unique identifier.

        Returns:
            Bot's unique ID from the active platform

        Raises:
            RuntimeError: If no active bot client is configured
        """
        if self.tgBot:
            return self.tgBot.id
        elif self.maxBot:
            return (await self.maxBot.getMyInfo()).user_id

        raise RuntimeError("No Active bot found")

    async def getBotUserName(self) -> Optional[str]:
        """Get bot's username.

        Returns:
            Bot's username from the active platform, or None if not set

        Raises:
            RuntimeError: If no active bot client is configured
        """
        if self.tgBot:
            return self.tgBot.username
        elif self.maxBot:
            return (await self.maxBot.getMyInfo()).username

        raise RuntimeError("No Active bot found")

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
        # If chat is None, then we are checking if it's bot owner only

        username = user.username
        if username:
            username = username.lower().lstrip("@")

        if allowBotOwners and (username in self.botOwnersUsername or user.id in self.botOwnersId):
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
        chatAdmins = self.cache.getChatAdmins(chat.id)
        if chatAdmins is not None:
            return user.id in chatAdmins

        chatAdmins = {}  # userID -> username
        if self.botProvider == BotProvider.TELEGRAM and self.tgBot is not None:
            for admin in await self.tgBot.get_chat_administrators(chat_id=chat.id):
                chatAdmins[admin.user.id] = admin.user.name

        elif self.botProvider == BotProvider.MAX and self.maxBot is not None:
            maxChatAdmins = (await self.maxBot.getAdmins(chatId=chat.id)).members
            for admin in maxChatAdmins:
                adminName = admin.username
                if adminName is None:
                    adminName = admin.first_name
                    if admin.last_name:
                        adminName += " " + admin.last_name
                else:
                    adminName = f"@{adminName}"

                chatAdmins[admin.user_id] = adminName

        else:
            raise RuntimeError(f"Unexpected platform: {self.botProvider}")

        self.cache.setChatAdmins(chat.id, chatAdmins)
        return user.id in chatAdmins

    def _keyboardToTelegram(self, keyboard: Sequence[Sequence[CallbackButton]]) -> telegram.InlineKeyboardMarkup:
        return telegram.InlineKeyboardMarkup([[btn.toTelegram() for btn in row] for row in keyboard])

    def _keyboardToMax(self, keyboard: Sequence[Sequence[CallbackButton]]) -> maxModels.InlineKeyboardAttachmentRequest:
        return maxModels.InlineKeyboardAttachmentRequest(
            payload=maxModels.Keyboard(buttons=[[btn.toMax() for btn in row] for row in keyboard])
        )

    async def editMessage(
        self,
        messageId: MessageIdType,
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
                ret = await self.tgBot.edit_message_reply_markup(
                    chat_id=chatId,
                    message_id=int(messageId),
                    reply_markup=self._keyboardToTelegram(inlineKeyboard) if inlineKeyboard is not None else None,
                )
            else:
                kwargs = {}
                if useMarkdown:
                    kwargs["parse_mode"] = telegram.constants.ParseMode.MARKDOWN_V2
                    text = markdownToMarkdownV2(text)
                ret = await self.tgBot.edit_message_text(
                    text=text,
                    chat_id=chatId,
                    message_id=int(messageId),
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
        replyToMessage: EnsuredMessage,
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
    ) -> List[EnsuredMessage]:
        """Send message as reply with text and/or photo.

        Args:
            replyToMessage: Message to reply to
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
                )
            case _:
                raise RuntimeError(f"Unexpected bot provider: {self.botProvider}")

    async def _sendMaxMessage(
        self,
        replyToMessage: EnsuredMessage,
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
    ) -> List[EnsuredMessage]:
        if self.maxBot is None:
            raise RuntimeError("Max bot is Undefined")

        if photoData is None and messageText is None:
            logger.error("No message text or photo data provided")
            raise ValueError("No message text or photo data provided")

        replyMessageList: List[maxModels.Message] = []
        ensuredReplyList: List[EnsuredMessage] = []
        # message = replyToMessage.getBaseMessage()
        # if not isinstance(message, maxModels.Message):
        #     logger.error("Invalid message type")
        #     raise ValueError("Invalid message type")
        chatType = replyToMessage.recipient.chatType

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
                "chatId": replyToMessage.recipient.id,
                "replyTo": str(replyToMessage.messageId),
                "format": maxModels.TextFormat.MARKDOWN if tryMarkdownV2 else None,
            }
        )
        attachments: Optional[List[maxModels.AttachmentRequest]] = []

        try:
            if photoData is not None:
                mimeType = magic.from_buffer(photoData, mime=True)
                ext = mimeType.split("/")[1]
                ret = await self.maxBot.uploadFile(
                    filename=f"generated_image.{ext}",
                    data=photoData,
                    mimeType=mimeType,
                    uploadType=maxModels.UploadType.IMAGE,
                )
                if isinstance(ret, maxModels.UploadedPhoto):
                    attachments.append(
                        maxModels.PhotoAttachmentRequest(
                            payload=maxModels.PhotoAttachmentRequestPayload(
                                photos=ret.payload.photos,
                            )
                        )
                    )

            if messageText is not None or attachments:
                # Send Message
                if not attachments:
                    attachments = None
                if messageText is None:
                    messageText = ""

                if not skipLogs:
                    logger.debug(f"Sending reply to {replyToMessage}")

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
                        chatId=replyToMessage.recipient.id,
                        replyTo=str(replyToMessage.messageId),
                    )
                except Exception as error_e:
                    logger.error(f"Failed to send error message: {type(error_e).__name__}#{error_e}")
            return ensuredReplyList

        return ensuredReplyList

    async def _sendTelegramMessage(
        self,
        replyToMessage: EnsuredMessage,
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

        if photoData is None and messageText is None:
            logger.error("No message text or photo data provided")
            raise ValueError("No message text or photo data provided")

        replyMessageList: List[telegram.Message] = []
        ensuredReplyList: List[EnsuredMessage] = []
        message = replyToMessage.toTelegramMessage()
        message.set_bot(self.tgBot)
        chatType = replyToMessage.recipient.chatType
        isPrivate = chatType == ChatType.PRIVATE
        isGroupChat = chatType == ChatType.GROUP

        if typingManager is not None:
            await typingManager.stopTask()

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
                "reply_markup": inlineKeyboard,
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

                replyMessage: Optional[telegram.Message] = None
                if tryMarkdownV2 and messageText is not None:
                    try:
                        messageTextParsed = markdownToMarkdownV2(addMessagePrefix + messageText)
                        # logger.debug(f"Sending MarkdownV2: {replyText}")
                        # TODO: One day start using self.tgBot
                        replyMessage = await message.reply_photo(
                            caption=messageTextParsed,
                            parse_mode=telegram.constants.ParseMode.MARKDOWN_V2,
                            **replyKwargs,
                        )
                    except Exception as e:
                        logger.error(f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}")
                        # Probably error in markdown formatting, fallback to raw text

                if replyMessage is None:
                    _messageText = messageText if messageText is not None else ""
                    replyMessage = await message.reply_photo(caption=addMessagePrefix + _messageText, **replyKwargs)
                if replyMessage is not None:
                    replyMessageList.append(replyMessage)

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
                            # logger.debug(f"Sending MarkdownV2: {replyText}")
                            replyMessage = await message.reply_text(
                                text=messageTextParsed,
                                parse_mode=telegram.constants.ParseMode.MARKDOWN_V2,
                                **replyKwargs,
                            )
                        except Exception as e:
                            logger.error(f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}")
                            # Probably error in markdown formatting, fallback to raw text

                    if replyMessage is None:
                        replyMessage = await message.reply_text(text=addMessagePrefix + _messageText, **replyKwargs)

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
                    await message.reply_text(
                        f"Error while sending message: {type(e).__name__}#{e}",
                        reply_to_message_id=int(replyToMessage.messageId),
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

    async def deleteMessagesById(self, chatId: int, messageIds: List[MessageIdType]) -> bool:
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
                message_ids=[int(v) for v in messageIds],
            )
        elif self.botProvider == BotProvider.MAX and self.maxBot is not None:
            return await self.maxBot.deleteMessages([str(messageId) for messageId in messageIds])

        logger.error(f"Can not delete {messageIds} in platform {self.botProvider}")
        return False

    async def sendChatAction(self, ensuredMessage: EnsuredMessage, typingAction: TypingAction) -> bool:
        """TODO: write docstring"""
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
