"""
Add reaction to user messages
https://docs.python-telegram-bot.org/en/stable/telegram.bot.html#telegram.Bot.set_message_reaction


"""

import json
import logging
from typing import Dict, Optional

import telegram

from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
    commandHandlerV2,
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

    def _getMessageAuthor(self, message: telegram.Message) -> MessageSender:
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
            ret = MessageSender.fromTelegramChat(message.sender_chat)
        elif message.from_user:
            ret = MessageSender.fromTelegramUser(message.from_user)

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

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """ """
        message = ensuredMessage.getBaseMessage()

        if self.botProvider != BotProvider.TELEGRAM or not isinstance(message, telegram.Message):
            logger.error("ReactOnUserMessageHandler support Telegram only for now")
            return HandlerResultStatus.SKIPPED

        authorToEmojiMap = self._getAuthorToEmojiMap(ensuredMessage.recipient.id)

        if not authorToEmojiMap:
            # No users to react, no reaction needed
            return HandlerResultStatus.SKIPPED

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

    @commandHandlerV2(
        commands=("set_reaction",),
        shortDescription="[<chatId>] <emoji> - Start reacting to author of replied message with given emoji",
        helpMessage=" [<chatId>] <emoji> - Ставить указанные реакции под сообщениями автора сообщения,"
        " на которое команда является ответом.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.ADMIN},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.ADMIN,
    )
    async def set_reaction_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """TODO"""
        message = ensuredMessage.getBaseMessage()
        if self.botProvider != BotProvider.TELEGRAM or not isinstance(message, telegram.Message):
            logger.error("ReactOnUserMessageHandler support Telegram only for now")
            await self.sendMessage(
                ensuredMessage,
                messageText="Команда не поддержана на данной платформе",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        replyMessage = message.reply_to_message
        if replyMessage is None:
            await self.sendMessage(
                ensuredMessage,
                messageText="Команда должна быть ответом на сообщение.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        argList = args.split()
        targetChatId = utils.extractInt(argList)
        if targetChatId is None:
            targetChatId = ensuredMessage.recipient.id
        else:
            argList = argList[1:]

        emoji = None
        if argList:
            emoji = argList[0]

        if not emoji:
            await self.sendMessage(
                ensuredMessage,
                messageText="Не указан эмодзи для реакции.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        targetChat = MessageRecipient(
            id=targetChatId,
            chatType=ChatType.PRIVATE if targetChatId > 0 else ChatType.GROUP,
        )

        if not await self.isAdmin(user=ensuredMessage.sender, chat=targetChat):
            await self.sendMessage(
                ensuredMessage,
                messageText="У Вас нет прав для выполнения данной команды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        authorToEmojiMap = self._getAuthorToEmojiMap(targetChatId)
        sender = self._getMessageAuthor(replyMessage)

        if sender.id:
            authorToEmojiMap[sender.id] = emoji
        if sender.username:
            authorToEmojiMap[sender.username.lower()] = emoji

        self.setChatSetting(
            targetChatId,
            ChatSettingsKey.REACTION_AUTHOR_TO_EMOJI_MAP,
            ChatSettingsValue(utils.jsonDumps(authorToEmojiMap, sort_keys=False)),
            user=ensuredMessage.sender,
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

    @commandHandlerV2(
        commands=("unset_reaction",),
        shortDescription="[<chatId>] - Stop reacting to author of replied message",
        helpMessage=" [<chatId>] - Перестать реакции под сообщениями автора сообщения,"
        " на которое команда является ответом.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.ADMIN},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.ADMIN,
    )
    async def unset_reaction_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        Remove a reaction from a message, dood!

        This command allows removing reactions that were previously added to messages.
        The command must be sent as a reply to the message from which to remove the reaction.
        """
        message = ensuredMessage.getBaseMessage()
        if self.botProvider != BotProvider.TELEGRAM or not isinstance(message, telegram.Message):
            logger.error("ReactOnUserMessageHandler support Telegram only for now")
            await self.sendMessage(
                ensuredMessage,
                messageText="Команда не поддержана на данной платформе",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        replyMessage = message.reply_to_message
        if replyMessage is None:
            await self.sendMessage(
                ensuredMessage,
                messageText="Команда должна быть ответом на сообщение.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        argList = args.split()
        targetChatId = utils.extractInt(argList)
        if targetChatId is None:
            targetChatId = ensuredMessage.recipient.id

        targetChat = MessageRecipient(
            id=targetChatId,
            chatType=ChatType.PRIVATE if targetChatId > 0 else ChatType.GROUP,
        )

        if not await self.isAdmin(user=ensuredMessage.sender, chat=targetChat):
            await self.sendMessage(
                ensuredMessage,
                messageText="У Вас нет прав для выполнения данной команды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        authorToEmojiMap = self._getAuthorToEmojiMap(targetChatId)
        sender = self._getMessageAuthor(replyMessage)
        emoji1 = authorToEmojiMap.pop(sender.id, None)
        emoji2 = authorToEmojiMap.pop(sender.username.lower(), None)

        emoji = emoji1 or emoji2

        self.setChatSetting(
            targetChatId,
            ChatSettingsKey.REACTION_AUTHOR_TO_EMOJI_MAP,
            ChatSettingsValue(utils.jsonDumps(authorToEmojiMap, sort_keys=False)),
            user=ensuredMessage.sender,
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

    @commandHandlerV2(
        commands=("dump_reactions",),
        shortDescription="[<chatId>] - Dump reactions settings",
        helpMessage=" [<chatId>] - Вывести настройки реакций в указанном чате (сфрой JSON-дамп)",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.ADMIN},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.ADMIN,
    )
    async def dump_reactions_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        Dump reaction statistics for a chat, dood!

        This command displays statistics about reactions in the specified chat,
        including the number of reactions and which users have reacted to messages.
        """
        argList = args.split()

        logger.debug(f"Args: {argList}")
        targetChatId = utils.extractInt(argList)
        if targetChatId is None:
            targetChatId = ensuredMessage.recipient.id

        logger.debug(f"chatId: {targetChatId}")
        targetChat = MessageRecipient(
            id=targetChatId,
            chatType=ChatType.PRIVATE if targetChatId > 0 else ChatType.GROUP,
        )

        if not await self.isAdmin(user=ensuredMessage.sender, chat=targetChat):
            await self.sendMessage(
                ensuredMessage,
                messageText="У Вас нет прав для выполнения данной команды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        authorToEmojiMap = self._getAuthorToEmojiMap(targetChatId)

        await self.sendMessage(
            ensuredMessage,
            messageText=f"```json\n{utils.jsonDumps(authorToEmojiMap, indent=2, sort_keys=False)}\n```\n",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
