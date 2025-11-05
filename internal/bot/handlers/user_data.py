"""
User data management handlers for Gromozeka bot, dood!

Provides handlers for user-specific data storage: viewing, deleting, clearing data,
and LLM tool integration for AI-assisted data management. All data is scoped to
specific chat and user combinations, dood!
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
from internal.services.cache import UserActiveActionEnum
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
from .base import BaseBotHandler, HandlerResultStatus, TypingManager, commandHandlerExtended

logger = logging.getLogger(__name__)


class UserDataHandler(BaseBotHandler):
    """
    Handler for user data management with LLM tool integration, dood!

    Attributes:
        llmService (LLMService): Service for LLM tool registration and management.
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """
        Initialize handler and register 'add_user_data' LLM tool, dood!

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
                "Remember some data/knowledge about user who, sent last message. "
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
            ],
            handler=self._llmToolSetUserData,
        )

    ###
    # LLM Tool-Calling handlers
    ###

    async def _llmToolSetUserData(self, extraData: Optional[Dict[str, Any]], key: str, data: str, **kwargs) -> str:
        """
        LLM tool handler for storing user data, dood!

        Args:
            extraData (Optional[Dict[str, Any]]): Context with ensuredMessage object.
            key (str): Storage key.
            data (str): Data to store.
            **kwargs: Additional arguments (ignored).

        Returns:
            str: JSON with operation status, key, and data value.

        Raises:
            RuntimeError: If extraData invalid or missing ensuredMessage, dood!
        """
        if extraData is None:
            raise RuntimeError("extraData should be provided")
        if "ensuredMessage" not in extraData:
            raise RuntimeError("extraData['ensuredMessage'] should be provided")
        ensuredMessage = extraData["ensuredMessage"]
        if not isinstance(ensuredMessage, EnsuredMessage):
            raise RuntimeError("ensuredMessage should be instance of EnsuredMessage")

        self.cache.setChatUserData(chatId=ensuredMessage.chat.id, userId=ensuredMessage.user.id, key=key, value=data)

        return utils.jsonDumps({"done": True, "key": key, "data": data})

    ###
    # Handling user-data configuration wizard
    ###

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """
        Handle messages for user data configuration wizard in private chats, dood!

        Args:
            update (Update): Telegram update object.
            context (ContextTypes.DEFAULT_TYPE): Callback context.
            ensuredMessage (Optional[EnsuredMessage]): Ensured message or None.

        Returns:
            HandlerResultStatus: FINAL if handled, SKIPPED otherwise.
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
        Initialize wizard with chat selection interface, dood!

        Args:
            data (CallbackDataDict): Callback data from button press.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
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
        Display user data for selected chat with edit options, dood!

        Args:
            data (CallbackDataDict): Callback data with chat ID.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
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
        Clear all user data for selected chat, dood!

        Args:
            data (CallbackDataDict): Callback data with chat ID.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
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
        Delete specific user data key from selected chat, dood!

        Args:
            data (CallbackDataDict): Callback data with chat ID and key.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
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
        Prompt user to enter value for key (new or existing), dood!

        Args:
            data (CallbackDataDict): Callback data with chat ID and optional key.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
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
                    "Удалить выбраный ключ",
                    callback_data=utils.packDict(
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.DeleteKey,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: key,
                        }
                    ),
                )
            ],
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
        Set or update user data value, extracting key from message if needed, dood!

        Args:
            data (CallbackDataDict): Callback data with chat ID, optional key, and value.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
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
        Route configuration actions to appropriate handlers, dood!

        Args:
            data (CallbackDataDict): Callback data with action and parameters.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
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

        Args:
            update (Update): Telegram update with callback query.
            context (ContextTypes.DEFAULT_TYPE): Callback context.
            data (CallbackDataDict): Parsed callback data.

        Returns:
            HandlerResultStatus: FINAL if handled, SKIPPED if not, FATAL if data missing.
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
        shortDescription="<chatId> - Dump data, bot knows about you in this chat",
        helpMessage=" [`<chatId>`]: Показать запомненную информацию о Вас в указанном (или текущем) чате.",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.GROUP},
        helpOrder=CommandHandlerOrder.TECHNICAL,
        category=CommandCategory.TOOLS,
    )
    async def get_my_data_command(
        self,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Display stored user data as JSON, dood!

        Args:
            ensuredMessage (EnsuredMessage): Ensured message object.
            update (Update): Telegram update object.
            context (ContextTypes.DEFAULT_TYPE): Callback context.
        """

        targetChatId = utils.extractInt(context.args)
        if targetChatId is None:
            targetChatId = ensuredMessage.chat.id

        userData = self.cache.getChatUserData(chatId=targetChatId, userId=ensuredMessage.user.id)

        await self.sendMessage(
            ensuredMessage,
            messageText=(f"```json\n{utils.jsonDumps(userData, indent=2)}\n```"),
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
        self,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Start interactive user data configuration wizard (private chats only), dood!

        Args:
            ensuredMessage (EnsuredMessage): Ensured message object.
            update (Update): Telegram update object.
            context (ContextTypes.DEFAULT_TYPE): Callback context.
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
