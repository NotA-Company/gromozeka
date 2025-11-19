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

import telegram
from telegram.constants import MessageEntityType

from internal.bot.models.ensured_message import MessageRecipient
import lib.utils as utils
from internal.bot.common.models import UpdateObjectType
from internal.bot.models import (
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    commandHandlerV2,
)
from internal.database.models import MessageCategory
from internal.services.cache import CacheNamespace

from .base import BaseBotHandler, TypingManager

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

    @commandHandlerV2(
        commands=("echo",),
        shortDescription="<Message> - Echo message back",
        helpMessage=" `<message>`: Просто ответить переданным сообщением (для тестирования живости бота).",
        visibility={CommandPermission.PRIVATE, CommandPermission.HIDDEN},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.SECOND,
        category=CommandCategory.TECHNICAL,
    )
    async def echo_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
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

        if args:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"🔄 Echo: {args}",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        else:
            await self.sendMessage(
                ensuredMessage,
                messageText="Please provide a message to echo!\nUsage: /echo <your message>",
                messageCategory=MessageCategory.BOT_ERROR,
            )

    @commandHandlerV2(
        commands=("models",),
        shortDescription="Get list of known LLM models",
        helpMessage=": Вывести список всех известных моделей и их параметров.",
        visibility={CommandPermission.BOT_OWNER},
        availableFor={CommandPermission.BOT_OWNER},
        category=CommandCategory.PRIVATE,
    )
    async def models_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
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
                "support_tools": "Поддержка вызова инструментов",
                "support_text": "Поддержка генерации текста",
                "support_images": "Поддержка генерации изображений",
            }
            replyText += f"**Модель: {modelName}**\n```{modelName}\n"
            for k, v in modelData.items():
                if k == "extra":
                    v = utils.jsonDumps(v, indent=2)
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

    @commandHandlerV2(
        commands=("settings",),
        shortDescription="[<chatId>] [skip-default] - Dump all settings for this chat",
        helpMessage="[`<chatId>`] [`skip-default`]: Вывести список настроек для указанного чата",
        visibility={CommandPermission.BOT_OWNER},
        availableFor={CommandPermission.BOT_OWNER},
        category=CommandCategory.TECHNICAL,
    )
    async def chat_settings_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the /settings command to display chat configuration, dood!

        Retrieves and displays all settings for a specified chat, including default
        values and custom overrides. This command is useful for debugging configuration
        issues and understanding the current state of chat-specific settings.

        Args:
            ensuredMessage: Ensured message object containing chat information
            typingManager: Optional typing manager for showing typing status
            update: Telegram update object containing the message
            context: Bot context with command arguments

        Command Usage:
            /settings - Display settings for current chat
            /settings <chatId> - Display settings for specified chat
            /settings <chatId> skip-default - Display only non-default settings

        Returns:
            None

        Settings Displayed:
            - All available chat settings with their current values
            - Default values marked with "(default)" indicator
            - Values matching defaults marked with "(as default)" indicator
            - Chat name and ID in the response header

        Note:
            - Restricted to bot owners only
            - If chatId is not provided, uses current chat
            - skip-default flag hides settings that are using default values
            - Sends error message if chat is not found, dood!
        """

        argList = args.split()
        targetChatId = utils.extractInt(argList)
        if targetChatId is None:
            targetChatId = ensuredMessage.recipient.id
        elif argList:
            argList = argList[1:]

        skipDefault = False
        if argList and argList[0].lower() == "skip-default":
            skipDefault = True

        chatInfo = self.getChatInfo(targetChatId)
        if not chatInfo:
            await self.sendMessage(
                ensuredMessage,
                messageText="Чат не найден",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        chatName = self.getChatTitle(chatInfo)

        resp = f"Настройки чата {chatName}:\n\n"
        chatSettings = self.getChatSettings(targetChatId)
        chatSettingsNoDef = self.getChatSettings(targetChatId, returnDefault=False)
        defaultSettings = self.getChatSettings(None, chatType=ChatType.PRIVATE if targetChatId > 0 else ChatType.GROUP)
        for k, v in chatSettings.items():
            isDefaultStr = ""
            if k not in chatSettingsNoDef:
                isDefaultStr = " **(default)**"
                if skipDefault:
                    continue
            elif chatSettings[k].toStr() == defaultSettings[k].toStr():
                isDefaultStr = " **(as default)**"
            resp += f"`{k}`{isDefaultStr}:```{k}\n{v}\n```\n"

        await self.sendMessage(
            ensuredMessage,
            messageText=resp,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerV2(
        commands=("set", "unset"),
        shortDescription="[<chatId>] <key> <value> - Set/Unset given setting for current chat",
        helpMessage="[`<chatId>`] `<key>` `<value>`: установить/сбросить настройку чата",
        visibility={CommandPermission.BOT_OWNER},
        availableFor={CommandPermission.BOT_OWNER},
        category=CommandCategory.TECHNICAL,
    )
    async def set_or_unset_chat_setting_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle /set and /unset commands for managing chat settings, dood!

        Allows bot owners to modify or reset chat-specific settings. The /set
        command assigns a new value to a setting key, while /unset resets it
        to the default value.

        Args:
            update: Telegram update object containing the message
            context: Bot context with command arguments

        Command Usage:
            /set [<chatId>] <key> <value> - Sets the specified key to the given value
            /unset [<chatId>] <key> - Resets the specified key to its default value

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
        message = ensuredMessage.getBaseMessage()
        if not isinstance(message, telegram.Message):
            raise ValueError("Invalid message type")

        commandStr = ""
        for entityStr in message.parse_entities([MessageEntityType.BOT_COMMAND]).values():
            commandStr = entityStr
            break
        logger.debug(f"Command string: {commandStr}")
        isSet = commandStr.lower().startswith("/set")

        notEnoughArgsText = (
            "Для установки настроек используйте `/set [<chatId] <key> <value>`, для сброса `/unset [<chatId>] <key>`"
        )

        if not args:
            await self.sendMessage(
                ensuredMessage,
                notEnoughArgsText,
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        argList = args.split()

        targetChatId = utils.extractInt(argList)
        if targetChatId is None:
            targetChatId = ensuredMessage.recipient.id
        else:
            argList = argList[1:]

        if any(
            [
                not argList,
                isSet and len(argList) < 2,
                not isSet and len(argList) != 1,
            ]
        ):
            await self.sendMessage(
                ensuredMessage,
                notEnoughArgsText,
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        keyStr = argList[0]
        key = ChatSettingsKey.UNKNOWN
        try:
            key = ChatSettingsKey(keyStr)
        except ValueError:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Неизвестный ключ: `{keyStr}`",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        if isSet:
            value = " ".join(argList[1:]).strip()

            self.setChatSetting(targetChatId, key, ChatSettingsValue(value))
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Готово, теперь `{keyStr}` в чате #`{targetChatId}`:\n```\n{value}\n```",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        else:
            self.unsetChatSetting(targetChatId, key)
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Готово, теперь `{keyStr}` в чате #`{targetChatId}` сброшено в значение по умолчанию",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )

    @commandHandlerV2(
        commands=("test",),
        shortDescription="<Test suite> [<args>] - Run some tests",
        helpMessage=" `<test_name>` `[<test_args>]`: Запустить тест (используется для тестирования).",
        visibility={CommandPermission.BOT_OWNER},
        availableFor={CommandPermission.BOT_OWNER},
        helpOrder=CommandHandlerOrder.TEST,
        category=CommandCategory.PRIVATE,
    )
    async def test_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle /test command to run various diagnostic test suites, dood!"""
        message = ensuredMessage.getBaseMessage()
        if not isinstance(message, telegram.Message):
            raise ValueError("Invalid message type")

        if not args:
            await self.sendMessage(
                ensuredMessage,
                messageText="You need to specify test suite.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        argList = args.split()
        suite = argList[0]

        match suite:
            case "long":
                iterationsCount = 2
                delay = 1
                if len(argList) > 1:
                    try:
                        iterationsCount = int(argList[1])
                    except ValueError as e:
                        await self.sendMessage(
                            ensuredMessage,
                            messageText=f"Invalid iterations count. {e}",
                            messageCategory=MessageCategory.BOT_ERROR,
                        )
                        pass
                if len(argList) > 2:
                    try:
                        delay = int(argList[2])
                    except ValueError as e:
                        await self.sendMessage(
                            ensuredMessage,
                            messageText=f"Invalid delay. {e}",
                            messageCategory=MessageCategory.BOT_ERROR,
                        )
                        pass

                for i in range(iterationsCount):
                    logger.debug(f"Iteration {i} of {iterationsCount} (delay is {delay}) {argList[3:]}")
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=f"Iteration {i}",
                        skipLogs=True,  # Do not spam logs
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                        typingManager=typingManager if i >= iterationsCount - 1 else None,
                    )
                    if i < iterationsCount - 1:
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

            case "dumpCache":
                for ns in CacheNamespace:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=f"**{ns}**: \n"
                        f"```json\n{utils.jsonDumps(self.cache._caches[ns], indent=2)}\n```\n\n"
                        "Dirty keys: \n"
                        f"```\n{self.cache.dirtyKeys[ns]}\n```\n",
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    )
                    await asyncio.sleep(0.5)

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

    @commandHandlerV2(
        commands=("clear_cache",),
        shortDescription="- Clear cache (all except of user state)",
        helpMessage=": Очистить кеш (кроме состояния пользователя) "
        "для перечитывания всех значений из базы (полезно при ручном вмешательстве в базу данных)",
        visibility={CommandPermission.BOT_OWNER},
        availableFor={CommandPermission.BOT_OWNER},
        helpOrder=CommandHandlerOrder.TECHNICAL,
        category=CommandCategory.PRIVATE,
    )
    async def clear_cache_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Clear cache"""
        # Dump only temporary caches, do not touch User and ChatPersistent ones
        self.cache.clearNamespace(CacheNamespace.CHAT_USERS)
        self.cache.clearNamespace(CacheNamespace.CHATS)

        await self.sendMessage(
            ensuredMessage,
            messageText="Готово, кеши очищены (используйте `/test dumpCache` для проверки состояния кеша)",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerV2(
        commands=("get_admins",),
        shortDescription="[<chatId>]- Get admin list of given chat",
        helpMessage=" [`<chatId>`]: Получить список администраторов указанного чата"
        ,
        visibility={CommandPermission.BOT_OWNER},
        availableFor={CommandPermission.BOT_OWNER},
        helpOrder=CommandHandlerOrder.TECHNICAL,
        category=CommandCategory.PRIVATE,
    )
    async def get_admins_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Clear cache"""
        targetChatId:Optional[int] = None
        if args:
            argList = args.split()
            targetChatId = utils.extractInt(argList)

        if targetChatId is None:
            targetChatId = ensuredMessage.recipient.id

        # Fill admin list cache
        await self.isAdmin(
            ensuredMessage.sender,
            MessageRecipient(id=targetChatId, chatType=ChatType.PRIVATE if targetChatId > 0 else ChatType.GROUP),
            allowBotOwners=False,
        )
        admins =  self.cache.getChatAdmins(targetChatId)

        await self.sendMessage(
            ensuredMessage,
            messageText=f"```json\n{utils.jsonDumps(admins, indent=2)}\n```",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
