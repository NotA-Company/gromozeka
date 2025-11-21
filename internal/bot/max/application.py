"""
Max Messenger bot application setup and management for Gromozeka.
"""

import asyncio
import logging
import random
import sys
from typing import Optional

import lib.max_bot as maxBot
import lib.max_bot.models as maxModels
from internal.bot.common.handlers.manager import HandlersManager
from internal.bot.models import BotProvider, EnsuredMessage
from internal.bot.models.ensured_message import MessageSender
from internal.config.manager import ConfigManager
from internal.database.wrapper import DatabaseWrapper
from internal.services.queue_service.service import QueueService
from lib import utils
from lib.ai import LLMManager

# from lib import utils
from lib.rate_limiter import RateLimiterManager

logger = logging.getLogger(__name__)


class MaxBotApplication:
    """Manages Max Messenger bot application setup and execution."""

    def __init__(
        self,
        configManager: ConfigManager,
        botToken: str,
        database: DatabaseWrapper,
        llmManager: LLMManager,
    ):
        """Initialize Max bot application with token, database, and LLM model.

        Args:
            configManager: Configuration manager instance
            botToken: Max bot token for authentication
            database: Database wrapper for data persistence
            llmManager: LLM manager for language model operations
        """
        self.configManager = configManager
        self.botToken = botToken
        self.database = database
        self.llmManager = llmManager

        self.handlerManager = HandlersManager(configManager, database, llmManager, BotProvider.MAX)
        self.queueService = QueueService.getInstance()
        self._schedulerTask: Optional[asyncio.Task] = None
        self.client: Optional[maxBot.MaxBotClient] = None

    async def postInit(self, *args, **kwargs):
        """Perform post-initialization tasks.

        Args:
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments
        """
        if self.client is None:
            raise RuntimeError("Client is not initialized")

        self.handlerManager.injectMaxBot(self.client)
        self._schedulerTask = asyncio.create_task(self.queueService.startDelayedScheduler(self.database))

        # TODO: set commands

    async def postStop(self, *args, **kwargs) -> None:
        """Handle application shutdown cleanup.

        Args:
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments
        """
        logger.info("Application stopping, stopping Delayed Tasks Scheduler...")
        await self.queueService.beginShutdown()
        logger.info("Step 1 of shutdown is done...")

        if self._schedulerTask is not None:
            await self._schedulerTask
        logger.info("Step 2 of shutdown is done...")

        # Destroy rate limiters
        # TODO: should we move it into doExit handler?
        logger.info("Destroying rate limiters...")
        manager = RateLimiterManager.getInstance()
        await manager.destroy()
        logger.info("Rate limiters destroyed...")

    def run(self):
        """Start the Max Messenger bot application."""
        if self.botToken in ["", "YOUR_BOT_TOKEN_HERE"]:
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)

        random.seed()

        logger.info("Starting Gromozeka Max bot, dood!")

        # Start the bot
        asyncio.run(self._runPolling())

    async def maxHandler(self, update: maxModels.Update) -> None:
        """Handle incoming Max Messenger updates.

        Args:
            update: Max Messenger update object
        """
        logger.debug(f"Handling Update#{update.update_type}@{update.timestamp}")
        if self.client is None:
            raise RuntimeError("Client is not initialized")

        if isinstance(update, maxModels.MessageCreatedUpdate):
            logger.debug("It's new message, processing...")
            ensuredMessage = EnsuredMessage.fromMaxMessage(update.message)

            # TODO: Add some parallelism support via asyncio.task(...)
            return await self.handlerManager.handleNewMessage(ensuredMessage=ensuredMessage, updateObj=update)

        elif isinstance(update, maxModels.MessageCallbackUpdate):
            logger.debug("It's callback, processing...")
            if update.message is None:
                logger.debug(f"Message is None in {update}, ignoring...")
                return
            if update.callback.payload is None:
                logger.debug("Callback payload is None in {update}, ignoring...")
                return

            ensuredMessage = EnsuredMessage.fromMaxMessage(update.message)
            payload = utils.unpackDict(update.callback.payload)
            userName = update.callback.user.first_name
            if update.callback.user.last_name:
                userName += " " + update.callback.user.last_name
            user = MessageSender(
                update.callback.user.user_id,
                name=userName,
                username=update.callback.user.username or "",
            )

            # TODO: self.client.answerCallbackQuery()
            return await self.handlerManager.handleCallback(
                ensuredMessage=ensuredMessage, data=payload, user=user, updateObj=update
            )

        else:
            logger.debug(f"Unsupported Update: {update}, ignoring for now...")

    async def maxExceptionHandler(self, exception: Exception) -> None:
        """Handle exceptions from Max Messenger bot.

        Args:
            exception: Exception that occurred during bot operation
        """
        logger.error(f"Unhandler MAX exception {type(exception).__name__}")
        logger.exception(exception)

    async def _runPolling(self):
        """Run the Max Messenger bot polling loop."""

        self.client = maxBot.MaxBotClient(self.botToken)

        try:
            botInfo = await self.client.getMyInfo()
            logger.debug(botInfo)

            await self.postInit()
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
            await self.postStop()
            await self.client.aclose()
