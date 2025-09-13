"""
EnsuredMessage: wrapper around telegram.Message
"""
import json
import logging

from typing import Optional

from telegram import Message


logger = logging.getLogger(__name__)


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
        self.messageText = ""
        self.messageType = "text"
        if not message.text:
            # Probably not a text message, ignore but log it for now
            logger.error(f"Message text undefined: {message}")
            self.messageType = "unknown"
        else:
            self.messageText = message.text

        self.replyId: Optional[int] = None
        self.replyText: Optional[str] = None
        self.isReply = False
        if message.reply_to_message:
            # If reply_to_message is message about creating topic, then it isn't reply
            if message.reply_to_message.forum_topic_created is None:
                self.replyId = message.reply_to_message.message_id
                self.isReply = True
                if message.reply_to_message.text:
                    self.replyText = message.reply_to_message.text

        self.threadId: Optional[int] = None
        self.isTopicMessage = message.is_topic_message == True if message.is_topic_message is not None else False
        if self.isTopicMessage:
            self.threadId = message.message_thread_id

        logger.debug(f"Ensured Message: {self}")

    def getBaseMessage(self) -> Message:
        return self._message
    
    def __str__(self) -> str:
        return json.dumps({
            "user.id": self.user.id,
            "chat.id": self.chat.id,
            "messageId": self.messageId,
            "date": self.date.isoformat(),
            "messageType": self.messageType,
            "messageText": self.messageText,
            "replyId": self.replyId,
            "isReply": self.isReply,
            "threadId": self.threadId,
            "isTopicMessage": self.isTopicMessage,
        })