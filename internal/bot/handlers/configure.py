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
        activeConfigureId = self.cache.getUserState(userId=userId, stateKey=UserActiveActionEnum.Configuration)
        if activeConfigureId is None:
            return HandlerResultStatus.SKIPPED

        await self._handle_chat_configuration(
            data={
                **activeConfigureId["data"],
                ButtonDataKey.Value: messageText,
            },
            message=activeConfigureId["message"],
            user=user,
        )
        return HandlerResultStatus.FINAL

    async def chatConfiguration_Init(
        self, data: Dict[str | int, Any], message: Message, user: User, chatId: Optional[int]
    ) -> None:
        """Draw list on configurable chats"""
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
            chatObj.set_bot(message.get_bot())

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
            await message.edit_text("Вы не являетесь администратором ни в одном чате.")
            return

        keyboard.append([exitButton])
        await message.edit_text(text="Выберите чат для настройки:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def chatConfiguration_ConfigureChat(
        self, data: Dict[str | int, Any], message: Message, user: User, chatId: Optional[int]
    ) -> None:
        if chatId is None:
            logger.error(f"ConfigureChat: chatId is None in {data}")
            await message.edit_text("Ошибка: Чат не выбран")
            return

        if not isinstance(chatId, int):
            logger.error(f"ConfigureChat: wrong chatId: {type(chatId).__name__}#{chatId}")
            await message.edit_text("Ошибка: некорректный идентификатор чата")
            return

        page = ChatSettingsPage(data.get(ButtonDataKey.Page, ChatSettingsPage.STANDART))

        chatInfo = self.getChatInfo(chatId)
        if chatInfo is None:
            logger.error(f"ConfigureChat: chatInfo is None in {chatId}")
            await message.edit_text("Ошибка: Выбран неизвестный чат")
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
            await message.edit_text(text=respMD, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.exception(e)
            await message.edit_text(text=f"Error while editing message: {e}")
            return

    async def chatConfiguration_ConfigureKey(
        self, data: Dict[str | int, Any], message: Message, user: User, chatId: Optional[int]
    ) -> None:
        keyId = data.get(ButtonDataKey.Key, None)

        if chatId is None or keyId is None:
            logger.error(f"ConfigureKey: chatId or key is None in {data}")
            await message.edit_text("Ошибка: Чат или настройка не выбрана.")
            return

        chatInfo = self.getChatInfo(chatId)
        if chatInfo is None:
            logger.error(f"ConfigureKey: chatInfo is None in {chatId}")
            await message.edit_text("Ошибка: Выбран неизвестный чат.")
            return

        chatSettings = self.getChatSettings(chatId)
        defaultChatSettings = self.getChatSettings(None, chatType=ChatType.PRIVATE if chatId > 0 else ChatType.GROUP)

        chatOptions = getChatSettingsInfo()

        try:
            key = ChatSettingsKey.fromId(keyId)
        except ValueError:
            logger.error(f"ConfigureKey: wrong key: {keyId}")
            await message.edit_text("Ошибка: Неизвестная настройка.")
            return

        if key not in chatOptions:
            logger.error(f"ConfigureKey: wrong key: {key}")
            await message.edit_text("Ошибка: Неверная настройка.")
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
                "message": message,
            },
        )

        keyboard: List[List[InlineKeyboardButton]] = []
        wasChanged = chatSettings[key].toStr() != defaultChatSettings[key].toStr()

        resp = (
            f"Настройка параметра **{chatOptions[key]['short']}** (`{key}`) в чате\n"
            f"**{chatInfo['title'] or chatInfo['username']}** ({chatId}):\n\n"
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
            await message.edit_text(text=respMD, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.exception(e)
            await message.edit_text(text=f"Error while editing message: {e}")

    async def chatConfiguration_SetValue(
        self, data: Dict[str | int, Any], message: Message, user: User, chatId: Optional[int]
    ) -> None:
        keyId = data.get(ButtonDataKey.Key, None)
        action = data.get(ButtonDataKey.ConfigureAction, None)

        if chatId is None or keyId is None:
            logger.error(f"[Re]SetValue: chatId or key is None in {data}")
            await message.edit_text("Ошибка: Не выбран чат или настройка")
            return

        chatInfo = self.getChatInfo(chatId)
        if chatInfo is None:
            logger.error(f"[Re]SetValue: chatInfo is None for {chatId}")
            await message.edit_text("Ошибка: Выбран неизвестный чат")
            return

        chatOptions = getChatSettingsInfo()

        try:
            key = ChatSettingsKey.fromId(keyId)
        except ValueError:
            logger.error(f"[Re]SetValue: wrong key: {keyId}")
            await message.edit_text("Ошибка: Выбрана несуществующая настройка")
            return

        if key not in chatOptions:
            logger.error(f"[Re]SetValue: wrong key: {key}")
            await message.edit_text("Ошибка: Ввбрана некорректная настройка")
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
            f"Параметр **{chatOptions[key]['short']}** (`{key}`) в чате "
            f"**{chatInfo['title'] or chatInfo['username']}** ({chatId}) успешно изменён.\n\n"
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
            await message.edit_text(text=respMD, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.exception(e)
            await message.edit_text(text=f"Error while editing message: {e}")
            return

    async def _handle_chat_configuration(self, data: Dict[str | int, Any], message: Message, user: User) -> None:
        """
        Process chat configuration actions and update the interface, dood!

        This is the core configuration handler that processes all configuration actions
        using a match/case statement. It handles navigation, value updates, and UI
        generation for the configuration wizard.

        Args:
            data: Dictionary containing action data with keys:
                - ConfigureAction (ButtonDataKey.ConfigureAction): The action to perform
                - ChatId (ButtonDataKey.ChatId): Target chat ID (optional, action-dependent)
                - Key (ButtonDataKey.Key): Setting key ID (optional, action-dependent)
                - Value (ButtonDataKey.Value): New value (optional, for SetValue action)
            message: Telegram message object to edit with new content
            user: User performing the configuration

        Returns:
            bool: True if action was processed successfully, False on error

        Actions:
            - Init: Display list of chats where user is admin
            - ConfigureChat: Show all settings for selected chat
            - ConfigureKey: Display options for specific setting with current/default values
            - SetTrue/SetFalse: Set boolean setting to True/False
            - ResetValue: Reset setting to default value
            - SetValue: Set setting to custom value from text input
            - Cancel: Exit configuration wizard

        Note:
            This method performs admin permission checks before allowing configuration
            changes. It also clears user state after value updates.
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
            chatObj.set_bot(message.get_bot())

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
                await message.edit_text(text="Вы не можете настраивать выбранный чат")
                return

        match action:
            case ButtonConfigureAction.Init:
                await self.chatConfiguration_Init(data=data, message=message, user=user, chatId=chatId)

            case ButtonConfigureAction.ConfigureChat:
                await self.chatConfiguration_ConfigureChat(data=data, message=message, user=user, chatId=chatId)

            case ButtonConfigureAction.ConfigureKey:
                await self.chatConfiguration_ConfigureKey(data=data, message=message, user=user, chatId=chatId)

            case (
                ButtonConfigureAction.SetTrue
                | ButtonConfigureAction.SetFalse
                | ButtonConfigureAction.ResetValue
                | ButtonConfigureAction.SetValue
            ):
                await self.chatConfiguration_SetValue(data=data, message=message, user=user, chatId=chatId)

            case ButtonConfigureAction.Cancel:
                await message.edit_text(text="Настройка закончена, буду ждать вас снова")
            case _:
                logger.error(f"handle_chat_configuration: unknown action: {data}")
                await message.edit_text(text=f"Unknown action: {action}")
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
                    message=msg,
                    user=ensuredMessage.user,
                )
            else:
                await self._handle_chat_configuration(
                    {ButtonDataKey.ConfigureAction: ButtonConfigureAction.Init}, message=msg, user=ensuredMessage.user
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
        # Used keys:
        # a: Action
        # c: ChatId
        # k: Key
        # v: Value
        if configureAction is not None:
            await self._handle_chat_configuration(data, query.message, user)
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.SKIPPED
