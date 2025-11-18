"""Utility functions for Telegram bot operations."""

from typing import Optional

import telegram

from internal.database.models import ChatMessageDict


def telegramMessageFromDBMessage(
    dbMessage: ChatMessageDict, bot: telegram.Bot, replyToMessage: Optional[telegram.Message] = None
) -> telegram.Message:
    """Convert a database message representation to a Telegram Message object.

    Args:
        dbMessage: Dictionary containing message data from database
        bot: Telegram Bot instance to associate with the message
        replyToMessage: Optional message that this message replies to

    Returns:
        telegram.Message: Constructed Telegram Message object with all fields populated
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
        message_id=int(dbMessage["message_id"]),
        date=dbMessage["date"],
        chat=chatObj,
        from_user=userObj,
        text=dbMessage["message_text"],
        message_thread_id=dbMessage["thread_id"],
        reply_to_message=replyToMessage,
    )
    message.set_bot(bot)
    return message
