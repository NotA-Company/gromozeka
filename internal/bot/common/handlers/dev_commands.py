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
import json
import logging
import sys
import time
from typing import Optional

import magic
import telegram

import lib.max_bot.models as maxModels
import lib.utils as utils
from internal.bot.common.models import TypingAction, UpdateObjectType
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
    MessageType,
    OutputFormat,
    commandHandlerV2,
)
from internal.bot.models.ensured_message import MessageRecipient
from internal.database.models import MessageCategory
from internal.services.cache import CacheNamespace
from internal.services.llm.models import ExtraDataDict
from lib.ai import ModelMessage, ModelResultStatus, ModelRunResult

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
            ensuredMessage: Ensured message object containing chat and sender information
            command: The command that was invoked (e.g., "echo")
            args: Command arguments (the message text to echo)
            UpdateObj: Telegram update object containing the message
            typingManager: Optional typing manager for showing typing status

        Command Usage:
            /echo <message> - Echoes back the provided message

        Returns:
            None

        Note:
            - Sends error if no message text is provided
            - Message is sent with BOT_COMMAND_REPLY category on success
            - Error messages are sent with BOT_ERROR category, dood!
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
            ensuredMessage: Ensured message object containing chat and sender information
            command: The command that was invoked (e.g., "models")
            args: Command arguments (not used for this command)
            UpdateObj: Telegram update object containing the message
            typingManager: Optional typing manager for showing typing status

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

        llmManager = self.llmService.getLLMManager()
        for i, modelName in enumerate(llmManager.listModels()):
            modelData = llmManager.getModelInfo(modelName)
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
        helpMessage=" [`<chatId>`] [`skip-default`]: Вывести список настроек для указанного чата",
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
            ensuredMessage: Ensured message object containing chat and sender information
            command: The command that was invoked (e.g., "settings")
            args: Command arguments (chatId and optional skip-default flag)
            UpdateObj: Telegram update object containing the message
            typingManager: Optional typing manager for showing typing status

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
        if argList and argList[0].lower() in ["skip-default", "skip-defaults"]:
            skipDefault = True

        chatInfo = await self.getChatInfo(targetChatId)
        if not chatInfo:
            await self.sendMessage(
                ensuredMessage,
                messageText="Чат не найден",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        chatName = self.getChatTitle(chatInfo)

        resp = f"Настройки чата {chatName}:\n\n"
        chatSettings = await self.getChatSettings(targetChatId)
        chatSettingsNoDef = await self.getChatSettings(targetChatId, returnDefault=False)
        defaultSettings = await self.getChatSettings(
            None,
            chatType=ChatType.PRIVATE if targetChatId > 0 else ChatType.GROUP,
            chatTier=self.getChatTier(chatSettings),
        )
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
        helpMessage=" [`<chatId>`] `<key>` `<value>`: установить/сбросить настройку чата",
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
            ensuredMessage: Ensured message object containing chat and sender information
            command: The command that was invoked (e.g., "set" or "unset")
            args: Command arguments (chatId, key, and optional value)
            UpdateObj: Telegram update object containing the message
            typingManager: Optional typing manager for showing typing status

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

        isSet = command.lower().startswith("set")

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

            await self.setChatSetting(targetChatId, key, ChatSettingsValue(value), user=ensuredMessage.sender)
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Готово, теперь `{keyStr}` в чате #`{targetChatId}`:\n```\n{value}\n```",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        else:
            await self.unsetChatSetting(targetChatId, key)
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
        category=CommandCategory.TECHNICAL,
    )
    async def test_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle /test command to run various diagnostic test suites, dood!

        Provides access to various test suites for debugging and development purposes.
        Each test suite performs specific diagnostic operations and returns results
        to the chat.

        Args:
            ensuredMessage: Ensured message object containing chat and sender information
            command: The command that was invoked (e.g., "test")
            args: Command arguments (test suite name and optional parameters)
            UpdateObj: Telegram update object containing the message
            typingManager: Optional typing manager for showing typing status

        Command Usage:
            /test long [<iterations>] [<delay>] - Test long-running operations
            /test delayedQueue - Display delayed actions queue state
            /test backgroundTasks - Display background tasks state
            /test cacheStats - Display cache statistics
            /test dumpCache - Dump all cache contents
            /test dumpEntities - Dump message entities (must reply to a message)
            /test dumpNativeEntities - Dump native message entities (must reply to a message)

        Returns:
            None

        Test Suites:
            long: Sends multiple messages with configurable iterations and delay
            delayedQueue: Shows the delayed actions queue and its size
            backgroundTasks: Shows currently running background tasks
            cacheStats: Displays cache statistics in JSON format
            dumpCache: Dumps all cache namespaces and dirty keys
            dumpEntities: Dumps formatted entities from a replied message
            dumpNativeEntities: Dumps native entities from a replied message

        Note:
            - Restricted to bot owners only
            - dumpEntities and dumpNativeEntities require replying to a message
            - Some test suites may have delays between messages, dood!
        """

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
                        typingManager=None,
                    )
                    if i < iterationsCount - 1:
                        await asyncio.sleep(delay)
                await asyncio.sleep(0.5)
                await self.sendMessage(
                    ensuredMessage,
                    messageText="Done",
                    skipLogs=True,  # Do not spam logs
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )

            case "delayedQueue":
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"```\n{self.queueService.delayedActionsQueue}\n\n"
                    f"{self.queueService.delayedActionsQueue.qsize()}\n```",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )

            case "backgroundTasks":
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"```\n{self.queueService.backgroundTasks}\n```",
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
                        f"```json\n{utils.jsonDumps(self.cache._caches[ns], indent=2, sort_keys=False)}\n```\n\n"
                        "Dirty keys: \n"
                        f"```\n{self.cache.dirtyKeys[ns]}\n```\n",
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    )
                    await asyncio.sleep(0.5)

            case "dumpEntities":
                if ensuredMessage.replyId is None:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText="`dumpEntities` should be reply to message with entities",
                        messageCategory=MessageCategory.BOT_ERROR,
                    )
                    return
                repliedMessage = ensuredMessage.getEnsuredRepliedToMessage()
                if repliedMessage is None:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText="No replied message found",
                        messageCategory=MessageCategory.BOT_ERROR,
                    )
                    return

                entities = repliedMessage.formatEntities
                messageText = repliedMessage.messagePrefix + repliedMessage.messageText
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
                await asyncio.sleep(0.5)

                outputFormat: OutputFormat = OutputFormat.MARKDOWN
                match self.botProvider:
                    case BotProvider.TELEGRAM:
                        outputFormat = OutputFormat.MARKDOWN_TG
                    case BotProvider.MAX:
                        outputFormat = OutputFormat.MARKDOWN_MAX

                logger.debug(f"outputFormat: {outputFormat}")

                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"```\n{repliedMessage.formatMessageText(outputFormat=outputFormat)}\n```",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )
                await asyncio.sleep(0.5)

                await self.sendMessage(
                    ensuredMessage,
                    messageText=repliedMessage.formatMessageText(outputFormat=outputFormat),
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )

            case "dumpNativeEntities":
                if ensuredMessage.replyId is None:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText="`dumpNativeEntities` should be reply to message with entities",
                        messageCategory=MessageCategory.BOT_ERROR,
                    )
                    return
                message = ensuredMessage.getBaseMessage()
                if isinstance(message, telegram.Message) and message.reply_to_message:
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
                elif isinstance(message, maxModels.Message) and message.link:
                    repliedMessage = message.link.message
                    entities = repliedMessage.markup
                    if entities is None:
                        entities = []

                    messageText = repliedMessage.text or ""
                    ret = "There are entities:\n\n"
                    for entity in entities:
                        ret += (
                            f"**{entity.type}**: {entity.fromField} {entity.length}:\n```\n"
                            f"{messageText[entity.fromField:entity.fromField + entity.length]}\n```\n"
                            f"```\n{entity}\n```\n\n"
                        )

                    await self.sendMessage(
                        ensuredMessage,
                        messageText=ret,
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
        """Clear cache to force reload from database, dood!

        Clears all temporary cache namespaces (CHAT_USERS and CHATS) to force
        the bot to reload values from the database. This is useful after manual
        database modifications or when troubleshooting cache-related issues.

        Args:
            ensuredMessage: Ensured message object containing chat and sender information
            command: The command that was invoked (e.g., "clear_cache")
            args: Command arguments (not used for this command)
            UpdateObj: Telegram update object containing the message
            typingManager: Optional typing manager for showing typing status

        Command Usage:
            /clear_cache - Clears temporary caches

        Returns:
            None

        Note:
            - Restricted to bot owners only
            - Does not clear User and ChatPersistent namespaces
            - Use /test dumpCache to verify cache state after clearing, dood!
        """
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
        helpMessage=" [`<chatId>`]: Получить список администраторов указанного чата",
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
        """Get list of admins of given chat, dood!

        Retrieves and displays the list of administrators for a specified chat.
        This command is useful for debugging permission issues and verifying
        admin status.

        Args:
            ensuredMessage: Ensured message object containing chat and sender information
            command: The command that was invoked (e.g., "get_admins")
            args: Command arguments (optional chatId)
            UpdateObj: Telegram update object containing the message
            typingManager: Optional typing manager for showing typing status

        Command Usage:
            /get_admins - Get admins for current chat
            /get_admins <chatId> - Get admins for specified chat

        Returns:
            None

        Note:
            - Restricted to bot owners only
            - If chatId is not provided, uses current chat
            - Admin list is cached and may be refreshed by this command
            - Results are displayed in JSON format, dood!
        """
        targetChatId: Optional[int] = None
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
        admins = self.cache.getChatAdmins(targetChatId)

        await self.sendMessage(
            ensuredMessage,
            messageText=f"```json\n{utils.jsonDumps(admins, indent=2)}\n```",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerV2(
        commands=("llm_replay",),
        shortDescription="[<Model>] - Replay LLM conversation from attached JSON file",
        helpMessage=(
            " `[<model_name>]` + JSON attachment: Повторить LLM-запрос из JSON-файла"
            " с указанной моделью (для отладки)."
        ),
        visibility={CommandPermission.BOT_OWNER},
        availableFor={CommandPermission.BOT_OWNER},
        helpOrder=CommandHandlerOrder.TECHNICAL,
        category=CommandCategory.PRIVATE,
        typingAction=TypingAction.TYPING,
    )
    async def llmReplayCommand(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Replay an LLM conversation from an attached JSON file for debugging, dood!

        Reads a JSON log entry from an attached document, reconstructs the
        message list using :py:func:`reconstructMessages`, and runs it through
        :py:meth:`LLMService.generateTextViaLLM` with the specified model and
        all registered tools. Intermediate tool-call results are sent back to
        the chat as they arrive, mirroring the :py:class:`LLMMessageHandler`
        pattern.

        Args:
            ensuredMessage: Ensured message object containing chat and sender information
            command: The command that was invoked (e.g., "llm_replay")
            args: Command arguments — the model name to use
            UpdateObj: Telegram update object containing the message
            typingManager: Optional typing manager for showing typing status

        Command Usage:
            /llm_replay <model_name> (with JSON file attached or replying to one)

        Returns:
            None

        Error Responses:
            - Missing model argument: usage hint
            - Unknown model name: list of available models
            - No JSON attachment: request to attach a file
            - Invalid JSON: parse error message
            - Missing 'request' field: log entry error
            - LLM API error: exception type and message
            - Non-FINAL status: intermediate status report, dood!
        """

        # 0. Get chat settings
        chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
        assert self._bot is not None, "self._bot is None, it shouldn't happen"

        # 1. Validate model argument
        modelName = args.strip()
        if not modelName:
            modelName = chatSettings[ChatSettingsKey.CHAT_MODEL].toStr()

        # 2. Resolve model
        model = self.llmService.getLLMManager().getModel(modelName)
        if model is None:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Model `{modelName}` not found.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        # 3. Get JSON attachment — either on this message or on a replied-to message
        sourceEnsured = ensuredMessage
        if ensuredMessage.messageType != MessageType.DOCUMENT:
            if ensuredMessage.isReply:
                repliedMessage = ensuredMessage.getEnsuredRepliedToMessage()
                if repliedMessage is not None:
                    sourceEnsured = repliedMessage
            if sourceEnsured.messageType != MessageType.DOCUMENT:
                await self.sendMessage(
                    ensuredMessage,
                    messageText="Please attach a JSON file with the command",
                    messageCategory=MessageCategory.BOT_ERROR,
                    typingManager=typingManager,
                )
                return

        # 4. Download and parse JSON
        baseMessage = sourceEnsured.getBaseMessage()
        jsonBytes: Optional[bytes] = None
        if isinstance(baseMessage, telegram.Message):
            if baseMessage.document is not None:
                jsonBytes = await self._bot.downloadAttachment(mediaId="", fileId=baseMessage.document.file_id)
        elif isinstance(baseMessage, maxModels.Message):
            # Max: look for a file attachment
            if baseMessage.body and baseMessage.body.attachments:
                for attachment in baseMessage.body.attachments:
                    if isinstance(attachment, maxModels.FileAttachment):
                        jsonBytes = await self._bot.downloadAttachment(mediaId="", fileId=attachment.payload.url)
                        break

        if jsonBytes is None:
            await self.sendMessage(
                ensuredMessage,
                messageText="Please attach a JSON file with the command",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        # Validate the file looks like JSON
        mimeType = magic.from_buffer(jsonBytes, mime=True)
        logger.debug(f"Attachment mime type is: {mimeType}")
        if not mimeType.startswith("application/json"):
            await self.sendMessage(
                ensuredMessage,
                messageText="Please attach a JSON file with the command",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        try:
            data = json.loads(jsonBytes)
        except json.JSONDecodeError as exc:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Failed to parse JSON: `{exc}`",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        # Normalize to list of entries (single dict or list)
        if isinstance(data, list) and data:
            data = data[0]

        if not isinstance(data, dict):
            await self.sendMessage(
                ensuredMessage,
                messageText="JSON must be an object or array of objects",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        # 5. Validate and reconstruct messages
        if "request" not in data or not isinstance(data["request"], list):
            await self.sendMessage(
                ensuredMessage,
                messageText="request fiels is required and should be list of objects",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        try:
            messages = ModelMessage.fromDictList(data["request"])
        except (TypeError, ValueError, KeyError) as exc:
            logger.error(exc)
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Failed to reconstruct messages: `{exc}`",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        # 6. Call LLM
        async def processIntermediateMessages(mRet: ModelRunResult, extraData: ExtraDataDict) -> None:
            """Process intermediate LLM results and send them to the chat.

            Args:
                mRet: Intermediate LLM result containing generated text.
                extraData: Additional data including ensuredMessage and typingManager.

            Returns:
                None
            """
            if mRet.resultText.strip():
                try:
                    prefixStr = ""
                    if mRet.isFallback:
                        prefixStr += chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=mRet.resultText,
                        messageCategory=MessageCategory.BOT,
                        addMessagePrefix=prefixStr,
                    )
                    tm = extraData.get("typingManager")
                    if isinstance(tm, TypingManager):
                        tm.addTimeout(120)
                        await tm.sendTypingAction()
                except Exception as exc:
                    logger.error(f"Failed to send intermediate message: {exc}")

        try:
            mlRet = await self.llmService.generateTextViaLLM(
                messages=messages,
                chatId=ensuredMessage.recipient.id,
                chatSettings=chatSettings,
                modelKey=model,
                fallbackModelKey=ChatSettingsKey.FALLBACK_MODEL,
                useTools=chatSettings[ChatSettingsKey.USE_TOOLS].toBool(),
                callback=processIntermediateMessages,
                extraData={
                    "ensuredMessage": ensuredMessage,
                    "typingManager": typingManager,
                },
            )
        except Exception as exc:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Error running query: `{type(exc).__name__}#{exc}`",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        # Check for non-FINAL status
        if mlRet.status != ModelResultStatus.FINAL:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"LLM returned non-final status: {mlRet.status.name}",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        # 7. Report result summary
        toolCount = len(mlRet.toolCalls) if mlRet.toolCalls else 0
        toolNames = ", ".join(tc.name for tc in mlRet.toolCalls) if mlRet.toolCalls else "none"
        elapsedStr = f"{mlRet.elapsedTime:.2f}s" if mlRet.elapsedTime is not None else "N/A"

        await self.sendMessage(
            ensuredMessage,
            messageText=f"**LLM Replay Result**\n"
            f"Model: {modelName}\n"
            f"Status: {mlRet.status.name}\n"
            f"Input tokens: {mlRet.inputTokens or 'N/A'}\n"
            f"Output tokens: {mlRet.outputTokens or 'N/A'}\n"
            f"Tool calls: {toolCount} ({toolNames})\n"
            f"Elapsed: {elapsedStr}",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            # typingManager=typingManager,
        )

        await self.sendMessage(
            ensuredMessage,
            messageText=mlRet.resultText.strip(),
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            typingManager=typingManager,
        )

    @commandHandlerV2(
        commands=("shutdown",),
        shortDescription="Shutdown the bot",
        helpMessage=": Разлогиниться и остановить бота",
        visibility={CommandPermission.BOT_OWNER},
        availableFor={CommandPermission.BOT_OWNER},
        helpOrder=CommandHandlerOrder.TECHNICAL,
        category=CommandCategory.PRIVATE,
    )
    async def shutdown_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Shutdown the bot gracefully, dood!

        Logs out from the bot platform and terminates the bot process.
        This command is used for controlled shutdown during maintenance
        or when the bot needs to be restarted.

        Args:
            ensuredMessage: Ensured message object containing chat and sender information
            command: The command that was invoked (e.g., "shutdown")
            args: Command arguments (not used for this command)
            UpdateObj: Telegram update object containing the message
            typingManager: Optional typing manager for showing typing status

        Command Usage:
            /shutdown - Shutdown the bot

        Returns:
            None

        Note:
            - Restricted to bot owners only
            - Sends goodbye message before shutting down
            - Logs out from Telegram if available
            - Terminates the process with exit code 0, dood!
        """

        await self.sendMessage(
            ensuredMessage,
            messageText=f"Bye-bye, {ensuredMessage.sender.name}",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

        if self._bot and self._bot.tgBot:
            await self._bot.tgBot.logOut()

        sys.exit(0)
