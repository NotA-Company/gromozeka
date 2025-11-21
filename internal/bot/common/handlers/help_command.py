"""
Help command handler for Gromozeka Telegram bot.

This module provides the HelpHandler class which generates and displays
help information for all available bot commands. It collects command
information from all handlers and presents it in a user-friendly format.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from internal.bot.common.models import UpdateObjectType
from internal.bot.models import (
    BotProvider,
    CommandCategory,
    CommandHandlerInfoV2,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from lib.ai import LLMManager

from .base import BaseBotHandler, TypingManager

logger = logging.getLogger(__name__)


class CommandHandlerGetterInterface(ABC):
    """Interface for getting command handlers from a manager.

    This abstract interface defines the contract for retrieving command
    handler information from a handlers manager.
    """

    @abstractmethod
    def getCommandHandlersDict(self, useCache: bool = True) -> Dict[str, CommandHandlerInfoV2]:
        """Get dictionary of command handlers.

        Args:
            useCache: If True, return cached commands; if False, rebuild cache

        Returns:
            Dictionary mapping command names to CommandHandlerInfo objects
        """
        raise NotImplementedError


class HelpHandler(BaseBotHandler):
    """Special handler for help command that gathers commands from all handlers.

    This class collects command information from all registered handlers
    and presents it in a structured help format. It handles permission
    filtering and command categorization.
    """

    def __init__(
        self,
        configManager: ConfigManager,
        database: DatabaseWrapper,
        llmManager: LLMManager,
        botProvider: BotProvider,
        commandsGetter: CommandHandlerGetterInterface,
    ):
        """Initialize help handler with required dependencies.

        Args:
            configManager: Configuration manager instance
            database: Database wrapper for data persistence
            llmManager: LLM manager for AI model operations
            botProvider: Bot provider type (TELEGRAM or MAX)
            commandsGetter: Interface to get command handlers from manager
        """
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager, botProvider=botProvider)
        self.commandsGetter = commandsGetter

    @commandHandlerV2(
        commands=("help",),
        shortDescription="Print help",
        helpMessage=": Показать список доступных команд.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE},
        helpOrder=CommandHandlerOrder.SECOND,
        category=CommandCategory.PRIVATE,
    )
    async def help_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the /help command to display available commands.

        Args:
            ensuredMessage: Message containing the help command
            command: Command name (always "help")
            args: Command arguments (unused for help)
            UpdateObj: Original update object from the platform
            typingManager: Optional typing manager (unused for help)
        """
        isBotOwner = await self.isAdmin(ensuredMessage.sender, allowBotOwners=True)

        commands: Dict[CommandHandlerOrder, List[str]] = {}
        for commandOrder in CommandHandlerOrder:
            commands[commandOrder] = []
        botOwnerCommands: List[str] = []

        # Sort command handlers by order, then by command name
        sortedHandlers = sorted(
            self.commandsGetter.getCommandHandlersDict().values(), key=lambda h: (h.helpOrder, h.commands[0])
        )

        for commandInfo in sortedHandlers:
            helpText = "* `/" + "`|`/".join(commandInfo.commands) + "`" + commandInfo.helpMessage
            for commandCategory in [
                CommandPermission.BOT_OWNER,
                CommandPermission.DEFAULT,
                CommandPermission.PRIVATE,
                CommandPermission.GROUP,
                CommandPermission.ADMIN,
            ]:
                if commandCategory in commandInfo.availableFor:
                    if commandCategory == CommandPermission.BOT_OWNER:
                        botOwnerCommands.append(helpText)
                    else:
                        commands[commandInfo.helpOrder].append(helpText)
                    # Do not add command several times
                    break

        commandsStr = ""
        for v in commands.values():
            if v:
                commandsStr += f"{'\n'.join(v)}\n\n"
        help_text = (
            "🤖 **Gromozeka Bot Help**\n\n"
            "**Поддерживаемые команды:**\n"
            f"{commandsStr}\n\n"
            "\n"
            "**Так же этот бот может:**\n"
            "* Анализировать картинки и стикеры и отвечать на вопросы по ним\n"
            "* Логировать все сообщения и вести некоторую статистику\n"
            "* Поддерживать беседу, если она затрагивает бота "
            "(ответ на сообщение бота, указание логина бота в любом месте сообщения "
            "или начало сообщения с имени бота или личный чат с ботом)\n"
            '* Специально отвечать на запросы "`Кто сегодня ...`" и "`Что там?`" '
            "(должно быть ответом на сообщение с медиа)\n"
            "* Что-нибудь еше: Мы открыты к фич-реквестам\n"
        )

        if isBotOwner:
            help_text += "\n\n**Команды, доступные только владельцам бота:**\n" f"{"\n".join(botOwnerCommands)}\n"

        # await self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER)
        # logger.debug(f"Help text: {help_text}")
        await self.sendMessage(
            ensuredMessage,
            messageText=help_text,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
