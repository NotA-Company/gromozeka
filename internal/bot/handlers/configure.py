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

from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Update, Message, User
from telegram.ext import ContextTypes

from internal.bot.handlers.base import HandlerResultStatus

from .base import BaseBotHandler
from internal.services.cache.types import UserActiveActionEnum

from lib.markdown import markdown_to_markdownv2
import lib.utils as utils

from internal.database.models import MessageCategory

from ..models import (
    ButtonConfigureAction,
    ButtonDataKey,
    ChatSettingsKey,
    ChatSettingsValue,
    CommandCategory,
    CommandHandlerOrder,
    EnsuredMessage,
    commandHandler,
    getChatSettingsInfo,
)
from .. import constants

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
        chat = update.effective_chat
        if not chat:
            logger.error("Chat undefined")
            return HandlerResultStatus.ERROR
        chatType = chat.type

        if chatType != Chat.PRIVATE:
            return HandlerResultStatus.SKIPPED

        if ensuredMessage is None:
            logger.error("Ensured message undefined")
            return HandlerResultStatus.ERROR

        message = update.message
        if not message or not message.text:
            logger.error("message.text is udefined")
            return HandlerResultStatus.ERROR

        user = ensuredMessage.user
        userId = user.id
        messageText = message.text
        activeConfigureId = self.cache.getUserState(userId=userId, stateKey=UserActiveActionEnum.Configuration)
        if activeConfigureId is None:
            return HandlerResultStatus.SKIPPED

        await self._handle_chat_configuration(
            data={
                ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetValue,
                ButtonDataKey.ChatId: activeConfigureId["chatId"],
                ButtonDataKey.Key: ChatSettingsKey(activeConfigureId["key"]).getId(),
                ButtonDataKey.Value: messageText,
            },
            message=activeConfigureId["message"],
            user=user,
        )
        return HandlerResultStatus.FINAL

    async def _handle_chat_configuration(self, data: Dict[str | int, Any], message: Message, user: User) -> bool:
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

        # Used keys:
        # a: Action
        # c: ChatId
        # k: Key
        # v: Value

        exitButton = InlineKeyboardButton(
            "Закончить настройку",
            callback_data=utils.packDict({ButtonDataKey.ConfigureAction: ButtonConfigureAction.Cancel}),
        )
        action = data.get(ButtonDataKey.ConfigureAction, None)
        # if "k" in data:
        #    action = "set_key"
        match action:
            case ButtonConfigureAction.Init:
                userChats = self.db.getUserChats(user.id)
                keyboard: List[List[InlineKeyboardButton]] = []
                # chatSettings = self.getChatSettings(ensuredMessage.chat.id)

                for chat in userChats:
                    chatObj = Chat(
                        id=chat["chat_id"],
                        type=chat["type"],
                        title=chat["title"],
                        username=chat["username"],
                        is_forum=chat["is_forum"],
                    )
                    chatObj.set_bot(message.get_bot())

                    if await self.isAdmin(user=user, chat=chatObj, allowBotOwners=True):
                        buttonTitle: str = f"#{chat['chat_id']}"
                        if chat["title"]:
                            buttonTitle = f"{constants.CHAT_ICON} {chat['title']} ({chat["type"]})"
                        elif chat["username"]:
                            buttonTitle = f"{constants.PRIVATE_ICON} {chat['username']} ({chat["type"]})"

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
                    return False

                keyboard.append([exitButton])
                await message.edit_text(text="Выберите чат для настройки:", reply_markup=InlineKeyboardMarkup(keyboard))
            case ButtonConfigureAction.ConfigureChat:
                chatId = data.get(ButtonDataKey.ChatId, None)
                if chatId is None:
                    logger.error(f"handle_chat_configuration: chatId is None in {data}")
                    return False

                if not isinstance(chatId, int):
                    logger.error(f"handle_chat_configuration: wrong chatId: {type(chatId).__name__}#{chatId}")
                    return False

                chatObj = Chat(id=chatId, type=Chat.PRIVATE if chatId == user.id else Chat.GROUP)
                chatObj.set_bot(message.get_bot())

                if not await self.isAdmin(user=user, chat=chatObj):
                    logger.error(f"handle_chat_configuration: user#{user.id} is not admin in {chatId}")
                    await message.edit_text(text="Вы не являетесь администратором в выбранном чате")
                    return False

                chatInfo = self.getChatInfo(chatId)
                if chatInfo is None:
                    logger.error(f"handle_chat_configuration: chatInfo is None in {chatId}")
                    return False

                logger.debug(f"handle_chat_configuration: chatInfo: {chatInfo}")
                resp = f"Настраиваем чат **{chatInfo['title'] or chatInfo['username']}#{chatId}**:\n"
                chatSettings = self.getChatSettings(chatId)
                defaultChatSettings = self.getChatSettings(None)

                chatOptions = getChatSettingsInfo()
                keyboard: List[List[InlineKeyboardButton]] = []

                for key, option in chatOptions.items():
                    wasChanged = chatSettings[key].toStr() != defaultChatSettings[key].toStr()
                    resp += (
                        "\n\n\n"
                        f"## **{option['short']}** (`{key}`):\n"
                        # f" {option['long']}\n"
                        f" Тип: **{option['type']}**\n"
                        f" Изменено: **{'Да' if wasChanged else 'Нет'}**\n"
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

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "<< Назад",
                            callback_data=utils.packDict({ButtonDataKey.ConfigureAction: ButtonConfigureAction.Init}),
                        )
                    ]
                )
                keyboard.append([exitButton])

                respMD = markdown_to_markdownv2(resp)
                # logger.debug(resp)
                # logger.debug(respMD)
                try:
                    await message.edit_text(
                        text=respMD, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    logger.exception(e)
                    await message.edit_text(text=f"Error while editing message: {e}")
                    return False

            case ButtonConfigureAction.ConfigureKey:
                chatId = data.get(ButtonDataKey.ChatId, None)
                _key = data.get(ButtonDataKey.Key, None)

                if chatId is None or _key is None:
                    logger.error(f"handle_chat_configuration: chatId or key is None in {data}")
                    return False

                chatInfo = self.getChatInfo(chatId)
                if chatInfo is None:
                    logger.error(f"handle_chat_configuration: chatInfo is None in {chatId}")
                    return False

                chatSettings = self.getChatSettings(chatId)
                defaultChatSettings = self.getChatSettings(None)

                chatOptions = getChatSettingsInfo()

                try:
                    key = ChatSettingsKey.fromId(_key)
                except ValueError:
                    logger.error(f"handle_chat_configuration: wrong key: {_key}")
                    return False

                if key not in chatOptions:
                    logger.error(f"handle_chat_configuration: wrong key: {key}")
                    await message.edit_text(text=f"Unknown key: {key}")
                    return False

                chatObj = Chat(id=chatId, type=Chat.PRIVATE if chatId == user.id else Chat.GROUP)
                chatObj.set_bot(message.get_bot())
                if not await self.isAdmin(user=user, chat=chatObj):
                    logger.error(f"handle_chat_configuration: user#{user.id} is not admin in {chatId} ({data})")
                    await message.edit_text(text="Вы не являетесь администратором в выбранном чате")
                    return False

                userId = user.id
                self.cache.setUserState(
                    userId=userId,
                    stateKey=UserActiveActionEnum.Configuration,
                    value={
                        "chatId": chatId,
                        "key": key,
                        "message": message,
                    },
                )

                keyboard: List[List[InlineKeyboardButton]] = []
                wasChanged = chatSettings[key].toStr() != defaultChatSettings[key].toStr()

                resp = (
                    f"Настройка ключа **{chatOptions[key]['short']}** (`{key}`) в чате "
                    f"**{chatInfo['title'] or chatInfo['username']}** ({chatId}):\n\n"
                    f"Описание: \n{chatOptions[key]['long']}\n\n"
                    f"Тип: **{chatOptions[key]['type']}**\n"
                    f"Был ли изменён: **{'Да' if wasChanged else 'Нет'}**\n"
                    f"Текущее значение:\n```\n{chatSettings[key].toStr()}\n```\n"
                    f"Значение по умолчанию:\n```\n{defaultChatSettings[key].toStr()}\n```\n\n"
                    "Введите новое значение или нажмите нужную кнопку под сообщением"
                )

                if chatOptions[key]["type"] == "bool":
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                "Включить (True)",
                                callback_data=utils.packDict(
                                    {
                                        ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetTrue,
                                        ButtonDataKey.ChatId: chatId,
                                        ButtonDataKey.Key: _key,
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
                                        ButtonDataKey.Key: _key,
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
                                    ButtonDataKey.Key: _key,
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
                                }
                            ),
                        )
                    ]
                )
                keyboard.append([exitButton])

                respMD = markdown_to_markdownv2(resp)
                # logger.debug(resp)
                # logger.debug(respMD)
                try:
                    await message.edit_text(
                        text=respMD, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    logger.exception(e)
                    await message.edit_text(text=f"Error while editing message: {e}")
                    return False

            case (
                ButtonConfigureAction.SetTrue
                | ButtonConfigureAction.SetFalse
                | ButtonConfigureAction.ResetValue
                | ButtonConfigureAction.SetValue
            ):
                chatId = data.get(ButtonDataKey.ChatId, None)
                _key = data.get(ButtonDataKey.Key, None)

                userId = user.id
                self.cache.clearUserState(userId=userId, stateKey=UserActiveActionEnum.Configuration)

                if chatId is None or _key is None:
                    logger.error(f"handle_chat_configuration: chatId or key is None in {data}")
                    return False

                chatInfo = self.getChatInfo(chatId)
                if chatInfo is None:
                    logger.error(f"handle_chat_configuration: chatInfo is None for {chatId}")
                    return False
                chatOptions = getChatSettingsInfo()

                try:
                    key = ChatSettingsKey.fromId(_key)
                except ValueError:
                    logger.error(f"handle_chat_configuration: wrong key: {_key}")
                    return False

                if key not in chatOptions:
                    logger.error(f"handle_chat_configuration: wrong key: {key}")
                    await message.edit_text(text=f"Unknown key: {key}")
                    return False

                chatObj = Chat(id=chatId, type=Chat.PRIVATE if chatId == user.id else Chat.GROUP)
                chatObj.set_bot(message.get_bot())
                if not await self.isAdmin(user=user, chat=chatObj):
                    logger.error(f"handle_chat_configuration: user#{user.id} is not admin in {chatId} ({data})")
                    await message.edit_text(text="Вы не являетесь администратором в выбранном чате")
                    return False

                keyboard: List[List[InlineKeyboardButton]] = []

                resp = ""

                if action == ButtonConfigureAction.SetTrue:
                    self.setChatSetting(chatId, key, ChatSettingsValue(True))
                elif action == "s-":
                    self.setChatSetting(chatId, key, ChatSettingsValue(False))
                elif action == "s#":
                    self.unsetChatSetting(chatId, key)
                elif action == "sv":
                    self.setChatSetting(chatId, key, ChatSettingsValue(data.get(ButtonDataKey.Value, None)))
                else:
                    logger.error(f"handle_chat_configuration: wrong action: {action}")
                    raise RuntimeError(f"handle_chat_configuration: wrong action: {action}")

                chatSettings = self.getChatSettings(chatId)

                resp = (
                    f"Ключ **{chatOptions[key]['short']}** (`{key}`) в чате "
                    f"**{chatInfo['title'] or chatInfo['username']}** ({chatId}) успешно изменён:\n\n"
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
                                }
                            ),
                        )
                    ]
                )
                keyboard.append([exitButton])

                respMD = markdown_to_markdownv2(resp)
                # logger.debug(resp)
                # logger.debug(respMD)
                try:
                    await message.edit_text(
                        text=respMD, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    logger.exception(e)
                    await message.edit_text(text=f"Error while editing message: {e}")
                    return False

            case ButtonConfigureAction.Cancel:
                await message.edit_text(text="Настройка закончена, буду ждать вас снова")
            case _:
                logger.error(f"handle_chat_configuration: unknown action: {data}")
                await message.edit_text(text=f"Unknown action: {action}")
                return False

        return True

    @commandHandler(
        commands=("configure",),
        shortDescription="Start chat configuration wizard",
        helpMessage=": Настроить поведение бота в одном из чатов, где вы админ",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.NORMAL,
    )
    async def configure_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        self.saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)

        msg = await self.sendMessage(
            ensuredMessage,
            messageText="Загружаю настройки....",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

        # TODO: Add support for /configure <chatId>
        if msg is not None:
            await self._handle_chat_configuration(
                {ButtonDataKey.ConfigureAction: ButtonConfigureAction.Init}, message=msg, user=ensuredMessage.user
            )
        else:
            logger.error("Message undefined")
            return

    async def buttonHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: Dict[str | int, str | int | float | bool | None]
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
