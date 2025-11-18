"""
Bot handlers manager
"""

import logging
from typing import List, Optional, Sequence, Set

import telegram
from telegram.ext import ContextTypes, ExtBot

import lib.max_bot as maxBot

# import lib.max_bot.models as maxModels
from internal.bot.common.models import UpdateObjectType
from internal.bot.models import BotProvider, CommandHandlerInfo, EnsuredMessage
from internal.config.manager import ConfigManager
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
    Bot handlers manager
    """

    def __init__(
        self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager, botProvider: BotProvider
    ):
        self.configManager = configManager
        self.db = database
        self.llmManager = llmManager
        self.botProvider: BotProvider = botProvider

        self.cache = CacheService.getInstance()
        self.cache.injectDatabase(self.db)

        self.queueService = QueueService.getInstance()

        self.handlers: List[BaseBotHandler] = [
            # Should be first to check for spam before other handlers
            SpamHandler(configManager, database, llmManager, botProvider),
            # Should be before MessagePreprocessorHandler to not save configuration answers
            ConfigureCommandHandler(configManager, database, llmManager, botProvider),
            SummarizationHandler(configManager, database, llmManager, botProvider),
            # Should be before other handlers to ensure message saving + media processing
            MessagePreprocessorHandler(configManager, database, llmManager, botProvider),
            #
            ReactOnUserMessageHandler(configManager, database, llmManager, botProvider),
            #
            UserDataHandler(configManager, database, llmManager, botProvider),
            DevCommandsHandler(configManager, database, llmManager, botProvider),
            MediaHandler(configManager, database, llmManager, botProvider),
            CommonHandler(configManager, database, llmManager, botProvider),
            # Special case - help command require all command handlers information
            HelpHandler(configManager, database, llmManager, botProvider, self),
        ]

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

    def injectTGBot(self, bot: ExtBot) -> None:
        for handler in self.handlers:
            handler.injectTGBot(bot)

    def injectMaxBot(self, bot: maxBot.MaxBotClient):
        for handler in self.handlers:
            handler.injectMaxBot(bot)

    def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
        ret: List[CommandHandlerInfo] = []
        for handler in self.handlers:
            ret.extend(handler.getCommandHandlers())
        return ret

    async def handleNewMessage(self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType) -> None:
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

    async def handle_message(self, update: telegram.Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle regular text messages."""
        logger.debug(f"Handling message Update#{update.update_id}")

        ensuredMessage: Optional[EnsuredMessage] = None
        message = update.message
        if not message:
            # Not new message, ignore
            logger.warning(f"Message undefined in {update}")
        else:
            # logger.debug(f"Message: {message}")
            logger.debug(f"Message: {utils.dumpTelegramMessage(message)}")
            try:
                ensuredMessage = EnsuredMessage.fromTelegramMessage(message)
                ensuredMessage.setUserData(
                    self.cache.getChatUserData(chatId=ensuredMessage.recipient.id, userId=ensuredMessage.sender.id)
                )
            except Exception as e:
                logger.error(f"Error while ensuring message {message}")
                logger.exception(e)

        resultSet: Set[HandlerResultStatus] = set()
        for handler in self.handlers:
            ret = await handler.messageHandler(update, context, ensuredMessage)
            if ret == HandlerResultStatus.SKIPPED and ensuredMessage is not None:
                logger.debug(f"Handler {type(handler).__name__} returned SKIPPED, trying newMessageHandler")
                ret = await handler.newMessageHandler(ensuredMessage, update)
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

        if ensuredMessage:
            logger.debug(
                f"Handled message from {ensuredMessage.sender}: {ensuredMessage.messageText[:50]}... "
                f"(resultSet: {resultSet})"
            )
        else:
            logger.debug(f"Handled not-a-message: #{update.update_id}, resultSet: {resultSet})")

    async def handle_button(self, update: telegram.Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button presses."""
        logger.debug(f"handle_button: {update}")

        query = update.callback_query
        if query is None:
            logger.error(f"CallbackQuery undefined in {update}")
            return

        # CallbackQueries need to be answered, even if no notification to the user is needed
        # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
        # await query.answer(text=query.data)
        # TODO: Answer something cool
        await query.answer()

        if query.data is None:
            logger.error(f"CallbackQuery data undefined in {query}")
            return

        data = utils.unpackDict(query.data)

        if query.message is None:
            logger.error(f"handle_button: message is None in {query}")
            return

        if not isinstance(query.message, telegram.Message):
            logger.error(f"handle_button: message is not a Message in {query}")
            return

        retSet: Set[HandlerResultStatus] = set()
        for handler in self.handlers:
            ret = await handler.buttonHandler(update, context, data)
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

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors."""
        logger.error(f"Unhandled exception while handling an update: {type(context.error).__name__}#{context.error}")
        logger.error(f"UpdateObj is: {update}")
        logger.exception(context.error)
