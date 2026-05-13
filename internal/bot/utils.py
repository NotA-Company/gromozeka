"""Utility functions for Telegram bot operations.

This module provides helper functions for converting between database
representations and Telegram API objects. It is used by bot handlers
and services to transform stored message data into Telegram Message
objects that can be used with the python-telegram-bot library.
"""

from typing import Optional

import telegram

from internal.database.models import ChatMessageDict


def telegramMessageFromDBMessage(
    dbMessage: ChatMessageDict, bot: telegram.Bot, replyToMessage: Optional[telegram.Message] = None
) -> telegram.Message:
    """Convert a database message representation to a Telegram Message object.

    This function transforms a ChatMessageDict (from the database) into a
    fully-populated telegram.Message object. It creates the necessary Chat
    and User objects, associates them with the bot instance, and populates
    all relevant message fields including text, date, and reply information.

    Args:
        dbMessage: Dictionary containing message data from database, including
            chat_id, user_id, message_id, date, message_text, thread_id,
            username, and full_name fields.
        bot: Telegram Bot instance to associate with the message and its
            related objects (Chat and User).
        replyToMessage: Optional message that this message replies to. If
            provided, it will be set as the reply_to_message field in the
            returned Message object.

    Returns:
        telegram.Message: Constructed Telegram Message object with all fields
            populated including chat, from_user, text, date, message_thread_id,
            and reply_to_message (if provided).

    Example:
        >>> bot = telegram.Bot(token="YOUR_TOKEN")
        >>> db_msg = {
        ...     "chat_id": 123456789,
        ...     "user_id": 987654321,
        ...     "message_id": 1,
        ...     "date": datetime.datetime.now(datetime.UTC),
        ...     "message_text": "Hello, world!",
        ...     "thread_id": 1,
        ...     "username": "john_doe",
        ...     "full_name": "John Doe"
        ... }
        >>> message = telegramMessageFromDBMessage(db_msg, bot)
        >>> print(message.text)
        Hello, world!
    """

    chatObj = telegram.Chat(
        id=dbMessage["chat_id"],
        type=telegram.Chat.PRIVATE if dbMessage["chat_id"] > 0 else telegram.Chat.GROUP,
    )
    chatObj.set_bot(bot)
    userObj = telegram.User(
        id=dbMessage["user_id"],
        first_name=dbMessage["full_name"],
        is_bot=dbMessage["username"].endswith("bot"),
        username=dbMessage["username"],
    )
    userObj.set_bot(bot)
    message = telegram.Message(
        message_id=dbMessage["message_id"].asInt(),
        date=dbMessage["date"],
        chat=chatObj,
        from_user=userObj,
        text=dbMessage["message_text"],
        message_thread_id=dbMessage["thread_id"],
        reply_to_message=replyToMessage,
    )
    message.set_bot(bot)
    return message
