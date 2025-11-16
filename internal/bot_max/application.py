import asyncio
import logging
import random
import sys
from typing import Optional

import lib.max_bot as maxBot
import lib.max_bot.models as maxModels
from internal.config.manager import ConfigManager
from internal.database.wrapper import DatabaseWrapper
from internal.services.queue_service.service import QueueService
from lib.ai import LLMManager

# from lib import utils
# from lib.rate_limiter import RateLimiterManager

logger = logging.getLogger(__name__)


class MaxBotApplication:
    """Manages Telegram bot application setup and execution."""

    def __init__(
        self,
        configManager: ConfigManager,
        botToken: str,
        database: DatabaseWrapper,
        llmManager: LLMManager,
    ):
        """Initialize bot application with token, database, and LLM model."""
        self.configManager = configManager
        self.botToken = botToken
        self.database = database
        self.llmManager = llmManager
        self.application = None
        # self.handlerManager = HandlersManager(configManager, database, llmManager)
        self.queueService = QueueService.getInstance()
        self._schedulerTask: Optional[asyncio.Task] = None
        self.client: Optional[maxBot.MaxBotClient] = None

    def run(self):
        """Start the bot."""
        if self.botToken in ["", "YOUR_BOT_TOKEN_HERE"]:
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)

        random.seed()

        # Create application

        # Setup handlers

        logger.info("Starting Gromozeka Max bot, dood!")

        # Start the bot
        asyncio.run(self._runPolling())

    async def maxHandler(self, update: maxModels.Update) -> None:
        logger.debug(update)
        if isinstance(update, maxModels.MessageCreatedUpdate):
            logger.debug("It's new message, processing...")
            # message = update.message
            # self.database.saveChatMessage()
        else:
            logger.debug(f"It's {type(update).__name__}, ignoring for now...")

    async def maxExceptionHandler(self, exception: Exception) -> None:
        logger.exception(exception)

    async def _runPolling(self):
        """Run the bot polling."""

        self.client = maxBot.MaxBotClient(self.botToken)

        try:
            botInfo = await self.client.getMyInfo()
            logger.debug(botInfo)
            logger.info("Start MAX polling....")
            await self.client.startPolling(
                handler=self.maxHandler,
                types=None,
                timeout=30,
                errorHandler=self.maxExceptionHandler,
            )

            # TODO: Somehow allow to await it properly
            if self.client._pollingTask is not None:
                await self.client._pollingTask
            logger.info("After polling...")
        finally:
            logger.info("Work is done, exiting...")
            await self.client.aclose()
