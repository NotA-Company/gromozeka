"""
Gromozeka Help command Handler.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Sequence

from telegram import Update
from telegram.ext import ContextTypes

from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from lib.ai import LLMManager

from ..models import (
    CommandCategory,
    CommandHandlerInfo,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
)
from .base import BaseBotHandler, commandHandlerExtended

logger = logging.getLogger(__name__)


class CommandHandlerGetterInterface(ABC):
    """Class for getting command handlers."""

    @abstractmethod
    def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
        raise NotImplementedError


class HelpHandler(BaseBotHandler):
    """Special class for handling help command (to gather commands from all handlers)"""

    def __init__(
        self,
        configManager: ConfigManager,
        database: DatabaseWrapper,
        llmManager: LLMManager,
        commandsGetter: CommandHandlerGetterInterface,
    ):
        """Initialize handlers with database and LLM model."""
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager)
        self.commandsGetter = commandsGetter

    @commandHandlerExtended(
        commands=("help",),
        shortDescription="Print help",
        helpMessage=": Показать список доступных команд.",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE},
        helpOrder=CommandHandlerOrder.SECOND,
        category=CommandCategory.PRIVATE,
    )
    async def help_command(
        self, ensuredMessage: EnsuredMessage, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle the /help command."""
        isBotOwner = await self.isAdmin(ensuredMessage.user, allowBotOwners=True)

        commands: Dict[CommandHandlerOrder, List[str]] = {}
        for commandOrder in CommandHandlerOrder:
            commands[commandOrder] = []
        botOwnerCommands: List[str] = []

        # Sort command handlers by order, then by command name
        sortedHandlers = sorted(self.commandsGetter.getCommandHandlers(), key=lambda h: (h.order, h.commands[0]))

        for commandInfo in sortedHandlers:
            helpText = "* `/" + "`|`/".join(commandInfo.commands) + "`" + commandInfo.helpMessage
            for commandCategory in [
                CommandPermission.BOT_OWNER,
                CommandPermission.DEFAULT,
                CommandPermission.PRIVATE,
                CommandPermission.GROUP,
                CommandPermission.ADMIN,
            ]:
                if commandCategory in commandInfo.categories:
                    if commandCategory == CommandPermission.BOT_OWNER:
                        botOwnerCommands.append(helpText)
                    else:
                        commands[commandInfo.order].append(helpText)
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

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER)
        # logger.debug(f"Help text: {help_text}")
        await self.sendMessage(
            ensuredMessage,
            messageText=help_text,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
