"""
Telegram Message Processing and Validation Module, dood!

This module provides robust wrappers and utilities for processing Telegram messages,
ensuring all essential attributes are present and properly formatted for downstream
processing, especially for LLM interactions and database storage, dood.

Key Components:
    - MessageSender: Encapsulates sender information (user or chat)
    - MentionCheckResult: Stores results of bot mention detection
    - EnsuredMessage: Main wrapper class for Telegram messages with validation

The module handles various message types (text, media, replies, quotes, topics)
and provides formatting utilities for AI model consumption, dood.

Constants:
    MAX_MEDIA_AWAIT_SECS: Maximum time to wait for media processing (300 seconds)
    MEDIA_AWAIT_DELAY: Delay between media status checks (2.5 seconds)
"""

import asyncio
from dataclasses import dataclass
import datetime
import logging

import time
from typing import Any, Dict, Optional, Sequence, Tuple, Union

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
    """
    Encapsulates sender information for a message, dood!

    This class stores essential sender details (ID, name, username) and provides
    factory methods to create instances from Telegram User or Chat objects.
    Uses __slots__ for memory efficiency, dood.

    Attributes:
        id (int): Unique identifier of the sender (user ID or chat ID)
        name (str): Display name of the sender (full name for users, effective name for chats)
        username (str): Username of the sender (with @ prefix for chats)
    """

    __slots__ = ("id", "name", "username")

    def __init__(self, id: int, name: str, username: str):
        """
        Initialize a MessageSender instance, dood!

        Args:
            id: Unique identifier of the sender
            name: Display name of the sender
            username: Username of the sender
        """
        self.id = id
        self.name = name
        self.username = username

    def __str__(self) -> str:
        """
        Return a string representation of the sender, dood!

        Returns:
            Formatted string: "#{id} {name} ({username})"
        """
        return f"#{self.id} {self.name} ({self.username})"

    def copy(self) -> "MessageSender":
        """
        Create a deep copy of this MessageSender instance, dood!

        Returns:
            A new MessageSender instance with the same attributes
        """
        return MessageSender(self.id, self.name, self.username)

    @classmethod
    def fromUser(cls, user: User) -> "MessageSender":
        """
        Create a MessageSender from a Telegram User object, dood!

        Args:
            user: Telegram User object containing user information

        Returns:
            MessageSender instance populated with user data
        """
        return cls(user.id, user.full_name, user.name)

    @classmethod
    def fromChat(cls, chat: Chat) -> "MessageSender":
        """
        Create a MessageSender from a Telegram Chat object, dood!

        Args:
            chat: Telegram Chat object containing chat information

        Returns:
            MessageSender instance populated with chat data.
            Username is prefixed with @ if available, dood.
        """
        return cls(chat.id, chat.effective_name or "", f"@{chat.username}" if chat.username else "")


@dataclass
class MentionCheckResult:
    """
    Stores the results of bot mention detection in a message, dood!

    This dataclass holds information about where and how a bot was mentioned
    in a message, including positions of mentions by nickname or username,
    and the remaining text after mention removal.

    Attributes:
        byNick: Tuple of (start_pos, end_pos) if bot was mentioned by custom nickname.
                None if no nickname mention found, dood.
        byName: Tuple of (start_pos, end_pos) if bot was mentioned by username.
                None if no username mention found, dood.
        restText: The remaining message text after removing the mention.
                  None if no mention was found, dood.
    """

    byNick: Optional[Tuple[int, int]] = None
    byName: Optional[Tuple[int, int]] = None

    restText: Optional[str] = None


class EnsuredMessage:
    """
    Wrapper class that ensures presence of essential Telegram message attributes, dood!

    This class processes Telegram Message objects or database chat messages, extracting
    and validating key information such as user, chat, message text, reply information,
    quote information, topic-related data, and media content. It provides methods for
    LLM formatting, media processing, and conversion to model messages for AI interactions.

    The class handles various message types (text, images, videos, audio, documents, etc.)
    and provides robust mention detection and media content processing capabilities, dood.

    Attributes:
        user (User): The user who sent the message
        chat (Chat): The chat the message belongs to
        sender (MessageSender): The sender information (user or chat)
        messageId (int): The unique identifier of the message
        date (datetime.datetime): The date and time when the message was sent
        messageText (str): The text of the message, or empty string if not present
        messageType (MessageType): The type of the message (TEXT, IMAGE, VIDEO, AUDIO, etc.)
        isReply (bool): Indicates if the message is a reply
        replyId (Optional[int]): The ID of the message being replied to, if applicable
        replyText (Optional[str]): The text of the message being replied to, if applicable
        isQuote (bool): Indicates if the message contains a quote
        quoteText (Optional[str]): The quoted text content, if applicable
        isTopicMessage (bool): Indicates if the message is part of a forum topic
        threadId (Optional[int]): The thread ID if the message is in a topic
        mediaId (Optional[str]): Unique identifier for media attachments
        mediaContent (Optional[str]): Description of media content, if applicable
        userData (Optional[Dict[str, Any]]): Additional user data associated with the message

    Class Methods:
        fromMessage: Creates EnsuredMessage from a Telegram Message object
        fromDBChatMessage: Creates EnsuredMessage from a database ChatMessageDict

    Methods:
        getBaseMessage: Returns the original Message object
        setBaseMessage: Sets the original Message object
        setUserData: Sets additional user data for the message
        setMediaId: Sets the media identifier
        setMediaProcessingInfo: Sets media processing information
        updateMediaContent: Updates media content from database (async)
        formatForLLM: Formats the message for LLM consumption in JSON or TEXT format (async)
        toModelMessage: Converts to ModelMessage for AI model interactions (async)
        setSender: Sets the sender information from User, Chat, or MessageSender
        checkHasMention: Checks if the message contains bot mentions
        clearMentionCheckResult: Clears cached mention check results
        __str__: Returns a JSON string representation of the message's key attributes

    Raises:
        ValueError: If the message's user or chat information is missing, or if invalid
                   sender type is provided, dood.
    """

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
        "_rawMessageText",
        "_mentionCheckResult",
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
        """
        Initialize an EnsuredMessage instance, dood!

        Args:
            user: The Telegram User who sent the message
            chat: The Telegram Chat where the message was sent
            messageId: Unique identifier for the message
            date: Timestamp when the message was sent
            messageText: The text content of the message (default: empty string)
            messageType: The type of message (default: MessageType.UNKNOWN)
        """
        self._message: Optional[Message] = None

        self.user: User = user
        self.chat: Chat = chat
        self.sender: MessageSender = MessageSender.fromUser(user)

        self.messageId: int = messageId
        self.date: datetime.datetime = date
        self.messageText: str = messageText
        self._rawMessageText: str = messageText  # Message text without any formating
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
        self._mentionCheckResult: Optional[MentionCheckResult] = None

    @classmethod
    def fromMessage(cls, message: Message) -> "EnsuredMessage":
        """
        Create an EnsuredMessage from a Telegram Message object, dood!

        This factory method extracts all relevant information from a Telegram Message,
        including text, media type, reply information, quotes, and topic data.
        It handles various message types (text, photo, video, audio, documents, etc.)
        and properly sets up all attributes, dood.

        Args:
            message: The Telegram Message object to process

        Returns:
            A fully initialized EnsuredMessage instance with all extracted data

        Raises:
            ValueError: If the message lacks required user or chat information, dood.
        """
        if not message.from_user:
            raise ValueError("Message User undefined")

        if not message.chat:
            raise ValueError("Message Chat undefined")

        messageText: str = ""
        messageType: MessageType = MessageType.TEXT
        rawMessageText: str = ""  # Message text without any formating
        if message.text:
            # TODO: think about parsing Entities to Markdown, but without escaping
            # messageText = message.text_markdown_v2
            messageText = message.text
            rawMessageText = message.text
        elif message.caption:
            # messageText = message.caption_markdown_v2
            messageText = message.caption
            rawMessageText = message.caption

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
        ensuredMessage.setRawMessageText(rawMessageText)

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
        """
        Create an EnsuredMessage from a database ChatMessageDict, dood!

        This factory method reconstructs an EnsuredMessage from database-stored
        message data, including all metadata like replies, quotes, topics, and
        media information, dood.

        Args:
            data: Dictionary containing chat message data from the database

        Returns:
            A fully initialized EnsuredMessage instance populated with database data
        """
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
        """
        Set additional user data for this message, dood!

        Creates a copy of the provided dictionary to avoid external modifications.

        Args:
            userData: Dictionary containing additional user-specific data
        """
        self.userData = userData.copy()

    def getBaseMessage(self) -> Message:
        """
        Get the original Telegram Message object, dood!

        Returns:
            The underlying Telegram Message object

        Raises:
            ValueError: If the base message has not been set, dood.
        """
        if self._message is None:
            raise ValueError("Message is not set")
        return self._message

    def setBaseMessage(self, message: Message):
        """
        Set the original Telegram Message object, dood!

        Args:
            message: The Telegram Message object to store
        """
        self._message = message

    def setRawMessageText(self, rawMessageText: str):
        """
        Set the raw message text without any formatting, dood!

        Args:
            rawMessageText: The unformatted message text
        """
        self._rawMessageText = rawMessageText

    def getRawMessageText(self) -> str:
        """
        Get the raw message text without any formatting, dood!

        Returns:
            The unformatted message text
        """
        return self._rawMessageText

    def setMediaId(self, mediaId: str):
        """
        Set the media identifier for this message, dood!

        Args:
            mediaId: Unique identifier for the media attachment
        """
        self.mediaId = mediaId

    def setMediaProcessingInfo(self, mediaProcessingInfo: MediaProcessingInfo):
        """
        Set media processing information and extract media ID, dood!

        Args:
            mediaProcessingInfo: Object containing media processing details and ID
        """
        self._mediaProcessingInfo = mediaProcessingInfo
        self.mediaId = mediaProcessingInfo.id

    async def updateMediaContent(self, db: DatabaseWrapper) -> None:
        """
        Update the media content description from the database, dood!

        This method waits for media processing to complete (if in progress),
        then retrieves the media description from the database and updates
        the mediaContent attribute, dood.

        Args:
            db: Database wrapper instance for accessing media attachments
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
        Wait for media processing to complete and retrieve media attachment, dood!

        This method polls the database for media attachment status, waiting up to
        MAX_MEDIA_AWAIT_SECS for processing to complete. It handles PENDING and
        DONE statuses appropriately, dood.

        Args:
            db: Database wrapper instance for accessing media attachments
            mediaId: Unique identifier of the media attachment to retrieve

        Returns:
            MediaAttachmentDict if found and processed, None if not found or timed out
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
        """
        Format the message for LLM consumption, dood!

        This method converts the message into a format suitable for AI model processing,
        supporting both JSON and TEXT formats. It includes media descriptions, quotes,
        and user data when available, dood.

        Args:
            db: Database wrapper for accessing media content
            format: Output format (JSON or TEXT), default is JSON
            replaceMessageText: Optional replacement text instead of original message text
            stripAtsign: Whether to strip @ from usernames, default is False

        Returns:
            Formatted string representation of the message for LLM processing

        Raises:
            ValueError: If an invalid format is specified, dood.
        """
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
        """
        Convert the message to a ModelMessage for AI model interactions, dood!

        This method creates a ModelMessage object suitable for passing to AI models,
        with the message content formatted according to the specified format.
        Supports SMART format which automatically chooses JSON for user messages
        and TEXT for other roles, dood.

        Args:
            db: Database wrapper for accessing media content
            format: Output format (JSON, TEXT, or SMART), default is JSON
            replaceMessageText: Optional replacement text instead of original message text
            stripAtsign: Whether to strip @ from usernames, default is False
            role: The role for the model message (e.g., "user", "assistant"), default is "user"

        Returns:
            ModelMessage object ready for AI model consumption, dood.
        """
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
        """
        Return a JSON string representation of the message, dood!

        Creates a comprehensive JSON representation including all key attributes,
        with truncation of long text fields for readability. Omits None values
        from the output, dood.

        Returns:
            JSON-formatted string representation of the message
        """
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
        """
        Set the sender information from User, Chat, or MessageSender, dood!

        This method accepts different types of sender objects and converts them
        to a MessageSender instance, creating a copy to avoid external modifications.

        Args:
            sender: The sender object (User, Chat, or MessageSender)

        Raises:
            ValueError: If an invalid sender type is provided, dood.
        """
        if isinstance(sender, User):
            self.sender = MessageSender.fromUser(sender)
        elif isinstance(sender, Chat):
            self.sender = MessageSender.fromChat(sender)
        elif isinstance(sender, MessageSender):
            self.sender = sender.copy()
        else:
            raise ValueError(f"Invalid sender type: {type(sender)}")

    def clearMentionCheckResult(self) -> None:
        """
        Clear the cached mention check result, dood!

        Call this method before checking mentions with different parameters
        to ensure fresh results.
        """
        self._mentionCheckResult = None

    def checkHasMention(self, username: Optional[str], customMentions: Sequence[str]) -> MentionCheckResult:
        """
        Check if the message contains bot mentions by username or custom nicknames, dood!

        This method searches for bot mentions in the message text, checking both
        the bot's username and custom mention strings. Results are cached for
        efficiency. The method handles mention stripping and returns the remaining
        text after mention removal, dood.

        Args:
            username: The bot's username to check for (without @), can be None
            customMentions: Sequence of custom mention strings to check for

        Returns:
            MentionCheckResult containing mention positions and remaining text, dood.
        """
        if self._mentionCheckResult is not None:
            # We suppose, that we'll check for mentions for the same
            # username and customMentions. If not - call clearMentionCheckResult() before (and after)
            return self._mentionCheckResult
        ret = MentionCheckResult()

        customMentions = [v.strip().lower() for v in customMentions if v]
        if not customMentions:
            logger.error("No custom mentions found")

        messageText = self._rawMessageText
        messageTextLower = messageText.lower()
        offset = 0

        # Check if bot has been mentioned in the message by username
        if username is not None:
            username = username.strip().lower()

            # In theory we can use built-it entities parser, but:
            #  1. messageText can be either text or caption
            #  2. Because of UTF-8 variable chars length, it is possible,
            #       that etity position differs from it's position in utf-8 string.
            # # If there is base message, use built-in mention parser:
            # if self._message is not None:
            #     message = self._message
            #     for entity in message.entities:
            #         if entity.type == telegram.constants.MessageEntityType.MENTION:
            #             mentionText = message.parse_entity(entity)
            #             if mentionText.lower() == username:
            #                 ret.byName = (entity.offset, entity.offset + entity.length)
            #                 break
            # else:
            if username in messageTextLower:
                try:
                    startPos = messageTextLower.index(username)
                    ret.byName = (startPos, startPos + len(username))
                except ValueError as e:
                    logger.error(f"Username {username} found in message {messageText}, but exception was raised: {e}")
                ret.byName = (messageTextLower.index(username), len(username))

            # If username is on begin of message, strip it before checking for custom mentions
            if messageTextLower.lstrip().startswith(username):
                origLen = len(messageText)
                messageText = messageText[len(username) :].lstrip()
                messageTextLower = messageText.lower()
                # We need to save offset to set proper offset for custom mentions
                offset += origLen - len(messageText)

        for mention in customMentions:
            if not mention:
                logger.error(f"Empty custom mention: {mention}")
                continue
            mentionLen = len(mention)
            if messageTextLower.startswith(mention) and (
                len(messageTextLower) <= mentionLen or messageTextLower[mentionLen] in [" ", ",", "." ":", "\n"]
            ):
                ret.byNick = (offset, offset + mentionLen)
                # origLen = len(messageText)
                messageText = messageText[len(mention) :].lstrip()
                # messageTextLower = messageText.lower()
                # # We need to save offset to set proper offset for ...
                # offset += origLen - len(messageText)
                break

        if ret.byName or ret.byNick:
            ret.restText = messageText.lstrip(".,:").strip()
            logger.debug(f"Mention found: {ret}")

        self._mentionCheckResult = ret
        return ret
