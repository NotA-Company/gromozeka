"""
Chat configuration handler for Gromozeka Telegram bot.

This module provides interactive chat configuration functionality through a wizard-style
interface. Users can configure bot behavior for chats where they have admin privileges
using inline keyboard buttons and text input.

The configuration system supports:
- Multi-step navigation through chat selection and settings
- Dynamic keyboard generation based on user permissions
- Type-safe setting updates with validation
- State management for active configuration sessions
"""

import logging
from typing import Any, Dict, List, Optional

import telegram
from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update, User
from telegram.constants import ChatType
from telegram.ext import ContextTypes

import lib.utils as utils
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.services.cache.types import UserActiveActionEnum
from lib.ai.manager import LLMManager
from lib.markdown import markdown_to_markdownv2

from ..models import (
    ButtonConfigureAction,
    ButtonDataKey,
    CallbackDataDict,
    ChatSettingsKey,
    ChatSettingsPage,
    ChatSettingsType,
    ChatSettingsValue,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    getChatSettingsInfo,
)
from .base import BaseBotHandler, HandlerResultStatus, commandHandlerExtended

logger = logging.getLogger(__name__)


class ConfigureCommandHandler(BaseBotHandler):
    """
    Handler for chat configuration commands and interactions, dood!

    This handler manages the complete configuration workflow including:
    - Initiating configuration via /configure command
    - Handling button callbacks for navigation and value updates
    - Processing text input for setting values
    - Managing user state during configuration sessions

    The handler uses a state machine approach with the following actions:
    - Init: Display list of configurable chats
    - ConfigureChat: Show settings for selected chat
    - ConfigureKey: Display options for specific setting
    - SetTrue/SetFalse/ResetValue/SetValue: Update setting values
    - Cancel: Exit configuration wizard
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """
        Initialize the configuration handler with required dependencies, dood!

        Builds a list of selectable AI models that users can choose from during
        configuration. Only models marked with can_be_choosen=True in their metadata
        are included in the selection list.

        Args:
            configManager: Configuration manager instance for accessing bot settings
            database: Database wrapper for data persistence operations
            llmManager: LLM manager for accessing available AI models

        Returns:
            None

        Side Effects:
            - Initializes parent BaseBotHandler
            - Populates self.selectableModels with choosable model names
            - Logs the list of selectable models at debug level
        """
        super().__init__(configManager, database, llmManager)

        selectableModels: List[str] = []

        for modelName in llmManager.listModels():
            modelInfo = llmManager.getModelInfo(modelName)
            if modelInfo and modelInfo.get("extra", {}).get("can_be_choosen", False):
                selectableModels.append(modelName)
        self.selectableModels = selectableModels
        logger.debug(f"Selectable models are: {selectableModels}")

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """
        Handle text messages during active configuration sessions, dood!

        This handler processes user text input when they are in an active configuration
        state (setting a value for a chat setting). It only operates in private chats
        and when the user has an active configuration session stored in cache.

        Args:
            update: Telegram update object containing the message
            context: Telegram context for the handler
            ensuredMessage: Validated message object with user and chat info, or None

        Returns:
            HandlerResultStatus indicating the result:
            - FINAL: Successfully processed configuration input
            - SKIPPED: Not a private chat or no active configuration
            - ERROR: Missing required data (chat, message, or ensured message)

        Note:
            The active configuration state is stored in cache with the key
            UserActiveActionEnum.Configuration and contains chatId, key, and message.
        """

        if ensuredMessage is None:
            # Not new message, Skip
            return HandlerResultStatus.SKIPPED

        if ensuredMessage.chat.type != Chat.PRIVATE:
            return HandlerResultStatus.SKIPPED

        user = ensuredMessage.user
        userId = user.id
        messageText = ensuredMessage.getRawMessageText()
        activeConfigure = self.cache.getUserState(userId=userId, stateKey=UserActiveActionEnum.Configuration)
        if activeConfigure is None:
            return HandlerResultStatus.SKIPPED

        await self._handle_chat_configuration(
            data={
                **activeConfigure["data"],
                ButtonDataKey.Value: messageText,
            },
            messageId=activeConfigure["messageId"],
            user=user,
            bot=context.bot,
        )
        return HandlerResultStatus.FINAL

    async def chatConfiguration_Init(
        self, data: Dict[str | int, Any], messageId: int, user: User, chatId: Optional[int], bot: telegram.Bot
    ) -> None:
        """
        Display the initial list of chats that the user can configure, dood!

        Shows all chats where the user has admin privileges and is allowed to change
        settings. Bot owners can see all chats. Each chat is presented as a button
        that leads to its configuration page.

        Args:
            data: Callback data dictionary (unused in Init action)
            messageId: ID of the message to edit with the chat list
            user: Telegram user who initiated the configuration
            chatId: Must be None for Init action (raises RuntimeError otherwise)
            bot: Telegram bot instance for API calls

        Returns:
            None

        Raises:
            RuntimeError: If chatId is not None (invalid state for Init action)

        Side Effects:
            - Edits the message to show list of configurable chats
            - Creates inline keyboard with chat selection buttons
            - Shows error message if user has no configurable chats
        """
        if chatId is not None:
            raise RuntimeError("Init: chatId should be None in Init action")

        exitButton = InlineKeyboardButton(
            "Закончить настройку",
            callback_data=utils.packDict({ButtonDataKey.ConfigureAction: ButtonConfigureAction.Cancel}),
        )
        userChats = self.db.getUserChats(user.id)
        keyboard: List[List[InlineKeyboardButton]] = []
        isBotOwner = await self.isAdmin(user=user, allowBotOwners=True)

        for chat in userChats:
            chatObj = Chat(
                id=chat["chat_id"],
                type=chat["type"],
                title=chat["title"],
                username=chat["username"],
                is_forum=chat["is_forum"],
            )
            chatObj.set_bot(bot)

            targetChatSettings = self.getChatSettings(chat["chat_id"])
            # Show chat only if:
            # User is Bot Owner (so can do anything)
            # Or chat settings can be changed AND user is Admin in chat
            if isBotOwner or (
                targetChatSettings[ChatSettingsKey.ADMIN_CAN_CHANGE_SETTINGS].toBool()
                and await self.isAdmin(user=user, chat=chatObj)
            ):
                buttonTitle = self.getChatTitle(chat, useMarkdown=False, addChatId=False)

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            buttonTitle,
                            callback_data=utils.packDict(
                                {
                                    ButtonDataKey.ChatId: chat["chat_id"],
                                    ButtonDataKey.ConfigureAction: ButtonConfigureAction.ConfigureChat,
                                }
                            ),
                        )
                    ]
                )

        if not keyboard:
            await bot.edit_message_text(
                "Вы не являетесь администратором ни в одном чате.",
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

    async def chatConfiguration_ConfigureChat(
        self, data: Dict[str | int, Any], messageId: int, user: User, chatId: Optional[int], bot: telegram.Bot
    ) -> None:
        """
        Display configuration settings page for a specific chat, dood!

        Shows all available settings for the selected chat, organized by page
        (STANDART, ADVANCED, etc.). Each setting is displayed with its current
        status and whether it differs from the default value.

        Args:
            data: Callback data dictionary containing chatId and optional page
            messageId: ID of the message to edit with settings
            user: Telegram user performing the configuration
            chatId: ID of the chat being configured (must not be None)
            bot: Telegram bot instance for API calls

        Returns:
            None

        Side Effects:
            - Edits message to show chat settings page
            - Creates inline keyboard with setting buttons
            - Shows navigation buttons for other pages
            - Displays error message if chat is invalid or not found
        """
        if chatId is None:
            logger.error(f"ConfigureChat: chatId is None in {data}")
            await bot.edit_message_text(
                "Ошибка: Чат не выбран",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        if not isinstance(chatId, int):
            logger.error(f"ConfigureChat: wrong chatId: {type(chatId).__name__}#{chatId}")
            await bot.edit_message_text(
                "Ошибка: некорректный идентификатор чата",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        page = ChatSettingsPage(data.get(ButtonDataKey.Page, ChatSettingsPage.STANDART))

        chatInfo = self.getChatInfo(chatId)
        if chatInfo is None:
            logger.error(f"ConfigureChat: chatInfo is None in {chatId}")
            await bot.edit_message_text(
                "Ошибка: Выбран неизвестный чат",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        logger.debug(f"ConfigureChat: chatInfo: {chatInfo}")
        resp = f"Настраиваем чат {self.getChatTitle(chatInfo)}:\n" "\n" f"**{page.getName()}**\n" "\n"
        chatSettings = self.getChatSettings(chatId)
        defaultChatSettings = self.getChatSettings(None, chatType=ChatType(chatInfo["type"]))

        chatOptions = {k: v for k, v in getChatSettingsInfo().items() if v["page"] == page}
        keyboard: List[List[InlineKeyboardButton]] = []

        for key, option in chatOptions.items():
            wasChanged = chatSettings[key].toStr() != defaultChatSettings[key].toStr()
            resp += (
                "\n\n\n"
                f"# **{option['short']}** (`{key}`):\n"
                # f" {option['long']}\n"
                f"Изменено: **{' Да' if wasChanged else 'Нет'}**  Тип: **{option['type']}**\n"
                # f" Текущее значение:\n```\n{chatSettings[key].toStr()}\n```\n"
                # f" Значение по умолчанию:\n```\n{defaultChatSettings[key].toStr()}\n```\n"
            )
            keyTitle = option["short"]
            if wasChanged:
                keyTitle += " (*)"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        keyTitle,
                        callback_data=utils.packDict(
                            {
                                ButtonDataKey.ChatId: chatId,
                                ButtonDataKey.Key: key.getId(),
                                ButtonDataKey.ConfigureAction: "sk",
                            }
                        ),
                    )
                ]
            )

        for pageElem in ChatSettingsPage:
            if pageElem == page:
                continue
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"📂 {pageElem.getName()}",
                        callback_data=utils.packDict(
                            {
                                ButtonDataKey.ConfigureAction: ButtonConfigureAction.ConfigureChat,
                                ButtonDataKey.ChatId: chatId,
                                ButtonDataKey.Page: pageElem.value,
                            }
                        ),
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "<< Назад",
                    callback_data=utils.packDict({ButtonDataKey.ConfigureAction: ButtonConfigureAction.Init}),
                )
            ]
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    "Закончить настройку",
                    callback_data=utils.packDict({ButtonDataKey.ConfigureAction: ButtonConfigureAction.Cancel}),
                )
            ]
        )

        respMD = markdown_to_markdownv2(resp)
        # logger.debug(resp)
        # logger.debug(respMD)
        try:
            await bot.edit_message_text(
                text=respMD,
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard),
                chat_id=user.id,
                message_id=messageId,
            )
        except Exception as e:
            logger.exception(e)
            await bot.edit_message_text(
                text=f"Error while editing message: {e}",
                chat_id=user.id,
                message_id=messageId,
            )
            return

    async def chatConfiguration_ConfigureKey(
        self, data: Dict[str | int, Any], messageId: int, user: User, chatId: Optional[int], bot: telegram.Bot
    ) -> None:
        """
        Display configuration options for a specific setting key, dood!

        Shows detailed information about a single setting including its description,
        type, current value, and default value. Provides appropriate input options
        based on the setting type (buttons for booleans/models, text input for others).

        Args:
            data: Callback data dictionary containing chatId and key
            messageId: ID of the message to edit with setting details
            user: Telegram user configuring the setting
            chatId: ID of the chat being configured (must not be None)
            bot: Telegram bot instance for API calls

        Returns:
            None

        Side Effects:
            - Edits message to show setting configuration interface
            - Creates inline keyboard with value selection buttons
            - Stores active configuration state in cache for text input
            - Shows error message if chat or key is invalid
        """
        keyId = data.get(ButtonDataKey.Key, None)

        if chatId is None or keyId is None:
            logger.error(f"ConfigureKey: chatId or key is None in {data}")
            await bot.edit_message_text(
                "Ошибка: Чат или настройка не выбрана.",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        chatInfo = self.getChatInfo(chatId)
        if chatInfo is None:
            logger.error(f"ConfigureKey: chatInfo is None in {chatId}")
            await bot.edit_message_text(
                "Ошибка: Выбран неизвестный чат.",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        chatSettings = self.getChatSettings(chatId)
        defaultChatSettings = self.getChatSettings(None, chatType=ChatType.PRIVATE if chatId > 0 else ChatType.GROUP)

        chatOptions = getChatSettingsInfo()

        try:
            key = ChatSettingsKey.fromId(keyId)
        except ValueError:
            logger.error(f"ConfigureKey: wrong key: {keyId}")
            await bot.edit_message_text(
                "Ошибка: Неизвестная настройка.",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        if key not in chatOptions:
            logger.error(f"ConfigureKey: wrong key: {key}")
            await bot.edit_message_text(
                "Ошибка: Неверная настройка.",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        self.cache.setUserState(
            userId=user.id,
            stateKey=UserActiveActionEnum.Configuration,
            value={
                "data": {
                    ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetValue,
                    ButtonDataKey.ChatId: chatId,
                    ButtonDataKey.Key: keyId,
                },
                "messageId": messageId,
            },
        )

        keyboard: List[List[InlineKeyboardButton]] = []
        wasChanged = chatSettings[key].toStr() != defaultChatSettings[key].toStr()

        resp = (
            f"Настройка параметра **{chatOptions[key]['short']}** (`{key}`) в чате\n"
            f"{self.getChatTitle(chatInfo)}:\n\n"
            f"Описание: \n{chatOptions[key]['long']}\n\n"
            f"Тип: **{chatOptions[key]['type']}**\n"
            f"Был ли изменён: **{'Да' if wasChanged else 'Нет'}**\n"
            f"Текущее значение:\n```\n{chatSettings[key].toStr()}\n```\n"
            f"Значение по умолчанию:\n```\n{defaultChatSettings[key].toStr()}\n```\n\n"
        )
        if chatOptions[key]["type"] in [ChatSettingsType.MODEL, ChatSettingsType.BOOL]:
            resp += "Нажмите нужную кнопку под сообщением"
        else:
            resp += "Введите новое значение или нажмите нужную кнопку под сообщением"

        if chatOptions[key]["type"] == ChatSettingsType.BOOL:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "Включить (True)",
                        callback_data=utils.packDict(
                            {
                                ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetTrue,
                                ButtonDataKey.ChatId: chatId,
                                ButtonDataKey.Key: keyId,
                            }
                        ),
                    )
                ]
            )
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "Выключить (False)",
                        callback_data=utils.packDict(
                            {
                                ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetFalse,
                                ButtonDataKey.ChatId: chatId,
                                ButtonDataKey.Key: keyId,
                            }
                        ),
                    )
                ]
            )
        elif chatOptions[key]["type"] == ChatSettingsType.MODEL:
            for modelIdx, modelName in enumerate(self.selectableModels):
                buttonText = modelName
                if modelName == chatSettings[key].toStr():
                    buttonText += " (*)"
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            buttonText,
                            callback_data=utils.packDict(
                                {
                                    ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetValue,
                                    ButtonDataKey.ChatId: chatId,
                                    ButtonDataKey.Key: keyId,
                                    ButtonDataKey.Value: modelIdx,
                                }
                            ),
                        )
                    ]
                )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "Сбросить в значение по умолчанию",
                    callback_data=utils.packDict(
                        {
                            ButtonDataKey.ConfigureAction: ButtonConfigureAction.ResetValue,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: keyId,
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
                            ButtonDataKey.ConfigureAction: ButtonConfigureAction.ConfigureChat,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Page: chatOptions[key]["page"],
                        }
                    ),
                )
            ]
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    "Закончить настройку",
                    callback_data=utils.packDict({ButtonDataKey.ConfigureAction: ButtonConfigureAction.Cancel}),
                )
            ]
        )

        respMD = markdown_to_markdownv2(resp)
        # logger.debug(resp)
        # logger.debug(respMD)
        try:
            await bot.edit_message_text(
                text=respMD,
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard),
                chat_id=user.id,
                message_id=messageId,
            )
        except Exception as e:
            logger.exception(e)
            await bot.edit_message_text(
                text=f"Error while editing message: {e}",
                chat_id=user.id,
                message_id=messageId,
            )

    async def chatConfiguration_SetValue(
        self, data: Dict[str | int, Any], messageId: int, user: User, chatId: Optional[int], bot: telegram.Bot
    ) -> None:
        """
        Update a chat setting with a new value, dood!

        Handles all setting update actions including SetTrue, SetFalse, ResetValue,
        and SetValue. Validates the new value based on the setting type and updates
        the database. Shows confirmation message with the new value.

        Args:
            data: Callback data dictionary containing chatId, key, action, and optional value
            messageId: ID of the message to edit with confirmation
            user: Telegram user performing the update
            chatId: ID of the chat being configured (must not be None)
            bot: Telegram bot instance for API calls

        Returns:
            None

        Raises:
            RuntimeError: If action is not a valid setting update action

        Side Effects:
            - Updates chat setting in database
            - Edits message to show success confirmation
            - Validates model index for MODEL type settings
            - Shows error message if chat or key is invalid
        """
        keyId = data.get(ButtonDataKey.Key, None)
        action = data.get(ButtonDataKey.ConfigureAction, None)

        if chatId is None or keyId is None:
            logger.error(f"[Re]SetValue: chatId or key is None in {data}")
            await bot.edit_message_text(
                "Ошибка: Не выбран чат или настройка",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        chatInfo = self.getChatInfo(chatId)
        if chatInfo is None:
            logger.error(f"[Re]SetValue: chatInfo is None for {chatId}")
            await bot.edit_message_text(
                "Ошибка: Выбран неизвестный чат",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        chatOptions = getChatSettingsInfo()

        try:
            key = ChatSettingsKey.fromId(keyId)
        except ValueError:
            logger.error(f"[Re]SetValue: wrong key: {keyId}")
            await bot.edit_message_text(
                "Ошибка: Выбрана несуществующая настройка",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        if key not in chatOptions:
            logger.error(f"[Re]SetValue: wrong key: {key}")
            await bot.edit_message_text(
                "Ошибка: Ввбрана некорректная настройка",
                chat_id=user.id,
                message_id=messageId,
            )
            return

        keyboard: List[List[InlineKeyboardButton]] = []

        resp = ""

        if action == ButtonConfigureAction.SetTrue:
            self.setChatSetting(chatId, key, ChatSettingsValue(True))
        elif action == ButtonConfigureAction.SetFalse:
            self.setChatSetting(chatId, key, ChatSettingsValue(False))
        elif action == ButtonConfigureAction.ResetValue:
            self.unsetChatSetting(chatId, key)
        elif action == ButtonConfigureAction.SetValue:
            value = data.get(ButtonDataKey.Value, None)
            chatSettings = self.getChatSettings(chatId)
            currentValue = chatSettings[key].toStr()
            if chatOptions[key]["type"] == ChatSettingsType.MODEL:
                # Validate And get ModelName bu index from selectable models list
                if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
                    value = int(value)
                    if value < 0 or value > len(self.selectableModels) - 1:
                        value = currentValue
                    else:
                        value = self.selectableModels[value]
                else:
                    value = currentValue
            # TODO: Validate other ChatSettingsType as well

            self.setChatSetting(chatId, key, ChatSettingsValue(value))
        else:
            logger.error(f"[Re]SetValue: wrong action: {action}")
            raise RuntimeError(f"[Re]SetValue: wrong action: {action}")

        chatSettings = self.getChatSettings(chatId)

        resp = (
            f"Параметр **{chatOptions[key]['short']}** (`{key}`) в чате\n"
            f"{self.getChatTitle(chatInfo)}\n"
            "успешно изменён.\n\n"
            f"Новое значение:\n```\n{chatSettings[key].toStr()}\n```\n"
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "<< К настройкам чата",
                    callback_data=utils.packDict(
                        {
                            ButtonDataKey.ConfigureAction: ButtonConfigureAction.ConfigureChat,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Page: chatOptions[key]["page"],
                        }
                    ),
                )
            ]
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    "Закончить настройку",
                    callback_data=utils.packDict({ButtonDataKey.ConfigureAction: ButtonConfigureAction.Cancel}),
                )
            ]
        )

        respMD = markdown_to_markdownv2(resp)
        # logger.debug(resp)
        # logger.debug(respMD)
        try:
            await bot.edit_message_text(
                text=respMD,
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard),
                chat_id=user.id,
                message_id=messageId,
            )
        except Exception as e:
            logger.exception(e)
            await bot.edit_message_text(
                text=f"Error while editing message: {e}",
                chat_id=user.id,
                message_id=messageId,
            )
            return

    async def _handle_chat_configuration(
        self, data: Dict[str | int, Any], messageId: int, user: User, bot: telegram.Bot
    ) -> None:
        """
        Route configuration actions to appropriate handlers with permission checks, dood!

        Central dispatcher for all configuration actions. Validates user permissions
        before delegating to specific action handlers (Init, ConfigureChat, ConfigureKey,
        SetValue, Cancel). Ensures users can only configure chats where they have
        admin privileges.

        Args:
            data: Callback data dictionary containing action and parameters
            messageId: ID of the message to edit
            user: Telegram user performing the action
            bot: Telegram bot instance for API calls

        Returns:
            None

        Side Effects:
            - Clears active configuration state from cache
            - Validates user permissions for chat configuration
            - Delegates to specific action handler based on action type
            - Shows error message if user lacks permissions or action is unknown
        """

        userId = user.id
        self.cache.clearUserState(userId=userId, stateKey=UserActiveActionEnum.Configuration)

        action = data.get(ButtonDataKey.ConfigureAction, None)

        isBotOwner = await self.isAdmin(user=user, allowBotOwners=True)
        chatId = data.get(ButtonDataKey.ChatId, None)
        if chatId is not None:
            # User configuring some chat, check permissions
            chatObj = Chat(
                id=chatId,
                type=Chat.PRIVATE if chatId > 0 else Chat.GROUP,
            )
            chatObj.set_bot(bot)

            targetChatSettings = self.getChatSettings(chatId)
            # Allow to configure only if:
            # User is Bot Owner (so can do anything)
            # Or chat settings can be changed AND user is Admin in chat
            canChangeSettings = isBotOwner or (
                targetChatSettings[ChatSettingsKey.ADMIN_CAN_CHANGE_SETTINGS].toBool()
                and await self.isAdmin(user=user, chat=chatObj)
            )
            if not canChangeSettings:
                logger.error(f"handle_chat_configuration: user#{user.id} is not allowed to configure {chatId}")
                await bot.edit_message_text(
                    text="Вы не можете настраивать выбранный чат",
                    chat_id=user.id,
                    message_id=messageId,
                )
                return

        match action:
            case ButtonConfigureAction.Init:
                await self.chatConfiguration_Init(data=data, messageId=messageId, user=user, chatId=chatId, bot=bot)

            case ButtonConfigureAction.ConfigureChat:
                await self.chatConfiguration_ConfigureChat(
                    data=data, messageId=messageId, user=user, chatId=chatId, bot=bot
                )

            case ButtonConfigureAction.ConfigureKey:
                await self.chatConfiguration_ConfigureKey(
                    data=data, messageId=messageId, user=user, chatId=chatId, bot=bot
                )

            case (
                ButtonConfigureAction.SetTrue
                | ButtonConfigureAction.SetFalse
                | ButtonConfigureAction.ResetValue
                | ButtonConfigureAction.SetValue
            ):
                await self.chatConfiguration_SetValue(data=data, messageId=messageId, user=user, chatId=chatId, bot=bot)

            case ButtonConfigureAction.Cancel:
                await bot.edit_message_text(
                    text="Настройка закончена, буду ждать вас снова",
                    chat_id=user.id,
                    message_id=messageId,
                )
            case _:
                logger.error(f"handle_chat_configuration: unknown action: {data}")
                await bot.edit_message_text(
                    text=f"Unknown action: {action}",
                    chat_id=user.id,
                    message_id=messageId,
                )
                return

        return

    @commandHandlerExtended(
        commands=("configure",),
        shortDescription="[<chatId>] - Start chat configuration wizard",
        helpMessage="[`<chatId>`]: Настроить поведение бота в одном из чатов, где вы админ",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE},
        helpOrder=CommandHandlerOrder.WIZARDS,
        category=CommandCategory.PRIVATE,
    )
    async def configure_command(
        self, ensuredMessage: EnsuredMessage, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle the /configure command to start configuration wizard, dood!

        This command initiates the chat configuration process by displaying a loading
        message and then calling the configuration handler with the Init action.
        The command is only available in private chats.

        Args:
            update: Telegram update object containing the command message
            context: Telegram context for the handler

        Returns:
            None

        Side Effects:
            - Saves the command message to database
            - Sends a loading message to user
            - Initiates configuration wizard with chat selection

        Note:
            The command is decorated with @commandHandler which restricts it to
            private chats (CommandCategory.PRIVATE) and sets its help text.
        """

        msg = await self.sendMessage(
            ensuredMessage,
            messageText="Загружаю настройки....",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

        if msg is not None:
            targetChatId = utils.extractInt(context.args)
            if targetChatId is not None:
                await self._handle_chat_configuration(
                    {
                        ButtonDataKey.ConfigureAction: ButtonConfigureAction.ConfigureChat,
                        ButtonDataKey.ChatId: targetChatId,
                    },
                    messageId=msg.id,
                    user=ensuredMessage.user,
                    bot=context.bot,
                )
            else:
                await self._handle_chat_configuration(
                    {ButtonDataKey.ConfigureAction: ButtonConfigureAction.Init},
                    messageId=msg.id,
                    user=ensuredMessage.user,
                    bot=context.bot,
                )
        else:
            logger.error("Message undefined")
            return

    async def buttonHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: CallbackDataDict
    ) -> HandlerResultStatus:
        """
        Handle inline keyboard button callbacks for configuration, dood!

        This handler processes button presses from the configuration wizard's inline
        keyboards. It extracts the callback data, validates the query, and delegates
        to _handle_chat_configuration for actual processing.

        Args:
            update: Telegram update object containing the callback query
            context: Telegram context for the handler
            data: Unpacked callback data dictionary containing action and parameters

        Returns:
            HandlerResultStatus indicating the result:
            - FINAL: Successfully processed configuration button
            - SKIPPED: Button is not a configuration action
            - FATAL: Missing or invalid query/message data

        Note:
            The handler checks for the presence of ButtonDataKey.ConfigureAction in
            the data dictionary to determine if this is a configuration button.
        """

        query = update.callback_query
        if query is None:
            logger.error("handle_button: query is None")
            return HandlerResultStatus.FATAL

        user = query.from_user

        if query.message is None:
            logger.error(f"handle_button: message is None in {query}")
            return HandlerResultStatus.FATAL

        if not isinstance(query.message, Message):
            logger.error(f"handle_button: message is not a Message in {query}")
            return HandlerResultStatus.FATAL

        configureAction = data.get(ButtonDataKey.ConfigureAction, None)

        if configureAction is not None:
            await self._handle_chat_configuration(data, query.message.id, user, context.bot)
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.SKIPPED
