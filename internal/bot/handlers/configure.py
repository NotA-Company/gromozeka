"""
Telegram bot command handlers for Gromozeka.
"""

import asyncio
import datetime
import json
import logging
import re

import random
import time
from typing import Any, Callable, Dict, List, Optional

import requests
import magic

from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Update, Message, User
from telegram.constants import MessageEntityType, MessageLimit
from telegram.ext import ContextTypes

from internal.bot.handlers.base import HandlerResultStatus

from .base import BaseBotHandler
from internal.cache.types import UserActiveActionEnum
from lib.ai.abstract import AbstractModel, LLMAbstractTool
from lib.ai.models import (
    LLMFunctionParameter,
    LLMParameterType,
    LLMToolFunction,
    ModelImageMessage,
    ModelMessage,
    ModelRunResult,
    ModelResultStatus,
)
from lib.ai.manager import LLMManager
from lib.openweathermap.client import OpenWeatherMapClient
from lib.openweathermap.models import CombinedWeatherResult
from lib.markdown import markdown_to_markdownv2
import lib.utils as utils

from internal.config.manager import ConfigManager

from internal.database.wrapper import DatabaseWrapper
from internal.database.openweathermap_cache import DatabaseWeatherCache
from internal.database.models import (
    ChatInfoDict,
    ChatMessageDict,
    MessageCategory,
)

from ..models import (
    ButtonConfigureAction,
    ButtonDataKey,
    ButtonSummarizationAction,
    ChatSettingsKey,
    ChatSettingsValue,
    CommandCategory,
    CommandHandlerOrder,
    DelayedTask,
    DelayedTaskFunction,
    EnsuredMessage,
    LLMMessageFormat,
    MessageType,
    commandHandler,
    getChatSettingsInfo,
)
from .. import constants

logger = logging.getLogger(__name__)


class ConfigureCommandHandler(BaseBotHandler):
    """Contains all bot command and message handlers, dood!"""


    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
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
        
        if not ensuredMessage.messageText:
            logger.error("ensuredMessage.messageText is udefined")
            return HandlerResultStatus.ERROR
        
        
        user = ensuredMessage.user
        userId = user.id
        messageText = ensuredMessage.messageText
        activeConfigureId = self.cache.getUserState(
            userId=userId, stateKey=UserActiveActionEnum.Configuration
        )
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

        # activeSummarizationId = self.cache.getUserState(
        #     userId=userId, stateKey=UserActiveActionEnum.Summarization
        # )
        # if activeSummarizationId is not None:
        #     data = activeSummarizationId.copy()
        #     data.pop("message", None)
        #     # TODO: Make user action enum
        #     userAction = data.pop(ButtonDataKey.UserAction, None)
        #     match userAction:
        #         case 1:
        #             try:
        #                 data[ButtonDataKey.MaxMessages] = int(messageText.strip())
        #             except Exception as e:
        #                 logger.error(f"Not int: {messageText}")
        #                 logger.exception(e)
        #         case 2:
        #             data[ButtonDataKey.Prompt] = messageText
        #         case _:
        #             logger.error(f"Wrong K in data {activeSummarizationId}")
        #     await self._handle_summarization(
        #         data=data,  # pyright: ignore[reportArgumentType]
        #         message=activeSummarizationId["message"],
        #         user=user,
        #     )
        #     return


    async def _handle_chat_configuration(self, data: Dict[str | int, Any], message: Message, user: User) -> bool:
        """Parses the CallbackQuery and updates the message text."""

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
        """Handle /configure command."""

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
        """Parses the CallbackQuery and updates the message text."""

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

        # summaryAction = data.get(ButtonDataKey.SummarizationAction, None)
        # # Used keys:
        # # s: Action
        # # c: ChatId
        # # t: topicId
        # # m: MaxMessages/time
        # if summaryAction is not None:
        #     await self._handle_summarization(data, query.message, user)
        #     return

        return HandlerResultStatus.SKIPPED