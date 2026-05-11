"""Help command handler for Gromozeka Telegram bot.

This module provides the HelpHandler class which generates and displays
help information for all available bot commands. It collects command
information from all handlers and presents it in a user-friendly format.

The module also defines the CommandHandlerGetterInterface abstract base class
that provides a contract for retrieving command handler information from a
handlers manager.

Example:
    To use the help handler, create an instance with the required dependencies
    and register it with the bot's command handler manager:

    ```python
    helpHandler = HelpHandler(
        configManager=configManager,
        database=database,
        botProvider=BotProvider.TELEGRAM,
        commandsGetter=handlersManager
    )
    ```
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
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
from internal.database import Database
from internal.database.models import MessageCategory

from .base import BaseBotHandler

logger = logging.getLogger(__name__)


class CommandHandlerGetterInterface(ABC):
    """Interface for getting command handlers from a manager.

    This abstract interface defines the contract for retrieving command
    handler information from a handlers manager. Implementations of this
    interface provide access to the bot's registered command handlers.

    Example:
        ```python
        class HandlersManager(CommandHandlerGetterInterface):
            def getCommandHandlersDict(self, useCache: bool = True) -> Dict[str, CommandHandlerInfoV2]:
                # Implementation to retrieve command handlers
                return self._handlers
        ```
    """

    @abstractmethod
    def getCommandHandlersDict(self, useCache: bool = True) -> Dict[str, CommandHandlerInfoV2]:
        """Get dictionary of command handlers.

        Retrieves all registered command handlers, optionally using a cache
        to improve performance. The returned dictionary maps command names
        to their corresponding handler information.

        Args:
            useCache: If True, return cached commands; if False, rebuild cache
                by scanning all registered handlers. Default is True.

        Returns:
            Dictionary mapping command names to CommandHandlerInfoV2 objects.
            Each key is a command name (e.g., "help", "start") and each value
            contains metadata about the command handler including permissions,
            descriptions, and handler references.

        Raises:
            NotImplementedError: This method must be implemented by subclasses.
        """
        raise NotImplementedError


class HelpHandler(BaseBotHandler):
    """Special handler for help command that gathers commands from all handlers.

    This class collects command information from all registered handlers
    and presents it in a structured help format. It handles permission
    filtering and command categorization, showing different commands to
    different users based on their permissions (e.g., bot owner, admin, regular user).

    The help command is automatically registered with the decorator and responds
    to the /help command in private chats.

    Attributes:
        commandsGetter: Interface instance used to retrieve command handler
            information from the handlers manager. This allows the help handler
            to dynamically discover all available commands without hardcoding them.

    Example:
        ```python
        helpHandler = HelpHandler(
            configManager=configManager,
            database=database,
            botProvider=BotProvider.TELEGRAM,
            commandsGetter=handlersManager
        )
        # The help command is automatically registered via the decorator
        ```
    """

    def __init__(
        self,
        *,
        configManager: ConfigManager,
        database: Database,
        botProvider: BotProvider,
        commandsGetter: CommandHandlerGetterInterface,
    ):
        """Initialize help handler with required dependencies.

        Sets up the help handler with all necessary dependencies for accessing
        configuration, database, LLM services, and command handler information.

        Args:
            configManager: Configuration manager instance for accessing bot
                configuration settings.
            database: Database wrapper for data persistence and message storage.
            botProvider: Bot provider type (TELEGRAM or MAX) indicating which
                messaging platform the bot is running on.
            commandsGetter: Interface to get command handlers from manager.
                This is used to dynamically discover all available commands
                for the help display.
        """
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, botProvider=botProvider)
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

        Generates and sends a formatted help message showing all available bot
        commands. Commands are filtered based on the user's permissions:
        - Regular users see commands available to them
        - Bot owners see additional bot-owner-only commands

        Commands are organized by their help order (FIRST, SECOND, etc.) and
        displayed with their aliases and descriptions. The help message also
        includes information about the bot's automatic features like image
        analysis and conversation support.

        Args:
            ensuredMessage: Message containing the help command. Contains
                information about the sender, chat, and message content.
            command: Command name (always "help" for this handler).
            args: Command arguments (unused for help command, but part of
                the handler signature).
            UpdateObj: Original update object from the platform (Telegram or MAX).
                Provides raw update data for advanced use cases.
            typingManager: Optional typing manager for showing typing indicators
                (unused for help command, but part of the handler signature).

        Returns:
            None

        Raises:
            Does not raise exceptions directly. Any errors during message sending
            are handled by the base class's sendMessage method.

        Example:
            User sends: /help
            Bot responds with:
            ```
            🤖 **Gromozeka Bot Help**

            **Поддерживаемые команды:**
            * `/start`: Начать работу с ботом.
            * `/help`: Показать список доступных команд.
            ...
            ```
        """
        isBotOwner = self.isBotOwner(ensuredMessage.sender)

        commands: Dict[CommandHandlerOrder, List[str]] = {}
        for commandOrder in CommandHandlerOrder:
            commands[commandOrder] = []
        botOwnerCommands: List[str] = []

        # Dedup + Sort command handlers by order, then by command name
        commandHandlersDedupDict = {
            "|".join(v.commands): v for v in self.commandsGetter.getCommandHandlersDict().values()
        }
        # logger.debug(f"Handlers: {utils.jsonDumps(commandHandlersDedupDict, indent=2)}")
        sortedHandlers = sorted(commandHandlersDedupDict.values(), key=lambda h: (h.helpOrder, h.commands[0]))

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
            '* Отвечать на запросы "`Кто сегодня ...`" и "`Что там?`" '
            "(должно быть ответом на сообщение с медиа)\n"
            "* Что-нибудь ещё: Мы открыты к фич-реквестам\n"
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
