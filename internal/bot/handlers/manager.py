"""
Bot handlers manager
"""

import logging
from typing import List, Optional, Sequence

from telegram import Message, Update
from telegram.ext import ExtBot, ContextTypes

from internal.bot.models import CommandHandlerInfo, EnsuredMessage

from internal.cache.service import CacheService
from internal.config.manager import ConfigManager
from internal.database.wrapper import DatabaseWrapper
from internal.services.queue.service import QueueService
from lib import utils
from lib.ai.manager import LLMManager

from .base import BaseBotHandler, HandlerResultStatus
from .main import BotHandlers
from .spam import SpamHandlers
from .help_command import CommandHandlerGetterInterface, HelpHandler

logger = logging.getLogger(__name__)


class HandlersManager(CommandHandlerGetterInterface):
    """
    Bot handlers manager
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        self.configManager = configManager
        self.db = database
        self.llmManager = llmManager

        self.cache = CacheService.getInstance()
        self.cache.injectDatabase(self.db)

        self.queueService = QueueService.getInstance()

        self.handlers: list[BaseBotHandler] = [
            SpamHandlers(configManager, database, llmManager),
            BotHandlers(configManager, database, llmManager),
            HelpHandler(
                configManager, database, llmManager, self
            ),  # Special case - help command require all command handlers information
        ]

    def injectBot(self, bot: ExtBot) -> None:
        for handler in self.handlers:
            handler.injectBot(bot)

    def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
        ret: List[CommandHandlerInfo] = []
        for handler in self.handlers:
            ret.extend(handler.getCommandHandlers())
        return ret

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle regular text messages."""
        logger.debug(f"Handling message Update#{update.update_id}")

        ensuredMessage: Optional[EnsuredMessage] = None
        message = update.message
        if not message:
            # Not new message, ignore
            logger.warning(f"Message undefined in {update}")
        else:
            # logger.debug(f"Message: {message}")
            logger.debug(f"Message: {utils.dumpMessage(message)}")
            try:
                ensuredMessage = EnsuredMessage.fromMessage(message)
                ensuredMessage.setUserData(
                    self.cache.getChatUserData(chatId=ensuredMessage.chat.id, userId=ensuredMessage.user.id)
                )
            except Exception as e:
                logger.error(f"Error while ensuring message: {e}")

        for handler in self.handlers:
            ret = await handler.messageHandler(update, context, ensuredMessage)
            match ret:
                case HandlerResultStatus.FINAL:
                    logger.debug(f"Handler {type(handler).__name__} returned FINAL, stop processing")
                    return
                case HandlerResultStatus.SKIPPED:
                    logger.debug(f"Handler {type(handler).__name__} returned SKIPPED")
                    continue
                case HandlerResultStatus.NEXT:
                    logger.debug(f"Handler {type(handler).__name__} returned NEXT")
                    continue
                case HandlerResultStatus.ERROR:
                    logger.error(f"Handler {type(handler).__name__} returned ERROR")
                    continue
                case HandlerResultStatus.FATAL:
                    logger.error(f"Handler {type(handler).__name__} returned FATAL, stop processing")
                    return
                case _:
                    logger.error(f"Unknown handler result: {ret}")

    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

        if not isinstance(query.message, Message):
            logger.error(f"handle_button: message is not a Message in {query}")
            return

        for handler in self.handlers:
            ret = await handler.buttonHandler(update, context, data)
            match ret:
                case HandlerResultStatus.FINAL:
                    logger.debug(f"Handler {type(handler).__name__} returned FINAL, stop processing")
                    return
                case HandlerResultStatus.SKIPPED:
                    logger.debug(f"Handler {type(handler).__name__} returned SKIPPED")
                    continue
                case HandlerResultStatus.NEXT:
                    logger.debug(f"Handler {type(handler).__name__} returned NEXT")
                    continue
                case HandlerResultStatus.ERROR:
                    logger.error(f"Handler {type(handler).__name__} returned ERROR")
                    continue
                case HandlerResultStatus.FATAL:
                    logger.error(f"Handler {type(handler).__name__} returned FATAL")
                    return
                case _:
                    logger.error(f"Unknown handler result: {ret}")
                    continue

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors."""
        logger.error(f"Unhandled exception while handling an update: {type(context.error).__name__}#{context.error}")
        logger.error(f"UpdateObj is: {update}")
        logger.exception(context.error)
