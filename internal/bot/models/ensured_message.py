"""
EnsuredMessage: wrapper around telegram.Message
"""

import asyncio
import datetime
import logging

import time
from typing import Any, Dict, Optional, Union

from telegram import Chat, Message, User
import telegram.constants

from lib.ai.models import ModelMessage
import lib.utils as utils

from .enums import LLMMessageFormat
from ...models import MessageType
from .media import MediaProcessingInfo
from internal.database.models import ChatMessageDict, MediaAttachmentDict, MediaStatus
from internal.database.wrapper import DatabaseWrapper


logger = logging.getLogger(__name__)

MAX_MEDIA_AWAIT_SECS = 300  # 5 minutes
MEDIA_AWAIT_DELAY = 2.5


class MessageSender:
    __slots__ = ("id", "name", "username")

    def __init__(self, id: int, name: str, username: str):
        self.id = id
        self.name = name
        self.username = username

    def __str__(self) -> str:
        return f"#{self.id} {self.name} ({self.username})"

    def copy(self) -> "MessageSender":
        return MessageSender(self.id, self.name, self.username)

    @classmethod
    def fromUser(cls, user: User) -> "MessageSender":
        return cls(user.id, user.full_name, user.name)

    @classmethod
    def fromChat(cls, chat: Chat) -> "MessageSender":
        return cls(chat.id, chat.effective_name or "", f"@{chat.username}" if chat.username else "")


"""
A class to encapsulate and ensure the presence of essential message attributes from a Telegram message.

This class processes a `Message` object or database chat message, extracting and validating key information such as
user, chat, message text, reply information, quote information, topic-related data, and media content. It provides
methods for LLM formatting, media processing, and conversion to model messages for AI interactions.

Attributes:
    user (User): The user who sent the message.
    chat (Chat): The chat the message belongs to.
    sender (MessageSender): The sender information (user or chat).
    messageId (int): The unique identifier of the message.
    date (datetime.datetime): The date and time when the message was sent.
    messageText (str): The text of the message, or an empty string if not present.
    messageType (MessageType): The type of the message (TEXT, IMAGE, VIDEO, AUDIO, etc.).
    isReply (bool): Indicates if the message is a reply.
    replyId (Optional[int]): The ID of the message being replied to, if applicable.
    replyText (Optional[str]): The text of the message being replied to, if applicable.
    isQuote (bool): Indicates if the message contains a quote.
    quoteText (Optional[str]): The quoted text content, if applicable.
    isTopicMessage (bool): Indicates if the message is part of a forum topic.
    threadId (Optional[int]): The thread ID if the message is in a topic.
    mediaId (Optional[str]): Unique identifier for media attachments.
    mediaContent (Optional[str]): Description of media content, if applicable.
    userData (Optional[Dict[str, Any]]): Additional user data associated with the message.

Class Methods:
    fromMessage: Creates EnsuredMessage from a Telegram Message object.
    fromDBChatMessage: Creates EnsuredMessage from a database ChatMessageDict.

Methods:
    getBaseMessage: Returns the original `Message` object.
    setBaseMessage: Sets the original `Message` object.
    setUserData: Sets additional user data for the message.
    setMediaId: Sets the media identifier.
    setMediaProcessingInfo: Sets media processing information.
    updateMediaContent: Updates media content from database (async).
    formatForLLM: Formats the message for LLM consumption in JSON or TEXT format (async).
    toModelMessage: Converts to ModelMessage for AI model interactions (async).
    setSender: Sets the sender information from User, Chat, or MessageSender.
    __str__: Returns a JSON string representation of the message's key attributes.

Raises:
    ValueError: If the message's user or chat information is missing, or if invalid sender type is provided.
"""


class EnsuredMessage:
    __slots__ = (
        "_message",
        "user",
        "chat",
        "sender",
        "messageId",
        "date",
        "messageText",
        "messageType",
        "replyId",
        "replyText",
        "isReply",
        "isQuote",
        "quoteText",
        "threadId",
        "isTopicMessage",
        "mediaContent",
        "mediaId",
        "_mediaProcessingInfo",
        "userData",
    )

    def __init__(
        self,
        user: User,
        chat: Chat,
        messageId: int,
        date: datetime.datetime,
        messageText: str = "",
        messageType: MessageType = MessageType.UNKNOWN,
    ):

        self._message: Optional[Message] = None

        self.user: User = user
        self.chat: Chat = chat
        self.sender: MessageSender = MessageSender.fromUser(user)

        self.messageId: int = messageId
        self.date: datetime.datetime = date
        self.messageText: str = messageText
        self.messageType: MessageType = messageType

        # If this is reply, then set replyId and replyText
        self.replyId: Optional[int] = None
        self.replyText: Optional[str] = None
        self.isReply: bool = False
        self.isQuote: bool = False
        self.quoteText: Optional[str] = None

        # If this is topic message, then set threadId
        self.threadId: Optional[int] = None
        self.isTopicMessage: bool = False

        self.mediaContent: Optional[str] = None
        self.mediaId: Optional[str] = None
        self._mediaProcessingInfo: Optional[MediaProcessingInfo] = None

        self.userData: Optional[Dict[str, Any]] = None

    @classmethod
    def fromMessage(cls, message: Message) -> "EnsuredMessage":
        """Create EnsuredMessage from Telegram message"""
        if not message.from_user:
            raise ValueError("Message User undefined")

        if not message.chat:
            raise ValueError("Message Chat undefined")

        messageText: str = ""
        messageType: MessageType = MessageType.TEXT
        if message.text:
            messageText = message.text_markdown_v2
        elif message.caption:
            messageText = message.caption_markdown_v2

        # If there are photo in message, set proper type + handle caption (if any) as messageText
        if message.photo:
            if messageType != MessageType.TEXT:
                logger.warning(
                    f"EnsuredMessage.fromMessage: messageType is {messageType}, "
                    f"but message has photo: {message.photo}"
                )
            messageType = MessageType.IMAGE

        if message.sticker:
            if messageType != MessageType.TEXT:
                logger.warning(
                    f"EnsuredMessage.fromMessage: messageType is {messageType}, "
                    f"but message has sticker: {message.sticker}"
                )
            messageType = MessageType.STICKER
            messageText = message.sticker.emoji if message.sticker.emoji else ""

        if message.animation:
            if messageType != MessageType.TEXT:
                logger.warning(
                    f"EnsuredMessage.fromMessage: messageType is {messageType}, "
                    f"but message has animation: {message.animation}"
                )
            messageType = MessageType.ANIMATION

        if message.video:
            if messageType != MessageType.TEXT:
                logger.warning(
                    f"EnsuredMessage.fromMessage: messageType is {messageType}, "
                    f"but message has video: {message.video}"
                )
            messageType = MessageType.VIDEO

        if message.video_note:
            if messageType != MessageType.TEXT:
                logger.warning(
                    f"EnsuredMessage.fromMessage: messageType is {messageType}, "
                    f"but message has video_note: {message.video_note}"
                )
            messageType = MessageType.VIDEO_NOTE

        if message.audio:
            if messageType != MessageType.TEXT:
                logger.warning(
                    f"EnsuredMessage.fromMessage: messageType is {messageType}, "
                    f"but message has audio: {message.audio}"
                )
            messageType = MessageType.AUDIO

        if message.voice:
            if messageType != MessageType.TEXT:
                logger.warning(
                    f"EnsuredMessage.fromMessage: messageType is {messageType}, "
                    f"but message has voice: {message.voice}"
                )
            messageType = MessageType.VOICE

        if message.document:
            if messageType != MessageType.TEXT:
                logger.warning(
                    f"EnsuredMessage.fromMessage: messageType is {messageType}, "
                    f"but message has document: {message.document}"
                )
            messageType = MessageType.DOCUMENT

        if messageType == MessageType.TEXT:
            if not message.text:
                # Probably not a text message, just log it for now
                logger.error(f"Message text undefined: {message}")
                messageType = MessageType.UNKNOWN

        ensuredMessage = EnsuredMessage(
            user=message.from_user,
            chat=message.chat,
            messageId=message.message_id,
            date=message.date,
            messageText=messageText,
            messageType=messageType,
        )
        ensuredMessage.setBaseMessage(message)

        # If this is reply, then set replyId and replyText
        if message.reply_to_message:
            # If reply_to_message is message about creating topic, then it isn't reply
            if message.reply_to_message.forum_topic_created is None:
                ensuredMessage.replyId = message.reply_to_message.message_id
                ensuredMessage.isReply = True
                if message.reply_to_message.text:
                    ensuredMessage.replyText = message.reply_to_message.text_markdown_v2

        # It is possible, that quote isn't reply to message in this chat
        if message.quote and message.quote.text:
            ensuredMessage.isQuote = True
            ensuredMessage.quoteText = message.quote.text

        # If this is topic message, then set threadId
        isTopicMessage = message.is_topic_message is True if message.is_topic_message is not None else False
        if isTopicMessage:
            ensuredMessage.isTopicMessage = True
            ensuredMessage.threadId = message.message_thread_id

        if message.sender_chat:
            ensuredMessage.setSender(message.sender_chat)
        else:
            ensuredMessage.setSender(message.from_user)

        logger.debug(f"Ensured Message from Telegram: {ensuredMessage}")
        return ensuredMessage

    @classmethod
    def fromDBChatMessage(cls, data: ChatMessageDict) -> "EnsuredMessage":
        """Create EnsuredMessage from DB chat message"""
        ensuredMessage = EnsuredMessage(
            user=User(
                id=data["user_id"],
                first_name=data["full_name"],
                is_bot=data["message_category"] == "bot",
                username=data["username"].lstrip("@"),
            ),
            chat=Chat(
                id=data["chat_id"],
                type=(
                    telegram.constants.ChatType.PRIVATE
                    if data["user_id"] == data["chat_id"]
                    else telegram.constants.ChatType.SUPERGROUP
                ),
            ),
            messageId=data["message_id"],
            date=data["date"],
            messageText=data["message_text"],
            messageType=MessageType(data["message_type"]),
        )

        ensuredMessage.replyId = data["reply_id"]
        # ensuredMessage.replyText: Optional[str] = None
        ensuredMessage.isReply = data["reply_id"] is not None

        ensuredMessage.quoteText = data["quote_text"]
        ensuredMessage.isQuote = data["quote_text"] is not None

        # If this is topic message, then set threadId
        ensuredMessage.threadId = data["thread_id"]
        ensuredMessage.isTopicMessage = data["thread_id"] != 0

        ensuredMessage.mediaContent = data["media_description"]
        ensuredMessage.mediaId = data["media_id"]

        # logger.debug(f"Ensured Message from DB Chat: {ensuredMessage}")
        return ensuredMessage

    def setUserData(self, userData: Dict[str, Any]):
        self.userData = userData.copy()

    def getBaseMessage(self) -> Message:
        if self._message is None:
            raise ValueError("Message is not set")
        return self._message

    def setBaseMessage(self, message: Message):
        self._message = message

    def setMediaId(self, mediaId: str):
        self.mediaId = mediaId

    def setMediaProcessingInfo(self, mediaProcessingInfo: MediaProcessingInfo):
        self._mediaProcessingInfo = mediaProcessingInfo
        self.mediaId = mediaProcessingInfo.id

    async def updateMediaContent(self, db: DatabaseWrapper) -> None:
        """
        Set the media content of the message from DB.
        """
        if self._mediaProcessingInfo:
            await self._mediaProcessingInfo.awaitResult()

        if self.mediaId is None:
            return

        mediaAttachment = await self.__class__._awaitMedia(db, self.mediaId)
        if mediaAttachment and mediaAttachment.get("description", None) is not None:
            self.mediaContent = mediaAttachment["description"]

    @classmethod
    async def _awaitMedia(cls, db: DatabaseWrapper, mediaId: str) -> Optional[MediaAttachmentDict]:
        """
        Await the media content of the message from DB.
        """
        startTime = time.time()
        mediaAttachment: Optional[MediaAttachmentDict] = None
        while time.time() - startTime < MAX_MEDIA_AWAIT_SECS:
            mediaAttachment = db.getMediaAttachment(mediaId)
            if mediaAttachment is None:
                logger.error(f"Media#{mediaId} not found")
                return None

            logger.debug(
                f"Media#{mediaId} awaiting for proper status (current: "
                f"{mediaAttachment['status']}) ({time.time() - startTime} secs passed)"
            )

            match MediaStatus(str(mediaAttachment["status"])):
                case MediaStatus.PENDING:
                    mediaUpdated = mediaAttachment["updated_at"]
                    if not isinstance(mediaUpdated, datetime.datetime):
                        logger.error(
                            f"Media#{mediaId} attachment `updated_at` is not a datetime: "
                            f"{type(mediaUpdated).__name__}({mediaUpdated})"
                        )
                        return mediaAttachment

                    if utils.getAgeInSecs(mediaUpdated) > MAX_MEDIA_AWAIT_SECS:
                        logger.warning(
                            f"Media#{mediaId} is pending for too long ({time.time() - mediaUpdated.timestamp()})"
                        )
                        return mediaAttachment
                    await asyncio.sleep(MEDIA_AWAIT_DELAY)
                case MediaStatus.DONE:
                    return mediaAttachment
                case _:
                    logger.error(f"Media#{mediaId} has invalid status: {mediaAttachment['status']}")
                    return mediaAttachment

        logger.error(f"Media#{mediaId} processing timed out")
        return mediaAttachment

    async def formatForLLM(
        self,
        db: DatabaseWrapper,
        format: LLMMessageFormat = LLMMessageFormat.JSON,
        replaceMessageText: Optional[str] = None,
        stripAtsign: bool = False,
    ) -> str:
        await self.updateMediaContent(db)

        messageText = self.messageText if replaceMessageText is None else replaceMessageText
        userName = self.user.name
        if stripAtsign:
            userName = userName.lstrip("@")
        match format:
            case LLMMessageFormat.JSON:
                ret = {
                    "login": userName,
                    "name": self.user.full_name,
                    "date": self.date.isoformat(),
                    "messageId": self.messageId,
                    "type": str(self.messageType),
                    "text": messageText,
                }
                if self.replyId:
                    ret["replyId"] = self.replyId
                if self.isQuote and self.quoteText:
                    ret["quote"] = self.quoteText

                if self.mediaContent:
                    ret["mediaDescription"] = self.mediaContent

                if self.userData:
                    ret["userData"] = self.userData

                # logger.debug(f"EM.formatForLLM():{self} -> {ret}")
                return utils.jsonDumps(ret, compact=False)

            case LLMMessageFormat.TEXT:
                ret = messageText
                if self.mediaContent:
                    ret = f"<media-description>{self.mediaContent}</media-description>\n\n{ret}"
                if self.isQuote and self.quoteText:
                    ret = f"<quote>{self.quoteText}</quote>\n\n{ret}"
                return ret

            case _:
                raise ValueError(f"Invalid format: {format}")

        raise RuntimeError("Unreacible code has been reached")

    async def toModelMessage(
        self,
        db: DatabaseWrapper,
        format: LLMMessageFormat = LLMMessageFormat.JSON,
        replaceMessageText: Optional[str] = None,
        stripAtsign: bool = False,
        role: str = "user",
    ) -> ModelMessage:
        """Convert the message to a model message."""

        if format == LLMMessageFormat.SMART:
            if role == "user":
                format = LLMMessageFormat.JSON
            else:
                format = LLMMessageFormat.TEXT
        return ModelMessage(
            role=role,
            content=await self.formatForLLM(
                db=db, format=format, replaceMessageText=replaceMessageText, stripAtsign=stripAtsign
            ),
        )

    def __str__(self) -> str:
        replyText = self.replyText
        if replyText is not None and len(replyText) > 30:
            replyText = f"{replyText[:25]}...({len(replyText)})"
        quoteText = self.quoteText
        if quoteText is not None and len(quoteText) > 30:
            quoteText = f"{quoteText[:25]}...({len(quoteText)})"
        ret = {
            "sender": self.sender,
            "chat.id": self.chat.id,
            "messageId": self.messageId,
            "date": self.date.isoformat(),
            "messageType": self.messageType,
            "messageText": self.messageText,
            "isReply": self.isReply,
            "replyId": self.replyId,
            "replyText": replyText,
            "isQuote": self.isQuote,
            "quoteText": quoteText,
            "isTopicMessage": self.isTopicMessage,
            "threadId": self.threadId,
            "mediaId": self.mediaId,
            "mediaContent": self.mediaContent,
            "userData": "{...}" if self.userData else None,
        }
        for key in list(ret.keys()):
            if ret[key] is None:
                ret.pop(key, None)
        return utils.jsonDumps(ret, compact=False, sort_keys=False)

    def setSender(self, sender: Union[User, Chat, MessageSender]):
        if isinstance(sender, User):
            self.sender = MessageSender.fromUser(sender)
        elif isinstance(sender, Chat):
            self.sender = MessageSender.fromChat(sender)
        elif isinstance(sender, MessageSender):
            self.sender = sender.copy()
        else:
            raise ValueError(f"Invalid sender type: {type(sender)}")
