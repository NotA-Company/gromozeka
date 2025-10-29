"""
Add reaction to user messages
https://docs.python-telegram-bot.org/en/stable/telegram.bot.html#telegram.Bot.set_message_reaction


"""

import logging
from typing import Optional

import telegram
from telegram import Update
from telegram.ext import ContextTypes

from internal.bot.models.chat_settings import ChatSettingsKey

from ..models import EnsuredMessage
from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class ReactOnUserMessageHandler(BaseBotHandler):
    """
    Example bot Handler
    """

    ###
    # Handling messages
    ###

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """ """

        if ensuredMessage is None:
            # Not new message, Skip
            return HandlerResultStatus.SKIPPED

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)

        authorIDList = chatSettings[ChatSettingsKey.REACTION_AUTHOR_ID].toList()
        authorUsernameList = chatSettings[ChatSettingsKey.REACTION_AUTHOR_USERNAME].toList()
        reactionEmoji = chatSettings[ChatSettingsKey.REACTION_EMOJI].toStr()
        if not reactionEmoji:
            # No emoji - no reaction
            return HandlerResultStatus.SKIPPED

        if not authorIDList and not authorUsernameList:
            # No users to react, no reaction needed
            return HandlerResultStatus.SKIPPED

        try:
            authorIDList = [int(authorID.strip()) for authorID in authorIDList]
        except ValueError:
            logger.error(f"ReactionAuthorID in chat {ensuredMessage.chat} is not a number: {authorIDList}")

        authorUsernameList = [authorUsername.strip().lower() for authorUsername in authorUsernameList]

        # if len(reactionEmoji) > 1:
        #     logger.warning(f"ReactionEmoji in chat {ensuredMessage.chat} is more than one symbol: {reactionEmoji}")

        message = ensuredMessage.getBaseMessage()

        if message.forward_origin:
            # It's forward, check if author is in authorIDList or authorUsernameList
            forwardOrigin = message.forward_origin
            authorUsername = None
            authorId = 0
            if isinstance(forwardOrigin, telegram.MessageOriginUser):
                authorUsername = forwardOrigin.sender_user.username
                authorId = forwardOrigin.sender_user.id
            elif isinstance(forwardOrigin, telegram.MessageOriginChat):
                authorUsername = forwardOrigin.sender_chat.username
                authorId = forwardOrigin.sender_chat.id
            elif isinstance(forwardOrigin, telegram.MessageOriginChannel):
                authorUsername = forwardOrigin.chat.username
                authorId = forwardOrigin.chat.id
            elif isinstance(forwardOrigin, telegram.MessageOriginHiddenUser):
                authorUsername = forwardOrigin.sender_user_name  # Better than nothing
            else:
                logger.error(f"Unknown forwardOrigin: {type(forwardOrigin).__name__}{forwardOrigin}")
                return HandlerResultStatus.ERROR

            lowerAuthorUsername = authorUsername.lower() if authorUsername else None
            if authorId in authorIDList or lowerAuthorUsername in authorUsernameList:
                # Some of needed authors, react
                try:
                    await message.set_reaction([reactionEmoji])
                except Exception as e:
                    logger.error(f"Error while reacting to message: {e}")
                    return HandlerResultStatus.ERROR
                return HandlerResultStatus.NEXT
            return HandlerResultStatus.SKIPPED

        # Not forward, chec sender
        sender = ensuredMessage.sender
        if sender.id in authorIDList or sender.username.lower() in authorUsernameList:
            # Some of needed authors itself, react
            try:
                await message.set_reaction([reactionEmoji])
            except Exception as e:
                logger.error(f"Error while reacting to message: {e}")
                return HandlerResultStatus.ERROR
            return HandlerResultStatus.NEXT

        return HandlerResultStatus.SKIPPED
