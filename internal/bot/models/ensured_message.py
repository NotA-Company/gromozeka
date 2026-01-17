"""
Telegram Message Processing and Validation Module, dood!

Provides wrappers and utilities for processing Telegram messages, ensuring essential
attributes are present and properly formatted for downstream processing, especially
for LLM interactions and database storage.

Key Components:
    - MessageSender: Encapsulates sender information (user or chat)
    - MentionCheckResult: Stores results of bot mention detection
    - EnsuredMessage: Main wrapper class for Telegram messages with validation

Constants:
    MAX_MEDIA_AWAIT_SECS: Maximum time to wait for media processing (300 seconds)
    MEDIA_AWAIT_DELAY: Delay between media status checks (2.5 seconds)
"""

import asyncio
import datetime
import json
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, List, Optional, Sequence, Tuple, TypedDict

import telegram
import telegram.constants

import lib.max_bot as libMax
import lib.max_bot.models as maxModels
import lib.utils as utils
from internal.database.models import ChatMessageDict, MediaAttachmentDict, MediaStatus
from internal.database.wrapper import DatabaseWrapper
from internal.models import MessageIdType, MessageType
from lib.ai.models import ModelMessage

from .enums import LLMMessageFormat
from .media import MediaProcessingInfo
from .text_formatter import FormatEntity, OutputFormat

logger = logging.getLogger(__name__)

MAX_MEDIA_AWAIT_SECS = 300  # 5 minutes
MEDIA_AWAIT_DELAY = 2.5
WORD_BREAKERS = ' \t\n\r\f\v.,;:?!…()[]{}<>«»„“”‘’"-–—+=×*÷=<>=≠≤≥%&|\\/@#$№©™®_.'  # Provided By Alice


class CondensingDict(TypedDict):
    text: str
    tillMessageId: MessageIdType
    tillTS: float


class MetadataDict(TypedDict, total=False):
    condensedThread: List[CondensingDict]
    forwardedFrom: Dict[str, Any]
    messagePrefix: str
    usedTools: List[Dict[str, Any]]


class ChatType(StrEnum):

    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"


class MessageRecipient:
    """
    Represents the recipient of a message, dood!

    Encapsulates information about where a message was sent, including the chat ID
    and type (private, group, or channel). Uses __slots__ for memory efficiency.

    Attributes:
        id (int): Unique identifier of the chat
        chatType (ChatType): Type of chat (PRIVATE, GROUP, or CHANNEL)
    """

    __slots__ = ("id", "chatType")

    def __init__(self, id: int, chatType: ChatType) -> None:
        """
        Initialize a MessageRecipient instance, dood!

        Args:
            id: Unique identifier of the chat
            chatType: Type of chat (PRIVATE, GROUP, or CHANNEL)
        """
        self.id = id
        self.chatType = chatType

    def __str__(self) -> str:
        """
        Return a string representation of the recipient, dood!

        Returns:
            Formatted string: "chatType#id"
        """
        return f"{self.chatType.value}#{self.id}"

    @classmethod
    def fromTelegramChat(cls, chat: telegram.Chat) -> "MessageRecipient":
        """
        Create a MessageRecipient from a Telegram Chat object, dood!

        Args:
            chat: Telegram Chat object containing chat information

        Returns:
            MessageRecipient instance populated with chat data
        """
        chatType: ChatType = ChatType.GROUP
        match chat.type:
            case telegram.constants.ChatType.SENDER | telegram.constants.ChatType.PRIVATE:
                chatType = ChatType.PRIVATE
            case telegram.constants.ChatType.GROUP | telegram.constants.ChatType.SUPERGROUP:
                chatType = ChatType.GROUP
            case telegram.constants.ChatType.CHANNEL:
                chatType = ChatType.CHANNEL
            case _:
                logger.warning(f"Unsupported chat type: {chat.type}")

        return cls(chat.id, chatType)

    @classmethod
    def fromMaxRecipient(cls, recipient: maxModels.Recipient) -> "MessageRecipient":
        """
        Create a MessageRecipient from a Max Messenger Recipient object, dood!

        Args:
            recipient: Max Messenger Recipient object containing recipient information

        Returns:
            MessageRecipient instance populated with recipient data
        """
        chatType: ChatType = ChatType.GROUP
        match recipient.chat_type:
            case maxModels.ChatType.DIALOG:
                chatType = ChatType.PRIVATE
            case maxModels.ChatType.CHAT:
                chatType = ChatType.GROUP
            case maxModels.ChatType.CHANNEL:
                chatType = ChatType.CHANNEL
            case _:
                logger.warning(f"Unsupported chat type: {recipient.chat_type}")

        recipientId = recipient.chat_id
        if recipientId is None:
            logger.error(f"Recipient ID is None: {recipient}")
            recipientId = 0

        return cls(recipientId, chatType)


class MessageSender:
    """
    Encapsulates sender information for a message, dood!

    Stores essential sender details (ID, name, username) and provides factory methods
    to create instances from Telegram User or Chat objects. Uses __slots__ for memory efficiency.

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
    def fromTelegramUser(cls, user: telegram.User) -> "MessageSender":
        """
        Create a MessageSender from a Telegram User object, dood!

        Args:
            user: Telegram User object containing user information

        Returns:
            MessageSender instance populated with user data
        """
        return cls(user.id, user.full_name, user.name)

    @classmethod
    def fromTelegramChat(cls, chat: telegram.Chat) -> "MessageSender":
        """
        Create a MessageSender from a Telegram Chat object, dood!

        Args:
            chat: Telegram Chat object containing chat information

        Returns:
            MessageSender instance populated with chat data.
            Username is prefixed with @ if available, dood.
        """
        return cls(chat.id, chat.effective_name or "", f"@{chat.username}" if chat.username else "")

    @classmethod
    def fromMaxUser(cls, sender: maxModels.User) -> "MessageSender":
        """
        Create a MessageSender from a Max Messenger User object, dood!

        Args:
            sender: Max Messenger User object containing user information

        Returns:
            MessageSender instance populated with user data.
            Username is prefixed with @ if available, dood.
        """
        full_name = sender.first_name
        if sender.last_name:
            full_name += " " + sender.last_name
        return cls(sender.user_id, full_name.strip(), f"@{sender.username}" if sender.username else "")


@dataclass
class MentionCheckResult:
    """
    Stores the results of bot mention detection in a message, dood!

    Holds information about where and how a bot was mentioned in a message,
    including positions of mentions by nickname or username, and the remaining
    text after mention removal.

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


class MediaContent:
    """
    Represents media content associated with a message, dood!

    Encapsulates media information including its unique identifier, LLM-parsed content
    description, and processing status information. Uses __slots__ for memory efficiency.

    Attributes:
        id (str): Unique identifier for the media attachment
        content (Optional[str]): LLM-parsed description of the media content, if available
        processingInfo (Optional[MediaProcessingInfo]): Media processing status and details, if available
    """

    __slots__ = ("id", "content", "processingInfo")

    def __init__(self, id: str, content: Optional[str], processingInfo: Optional[MediaProcessingInfo]):
        """
        Initialize a MediaContent instance, dood!

        Args:
            id: Unique identifier for the media attachment
            content: LLM-parsed description of the media content, or None if not yet processed
            processingInfo: Media processing status and details, or None if not available
        """
        self.id = id
        """Media Id"""
        self.content = content
        """Media LLM-parsed content if any"""
        self.processingInfo = processingInfo
        """Processing info if any"""

    def __str__(self) -> str:
        """
        Return a concise string representation of the media content, dood!

        Returns:
            Formatted string: "MediaContent(id={id}, content={content})"
        """
        return f"MediaContent(id={self.id}, content={self.content})"

    def __repr__(self) -> str:
        """
        Return a detailed string representation of the media content, dood!

        Returns:
            Formatted string including id, content, and processingInfo
        """
        return f"MediaContent(id={self.id}, content={self.content}, processingInfo={self.processingInfo})"


class EnsuredMessage:
    """
    Wrapper class that ensures presence of essential Telegram message attributes, dood!

    Processes Telegram Message objects or database chat messages, extracting and validating
    key information such as sender, recipient, message text, reply information, quote
    information, topic-related data, and media content. Provides methods for LLM formatting,
    media processing, and conversion to model messages for AI interactions.

    Handles various message types (text, images, videos, audio, documents, etc.) and provides
    robust mention detection and media content processing capabilities.

    Attributes:
        sender (MessageSender): The sender information (user or chat)
        recipient (MessageRecipient): The recipient information (chat)
        messageId (MessageIdType): The unique identifier of the message
        date (datetime.datetime): The date and time when the message was sent
        messageText (str): The text of the message, or empty string if not present
        messageType (MessageType): The type of the message (TEXT, IMAGE, VIDEO, AUDIO, etc.)
        isReply (bool): Indicates if the message is a reply
        replyId (Optional[MessageIdType]): The ID of the message being replied to, if applicable
        replyText (Optional[str]): The text of the message being replied to, if applicable
        isQuote (bool): Indicates if the message contains a quote
        quoteText (Optional[str]): The quoted text content, if applicable
        isTopicMessage (bool): Indicates if the message is part of a forum topic
        threadId (Optional[int]): The thread ID if the message is in a topic
        mediaId (Optional[str]): Unique identifier for media attachments (deprecated, use mediaList)
        mediaContent (Optional[str]): Description of media content (deprecated, use mediaList)
        mediaGroupId (Optional[str]): Identifier for media group if message contains grouped media
        mediaList (List[MediaContent]): List of media content objects associated with the message
        userData (Optional[Dict[str, Any]]): Additional user data associated with the message
        formatEntities (Sequence[FormatEntity]): Text formatting entities for the message
        metadata (MetadataDict): Additional metadata including condensed thread information
    """

    __slots__ = (
        "_message",
        "sender",
        "recipient",
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
        "mediaPrompt",
        "mediaId",
        "userData",
        "_mentionCheckResult",
        "formatEntities",
        "metadata",
        "mediaGroupId",
        "mediaList",
        "messagePrefix",
    )

    def __init__(
        self,
        *,
        sender: MessageSender,
        recipient: MessageRecipient,
        messageId: MessageIdType,
        date: datetime.datetime,
        messageText: str = "",
        messageType: MessageType = MessageType.UNKNOWN,
        formatEntities: Optional[Sequence[FormatEntity]] = None,
        metadata: Optional[MetadataDict] = None,
        mediaGroupId: Optional[str] = None,
    ):
        """
        Initialize an EnsuredMessage instance, dood!

        Args:
            sender: The MessageSender who sent the message
            recipient: The MessageRecipient where the message was sent
            messageId: Unique identifier for the message
            date: Timestamp when the message was sent
            messageText: The text content of the message (default: empty string)
            messageType: The type of message (default: MessageType.UNKNOWN)
            formatEntities: Sequence of text formatting entities (default: None)
            metadata: Additional metadata dictionary (default: None)
            mediaGroupId: Identifier for media group if applicable (default: None)
        """
        self._message: Optional[telegram.Message | maxModels.Message] = None
        """Base message"""

        self.sender: MessageSender = sender
        """Message sender"""
        self.recipient: MessageRecipient = recipient
        """Message recipient"""

        self.messageId: MessageIdType = messageId
        """Message Id (int for Telegram, str for Max)"""
        self.date: datetime.datetime = date
        """Message date"""
        self.messageText: str = messageText
        """Message text if any"""
        self.messageType: MessageType = messageType
        """Message Type"""
        self.messagePrefix: str = ""
        """Prefix for message (usually in bot's answers)"""

        # If this is reply, then set replyId and replyText
        self.replyId: Optional[MessageIdType] = None
        """Id of message this message is reply to (If Any)"""
        self.replyText: Optional[str] = None
        """Text of message this message is reply to (If Any)"""
        self.isReply: bool = False
        """If this message is reply to another message"""
        self.isQuote: bool = False
        """If this message is quote of another message"""
        self.quoteText: Optional[str] = None
        """Quoted text if any"""

        # If this is topic message, then set threadId
        self.threadId: Optional[int] = None
        """Thread Id if any (only for Telegram threaded supergroups)"""
        self.isTopicMessage: bool = False
        """If this message is topic message"""

        # TODO: should we deprecate it in favor of mediaList?
        self.mediaContent: Optional[str] = None
        self.mediaPrompt: Optional[str] = None
        self.mediaId: Optional[str] = None

        self.mediaGroupId: Optional[str] = mediaGroupId
        """Id of Media group if any"""
        self.mediaList: List[MediaContent] = []
        """List of Media content if any"""

        self.userData: Optional[Dict[str, Any]] = None
        """User data if any"""
        self._mentionCheckResult: Optional[MentionCheckResult] = None

        self.formatEntities: Sequence[FormatEntity] = formatEntities if formatEntities is not None else []
        """Format entities if any"""
        self.metadata: MetadataDict = metadata if metadata is not None else {}
        """Metadata if any"""

    @classmethod
    def fromMaxMessage(cls, message: maxModels.Message) -> "EnsuredMessage":
        """
        Create an EnsuredMessage from a Max Messenger Message object, dood!

        Factory method that extracts all relevant information from a Max Messenger Message,
        including text, media type, and reply information. Handles various message types
        (text, images, videos, audio, documents, etc.) and properly sets up all attributes.

        Args:
            message: The Max Messenger Message object to process

        Returns:
            A fully initialized EnsuredMessage instance with all extracted data
        """

        messageText: str = ""
        messageType: MessageType = MessageType.TEXT
        markupList: List[FormatEntity] = []
        mediaGroupId: Optional[str] = None
        if message.body.text:
            # TODO: think about parsing Entities to Markdown, but without escaping
            # messageText = message.text_markdown_v2
            messageText = message.body.text
            if message.body.markup:
                markupList = FormatEntity.fromList(message.body.markup)
        elif message.link and message.link.type == maxModels.MessageLinkType.FORWARD and message.link.message.text:
            # TODO: Add originalAuthor info
            messageText = message.link.message.text
            # It's forward, get text from forward
            if message.link.message.markup:
                markupList = FormatEntity.fromList(message.link.message.markup)

        if message.body.attachments:
            # Max Is able to store miltiple attachments, so we use message id as mediaGroupId
            mediaGroupId = message.body.mid
            match message.body.attachments[0].type:
                case maxModels.AttachmentType.IMAGE:
                    messageType = MessageType.IMAGE
                case maxModels.AttachmentType.VIDEO:
                    messageType = MessageType.VIDEO
                case maxModels.AttachmentType.AUDIO:
                    messageType = MessageType.AUDIO
                case maxModels.AttachmentType.FILE:
                    messageType = MessageType.DOCUMENT
                case maxModels.AttachmentType.STICKER:
                    messageType = MessageType.STICKER
                # case maxModels.AttachmentType.CONTACT:
                #     messageType = MessageType.UNKNOWN
                # case maxModels.AttachmentType.INLINE_KEYBOARD:
                #     messageType = MessageType.UNKNOWN
                # case maxModels.AttachmentType.SHARE:
                #     messageType = MessageType.UNKNOWN
                # case maxModels.AttachmentType.LOCATION:
                #     messageType = MessageType.UNKNOWN
                # case maxModels.AttachmentType.REPLY_KEYBOARD:
                #     messageType = MessageType.UNKNOWN
                case maxModels.AttachmentType.DATA:
                    messageType = MessageType.DOCUMENT
                # case _:
                #     messageType = MessageType.UNKNOWN

        if messageType == MessageType.TEXT:
            if not messageText:
                # Probably not a text message, just log it for now
                logger.error(f"Message text undefined: {message}")
                messageType = MessageType.UNKNOWN

        ensuredMessage = EnsuredMessage(
            sender=MessageSender.fromMaxUser(message.sender),
            recipient=MessageRecipient.fromMaxRecipient(message.recipient),
            messageId=message.body.mid,
            date=datetime.datetime.fromtimestamp(message.timestamp / 1000, datetime.timezone.utc),
            messageText=messageText,
            messageType=messageType,
            formatEntities=markupList,
            mediaGroupId=mediaGroupId,
        )
        ensuredMessage.setBaseMessage(message)

        # If this is reply, then set replyId and replyText
        if message.link and message.link.type == maxModels.MessageLinkType.REPLY:
            # If reply_to_message is message about creating topic, then it isn't reply
            repliedMessage = message.link.message
            ensuredMessage.replyId = repliedMessage.mid
            ensuredMessage.isReply = True
            if repliedMessage.text:
                ensuredMessage.replyText = repliedMessage.text  # TODO: Parse markup

        # NOTE: No Quote support in Max

        # NOTE: No Topics support in Max

        logger.debug(f"Ensured Message from Max: {ensuredMessage}")
        return ensuredMessage

    @classmethod
    def fromTelegramMessage(cls, message: telegram.Message) -> "EnsuredMessage":
        """
        Create an EnsuredMessage from a Telegram Message object, dood!

        Factory method that extracts all relevant information from a Telegram Message,
        including text, media type, reply information, quotes, and topic data.
        Handles various message types (text, photo, video, audio, documents, etc.)
        and properly sets up all attributes.

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

        messageMetadata: MetadataDict = {}
        messageText: str = ""
        messageType: MessageType = MessageType.TEXT
        markupList: List[FormatEntity] = []
        mediaGroupId: Optional[str] = message.media_group_id
        if message.text:
            # TODO: think about parsing Entities to Markdown, but without escaping
            # messageText = message.text_markdown_v2
            messageText = message.text
            if message.entities:
                markupList = FormatEntity.fromList(message.entities)
        elif message.caption:
            # messageText = message.caption_markdown_v2
            messageText = message.caption
            if message.caption_entities:
                markupList = FormatEntity.fromList(message.caption_entities)

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
        elif mediaGroupId is None:
            # We have media but have no media goup id, so use message chat id + message_id as mediaGroupId
            mediaGroupId = f"{message.chat.id}:{message.message_id}"

        sender: Optional[MessageSender] = None
        if message.sender_chat:
            sender = MessageSender.fromTelegramChat(message.sender_chat)
        else:
            sender = MessageSender.fromTelegramUser(message.from_user)

        if message.forward_origin:
            # forward_origin=MessageOriginChannel(
            #   chat=Chat(
            #       id=-1,
            #       title='TITLE',
            #       type=<ChatType.CHANNEL>,
            #       username='USERNAME'),
            #   date=datetime.datetime(...),
            #   message_id=1,
            #   type=<MessageOriginType.CHANNEL>)
            forwardedFrom = message.forward_origin
            forwardedFromDict: Dict[str, Any] = {
                "date": forwardedFrom.date.isoformat(),
                "type": forwardedFrom.type,
                "message_id": None,
                "from_id": None,
                "from_name": None,
                "from_username": None,
                "author_signature": None,
                "from_title": None,
            }
            if isinstance(forwardedFrom, telegram.MessageOriginChannel):
                forwardedFromDict.update(
                    {
                        "message_id": forwardedFrom.message_id,
                        "from_id": forwardedFrom.chat.id,
                        "from_name": forwardedFrom.chat.title,
                        "from_username": forwardedFrom.chat.username,
                        "from_title": forwardedFrom.chat.title,
                    }
                )
            elif isinstance(forwardedFrom, telegram.MessageOriginChat):
                forwardedFromDict.update(
                    {
                        "author_signature": forwardedFrom.author_signature,
                        "from_id": forwardedFrom.sender_chat.id,
                        "from_name": forwardedFrom.sender_chat.title,
                        "from_username": forwardedFrom.sender_chat.username,
                        "from_title": forwardedFrom.sender_chat.title,
                    }
                )
            elif isinstance(forwardedFrom, telegram.MessageOriginUser):
                forwardedFromDict.update(
                    {
                        "from_id": forwardedFrom.sender_user.id,
                        "from_name": forwardedFrom.sender_user.name,
                        "from_username": forwardedFrom.sender_user.username,
                        "from_title": forwardedFrom.sender_user.name,
                    }
                )
            elif isinstance(forwardedFrom, telegram.MessageOriginHiddenUser):
                forwardedFromDict.update(
                    {
                        "from_name": forwardedFrom.sender_user_name,
                        "from_title": forwardedFrom.sender_user_name,
                    }
                )
            else:
                logger.error(f"Unknown forwardedFrom type: {type(forwardedFrom)}")

            messageMetadata["forwardedFrom"] = forwardedFromDict

        ensuredMessage = EnsuredMessage(
            sender=sender,
            recipient=MessageRecipient.fromTelegramChat(message.chat),
            messageId=message.message_id,
            date=message.date,
            messageText=messageText,
            messageType=messageType,
            formatEntities=markupList,
            mediaGroupId=mediaGroupId,
            metadata=messageMetadata,
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

        logger.debug(f"Ensured Message from Telegram: {ensuredMessage}")
        return ensuredMessage

    @classmethod
    def fromDBChatMessage(
        cls, data: ChatMessageDict, db: DatabaseWrapper, forceGetAllMedia: bool = False
    ) -> "EnsuredMessage":
        """
        Create an EnsuredMessage from a database ChatMessageDict, dood!

        Factory method that reconstructs an EnsuredMessage from database-stored
        message data, including all metadata like replies, quotes, topics, and
        media information.

        Args:
            data: Dictionary containing chat message data from the database

        Returns:
            A fully initialized EnsuredMessage instance populated with database data
        """
        markupList: List[FormatEntity] = []
        if data["markup"]:
            dataList = json.loads(data["markup"])
            if not isinstance(dataList, list):
                logger.error(f"data[markup] is not JSON-serialized list: {data['markup']}")
            else:
                markupList = FormatEntity.fromDictList(dataList)

        metadata: MetadataDict = {}
        if data["metadata"]:
            metadata = json.loads(data["metadata"])

        ensuredMessage = EnsuredMessage(
            sender=MessageSender(id=data["user_id"], name=data["full_name"], username=data["username"]),
            recipient=MessageRecipient(
                data["chat_id"],
                chatType=(
                    # TODO: Think about fetching real chat type from DB
                    ChatType.PRIVATE
                    if data["chat_id"] > 0
                    else ChatType.GROUP
                ),
            ),
            messageId=data["message_id"],
            date=data["date"],
            messageText=data["message_text"],
            messageType=MessageType(data["message_type"]),
            formatEntities=markupList,
            metadata=metadata,
            mediaGroupId=data["media_group_id"],
        )

        ensuredMessage.replyId = data["reply_id"]
        # ensuredMessage.replyText: Optional[str] = None
        ensuredMessage.isReply = data["reply_id"] is not None

        ensuredMessage.quoteText = data["quote_text"]
        ensuredMessage.isQuote = data["quote_text"] is not None

        # If this is topic message, then set threadId
        ensuredMessage.threadId = data["thread_id"]
        ensuredMessage.isTopicMessage = data["thread_id"] != 0

        ensuredMessage.mediaId = data["media_id"]

        if data["media_group_id"] is not None and (not data["media_id"] or forceGetAllMedia):
            for media in db.getMediaAttachmentsByGroupId(data["media_group_id"]):
                ensuredMessage.addMedia(
                    mediaId=media["file_unique_id"],
                    mediaContent=media["description"],
                    setMediaId=False,
                )
                if ensuredMessage.mediaId == media["file_unique_id"]:
                    ensuredMessage.mediaContent = media["description"]
        elif data["media_id"] is not None:
            # If we aren't getting list of attachments, add media_it to list
            ensuredMessage.addMedia(mediaId=data["media_id"], setMediaId=True)

        ensuredMessage.messagePrefix = metadata.get("messagePrefix", "")

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

    def getBaseMessage(self) -> telegram.Message | maxModels.Message:
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

    def setBaseMessage(self, message: telegram.Message | maxModels.Message):
        """
        Set the original Telegram Message object, dood!

        Args:
            message: The Telegram Message object to store
        """
        self._message = message

    def formatMessageText(self, outputFormat: OutputFormat = OutputFormat.MARKDOWN) -> str:
        """
        Parse the message to the specified output format, dood.

        Args:
            outputFormat: Output format to parse the message to

        Returns:
            The parsed message text in the specified format
        """
        if not self.formatEntities:
            return self.messageText

        ret = FormatEntity.parseText(self.messagePrefix + self.messageText, self.formatEntities, outputFormat)
        if self.messagePrefix:
            return ret[len(self.messagePrefix) :]
        return ret

    def addMedia(self, mediaId: str, mediaContent: Optional[str] = None, setMediaId: bool = True):
        """
        Set the media identifier for this message, dood!

        Args:
            mediaId: Unique identifier for the media attachment
        """
        self.mediaList.append(MediaContent(id=mediaId, content=mediaContent, processingInfo=None))

        if setMediaId:
            self.mediaId = mediaId
            self.mediaContent = mediaContent

    def addMediaProcessingInfo(self, mediaProcessingInfo: MediaProcessingInfo, setMediaId: bool = True):
        """
        Set media processing information and extract media ID, dood!

        Args:
            mediaProcessingInfo: Object containing media processing details and ID
        """
        self.mediaList.append(
            MediaContent(
                id=mediaProcessingInfo.id,
                content=None,
                processingInfo=mediaProcessingInfo,
            )
        )

        if setMediaId:
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
        for media in self.mediaList:
            if media.processingInfo:
                await media.processingInfo.awaitResult()

            mediaAttachment = await self.__class__._awaitMedia(db, media.id)
            if mediaAttachment and mediaAttachment.get("description", None) is not None:
                media.content = mediaAttachment["description"]

        if self.mediaId is None:
            return

        mediaAttachment = await self.__class__._awaitMedia(db, self.mediaId)
        if mediaAttachment and mediaAttachment.get("description", None) is not None:
            self.mediaContent = mediaAttachment["description"]
            self.mediaPrompt = mediaAttachment["prompt"]

    def setMessagePrefix(self, messagePrefix: str) -> None:
        """
        Add message prefix
        """

        self.messagePrefix = messagePrefix
        self.metadata["messagePrefix"] = messagePrefix

    @classmethod
    async def _awaitMedia(cls, db: DatabaseWrapper, mediaId: str) -> Optional[MediaAttachmentDict]:
        """
        Wait for media processing to complete and retrieve media attachment, dood!

        Polls the database for media attachment status, waiting up to MAX_MEDIA_AWAIT_SECS
        for processing to complete. Handles PENDING and DONE statuses appropriately.

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
        outputFormat: OutputFormat = OutputFormat.MARKDOWN,
        useSingleMedia: bool = True,
    ) -> str:
        """
        Format the message for LLM consumption, dood!

        Converts the message into a format suitable for AI model processing,
        supporting both JSON and TEXT formats. Includes media descriptions, quotes,
        and user data when available.

        Args:
            db: Database wrapper for accessing media content
            format: Output format (JSON or TEXT), default is JSON
            replaceMessageText: Optional replacement text instead of original message text
            stripAtsign: Whether to strip @ from usernames, default is False
            outputFormat: Output format for message text parsing (default: MARKDOWN)
            useSingleMedia: Whether to use single media content or media list (default: True)

        Returns:
            Formatted string representation of the message for LLM processing

        Raises:
            ValueError: If an invalid format is specified, dood.
        """
        await self.updateMediaContent(db)
        mediaContent = self.mediaContent
        if not useSingleMedia or self.mediaContent is None:
            mediaContent = [v.content for v in self.mediaList if v.content]

        messageText = self.formatMessageText(outputFormat) if replaceMessageText is None else replaceMessageText
        userName = self.sender.username
        if stripAtsign:
            userName = userName.lstrip("@")
        match format:
            case LLMMessageFormat.JSON:
                # Drop empty-values to save context
                ret = {
                    k: v
                    for k, v in {
                        "login": userName,
                        "name": self.sender.name,
                        "date": self.date.isoformat(),
                        "messageId": self.messageId,
                        "type": str(self.messageType),
                        "text": messageText,
                        "replyId": self.replyId,
                        "quote": self.quoteText if self.isQuote else None,
                        "mediaDescription": mediaContent,
                        "userData": self.userData,
                    }.items()
                    if v
                }

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

    async def toModelMessageList(
        self,
        db: DatabaseWrapper,
        format: LLMMessageFormat = LLMMessageFormat.JSON,
        replaceMessageText: Optional[str] = None,
        stripAtsign: bool = False,
        role: str = "user",
        outputFormat: OutputFormat = OutputFormat.MARKDOWN,
        useSingleMedia: bool = True,
    ) -> List[ModelMessage]:
        """Convert to ModelMessage + tools history (if any)"""

        ret: List[ModelMessage] = []
        toolsHistory = self.metadata.get("usedTools", None)
        if toolsHistory:
            for toolsMessage in toolsHistory:
                ret.append(ModelMessage.fromDict(toolsMessage))

        ret.append(
            await self.toModelMessage(
                db=db,
                format=format,
                replaceMessageText=replaceMessageText,
                stripAtsign=stripAtsign,
                role=role,
                outputFormat=outputFormat,
                useSingleMedia=useSingleMedia,
            )
        )
        return ret

    async def toModelMessage(
        self,
        db: DatabaseWrapper,
        format: LLMMessageFormat = LLMMessageFormat.JSON,
        replaceMessageText: Optional[str] = None,
        stripAtsign: bool = False,
        role: str = "user",
        outputFormat: OutputFormat = OutputFormat.MARKDOWN,
        useSingleMedia: bool = True,
    ) -> ModelMessage:
        """
        Convert the message to a ModelMessage for AI model interactions, dood!

        Creates a ModelMessage object suitable for passing to AI models,
        with the message content formatted according to the specified format.
        Supports SMART format which automatically chooses JSON for user messages
        and TEXT for other roles.

        Args:
            db: Database wrapper for accessing media content
            format: Output format (JSON, TEXT, or SMART), default is JSON
            replaceMessageText: Optional replacement text instead of original message text
            stripAtsign: Whether to strip @ from usernames, default is False
            role: The role for the model message (e.g., "user", "assistant"), default is "user"
            outputFormat: Output format for message text parsing (default: MARKDOWN)
            useSingleMedia: Whether to use single media content or media list (default: True)

        Returns:
            ModelMessage object ready for AI model consumption, dood.
        """
        if format == LLMMessageFormat.SMART:
            if role == "assistant":
                # It's better to use TEXT format for assistant messages
                # To not show LLM that it should respond in JSON format
                format = LLMMessageFormat.TEXT
            else:
                format = LLMMessageFormat.JSON

        return ModelMessage(
            role=role,
            content=await self.formatForLLM(
                db=db,
                format=format,
                replaceMessageText=replaceMessageText,
                stripAtsign=stripAtsign,
                outputFormat=outputFormat,
                useSingleMedia=useSingleMedia,
            ),
        )

    def __str__(self) -> str:
        """
        Return a JSON string representation of the message, dood!

        Creates a comprehensive JSON representation including all key attributes,
        with truncation of long text fields for readability. Omits None values
        from the output.

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
            "recipient": self.recipient,
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
            "mediaList": self.mediaList,
            "userData": "{...}" if self.userData else None,
        }
        for key in list(ret.keys()):
            if ret[key] is None:
                ret.pop(key, None)
        return utils.jsonDumps(ret, compact=False, sort_keys=False)

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

        Searches for bot mentions in the message text, checking both the bot's username
        and custom mention strings. Results are cached for efficiency. Handles mention
        stripping and returns the remaining text after mention removal.

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

        messageText = self.messageText
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
                len(messageTextLower) <= mentionLen or messageTextLower[mentionLen] in WORD_BREAKERS
            ):
                ret.byNick = (offset, offset + mentionLen)
                # origLen = len(messageText)
                messageText = messageText[len(mention) :].lstrip()
                # messageTextLower = messageText.lower()
                # # We need to save offset to set proper offset for ...
                # offset += origLen - len(messageText)
                break

        if ret.byName or ret.byNick:
            ret.restText = messageText.lstrip(WORD_BREAKERS).strip()
            logger.debug(f"Mention found: {ret}")

        self._mentionCheckResult = ret
        return ret

    def getEnsuredRepliedToMessage(self) -> Optional["EnsuredMessage"]:
        """
        Get the message that this message is replying to, dood.

        Returns:
            EnsuredMessage object if this message is a reply, dood. None otherwise.
        """
        if not self.isReply:
            return None
        if self._message is None:
            logger.error("getEnsuredRepliedToMessage(): message is None")
            return None

        message = self.getBaseMessage()
        if isinstance(message, telegram.Message):
            if not message.reply_to_message:
                logger.error(
                    "getEnsuredRepliedToMessage(): message.reply_to_message is None, but should be telegram Message()"
                )
                return None
            return EnsuredMessage.fromTelegramMessage(message.reply_to_message)
        elif isinstance(message, maxModels.Message):
            linkedMessage = libMax.MessageLinkToMessage(message)
            if linkedMessage is None:
                logger.error("getEnsuredRepliedToMessage(): message.link is None, but should be max Message()")
                return None
            return EnsuredMessage.fromMaxMessage(linkedMessage)

        logger.error(f"getEnsuredRepliedToMessage(): message has unexpected type: {type(message)}")
        return None

    def toTelegramMessage(self) -> telegram.Message:
        """
        Convert this EnsuredMessage to a Telegram Message object, dood!

        Creates a Telegram Message object from the EnsuredMessage data,
        which can be useful for compatibility with Telegram-specific APIs.

        Returns:
            A Telegram Message object with the same data as this EnsuredMessage
        """
        return telegram.Message(
            message_id=int(self.messageId),
            date=self.date,
            chat=telegram.Chat(
                id=self.recipient.id,
                type=telegram.Chat.PRIVATE if self.recipient.chatType == ChatType.PRIVATE else telegram.Chat.SUPERGROUP,
            ),
            from_user=telegram.User(
                id=self.sender.id, first_name=self.sender.name, username=self.sender.username, is_bot=False
            ),
            text=self.messageText,
            message_thread_id=self.threadId,
        )
