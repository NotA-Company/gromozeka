"""
EnsuredMessage: wrapper around telegram.Message
"""
import asyncio
import json
import logging

import time
from typing import Any, Dict, Optional

from telegram import Message

from .models import LLMMessageFormat, MediaProcessingInfo, MessageType
from internal.database.models import MediaStatus
from internal.database.wrapper import DatabaseWrapper


logger = logging.getLogger(__name__)

MAX_MEDIA_AWAIT_SECS = 300 # 5 minutes
MEDIA_AWAIT_DELAY = 10

"""
A class to encapsulate and ensure the presence of essential message attributes from a Telegram message.

This class processes a `Message` object, extracting and validating key information such as user, chat, message text,
reply information, and topic-related data. It raises exceptions for missing critical fields and logs warnings for
unexpected or missing data. It also provides methods to retrieve the original message and a JSON string representation
of selected attributes.

Attributes:
    user (User): The user who sent the message.
    chat (Chat): The chat the message belongs to.
    messageId (int): The unique identifier of the message.
    date (datetime): The date and time when the message was sent.
    messageText (str): The text of the message, or an empty string if not present.
    messageType (str): The type of the message, defaults to "text" or "unknown" if text is missing.
    replyId (Optional[int]): The ID of the message being replied to, if applicable.
    replyText (Optional[str]): The text of the message being replied to, if applicable.
    isReply (bool): Indicates if the message is a reply.
    threadId (Optional[int]): The thread ID if the message is in a topic.
    isTopicMessage (bool): Indicates if the message is part of a forum topic.

Methods:
    getBaseMessage: Returns the original `Message` object.
    __str__: Returns a JSON string representation of the message's key attributes.

Raises:
    ValueError: If the message's user or chat information is missing.
"""
class EnsuredMessage:

    def __init__(self, message: Message):
        self._message = message

        if not message.from_user:
            raise ValueError("Message User undefined")

        self.user = message.from_user

        if not message.chat:
            raise ValueError("Message Chat undefined")
        self.chat = message.chat

        self.messageId = message.message_id
        self.date = message.date
        self.messageText: str = ""
        self.messageType: MessageType = MessageType.TEXT

        # If there are photo in message, set proper type + handle caption (if any) as messageText
        if message.photo:
            self.messageType = MessageType.IMAGE
            if message.caption:
                self.messageText = message.caption


        if self.messageType == MessageType.TEXT:
            if not message.text:
                # Probably not a text message, just log it for now
                logger.error(f"Message text undefined: {message}")
                self.messageType = MessageType.UNKNOWN
            else:
                self.messageText = message.text

        # If this is reply, then set replyId and replyText
        self.replyId: Optional[int] = None
        self.replyText: Optional[str] = None
        self.isReply = False
        self.isQuote = False
        self.quoteText: Optional[str] = None
        if message.reply_to_message:
            # If reply_to_message is message about creating topic, then it isn't reply
            if message.reply_to_message.forum_topic_created is None:
                self.replyId = message.reply_to_message.message_id
                self.isReply = True
                if message.reply_to_message.text:
                    self.replyText = message.reply_to_message.text
                if message.quote and message.quote.text:
                    self.isQuote = True
                    self.quoteText = message.quote.text

        # If this is topic message, then set threadId
        self.threadId: Optional[int] = None
        self.isTopicMessage = message.is_topic_message == True if message.is_topic_message is not None else False
        if self.isTopicMessage:
            self.threadId = message.message_thread_id

        self.mediaContent: Optional[str] = None
        self.mediaId: Optional[str] = None
        self.mediaProcessingInfo: Optional[MediaProcessingInfo] = None

        logger.debug(f"Ensured Message: {self}")

    def getBaseMessage(self) -> Message:
        return self._message

    def setMediaId(self, mediaId: str):
        self.mediaId = mediaId

    def setMediaProcessingInfo(self, mediaProcessingInfo: MediaProcessingInfo):
        self.mediaProcessingInfo = mediaProcessingInfo
        self.mediaId = mediaProcessingInfo.id
    
    async def updateMediaContent(self, db: DatabaseWrapper) -> None:
        """
        Set the media content of the message from DB.
        """
        if self.mediaProcessingInfo:
            await self.mediaProcessingInfo.awaitResult()

        if self.mediaId is None:
            return
        
        startTime = time.time()
        while time.time() - startTime < MAX_MEDIA_AWAIT_SECS:
            mediaAttachment = db.getMediaAttachment(self.mediaId)
            if mediaAttachment is None:
                raise ValueError(f"Media attachment {self.mediaId} not found")
            
            match MediaStatus(str(mediaAttachment["status"])):
                case MediaStatus.PENDING:
                    await asyncio.sleep(MEDIA_AWAIT_DELAY)
                case MediaStatus.DONE:
                    self.mediaContent = mediaAttachment["description"]
                    return
                case _:
                    raise ValueError("Invalid media status")
        
        raise TimeoutError("Media processing timed out")

    async def formatForLLM(self, db: DatabaseWrapper, format: LLMMessageFormat = LLMMessageFormat.JSON, replaceMessageText: Optional[str] = None) -> str:
        await self.updateMediaContent(db)
        messageText = self.messageText if replaceMessageText is None else replaceMessageText
        match format:
            case LLMMessageFormat.JSON:
                ret = {
                    "login": self.user.name,
                    "name": self.user.full_name,
                    "date": self.date.isoformat(),
                    "type": str(self.messageType),
                    "text": messageText,
                }
                if self.isQuote and self.quoteText:
                    ret["quote"] = self.quoteText

                if self.mediaContent:
                    ret["media_description"] = self.mediaContent

                #logger.debug(f"EM.formatForLLM():{self} -> {ret}")
                return json.dumps(ret, ensure_ascii=False)

            case LLMMessageFormat.TEXT:
                ret = messageText
                if self.isQuote and self.quoteText:
                    ret = f"<quote>{self.quoteText}</quote>\n\n{ret}"
                return ret

        raise ValueError(f"Invalid format: {format}")

    @classmethod
    def formatDBChatMessageToLLM(cls, data: Dict[str, Any], format: LLMMessageFormat = LLMMessageFormat.JSON, replaceMessageText: Optional[str] = None) -> str:
        # TODO: Somehow merge with prevoius method
        messageText = data["message_text"] if replaceMessageText is None else replaceMessageText
        match format:
            case LLMMessageFormat.JSON:
                ret = {
                    "login": data["username"],
                    "name": data["full_name"],
                    "date": data["date"],
                    "type": data["message_type"],
                    "text": messageText,
                }
                if data.get("quote_text", None):
                    ret["quote"] = data["quote_text"]

                if data.get("media_description", None):
                        ret["media_description"] = data["media_description"]

                #logger.debug(f"EM.formatDBChatMessageToLLM():{data} -> {ret}")
                return json.dumps(ret, ensure_ascii=False, default=str)
            case LLMMessageFormat.TEXT:
                ret = messageText
                if data.get("quote_text", None):
                    ret = f"<quote>{data["quote_text"]}</quote>\n\n{ret}"
                return ret

        raise ValueError(f"Invalid format: {format}")

    def __str__(self) -> str:
        return json.dumps(
            {
                "user.id": self.user.id,
                "chat.id": self.chat.id,
                "messageId": self.messageId,
                "date": self.date.isoformat(),
                "messageType": self.messageType,
                "messageText": self.messageText,
                "replyId": self.replyId,
                "isReply": self.isReply,
                "replyText": self.replyText,
                "isQuote": self.isQuote,
                "quoteText": self.quoteText,
                "threadId": self.threadId,
                "isTopicMessage": self.isTopicMessage,
            },
            ensure_ascii=False,
        )
