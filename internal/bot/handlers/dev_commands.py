"""Development and debugging command handlers for the Telegram bot, dood!

This module contains command handlers specifically designed for development,
debugging, and administrative purposes. These commands are typically restricted
to bot owners and are used for testing bot functionality, inspecting system
state, and managing chat settings.

The module provides handlers for:
- Echo command for testing bot responsiveness
- Model listing for LLM configuration inspection
- Chat settings management (view, set, unset)
- Various test suites for debugging and development

All commands in this module require elevated permissions and are not available
to regular users, dood!
"""

import asyncio
import logging
import time
from typing import Optional

from telegram import Update
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes

import lib.utils as utils
from internal.database.models import MessageCategory

from ..models import (
    ChatSettingsKey,
    ChatSettingsValue,
    CommandCategory,
    CommandHandlerOrder,
    EnsuredMessage,
    commandHandler,
)
from .base import BaseBotHandler

logger = logging.getLogger(__name__)


class DevCommandsHandler(BaseBotHandler):
    """Development and administrative command handlers for bot maintenance, dood!

    This class provides command handlers for development, debugging, and
    administrative tasks. All commands are restricted to bot owners and
    provide functionality for:

    - Testing bot responsiveness and message handling
    - Inspecting available LLM models and their configurations
    - Managing chat-specific settings
    - Running diagnostic test suites
    - Debugging message entities and system state

    Inherits from BaseBotHandler to access core bot functionality including
    message sending, database operations, and permission checking, dood!
    """

    ###
    # COMMANDS Handlers
    ###

    @commandHandler(
        commands=("echo",),
        shortDescription="<Message> - Echo message back",
        helpMessage=" `<message>`: Просто ответить переданным сообщением (для тестирования живости бота).",
        categories={CommandCategory.PRIVATE, CommandCategory.HIDDEN},
        order=CommandHandlerOrder.SECOND,
    )
    async def echo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /echo command for testing bot responsiveness, dood!

        This command echoes back the provided message text, serving as a simple
        test to verify the bot is alive and responding correctly. It's useful
        for debugging message handling and testing bot availability.

        Args:
            update: Telegram update object containing the message
            context: Bot context with command arguments

        Command Usage:
            /echo <message> - Echoes back the provided message

        Returns:
            None

        Note:
            - Requires message to be present in update
            - Saves command to database with USER_COMMAND category
            - Sends error if no message text is provided, dood!
        """
        if not update.message:
            logger.error("Message undefined")
            return
        ensuredMessage = EnsuredMessage.fromMessage(update.message)

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        if context.args:
            echo_text = " ".join(context.args)
            await self.sendMessage(
                ensuredMessage,
                messageText=f"🔄 Echo: {echo_text}",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        else:
            await self.sendMessage(
                ensuredMessage,
                messageText="Please provide a message to echo!\nUsage: /echo <your message>",
                messageCategory=MessageCategory.BOT_ERROR,
            )

    @commandHandler(
        commands=("models",),
        shortDescription="Get list of known LLM models",
        helpMessage=": Вывести список всех известных моделей и их параметров.",
        categories={CommandCategory.BOT_OWNER},
    )
    async def models_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /models command to list all available LLM models, dood!

        Retrieves and displays information about all LLM models known to the bot,
        including their configurations, capabilities, and provider details. This
        is useful for understanding which models are available and their specific
        parameters.

        Args:
            update: Telegram update object containing the message
            context: Bot context (args not used for this command)

        Command Usage:
            /models - Lists all available models with their details

        Returns:
            None

        Model Information Displayed:
            - Model ID and version
            - Temperature setting
            - Context size
            - Provider name
            - Tool support capability
            - Text generation support
            - Image generation support

        Note:
            - Restricted to bot owners only
            - Sends models in batches of 4 to avoid message size limits
            - Uses 0.5 second delay between batches, dood!
        """
        modelsPerMessage = 4
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

        if not await self.isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/models` by not owner {ensuredMessage.user}")
            return

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        replyText = "**Доступные модели:**\n\n"

        for i, modelName in enumerate(self.llmManager.listModels()):
            modelData = self.llmManager.getModelInfo(modelName)
            if modelData is None:
                modelData = {}
            modelKeyI18n = {
                "model_id": "ID Модели",
                "model_version": "Версия",
                "temperature": "Температура",
                "context_size": "Размер контекста",
                "provider": "Провайдер",
                "support_tools": "Поддерживает вызов инструментов?",
                "support_text": "Поддерживает генерацию текста?",
                "support_images": "Поддерживает генерацию изображений?",
            }
            replyText += f"**Модель: {modelName}**\n```{modelName}\n"
            for k, v in modelData.items():
                replyText += f"{modelKeyI18n.get(k, k)}: {v}\n"

            replyText += "```\n\n"

            if i % modelsPerMessage == (modelsPerMessage - 1):
                await self.sendMessage(
                    ensuredMessage,
                    messageText=replyText,
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )
                replyText = ""
                time.sleep(0.5)

        if replyText:
            await self.sendMessage(
                ensuredMessage,
                messageText=replyText,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )

    @commandHandler(
        commands=("settings",),
        shortDescription="Dump all settings for this chat",
        helpMessage=": Вывести список настроек для данного чата",
        categories={CommandCategory.BOT_OWNER},
    )
    async def chat_settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /settings command to display current chat configuration, dood!

        Dumps all settings for the current chat, showing both keys and values.
        This is useful for debugging chat-specific configurations and verifying
        that settings are applied correctly.

        Args:
            update: Telegram update object containing the message
            context: Bot context with optional 'debug' argument

        Command Usage:
            /settings - Shows all chat settings
            /settings debug - Shows settings with additional debug logging

        Returns:
            None

        Note:
            - Restricted to bot owners only
            - Debug mode logs settings to console for troubleshooting
            - Displays settings in formatted code blocks for readability, dood!
        """
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        moreDebug = True if context.args and context.args[0].lower() == "debug" else False

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        if not await self.isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/settings` by not owner {ensuredMessage.user}")
            return

        self.saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)

        # user = ensuredMessage.user
        chat = ensuredMessage.chat

        resp = f"Настройки чата **#{chat.id}**:\n\n"
        chatSettings = self.getChatSettings(chat.id)
        for k, v in chatSettings.items():
            resp += f"`{k}`:```{k}\n{v}\n```\n"

        if moreDebug:
            logger.debug(resp)
            logger.debug(repr(resp))

        await self.sendMessage(
            ensuredMessage,
            messageText=resp,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandler(
        commands=("set", "unset"),
        shortDescription="<key> <value> - Set/Unset given setting for current chat",
        helpMessage=" `<key>` `<value>`: установить/сбросить настройку чата",
        categories={CommandCategory.BOT_OWNER},
    )
    async def set_or_unset_chat_setting_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /set and /unset commands for managing chat settings, dood!

        Allows bot owners to modify or reset chat-specific settings. The /set
        command assigns a new value to a setting key, while /unset resets it
        to the default value.

        Args:
            update: Telegram update object containing the message
            context: Bot context with command arguments

        Command Usage:
            /set <key> <value> - Sets the specified key to the given value
            /unset <key> - Resets the specified key to its default value

        Returns:
            None

        Validation:
            - Key must be a valid ChatSettingsKey enum value
            - /set requires both key and value arguments
            - /unset requires only the key argument

        Note:
            - Restricted to bot owners only
            - Changes are persisted to the database immediately
            - Invalid keys result in an error message, dood!
        """
        logger.debug(f"Got set or unset command: {update}")

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

        if not await self.isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/[un]set` by not owner {ensuredMessage.user}")
            return

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        commandStr = ""
        for entity in message.entities:
            if entity.type == MessageEntityType.BOT_COMMAND:
                commandStr = ensuredMessage.messageText[entity.offset : entity.offset + entity.length]
                break

        logger.debug(f"Command string: {commandStr}")
        isSet = commandStr.lower().startswith("/set")

        chat = ensuredMessage.chat

        # user = ensuredMessage.user
        # chatSettings = self.getChatSettings(chat.id)
        # adminAllowedChangeSettings = chatSettings[ChatSettingsKey.ADMIN_CAN_CHANGE_SETTINGS].toBool()
        # isAdmin = await self._isAdmin(user, chat if adminAllowedChangeSettings else None, True)
        # if not isAdmin:
        #     await self._sendMessage(
        #         ensuredMessage,
        #         messageText="You are not allowed to change chat settings.",
        #         messageCategory=MessageCategory.BOT_ERROR,
        #     )
        #     return

        if isSet and (not context.args or len(context.args) < 2):
            await self.sendMessage(
                ensuredMessage,
                messageText="You need to specify a key and a value to change chat setting.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return
        if not isSet and (not context.args or len(context.args) < 1):
            await self.sendMessage(
                ensuredMessage,
                messageText="You need to specify a key to clear chat setting.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        if not context.args:
            # It is impossible, actually as we have checked it before, but we do it to make linters happy
            raise ValueError("No args provided")

        key = context.args[0]
        _key = ChatSettingsKey.UNKNOWN
        try:
            _key = ChatSettingsKey(key)
        except ValueError:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Неизвестный ключ: `{key}`",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        if isSet:
            value = " ".join(context.args[1:])

            self.setChatSetting(chat.id, _key, ChatSettingsValue(value))
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Готово, теперь `{key}` = `{value}`",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        else:
            self.unsetChatSetting(chat.id, _key)
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Готово, теперь `{key}` сброшено в значение по умолчанию",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )

    @commandHandler(
        commands=("test",),
        shortDescription="<Test suite> [<args>] - Run some tests",
        helpMessage=" `<test_name>` `[<test_args>]`: Запустить тест (используется для тестирования).",
        categories={CommandCategory.BOT_OWNER, CommandCategory.HIDDEN},
        order=CommandHandlerOrder.TEST,
    )
    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /test command to run various diagnostic test suites, dood!

        Executes different test suites for debugging and development purposes.
        Each suite tests specific bot functionality or system components.

        Args:
            update: Telegram update object containing the message
            context: Bot context with test suite name and optional arguments

        Command Usage:
            /test <suite> [<args>] - Runs the specified test suite

        Available Test Suites:
            - long [iterations] [delay]: Sends multiple messages with delays
              (default: 10 iterations, 10 second delay)
            - delayedQueue: Shows current state of delayed actions queue
            - cacheStats: Displays cache service statistics in JSON format
            - dumpEntities: Dumps message entities from replied message
              (must be used as a reply to a message with entities)

        Returns:
            None

        Note:
            - Restricted to bot owners only
            - 'long' test useful for testing bot stability over time
            - 'dumpEntities' requires replying to a message
            - Unknown suite names result in an error message, dood!
        """
        logger.debug(f"Got test command: {update}")

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

        if not await self.isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/test` by not owner {ensuredMessage.user}")
            return

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        if not context.args or len(context.args) < 1:
            await self.sendMessage(
                ensuredMessage,
                messageText="You need to specify test suite.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        suite = context.args[0]
        await self.startTyping(ensuredMessage)

        match suite:
            case "long":
                iterationsCount = 2
                delay = 1
                if len(context.args) > 1:
                    try:
                        iterationsCount = int(context.args[1])
                    except ValueError as e:
                        await self.sendMessage(
                            ensuredMessage,
                            messageText=f"Invalid iterations count. {e}",
                            messageCategory=MessageCategory.BOT_ERROR,
                        )
                        pass
                if len(context.args) > 2:
                    try:
                        delay = int(context.args[2])
                    except ValueError as e:
                        await self.sendMessage(
                            ensuredMessage,
                            messageText=f"Invalid delay. {e}",
                            messageCategory=MessageCategory.BOT_ERROR,
                        )
                        pass

                for i in range(iterationsCount):
                    logger.debug(f"Iteration {i} of {iterationsCount} (delay is {delay}) {context.args[3:]}")
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=f"Iteration {i}",
                        skipLogs=True,  # Do not spam logs
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    )
                    if i < iterationsCount - 1:
                        await self.startTyping(ensuredMessage)
                    await asyncio.sleep(delay)

            case "delayedQueue":
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"```\n{self.queueService.delayedActionsQueue}\n\n"
                    f"{self.queueService.delayedActionsQueue.qsize()}\n```",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )

            case "cacheStats":
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"```json\n{utils.jsonDumps(self.cache.getStats(), indent=2)}\n```",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )

            case "dumpEntities":
                if message.reply_to_message is None:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText="`dumpEntities` should be retly to message with entities",
                        messageCategory=MessageCategory.BOT_ERROR,
                    )
                    return
                repliedMessage = message.reply_to_message
                if not repliedMessage.entities:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText="No entities found",
                        messageCategory=MessageCategory.BOT_ERROR,
                    )
                    return
                entities = repliedMessage.entities
                messageText = repliedMessage.text or ""
                ret = ""
                for entity in entities:
                    ret += (
                        f"{entity.type}: {entity.offset} {entity.length}:\n```\n"
                        f"{messageText[entity.offset:entity.offset + entity.length]}\n```\n"
                        f"```\n{entity}\n```\n"
                    )
                await self.sendMessage(
                    ensuredMessage,
                    messageText=ret,
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )

                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"```\n{repliedMessage.parse_entities()}\n```",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )

            case _:
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"Unknown test suite: {suite}.",
                    messageCategory=MessageCategory.BOT_ERROR,
                )
