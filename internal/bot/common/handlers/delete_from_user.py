"""Handler for deleting messages from specific authors.

This module provides functionality to automatically delete messages from specific
users in Telegram chats. It allows administrators to configure a list of authors
(by user ID or username) whose messages should be removed on arrival.

Reference:
    https://docs.python-telegram-bot.org/en/stable/telegram.bot.html#telegram.Bot.delete_message
"""

import json
import logging
from typing import List, Optional

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


class DeleteFromUserMessageHandler(BaseBotHandler):
    """Handler for automatically deleting messages from specific users.

    This handler allows administrators to configure a list of authors whose
    messages will be automatically deleted in Telegram chats. Authors can be
    identified by either user ID (int) or username (str, lowercase).
    """

    ###
    # Handling messages
    ###

    def _getMessageAuthor(self, message: telegram.Message) -> MessageSender:
        """Extract the author information from a Telegram message.

        This method determines the actual author of a message, handling both regular
        messages and forwarded messages. For forwarded messages, it extracts the
        original author's information from the forward origin.

        Args:
            message: The Telegram message to extract author information from.

        Returns:
            A MessageSender object containing the author's ID and username.
            Returns an empty MessageSender if the author cannot be determined.
        """
        # We use MessageSender here to not invent a new type
        ret = MessageSender(0, "", "")
        if message.forward_origin:
            # It's forward, check if author is in authorList
            forwardOrigin = message.forward_origin
            if isinstance(forwardOrigin, telegram.MessageOriginUser):
                ret.username = forwardOrigin.sender_user.name or ""
                ret.name = forwardOrigin.sender_user.full_name
                ret.id = forwardOrigin.sender_user.id
            elif isinstance(forwardOrigin, telegram.MessageOriginChat):
                ret.username = f"@{forwardOrigin.sender_chat.username}" if forwardOrigin.sender_chat.username else ""
                ret.name = forwardOrigin.sender_chat.effective_name or ""
                ret.id = forwardOrigin.sender_chat.id
            elif isinstance(forwardOrigin, telegram.MessageOriginChannel):
                ret.username = f"@{forwardOrigin.chat.username}" if forwardOrigin.chat.username else ""
                ret.name = forwardOrigin.chat.effective_name or ""
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

    async def _getAuthorList(self, chatId: int) -> List[int | str]:
        """Retrieve the delete-author list for a specific chat.

        This method fetches the chat settings and parses the JSON string that holds
        a list of user IDs (int) and usernames (str) whose messages should be deleted.

        Args:
            chatId: The ID of the chat to retrieve the list for.

        Returns:
            A list of user IDs (int) and/or usernames (str). Returns an empty list
            if the setting is not configured or invalid. Entries of invalid types
            (e.g. dict, list, None, bool, float) are filtered out and logged as a warning.
        """
        chatSettings = await self.getChatSettings(chatId)
        authorListStr = chatSettings[ChatSettingsKey.DELETE_AUTHOR_LIST].toStr()

        authorList: List[int | str] = []
        if not authorListStr:
            return authorList

        try:
            parsed = json.loads(authorListStr)
            if not isinstance(parsed, list):
                raise ValueError(f"deleteAuthorList for chat#{chatId} is not a list: {parsed}")
            authorList = [x for x in parsed if isinstance(x, (int, str)) and not isinstance(x, bool)]
            if len(authorList) != len(parsed):
                logger.warning(f"deleteAuthorList in chat#{chatId} contained invalid entries, filtered")
        except json.JSONDecodeError:
            logger.error(f"deleteAuthorList in chat#{chatId} is not a valid JSON: {authorListStr}")
        except Exception as e:
            logger.error(f"Error while parsing deleteAuthorList: {e}")

        return authorList

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Handle new messages and delete them if the author is in the delete list.

        This method is called for each new message and checks if the message author
        is in the configured delete-author list. If so, the message is deleted.

        Args:
            ensuredMessage: The ensured message object containing message details.
            updateObj: The update object from the messaging platform.

        Returns:
            HandlerResultStatus.FINAL if a message was successfully deleted,
            HandlerResultStatus.SKIPPED if no deletion was needed or configured,
            HandlerResultStatus.ERROR if an error occurred while deleting the message.
        """
        message = ensuredMessage.getBaseMessage()

        if self.botProvider != BotProvider.TELEGRAM or not isinstance(message, telegram.Message):
            logger.warning("DeleteFromUserMessageHandler supports Telegram only for now")
            return HandlerResultStatus.SKIPPED

        authorList = await self._getAuthorList(ensuredMessage.recipient.id)

        if not authorList:
            # No users to delete, nothing to do
            return HandlerResultStatus.SKIPPED

        authorSet = set(authorList)
        sender = self._getMessageAuthor(message)

        isTarget = (sender.id and sender.id in authorSet) or (sender.username and sender.username.lower() in authorSet)

        if isTarget:
            try:
                await self.deleteMessage(ensuredMessage)
            except Exception as e:
                logger.error(f"Error while deleting message: {e}")
                return HandlerResultStatus.ERROR
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.SKIPPED

    @commandHandlerV2(
        commands=("set_delete_author",),
        shortDescription="[<chatId>] - Start deleting messages from author of replied message",
        helpMessage=" [<chatId>] - Удалять сообщения автора сообщения, на которое команда является ответом.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.ADMIN},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.ADMIN,
    )
    async def set_delete_author_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Add the author of a replied-to message to the delete list.

        This command allows administrators to add the author of the replied-to
        message to the list of users whose messages will be automatically deleted.
        The command must be sent as a reply to a message from the target user.

        Args:
            ensuredMessage: The ensured message object containing command details.
            command: The command name that was triggered.
            args: Command arguments. Format: [<chatId>].
            UpdateObj: The update object from the messaging platform.
            typingManager: Optional typing manager for showing typing status.

        Returns:
            None
        """
        message = ensuredMessage.getBaseMessage()
        if self.botProvider != BotProvider.TELEGRAM or not isinstance(message, telegram.Message):
            logger.error("DeleteFromUserMessageHandler supports Telegram only for now")
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

        authorList = await self._getAuthorList(targetChatId)
        sender = self._getMessageAuthor(replyMessage)

        if sender.id == 0 and not sender.username:
            await self.sendMessage(
                ensuredMessage,
                messageText="Не удалось определить автора сообщения.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        if sender.id and sender.id not in authorList:
            authorList.append(sender.id)
        if sender.username:
            usernameLower = sender.username.lower()
            if usernameLower not in authorList:
                authorList.append(usernameLower)

        await self.setChatSetting(
            targetChatId,
            ChatSettingsKey.DELETE_AUTHOR_LIST,
            ChatSettingsValue(utils.jsonDumps(authorList, sort_keys=False)),
            user=ensuredMessage.sender,
        )

        await self.sendMessage(
            ensuredMessage,
            messageText="Готово",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerV2(
        commands=("unset_delete_author",),
        shortDescription="[<chatId>] - Stop deleting messages from author of replied message",
        helpMessage=" [<chatId>] - Перестать удалять сообщения автора сообщения,"
        " на которое команда является ответом.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.ADMIN},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.ADMIN,
    )
    async def unset_delete_author_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Remove the author of a replied-to message from the delete list.

        This command allows administrators to remove the author of the replied-to
        message from the list of users whose messages are automatically deleted.
        The command must be sent as a reply to a message from the target user.

        Args:
            ensuredMessage: The ensured message object containing command details.
            command: The command name that was triggered.
            args: Command arguments. Format: [<chatId>].
            UpdateObj: The update object from the messaging platform.
            typingManager: Optional typing manager for showing typing status.

        Returns:
            None
        """
        message = ensuredMessage.getBaseMessage()
        if self.botProvider != BotProvider.TELEGRAM or not isinstance(message, telegram.Message):
            logger.warning("DeleteFromUserMessageHandler supports Telegram only for now")
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

        authorList = await self._getAuthorList(targetChatId)
        sender = self._getMessageAuthor(replyMessage)

        if sender.id == 0 and not sender.username:
            await self.sendMessage(
                ensuredMessage,
                messageText="Не удалось определить автора сообщения.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        removed = False
        if sender.id and sender.id in authorList:
            authorList.remove(sender.id)
            removed = True
        if sender.username:
            usernameLower = sender.username.lower()
            if usernameLower in authorList:
                authorList.remove(usernameLower)
                removed = True

        await self.setChatSetting(
            targetChatId,
            ChatSettingsKey.DELETE_AUTHOR_LIST,
            ChatSettingsValue(utils.jsonDumps(authorList, sort_keys=False)),
            user=ensuredMessage.sender,
        )

        resp = "Готово" if removed else "Готово (Не было в списке на удаление)"

        await self.sendMessage(
            ensuredMessage,
            messageText=resp,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerV2(
        commands=("dump_delete_authors",),
        shortDescription="[<chatId>] - Dump delete authors settings",
        helpMessage=" [<chatId>] - Вывести настройки удаления авторов в указанном чате (сырой JSON-дамп)",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.ADMIN},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.ADMIN,
    )
    async def dump_delete_authors_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Display the current delete-author list for a chat.

        This command outputs the JSON configuration of which users have message
        deletion configured in the specified chat. This is useful for reviewing
        and debugging delete settings.

        Args:
            ensuredMessage: The ensured message object containing command details.
            command: The command name that was triggered.
            args: Command arguments. Format: [<chatId>].
            UpdateObj: The update object from the messaging platform.
            typingManager: Optional typing manager for showing typing status.

        Returns:
            None
        """
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

        authorList = await self._getAuthorList(targetChatId)

        await self.sendMessage(
            ensuredMessage,
            messageText=f"```json\n{utils.jsonDumps(authorList, indent=2, sort_keys=False)}\n```\n",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
