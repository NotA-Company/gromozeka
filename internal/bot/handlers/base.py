"""
Telegram bot command handlers for Gromozeka.
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
    """Enum for handler result status."""

    FINAL = "final"  # Processed and no need further processing
    SKIPPED = "skipped"  # Skipped processing
    NEXT = "next"  # Processed, need to process further
    ERROR = "error"  # Processing error (can be processed further)
    FATAL = "fatal"  # Fatal error, need to stop processing


class BaseBotHandler(CommandHandlerMixin):
    """Base class for bot handlers."""

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """Initialize handlers with database and LLM model."""
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
        self.cache.injectDatabase(self.db)

        self.queueService = QueueService.getInstance()

        self._bot: Optional[ExtBot] = None

    def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
        """Get all command handlers (auto-discovered via decorators), dood!"""
        return super().getCommandHandlers()

    def injectBot(self, bot: ExtBot) -> None:
        """Inject the bot instance."""
        self._bot = bot

    ###
    # Chat settings Managenent
    ###

    def getChatSettings(
        self, chatId: Optional[int], returnDefault: bool = True
    ) -> Dict[ChatSettingsKey, ChatSettingsValue]:
        """Get the chat settings for the given chat."""
        if chatId is None:
            return self.chatDefaults.copy()

        chatSettings = self.cache.getChatSettings(chatId)

        if returnDefault:
            return {**self.chatDefaults, **chatSettings}

        return chatSettings

    def setChatSetting(self, chatId: int, key: ChatSettingsKey, value: ChatSettingsValue) -> None:
        """Set the chat settings for the given chat."""
        # TODO: Should I add deprecation warning?
        self.cache.setChatSetting(chatId, key, value)

    def unsetChatSetting(self, chatId: int, key: ChatSettingsKey) -> None:
        """Unset the chat settings for the given chat."""
        self.cache.unsetChatSetting(chatId=chatId, key=key)

    ###
    # User Data Management
    ###

    def getUserData(self, chatId: int, userId: int) -> UserDataType:
        """Get the user data for the given chat."""
        return self.cache.getChatUserData(chatId=chatId, userId=userId)

    def setUserData(
        self, chatId: int, userId: int, key: str, value: UserDataValueType, append: bool = False
    ) -> UserDataValueType:
        """Set specific user data for the given chat."""
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
        """Unset specific user data for the given chat."""
        self.cache.unsetChatUserData(chatId=chatId, userId=userId, key=key)

    def clearUserData(self, chatId: int, userId: int) -> None:
        """Clear all user data for the given chat."""
        self.cache.clearChatUserData(chatId=chatId, userId=userId)

    def _updateEMessageUserData(self, ensuredMessage: EnsuredMessage) -> None:
        ensuredMessage.setUserData(self.getUserData(ensuredMessage.chat.id, ensuredMessage.user.id))

    def checkEMMentionsMe(self, ensuredMessage: EnsuredMessage) -> MentionCheckResult:
        """Check if the ensuredMessage mentions the bot."""
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
        """Check if the user is an admin (or bot owner)."""
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
        """Send a message to the chat or user."""

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
        """Get Chat info from cache or DB"""
        return self.cache.getChatInfo(chatId)

    def updateChatInfo(self, chat: Chat) -> None:
        """Update Chat info. Do not save it to DB if it is in cache and wasn't changed"""
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
        """Update Chat Topic info. Do not save it to DB if it is in cache and wasn't changed"""
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
        """Save a chat message to the database."""
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
        """Get user metadata."""
        if userInfo is None:
            return {}

        metadataStr = userInfo["metadata"]
        if metadataStr:
            return json.loads(metadataStr)
        return {}

    def setUserMetadata(self, chatId: int, userId: int, metadata: UserMetadataDict, isUpdate: bool = False) -> None:
        """Set user metadata."""
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
        Parse image content using LLM
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
        Process Media from message
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
        Process a sticker from message if needed
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
        Process a photo from message if needed
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
        """Handle regular text messages."""
        # By default, skip processing
        return HandlerResultStatus.SKIPPED

    async def buttonHandler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        data: CallbackDataDict,
    ) -> HandlerResultStatus:
        """Parses the CallbackQuery and updates the message text."""
        # By default, skip processing
        return HandlerResultStatus.SKIPPED
