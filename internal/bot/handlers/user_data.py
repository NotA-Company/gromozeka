"""
User data management handlers for the Gromozeka Telegram bot, dood!

This module provides handlers for managing user-specific data storage within the bot.
It includes command handlers for viewing, deleting, and clearing user data, as well as
LLM tool integration for AI-assisted data management, dood!

The module implements:
- User data retrieval and display
- Selective data deletion by key
- Complete data clearing
- LLM tool for AI-driven data storage

All user data is scoped to specific chat and user combinations, dood!
"""

import logging
from typing import Any, Dict, List, Optional

import telegram
from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update, User
from telegram.ext import ContextTypes

import lib.utils as utils
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.services.cache.types import UserActiveActionEnum
from internal.services.llm import LLMService
from lib.ai import (
    LLMFunctionParameter,
    LLMManager,
    LLMParameterType,
)
from lib.markdown.parser import markdownToMarkdownV2

from ..models import (
    ButtonDataKey,
    ButtonUserDataConfigAction,
    CallbackDataDict,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
)
from .base import BaseBotHandler, HandlerResultStatus, commandHandlerExtended

logger = logging.getLogger(__name__)


class UserDataHandler(BaseBotHandler):
    """
    Handler class for user data management operations, dood!

    This class provides command handlers and LLM tool integration for managing
    user-specific data within the bot. It allows users to store, retrieve, and
    delete personalized information that the bot can use to improve interactions.

    The handler registers an LLM tool that enables the AI to automatically store
    relevant user information during conversations, dood!

    Attributes:
        llmService (LLMService): Service for LLM tool registration and management.
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """
        Initialize the user data handler with required services, dood!

        Sets up the handler and registers the 'add_user_data' LLM tool for
        AI-assisted data storage during conversations.

        Args:
            configManager (ConfigManager): Configuration manager instance.
            database (DatabaseWrapper): Database wrapper for data persistence.
            llmManager (LLMManager): LLM manager for AI model interactions.
        """
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager)

        self.llmService = LLMService.getInstance()

        self.llmService.registerTool(
            name="add_user_data",
            description=(
                "Add some data/knowledge about user, sent last message. "
                "Use it in following cases:\n"
                "1. User asked to learn/remember something about him/her.\n"
                "2. You learned new information about user "
                "(e.g., real name, birth dare, what he like, etc).\n"
                "3. You want to remember something relating to user.\n"
                "4. When you needs to store information related to the user "
                "to improve interaction quality (e.g., remembering formatting preferences, "
                "command usage frequency, communication style).\n"
                "\n"
                "Will return new data for given key."
            ),
            parameters=[
                LLMFunctionParameter(
                    name="key",
                    description="Key for data (for structured data usage)",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
                LLMFunctionParameter(
                    name="data",
                    description="Data/knowledbe you want to remember",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
                LLMFunctionParameter(
                    name="append",
                    description=(
                        "True: Append data to existing data, "
                        "False: replace existing data for given key. "
                        "Default: False"
                    ),
                    type=LLMParameterType.BOOLEAN,
                    required=False,
                ),
            ],
            handler=self._llmToolSetUserData,
        )

    ###
    # LLM Tool-Calling handlers
    ###

    async def _llmToolSetUserData(
        self, extraData: Optional[Dict[str, Any]], key: str, data: str, append: bool = False, **kwargs
    ) -> str:
        """
        LLM tool handler for storing user data, dood!

        This method is called by the LLM when it needs to store information about
        a user. It validates the required context and delegates to the base handler's
        setUserData method.

        Args:
            extraData (Optional[Dict[str, Any]]): Extra context data containing the
                ensuredMessage object. Must not be None.
            key (str): The key under which to store the data.
            data (str): The data/knowledge to store.
            append (bool, optional): If True, append to existing data; if False,
                replace existing data. Defaults to False.
            **kwargs: Additional keyword arguments (ignored).

        Returns:
            str: JSON string containing operation status, key, and the new data value.

        Raises:
            RuntimeError: If extraData is None, doesn't contain ensuredMessage,
                or ensuredMessage is not an EnsuredMessage instance, dood!
        """
        if extraData is None:
            raise RuntimeError("extraData should be provided")
        if "ensuredMessage" not in extraData:
            raise RuntimeError("ensuredMessage should be provided")
        ensuredMessage = extraData["ensuredMessage"]
        if not isinstance(ensuredMessage, EnsuredMessage):
            raise RuntimeError("ensuredMessage should be EnsuredMessage")

        newData = self.setUserData(
            chatId=ensuredMessage.chat.id, userId=ensuredMessage.user.id, key=key, value=data, append=append
        )
        return utils.jsonDumps({"done": True, "key": key, "data": newData})

    ###
    # Handling user-data configuration wizard
    ###

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """
        Handle incoming messages for user data configuration wizard, dood!

        Processes messages sent during the user data configuration flow in private chats.
        Captures user input for setting key-value pairs in the configuration wizard.

        Args:
            update (Update): The Telegram update object containing the message.
            context (ContextTypes.DEFAULT_TYPE): The callback context from python-telegram-bot.
            ensuredMessage (Optional[EnsuredMessage]): The ensured message object, or None if not a new message.

        Returns:
            HandlerResultStatus: FINAL if message was handled in configuration flow, SKIPPED otherwise.
        """

        if ensuredMessage is None:
            # Not new message, Skip
            return HandlerResultStatus.SKIPPED

        if ensuredMessage.chat.type != Chat.PRIVATE:
            return HandlerResultStatus.SKIPPED

        user = ensuredMessage.user
        userId = user.id
        messageText = ensuredMessage.getRawMessageText()
        userDataConfig = self.cache.getUserState(userId=userId, stateKey=UserActiveActionEnum.UserDataConfig)
        if userDataConfig is None:
            return HandlerResultStatus.SKIPPED

        await self._handleUserDataConfiguration(
            data={
                **userDataConfig["data"],
                ButtonDataKey.Value: messageText,
            },
            messageId=userDataConfig["messageId"],
            user=user,
            bot=context.bot,
        )
        return HandlerResultStatus.FINAL

    async def _handleConfigAction_Init(
        self,
        data: CallbackDataDict,
        messageId: int,
        user: User,
        bot: telegram.Bot,
    ) -> None:
        """
        Initialize the user data configuration wizard, dood!

        Displays a list of chats where the user can configure their data.
        Creates an inline keyboard with buttons for each available chat.

        Args:
            data (CallbackDataDict): Callback data dictionary from the button press.
            messageId (int): The message ID to edit with the chat selection interface.
            user (User): The Telegram user initiating the configuration.
            bot (telegram.Bot): The bot instance for sending messages.

        Returns:
            None
        """
        # Print list of known chats

        exitButton = InlineKeyboardButton(
            "Закончить настройку",
            callback_data=utils.packDict({ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel}),
        )
        keyboard: List[List[InlineKeyboardButton]] = []

        for chat in self.db.getUserChats(user.id):
            keyboard.append(
                [
                    InlineKeyboardButton(
                        self.getChatTitle(chat, useMarkdown=False, addChatId=False),
                        callback_data=utils.packDict(
                            {
                                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                                ButtonDataKey.ChatId: chat["chat_id"],
                            }
                        ),
                    )
                ]
            )

        if not keyboard:
            await bot.edit_message_text(
                "Чаты не найдены.",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        keyboard.append([exitButton])
        await bot.edit_message_text(
            text="Выберите чат для настройки:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            chat_id=user.id,
            message_id=messageId,
        )

    async def _handleConfigAction_ChatSelected(
        self,
        data: CallbackDataDict,
        messageId: int,
        user: User,
        bot: telegram.Bot,
    ) -> None:
        """
        Handle chat selection in the configuration wizard, dood!

        Displays all stored user data for the selected chat and provides options
        to add new keys, modify existing ones, or clear all data.

        Args:
            data (CallbackDataDict): Callback data containing the selected chat ID.
            messageId (int): The message ID to edit with the chat data interface.
            user (User): The Telegram user managing their data.
            bot (telegram.Bot): The bot instance for sending messages.

        Returns:
            None
        """
        exitButton = InlineKeyboardButton(
            "Закончить настройку",
            callback_data=utils.packDict({ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel}),
        )

        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"ChatSelected: wrong chatId: {type(chatId).__name__}#{chatId}")
            await bot.edit_message_text(
                "Ошибка: некорректный идентификатор чата",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        chatInfo = self.getChatInfo(chatId)
        if chatInfo is None:
            logger.error(f"ChatSelected: chatInfo is None in {chatId}")
            await bot.edit_message_text(
                "Ошибка: Выбран неизвестный чат",
                chat_id=user.id,
                message_id=messageId,
            )
            return
        # TODO: Check if user is present in given chat

        logger.debug(f"ChatSelected: chatInfo: {chatInfo}")
        resp = f"Выбран чат {self.getChatTitle(chatInfo)}:\n\n"
        keyboard: List[List[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    "Добавить новый ключ",
                    callback_data=utils.packDict(
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.KeySelected,
                            ButtonDataKey.ChatId: chatId,
                        }
                    ),
                )
            ]
        ]

        userData = self.cache.getChatUserData(chatId=chatId, userId=user.id)
        for k, v in userData.items():
            resp += f"**Ключ**: `{k}`:\n```{k}\n{v}\n```\n\n"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        k,
                        callback_data=utils.packDict(
                            {
                                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.KeySelected,
                                ButtonDataKey.ChatId: chatId,
                                ButtonDataKey.Key: k,
                            }
                        ),
                    )
                ]
            )

        resp += "Выберите нужное действие:"
        keyboard.append(
            [
                InlineKeyboardButton(
                    "Очистить все данные",
                    callback_data=utils.packDict(
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ClearChatData,
                            ButtonDataKey.ChatId: chatId,
                        }
                    ),
                )
            ]
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    "<< Назад",
                    callback_data=utils.packDict(
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Init,
                        }
                    ),
                )
            ]
        )
        keyboard.append([exitButton])
        await bot.edit_message_text(
            markdownToMarkdownV2(resp),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="MarkdownV2",
            chat_id=user.id,
            message_id=messageId,
        )

    async def _handleConfigAction_ClearChatData(
        self,
        data: CallbackDataDict,
        messageId: int,
        user: User,
        bot: telegram.Bot,
    ) -> None:
        """
        Clear all user data for the selected chat, dood!

        Removes all stored key-value pairs for the user in the specified chat
        and displays a confirmation message with navigation options.

        Args:
            data (CallbackDataDict): Callback data containing the chat ID to clear data for.
            messageId (int): The message ID to edit with the confirmation.
            user (User): The Telegram user whose data is being cleared.
            bot (telegram.Bot): The bot instance for sending messages.

        Returns:
            None
        """
        exitButton = InlineKeyboardButton(
            "Закончить настройку",
            callback_data=utils.packDict({ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel}),
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"ClearChatData: wrong chatId: {type(chatId).__name__}#{chatId}")
            await bot.edit_message_text(
                "Ошибка: некорректный идентификатор чата",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        # TODO: Check if user is present in given chat
        self.cache.clearChatUserData(chatId=chatId, userId=user.id)
        keyboard: List[List[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    "<< Назад",
                    callback_data=utils.packDict(
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                            ButtonDataKey.ChatId: chatId,
                        }
                    ),
                )
            ],
            [exitButton],
        ]
        await bot.edit_message_text(
            "Все данные очищены",
            reply_markup=InlineKeyboardMarkup(keyboard),
            chat_id=user.id,
            message_id=messageId,
        )

    async def _handleConfigAction_DeleteKey(
        self,
        data: CallbackDataDict,
        messageId: int,
        user: User,
        bot: telegram.Bot,
    ) -> None:
        """
        Delete a specific user data key from the selected chat, dood!

        Removes the data associated with the specified key for the user in the
        given chat and displays a confirmation message.

        Args:
            data (CallbackDataDict): Callback data containing the chat ID and key to delete.
            messageId (int): The message ID to edit with the confirmation.
            user (User): The Telegram user whose data key is being deleted.
            bot (telegram.Bot): The bot instance for sending messages.

        Returns:
            None
        """
        exitButton = InlineKeyboardButton(
            "Закончить настройку",
            callback_data=utils.packDict({ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel}),
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"DeleteKey: wrong chatId: {type(chatId).__name__}#{chatId}")
            await bot.edit_message_text(
                "Ошибка: некорректный идентификатор чата",
                chat_id=user.id,
                message_id=messageId,
            )
            return
        # TODO: Check if user is present in given chat

        # We need to check if key is passed, actually.
        # But I don't care
        key = str(data.get(ButtonDataKey.Key, None))

        self.cache.unsetChatUserData(chatId=chatId, userId=user.id, key=key)
        keyboard: List[List[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    "<< Назад",
                    callback_data=utils.packDict(
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                            ButtonDataKey.ChatId: chatId,
                        }
                    ),
                )
            ],
            [exitButton],
        ]
        await bot.edit_message_text(
            f"Данные по ключу {key} удалены",
            reply_markup=InlineKeyboardMarkup(keyboard),
            chat_id=user.id,
            message_id=messageId,
        )

    async def _handleConfigAction_KeySelected(
        self,
        data: CallbackDataDict,
        messageId: int,
        user: User,
        bot: telegram.Bot,
    ) -> None:
        """
        Handle key selection for editing or creating user data, dood!

        Prompts the user to enter a new value for an existing key or to create
        a new key-value pair. Sets up the user state to capture the next message.

        Args:
            data (CallbackDataDict): Callback data containing the chat ID and optional key.
            messageId (int): The message ID to edit with the input prompt.
            user (User): The Telegram user editing their data.
            bot (telegram.Bot): The bot instance for sending messages.

        Returns:
            None
        """
        exitButton = InlineKeyboardButton(
            "Закончить настройку",
            callback_data=utils.packDict({ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel}),
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"KeySelected: wrong chatId: {type(chatId).__name__}#{chatId}")
            await bot.edit_message_text(
                "Ошибка: некорректный идентификатор чата",
                chat_id=user.id,
                message_id=messageId,
            )
            return
        # TODO: Check if user is present in given chat

        key = data.get(ButtonDataKey.Key, None)

        self.cache.setUserState(
            userId=user.id,
            stateKey=UserActiveActionEnum.UserDataConfig,
            value={
                "data": {
                    ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.SetValue,
                    ButtonDataKey.ChatId: chatId,
                    ButtonDataKey.Key: key,
                },
                "messageId": messageId,
            },
        )

        userData = self.cache.getChatUserData(chatId=chatId, userId=user.id)
        if userData is None:
            userData = {}

        resp = (
            (
                "Введите новый ключ и его значение.\n"
                "Первое слово будет использовано как ключ, остальной текст "
                "будет использован как значение:"
            )
            if key is None
            else f"Введите новое значение для ключа {key}.\n"
            f"Текущее значение:\n```{key}\n{userData.get(str(key), '')}\n```"
        )

        keyboard: List[List[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    "<< Назад",
                    callback_data=utils.packDict(
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                            ButtonDataKey.ChatId: chatId,
                        }
                    ),
                )
            ],
            [exitButton],
        ]
        await bot.edit_message_text(
            markdownToMarkdownV2(resp),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="MarkdownV2",
            chat_id=user.id,
            message_id=messageId,
        )

    async def _handleConfigAction_SetValue(
        self,
        data: CallbackDataDict,
        messageId: int,
        user: User,
        bot: telegram.Bot,
    ) -> None:
        """
        Set or update a user data value in the configuration wizard, dood!

        Processes the user's input to set a new value for a key or create a new
        key-value pair. If no key was pre-selected, extracts the key from the message.

        Args:
            data (CallbackDataDict): Callback data containing chat ID, optional key, and the value.
            messageId (int): The message ID to edit with the confirmation.
            user (User): The Telegram user setting the data.
            bot (telegram.Bot): The bot instance for sending messages.

        Returns:
            None
        """
        exitButton = InlineKeyboardButton(
            "Закончить настройку",
            callback_data=utils.packDict({ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel}),
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"SetValue: wrong chatId: {type(chatId).__name__}#{chatId}")
            await bot.edit_message_text(
                "Ошибка: некорректный идентификатор чата",
                chat_id=user.id,
                message_id=messageId,
            )
            return
        # TODO: Check if user is present in given chat

        key = data.get(ButtonDataKey.Key, None)
        value = data.get(ButtonDataKey.Value, None)

        if not value:
            logger.error(f"SetValue: Value is empty in {data}")
            await bot.edit_message_text(
                "Произошла ошибка",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        if key is None:
            key, value = str(value).split(" ", 1)

        self.cache.setChatUserData(chatId=chatId, userId=user.id, key=str(key), value=str(value))

        keyboard: List[List[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    "<< Назад",
                    callback_data=utils.packDict(
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                            ButtonDataKey.ChatId: chatId,
                        }
                    ),
                )
            ],
            [exitButton],
        ]

        await bot.edit_message_text(
            markdownToMarkdownV2(f"Готово, теперь ключ {key} установлен в \n```{key}\n{value}\n```"),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="MarkdownV2",
            chat_id=user.id,
            message_id=messageId,
        )

    async def _handleUserDataConfiguration(
        self,
        data: CallbackDataDict,
        messageId: int,
        user: User,
        bot: telegram.Bot,
    ) -> None:
        """
        Route user data configuration actions to appropriate handlers, dood!

        Main dispatcher for the user data configuration wizard. Clears the user state
        and routes the action to the corresponding handler method based on the action type.

        Args:
            data (CallbackDataDict): Callback data containing the action and related parameters.
            messageId (int): The message ID to edit with the action result.
            user (User): The Telegram user performing the configuration.
            bot (telegram.Bot): The bot instance for sending messages.

        Returns:
            None
        """

        self.cache.clearUserState(userId=user.id, stateKey=UserActiveActionEnum.UserDataConfig)

        action = data.get(ButtonDataKey.UserDataConfigAction, None)
        if action not in ButtonUserDataConfigAction.all():
            logger.error(f"_handleUserDataConfiguration: Invalid action: {action}")
            return
        action = ButtonUserDataConfigAction(action)

        match action:
            case ButtonUserDataConfigAction.Init:
                await self._handleConfigAction_Init(data, messageId, user, bot)
            case ButtonUserDataConfigAction.Cancel:
                await bot.edit_message_text(
                    text="Настройка закончена, буду ждать вас снова",
                    chat_id=user.id,
                    message_id=messageId,
                )
            case ButtonUserDataConfigAction.ChatSelected:
                await self._handleConfigAction_ChatSelected(data, messageId, user, bot)
            case ButtonUserDataConfigAction.ClearChatData:
                await self._handleConfigAction_ClearChatData(data, messageId, user, bot)
            case ButtonUserDataConfigAction.DeleteKey:
                await self._handleConfigAction_DeleteKey(data, messageId, user, bot)
            case ButtonUserDataConfigAction.KeySelected:
                await self._handleConfigAction_KeySelected(data, messageId, user, bot)
            case ButtonUserDataConfigAction.SetValue:
                await self._handleConfigAction_SetValue(data, messageId, user, bot)

            case _:
                logger.error(f"_handleUserDataConfiguration: Invalid action: {action}")
                await bot.edit_message_text(
                    text=f"Unknown action: {action}",
                    chat_id=user.id,
                    message_id=messageId,
                )
                return

    async def buttonHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: CallbackDataDict
    ) -> HandlerResultStatus:
        """
        Handle button callbacks for user data configuration, dood!

        Processes inline keyboard button presses related to user data management.
        Routes configuration actions to the main configuration handler.

        Args:
            update (Update): The Telegram update object containing the callback query.
            context (ContextTypes.DEFAULT_TYPE): The callback context from python-telegram-bot.
            data (CallbackDataDict): Parsed callback data from the button press.

        Returns:
            HandlerResultStatus: FINAL if a user data action was handled, SKIPPED otherwise,
                or FATAL if critical data is missing.
        """

        query = update.callback_query
        if query is None:
            logger.error("buttonHandler: query is None")
            return HandlerResultStatus.FATAL

        user = query.from_user

        if query.message is None:
            logger.error(f"buttonHandler: message is None in {query}")
            return HandlerResultStatus.FATAL

        if not isinstance(query.message, Message):
            logger.error(f"buttonHandler: message is not a Message in {query}")
            return HandlerResultStatus.FATAL

        userDataAction = data.get(ButtonDataKey.UserDataConfigAction, None)
        if userDataAction is not None:
            await self._handleUserDataConfiguration(data, query.message.id, user, context.bot)
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.SKIPPED

    ###
    # COMMANDS Handlers
    ###

    @commandHandlerExtended(
        commands=("get_my_data",),
        shortDescription="Dump data, bot knows about you in this chat",
        helpMessage=": Показать запомненную информацию о Вас в текущем чате.",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.GROUP},
        helpOrder=CommandHandlerOrder.TECHNICAL,
        category=CommandCategory.TOOLS,
    )
    async def get_my_data_command(
        self, ensuredMessage: EnsuredMessage, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle the /get_my_data command to display stored user data, dood!

        Retrieves and displays all data the bot has stored about the user in the
        current chat. The data is formatted as JSON for easy reading.

        Args:
            update (Update): The Telegram update object containing the message.
            context (ContextTypes.DEFAULT_TYPE): The callback context from python-telegram-bot.

        Returns:
            None

        Note:
            This command is only available in private chats and is categorized as
            a technical command, dood!
        """

        self._updateEMessageUserData(ensuredMessage)

        await self.sendMessage(
            ensuredMessage,
            messageText=(f"```json\n{utils.jsonDumps(ensuredMessage.userData, indent=2)}\n```"),
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerExtended(
        commands=("delete_my_data",),
        shortDescription="<key> - Delete user data for given key",
        helpMessage=" `<key>`: Удалить информацию о Вас по указанному ключу.",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.GROUP},
        helpOrder=CommandHandlerOrder.TECHNICAL,
        category=CommandCategory.TOOLS,
    )
    async def delete_my_data_command(
        self, ensuredMessage: EnsuredMessage, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle the /delete_my_data command to remove specific user data, dood!

        Deletes a specific piece of user data identified by the provided key.
        Requires a key argument to be provided with the command.

        Args:
            update (Update): The Telegram update object containing the message.
            context (ContextTypes.DEFAULT_TYPE): The callback context from python-telegram-bot.
                context.args[0] should contain the key to delete.

        Returns:
            None

        Note:
            If no key is provided, sends an error message to the user.
            This command is only available in private chats, dood!
        """

        self._updateEMessageUserData(ensuredMessage)

        if not context.args:
            await self.sendMessage(
                ensuredMessage,
                messageText=("Для команды `/delete_my_data` нужно указать ключ, который нужно удалить."),
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        key = context.args[0]
        self.unsetUserData(chatId=ensuredMessage.chat.id, userId=ensuredMessage.user.id, key=key)

        await self.sendMessage(
            ensuredMessage,
            messageText=f"Готово, ключ {key} успешно удален.",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerExtended(
        commands=("clear_my_data",),
        shortDescription="Clear all user data",
        helpMessage=": Очистить все сзнания о Вас в этом чате.",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.GROUP},
        helpOrder=CommandHandlerOrder.TECHNICAL,
        category=CommandCategory.TOOLS,
    )
    async def clear_my_data_command(
        self, ensuredMessage: EnsuredMessage, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle the /clear_my_data command to remove all user data, dood!

        Completely clears all data the bot has stored about the user in the
        current chat. This operation cannot be undone.

        Args:
            update (Update): The Telegram update object containing the message.
            context (ContextTypes.DEFAULT_TYPE): The callback context from python-telegram-bot.

        Returns:
            None

        Note:
            This command is only available in private chats and is categorized as
            a technical command, dood!
        """

        self._updateEMessageUserData(ensuredMessage)
        self.clearUserData(userId=ensuredMessage.user.id, chatId=ensuredMessage.chat.id)

        await self.sendMessage(
            ensuredMessage,
            messageText="Готово, память о Вас очищена.",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerExtended(
        commands=("knowledge_config",),
        shortDescription="Start wisard for user-data manaagement",
        helpMessage=": Запустить мастер управления знаниями бота о вас.",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE},
        helpOrder=CommandHandlerOrder.WIZARDS,
        category=CommandCategory.PRIVATE,
    )
    async def knowledge_config_command(
        self, ensuredMessage: EnsuredMessage, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle the /knowledge_config command to start the configuration wizard, dood!

        Initiates the interactive user data configuration wizard in private chats.
        Allows users to manage their stored data across different chats through
        an inline keyboard interface.

        Args:
            ensuredMessage (EnsuredMessage): The ensured message object containing user and chat info.
            update (Update): The Telegram update object containing the message.
            context (ContextTypes.DEFAULT_TYPE): The callback context from python-telegram-bot.

        Returns:
            None

        Note:
            This command is only available in private chats and starts a wizard
            for managing user knowledge data, dood!
        """

        msg = await self.sendMessage(
            ensuredMessage,
            messageText="Запускаю мастер управления знаниями бота о вас...",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
        if msg is not None:
            await self._handleUserDataConfiguration(
                {
                    ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Init,
                },
                msg.message_id,
                ensuredMessage.user,
                context.bot,
            )
        else:
            logger.error("Failed to send message")
