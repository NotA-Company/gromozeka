"""
Bot handlers manager for coordinating message processing across multiple handlers.
"""

import logging
from typing import Dict, List, Optional, Set, Tuple

from telegram.ext import ExtBot

import lib.max_bot as libMax
from internal.bot.common.bot import TheBot

# import lib.max_bot.models as maxModels
from internal.bot.common.models import UpdateObjectType
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    ChatType,
    CommandCategory,
    CommandHandlerInfoV2,
    CommandPermission,
    EnsuredMessage,
)
from internal.bot.models.chat_settings import ChatSettingsValue
from internal.bot.models.ensured_message import MessageSender
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.services.cache import CacheService
from internal.services.queue_service import QueueService
from lib import utils
from lib.ai import LLMManager

from .base import BaseBotHandler, HandlerResultStatus
from .common import CommonHandler
from .configure import ConfigureCommandHandler
from .dev_commands import DevCommandsHandler
from .help_command import CommandHandlerGetterInterface, HelpHandler
from .llm_messages import LLMMessageHandler
from .media import MediaHandler
from .message_preprocessor import MessagePreprocessorHandler
from .react_on_user import ReactOnUserMessageHandler
from .spam import SpamHandler
from .summarization import SummarizationHandler
from .user_data import UserDataHandler
from .weather import WeatherHandler
from .yandex_search import YandexSearchHandler

logger = logging.getLogger(__name__)


class HandlersManager(CommandHandlerGetterInterface):
    """
    Manages and coordinates multiple bot handlers for message processing.

    This class orchestrates the execution of various handlers in a specific order,
    handles command parsing and routing, and manages handler lifecycle.
    """

    def __init__(
        self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager, botProvider: BotProvider
    ):
        """Initialize the handlers manager with required services.

        Args:
            configManager: Configuration manager instance
            database: Database wrapper for data persistence
            llmManager: LLM manager for AI model operations
            botProvider: Bot provider type (TELEGRAM or MAX)
        """
        self.configManager = configManager
        self.db = database
        self.llmManager = llmManager
        self.botProvider: BotProvider = botProvider

        # Map of command name -> CommandHandlerInfo
        self._commands: Dict[str, CommandHandlerInfoV2] = {}

        self.cache = CacheService.getInstance()
        self.cache.injectDatabase(self.db)

        self.queueService = QueueService.getInstance()
        # Initialize default Chat Settings
        # TODO: Put all botOwners and chatDefaults to some service to not duplicate it for each handler class
        # Init different defaults
        botConfig = configManager.getBotConfig()
        defaultSettings: Dict[ChatSettingsKey, ChatSettingsValue] = {k: ChatSettingsValue("") for k in ChatSettingsKey}
        defaultSettings.update(
            {
                ChatSettingsKey(k): ChatSettingsValue(v)
                for k, v in botConfig.get("defaults", {}).items()
                if k in ChatSettingsKey
            }
        )
        self.cache.setDefaultChatSettings(None, defaultSettings)
        privateDefaultSettings: Dict[ChatSettingsKey, ChatSettingsValue] = {
            ChatSettingsKey(k): ChatSettingsValue(v)
            for k, v in botConfig.get("private-defaults", {}).items()
            if k in ChatSettingsKey
        }
        self.cache.setDefaultChatSettings(ChatType.PRIVATE, privateDefaultSettings)
        chatDefaultSettings: Dict[ChatSettingsKey, ChatSettingsValue] = {
            ChatSettingsKey(k): ChatSettingsValue(v)
            for k, v in botConfig.get("chat-defaults", {}).items()
            if k in ChatSettingsKey
        }
        self.cache.setDefaultChatSettings(ChatType.GROUP, chatDefaultSettings)

        # Initialize handlers
        self.handlers: List[BaseBotHandler] = [
            # Should be first to check for spam before other handlers
            SpamHandler(configManager, database, llmManager, botProvider),
            # Should be before MessagePreprocessorHandler to not save configuration answers
            ConfigureCommandHandler(configManager, database, llmManager, botProvider),
            SummarizationHandler(configManager, database, llmManager, botProvider),
            # Should be before other handlers to ensure message saving + media processing
            MessagePreprocessorHandler(configManager, database, llmManager, botProvider),
            #
            UserDataHandler(configManager, database, llmManager, botProvider),
            DevCommandsHandler(configManager, database, llmManager, botProvider),
            MediaHandler(configManager, database, llmManager, botProvider),
            CommonHandler(configManager, database, llmManager, botProvider),
            # Special case - help command require all command handlers information
            HelpHandler(configManager, database, llmManager, botProvider, self),
        ]

        if self.botProvider == BotProvider.TELEGRAM:
            self.handlers.append(ReactOnUserMessageHandler(configManager, database, llmManager, botProvider))

        # Add WeatherHandler only if OpenWeatherMap integration is enabled
        openWeatherMapConfig = self.configManager.getOpenWeatherMapConfig()
        if openWeatherMapConfig.get("enabled", False):
            self.handlers.append(WeatherHandler(configManager, database, llmManager, botProvider))
        yandexSearchConfig = self.configManager.getYandexSearchConfig()
        if yandexSearchConfig.get("enabled", False):
            self.handlers.append(YandexSearchHandler(configManager, database, llmManager, botProvider))

        self.handlers.append(
            # Should be last messageHandler as it can handle any message
            LLMMessageHandler(configManager, database, llmManager, botProvider)
        )

    def injectBot(self, bot: ExtBot | libMax.MaxBotClient) -> None:
        """Inject bot instance into all registered handlers.

        Args:
            bot: Bot client instance (ExtBot for Telegram or MaxBotClient for Max Messenger)

        Returns:
            None

        Raises:
            ValueError: If bot type doesn't match the configured bot provider
        """
        theBot: Optional[TheBot] = None
        if self.botProvider == BotProvider.TELEGRAM and isinstance(bot, ExtBot):
            theBot = TheBot(botProvider=self.botProvider, config=self.configManager.getBotConfig(), tgBot=bot)
        elif self.botProvider == BotProvider.MAX and isinstance(bot, libMax.MaxBotClient):
            theBot = TheBot(botProvider=self.botProvider, config=self.configManager.getBotConfig(), maxBot=bot)

        if theBot is None:
            raise ValueError("Unexpected bot class")

        for handler in self.handlers:
            handler.injectBot(theBot)

    def getCommandHandlersDict(self, useCache: bool = True) -> Dict[str, CommandHandlerInfoV2]:
        """Get dictionary of all available command handlers.

        Args:
            useCache: If True, return cached commands; if False, rebuild cache

        Returns:
            Dictionary mapping command names to CommandHandlerInfo objects
        """
        # logger.debug(f"gCHD(),p1, commands: {self._commands}")
        if useCache and self._commands:
            return self._commands

        ret: Dict[str, CommandHandlerInfoV2] = {}
        for handler in self.handlers:
            for cmdHandlerInfo in handler.getCommandHandlersV2():
                ret.update({cmd.lower(): cmdHandlerInfo for cmd in cmdHandlerInfo.commands})

        self._commands = ret

        logger.debug(f"Found commands: {self._commands.keys()}")
        return self._commands

    async def parseCommand(self, ensuredMessage: EnsuredMessage) -> Optional[Tuple[str, str]]:
        """Parse message to extract command name and arguments.

        Args:
            ensuredMessage: Message to parse for commands

        Returns:
            Tuple of (command, args) if message contains command, None otherwise
        """
        if not self.handlers:
            # No handlers, no command
            logger.error("No handlers initialized, cannot parse command")
            return None

        messageText = ensuredMessage.messageText
        if not messageText:
            return None
        messageText = messageText.strip()
        if messageText.startswith("/"):
            splittedText = messageText[1:].split(" ", 1)
            command = splittedText[0]
            args = splittedText[1] if len(splittedText) > 1 else ""

            # Check if bot username privided in command and check if it is our username
            splittedCommand = command.split("@")
            command = splittedCommand[0]
            if len(splittedCommand) > 1:
                myUsername = await self.handlers[0].getBotUserName()
                if not myUsername or myUsername.lower() != splittedCommand[1].lower():
                    # TODO: Should we somehow indicate, that it is command but for someone else?
                    logger.debug(
                        f"Recieved command for someone else: {command}, bot: {splittedCommand[1]}, args: {args}"
                    )
                    return None

            logger.debug(f"Recieved command: {command}, args: {args}")
            return command, args

        return None

    async def handleCommand(self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType) -> Optional[bool]:
        """Handle command execution with permission checking.

        Args:
            ensuredMessage: Message containing the command
            updateObj: Original update object from the platform

        Returns:
            None: Not a command
            True: Command handled successfully
            False: Command not handled due to permissions or errors
        """

        commandTouple = await self.parseCommand(ensuredMessage)
        if commandTouple is None:
            return None

        command, args = commandTouple
        commands = self.getCommandHandlersDict()
        commandLower = command.lower()
        if commandLower not in commands:
            logger.debug(f"Unknown command: {command}")
            # TODO: Check if we need to delete unknown commands
            return None

        handlerInfo = commands[commandLower]
        if handlerInfo.boundHandler is None:
            raise ValueError(f"boundHandler is undefined for {handlerInfo}")

        handlerObj = handlerInfo.boundHandler.__self__
        if not isinstance(handlerObj, BaseBotHandler):
            raise RuntimeError(f"Command handler type is {type(handlerObj)} instead of BaseBotHandler")

        logger.debug(f"Got {command}:{args} command: {updateObj}")

        # Check permissions if needed

        isBotOwner = await handlerObj.isAdmin(ensuredMessage.sender, None, allowBotOwners=True)
        chatSettings = handlerObj.getChatSettings(ensuredMessage.recipient.id)
        chatType = ensuredMessage.recipient.chatType

        canProcess = (
            CommandPermission.DEFAULT in handlerInfo.availableFor
            or (CommandPermission.PRIVATE in handlerInfo.availableFor and chatType == ChatType.PRIVATE)
            or (CommandPermission.GROUP in handlerInfo.availableFor and chatType == ChatType.GROUP)
            or (CommandPermission.BOT_OWNER in handlerInfo.availableFor and isBotOwner)
            or (
                CommandPermission.ADMIN in handlerInfo.availableFor
                and chatType == ChatType.GROUP
                and await handlerObj.isAdmin(ensuredMessage.sender, ensuredMessage.recipient)
            )
        )

        if not canProcess:
            logger.warning(
                f"Command `{command}` is not allowed in "
                f"chat {ensuredMessage.recipient} for "
                f"user {ensuredMessage.sender}. Needed permissions: {handlerInfo.availableFor}"
            )
            if chatSettings[ChatSettingsKey.DELETE_DENIED_COMMANDS].toBool():
                try:
                    await handlerObj.deleteMessage(ensuredMessage)
                except Exception as e:
                    logger.error(f"Error while deleting message: {e}")
            return False

        isAdmin = await handlerObj.isAdmin(ensuredMessage.sender, ensuredMessage.recipient)
        match handlerInfo.category:
            case CommandCategory.UNSPECIFIED:
                # No category specified, deny by default
                canProcess = False
            case CommandCategory.PRIVATE:
                canProcess = chatType == ChatType.PRIVATE
            case CommandCategory.ADMIN | CommandCategory.SPAM_ADMIN:
                canProcess = isAdmin
            case CommandCategory.TOOLS:
                # BotOwners could bypass TollsAllowed check
                canProcess = chatSettings[ChatSettingsKey.ALLOW_TOOLS_COMMANDS].toBool() or isBotOwner
            case CommandCategory.SPAM:
                canProcess = isAdmin or chatSettings[ChatSettingsKey.ALLOW_USER_SPAM_COMMAND].toBool()
            case CommandCategory.TECHNICAL:
                # Actually technical command shouldn't present in group chats except of debug purposes, but whatever
                canProcess = isAdmin
            case _:
                logger.error(f"Unhandled command category: {handlerInfo.category}, deny")
                canProcess = False
                pass

        if not canProcess:
            logger.warning(
                f"Command `{str(command)}` is not allowed in "
                f"chat {ensuredMessage.recipient} for "
                f"user {ensuredMessage.sender}. Command category: {handlerInfo.category}."
            )
            if chatSettings[ChatSettingsKey.DELETE_DENIED_COMMANDS].toBool():
                try:
                    await handlerObj.deleteMessage(ensuredMessage)
                except Exception as e:
                    logger.error(f"Error while deleting message: {e}")
            return False

        # Store command message in database
        await handlerObj.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        # Actually handle command
        try:
            if handlerInfo.typingAction is not None:
                async with await handlerObj.startTyping(
                    ensuredMessage, action=handlerInfo.typingAction
                ) as typingManager:
                    await handlerInfo.boundHandler(ensuredMessage, command, args, updateObj, typingManager)
            else:
                await handlerInfo.boundHandler(ensuredMessage, command, args, updateObj, None)

            return True
        except Exception as e:
            logger.error(f"Error while handling command {command}: {e}")
            logger.exception(e)
            if handlerInfo.replyErrorOnException:
                await handlerObj.sendMessage(
                    ensuredMessage,
                    messageText=f"Error while handling command:\n```\n{e}\n```",
                    messageCategory=MessageCategory.BOT_ERROR,
                )
            return False

    async def handleNewMessage(self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType) -> None:
        """Handle new message by routing through handlers in order.

        Args:
            ensuredMessage: Normalized message object
            updateObj: Original update object from the platform
        """
        ensuredMessage.setUserData(
            self.cache.getChatUserData(chatId=ensuredMessage.recipient.id, userId=ensuredMessage.sender.id)
        )

        commandRet = await self.handleCommand(ensuredMessage, updateObj)
        if commandRet is not None:
            logger.debug(f"Handled as command with result: {commandRet}")
            return

        resultSet: Set[HandlerResultStatus] = set()
        for handler in self.handlers:
            ret = await handler.newMessageHandler(ensuredMessage, updateObj)
            resultSet.add(ret)
            match ret:
                case HandlerResultStatus.FINAL:
                    logger.debug(f"Handler {type(handler).__name__} returned FINAL, stop processing")
                    break
                case HandlerResultStatus.SKIPPED:
                    # logger.debug(f"Handler {type(handler).__name__} returned SKIPPED")
                    continue
                case HandlerResultStatus.NEXT:
                    logger.debug(f"Handler {type(handler).__name__} returned NEXT")
                    continue
                case HandlerResultStatus.ERROR:
                    logger.error(f"Handler {type(handler).__name__} returned ERROR")
                    continue
                case HandlerResultStatus.FATAL:
                    logger.error(f"Handler {type(handler).__name__} returned FATAL, stop processing")
                    break
                case _:
                    logger.error(f"Unknown handler result: {ret}")

        logger.debug(
            f"Handled message from {ensuredMessage.sender}: {ensuredMessage.messageText[:50]}... "
            f"(resultSet: {resultSet})"
        )

    async def handleCallback(
        self, ensuredMessage: EnsuredMessage, data: utils.PayloadDict, user: MessageSender, updateObj: UpdateObjectType
    ) -> None:
        """Handle callback query from inline keyboard buttons.

        Args:
            ensuredMessage: Message associated with the callback
            data: Callback data payload
            user: User who triggered the callback
            updateObj: Original update object from the platform
        """

        retSet: Set[HandlerResultStatus] = set()
        for handler in self.handlers:
            ret = await handler.callbackHandler(
                ensuredMessage=ensuredMessage, data=data, user=user, updateObj=updateObj
            )
            retSet.add(ret)
            match ret:
                case HandlerResultStatus.FINAL:
                    logger.debug(f"Handler {type(handler).__name__} returned FINAL, stop processing")
                    break
                case HandlerResultStatus.SKIPPED:
                    # logger.debug(f"Handler {type(handler).__name__} returned SKIPPED")
                    continue
                case HandlerResultStatus.NEXT:
                    logger.debug(f"Handler {type(handler).__name__} returned NEXT")
                    continue
                case HandlerResultStatus.ERROR:
                    logger.error(f"Handler {type(handler).__name__} returned ERROR")
                    continue
                case HandlerResultStatus.FATAL:
                    logger.error(f"Handler {type(handler).__name__} returned FATAL")
                    break
                case _:
                    logger.error(f"Unknown handler result: {ret}")
                    continue

        expectedFinalResults: Set[HandlerResultStatus] = set([HandlerResultStatus.FINAL, HandlerResultStatus.NEXT])
        logger.debug(f"Handled CallbackQuery, resultsSet: {retSet}")
        if not expectedFinalResults.intersection(retSet):
            logger.error(
                f"No handler returned any of ({expectedFinalResults}), but only ({retSet}), something went wrong"
            )
            return
