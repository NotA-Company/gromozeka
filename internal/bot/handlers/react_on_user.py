"""
Add reaction to user messages
https://docs.python-telegram-bot.org/en/stable/telegram.bot.html#telegram.Bot.set_message_reaction


"""

import json
import logging
from typing import Dict, Optional

import telegram
from telegram import Chat, Message, Update
from telegram.ext import ContextTypes

from internal.bot.models import (
    ChatSettingsKey,
    ChatSettingsValue,
    CommandCategory,
    CommandHandlerOrder,
    EnsuredMessage,
    MessageSender,
    commandHandler,
)
from internal.database.models import MessageCategory
from lib import utils

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class ReactOnUserMessageHandler(BaseBotHandler):
    """
    Example bot Handler
    """

    ###
    # Handling messages
    ###

    def _getMessageAuthor(self, message: Message) -> MessageSender:
        # We use MessageSender here to not invent new type
        ret = MessageSender(0, "", "")
        if message.forward_origin:
            # It's forward, check if author is in authorIDList or authorUsernameList
            forwardOrigin = message.forward_origin
            if isinstance(forwardOrigin, telegram.MessageOriginUser):
                ret.username = forwardOrigin.sender_user.username or ""
                ret.id = forwardOrigin.sender_user.id
            elif isinstance(forwardOrigin, telegram.MessageOriginChat):
                ret.username = forwardOrigin.sender_chat.username or ""
                ret.id = forwardOrigin.sender_chat.id
            elif isinstance(forwardOrigin, telegram.MessageOriginChannel):
                ret.username = forwardOrigin.chat.username or ""
                ret.id = forwardOrigin.chat.id
            elif isinstance(forwardOrigin, telegram.MessageOriginHiddenUser):
                ret.username = forwardOrigin.sender_user_name  # Better than nothing
            else:
                logger.error(f"Unknown forwardOrigin: {type(forwardOrigin).__name__}{forwardOrigin}")

            return ret

        # Not forward, check sender
        if message.sender_chat:
            ret = MessageSender.fromChat(message.sender_chat)
        elif message.from_user:
            ret = MessageSender.fromUser(message.from_user)

        return ret

    def _getAuthorToEmojiMap(self, chatId: int) -> Dict[str | int, str]:
        chatSettings = self.getChatSettings(chatId)
        authorToEmojiMapStr = chatSettings[ChatSettingsKey.REACTION_AUTHOR_TO_EMOJI_MAP].toStr()

        authorToEmojiMap = {}
        if not authorToEmojiMapStr:
            return authorToEmojiMap

        try:
            authorToEmojiMap = json.loads(authorToEmojiMapStr)
            if not isinstance(authorToEmojiMap, dict):
                raise ValueError(f"authorToEmojiMap for chat#{chatId} is not a dict: {authorToEmojiMap}")

        except json.JSONDecodeError:
            logger.error(f"authorToEmojiMap in chat#{chatId} " f"is not a valid JSON: {authorToEmojiMapStr}")
        except Exception as e:
            logger.error(f"Error while parsing ReactionAuthorToEmojiMap: {e}")

        # TODO: Add type validation
        return authorToEmojiMap

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """ """

        if ensuredMessage is None:
            # Not new message, Skip
            return HandlerResultStatus.SKIPPED

        authorToEmojiMap = self._getAuthorToEmojiMap(ensuredMessage.chat.id)

        if not authorToEmojiMap:
            # No users to react, no reaction needed
            return HandlerResultStatus.SKIPPED

        message = ensuredMessage.getBaseMessage()

        sender = self._getMessageAuthor(message)
        emoji = authorToEmojiMap.get(sender.id, authorToEmojiMap.get(sender.username.lower(), None))
        if emoji:
            try:
                await message.set_reaction([emoji])
            except Exception as e:
                logger.error(f"Error while reacting to message: {e}")
                return HandlerResultStatus.ERROR
            return HandlerResultStatus.NEXT

        return HandlerResultStatus.SKIPPED

    @commandHandler(
        commands=("set_reaction",),
        shortDescription="[<chatId>] <emoji> - Start reacting to author of replied message with given emoji",
        helpMessage=" [<chatId>] <emoji> - Ставить указанные реакции под сообщениями автора сообщения,"
        " на которое команда является ответом.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.NORMAL,
    )
    async def set_reaction_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Bun bip bop"""
        message = update.message
        if not message:
            logger.error(f"Message undefined in {update}")
            return
        logger.debug(f"Got set_reaction command: {utils.dumpMessage(message)}")

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        self.saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)

        replyMessage = message.reply_to_message
        if replyMessage is None:
            await self.sendMessage(
                ensuredMessage,
                messageText="Команда должна быть ответом на сообщение.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        chatId = ensuredMessage.chat.id
        emoji = None

        if context.args:
            emoji = context.args[-1]  # Just get last argument as emoji
            arg0 = context.args[0]
            try:
                if arg0.isdigit() or (arg0.startswith("-") and arg0[1:].isdigit()):
                    chatId = int(arg0)
            except ValueError:
                logger.error(f"Invalid chatId: {context.args[0]}")

        if not emoji:
            await self.sendMessage(
                ensuredMessage,
                messageText="Не указан emoji.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        targetChat = Chat(id=chatId, type=Chat.PRIVATE if chatId > 0 else Chat.SUPERGROUP)
        targetChat.set_bot(message.get_bot())

        if not await self.isAdmin(user=ensuredMessage.user, chat=targetChat):
            await self.sendMessage(
                ensuredMessage,
                messageText="У Вас нет прав для выполнения данной команды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        authorToEmojiMap = self._getAuthorToEmojiMap(chatId)
        sender = self._getMessageAuthor(replyMessage)

        if sender.id:
            authorToEmojiMap[sender.id] = emoji
        if sender.username:
            authorToEmojiMap[sender.username.lower()] = emoji

        self.setChatSetting(
            chatId,
            ChatSettingsKey.REACTION_AUTHOR_TO_EMOJI_MAP,
            ChatSettingsValue(utils.jsonDumps(authorToEmojiMap, sort_keys=False)),
        )

        try:
            await message.set_reaction([emoji])
        except Exception as e:
            logger.error(f"Error while setting reaction: {e}")

        await self.sendMessage(
            ensuredMessage,
            messageText="Готово",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandler(
        commands=("unset_reaction",),
        shortDescription="[<chatId>] - Stop reacting to author of replied message",
        helpMessage=" [<chatId>] - Перестать реакции под сообщениями автора сообщения,"
        " на которое команда является ответом.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.NORMAL,
    )
    async def unset_reaction_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Bun bip bop"""
        message = update.message
        if not message:
            logger.error(f"Message undefined in {update}")
            return
        logger.debug(f"Got unset_reaction command: {utils.dumpMessage(message)}")

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        self.saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)

        replyMessage = message.reply_to_message
        if replyMessage is None:
            await self.sendMessage(
                ensuredMessage,
                messageText="Команда должна быть ответом на сообщение.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        chatId = ensuredMessage.chat.id
        if context.args:
            arg0 = context.args[0]
            try:
                if arg0.isdigit() or (arg0.startswith("-") and arg0[1:].isdigit()):
                    chatId = int(arg0)
            except ValueError:
                logger.error(f"Invalid chatId: {context.args[0]}")

        targetChat = Chat(id=chatId, type=Chat.PRIVATE if chatId > 0 else Chat.SUPERGROUP)
        targetChat.set_bot(message.get_bot())

        if not await self.isAdmin(user=ensuredMessage.user, chat=targetChat):
            await self.sendMessage(
                ensuredMessage,
                messageText="У Вас нет прав для выполнения данной команды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        authorToEmojiMap = self._getAuthorToEmojiMap(chatId)
        sender = self._getMessageAuthor(replyMessage)
        emoji1 = authorToEmojiMap.pop(sender.id, None)
        emoji2 = authorToEmojiMap.pop(sender.username.lower(), None)

        emoji = emoji1 or emoji2

        self.setChatSetting(
            chatId,
            ChatSettingsKey.REACTION_AUTHOR_TO_EMOJI_MAP,
            ChatSettingsValue(utils.jsonDumps(authorToEmojiMap, sort_keys=False)),
        )

        resp = ""
        if emoji:
            resp = f"Готово (Была реакция: {emoji})"
            try:
                await message.set_reaction([emoji])
            except Exception as e:
                logger.error(f"Error while setting reaction: {e}")
        else:
            resp = "Готово (Не было реакции)"

        await self.sendMessage(
            ensuredMessage,
            messageText=resp,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandler(
        commands=("dump_reactions",),
        shortDescription="[<chatId>] - Dump reactions settings",
        helpMessage=" [<chatId>] - Вывести настройки реакций в указанном чате (сфрой JSON-дамп)",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.NORMAL,
    )
    async def dump_reactions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Bun bip bop"""
        message = update.message
        if not message:
            logger.error(f"Message undefined in {update}")
            return
        logger.debug(f"Got dump_reactions command: {utils.dumpMessage(message)}")

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        self.saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)

        logger.debug(f"Args: {context.args}")
        chatId = ensuredMessage.chat.id
        if context.args:
            arg0 = context.args[0]
            try:
                if arg0.isdigit() or (arg0.startswith("-") and arg0[1:].isdigit()):
                    chatId = int(arg0)
            except ValueError:
                logger.error(f"Invalid chatId: {context.args[0]}")

        logger.debug(f"chatId: {chatId}")
        targetChat = Chat(id=chatId, type=Chat.PRIVATE if chatId > 0 else Chat.SUPERGROUP)
        targetChat.set_bot(message.get_bot())

        if not await self.isAdmin(user=ensuredMessage.user, chat=targetChat):
            await self.sendMessage(
                ensuredMessage,
                messageText="У Вас нет прав для выполнения данной команды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        authorToEmojiMap = self._getAuthorToEmojiMap(chatId)

        await self.sendMessage(
            ensuredMessage,
            messageText=f"```json\n{utils.jsonDumps(authorToEmojiMap, indent=2, sort_keys=False)}\n```\n",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
