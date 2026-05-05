"""
Max Messenger bot application setup and management for Gromozeka.
"""

import asyncio
import logging
import random
import sys
from collections.abc import MutableSet
from typing import Optional

import lib.max_bot as libMax
import lib.max_bot.models as maxModels
from internal.bot.common.handlers.manager import HandlersManager
from internal.bot.models import BotProvider, EnsuredMessage
from internal.bot.models.ensured_message import ChatType, MessageRecipient, MessageSender
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.services.queue_service.service import QueueService
from lib import utils
from lib.ai import LLMManager

# from lib import utils
from lib.rate_limiter import RateLimiterManager

logger = logging.getLogger(__name__)


class MaxBotApplication:
    """Manages Max Messenger bot application setup and execution.

    This class provides the main application logic for the Max Messenger bot integration
    in the Gromozeka framework. It handles the complete bot lifecycle including initialization,
    update processing, message handling, and graceful shutdown.

    The application integrates with various services:
    - HandlersManager: Routes incoming updates to appropriate handlers
    - QueueService: Manages delayed task scheduling
    - RateLimiterManager: Controls API request rates
    - Database: Persists bot state and user data
    - LLMManager: Provides language model capabilities

    Attributes:
        configManager: Configuration manager instance for accessing bot settings
        botToken: Max bot authentication token
        database: Database instance for data persistence
        llmManager: LLM manager for language model operations
        handlerManager: Handler manager for routing updates to appropriate handlers
        queueService: Queue service for managing delayed tasks
        _schedulerTask: Async task for the delayed message scheduler
        maxBot: Max bot client instance for API communication
        _tasks: Set of active async tasks managed by the application
        maxTasks: Maximum number of concurrent tasks allowed (default: 128)
    """

    def __init__(
        self,
        configManager: ConfigManager,
        botToken: str,
        database: Database,
        llmManager: LLMManager,
    ):
        """Initialize Max bot application with token, database, and LLM model.

        Args:
            configManager: Configuration manager instance for accessing bot settings
            botToken: Max bot token for authentication with Max Messenger API
            database: Database object for data persistence and state management
            llmManager: LLM manager for language model operations and AI features
        """
        self.configManager = configManager
        self.botToken = botToken
        self.database = database
        self.llmManager = llmManager

        self.handlerManager = HandlersManager(configManager, database, llmManager, BotProvider.MAX)
        self.queueService = QueueService.getInstance()
        self._schedulerTask: Optional[asyncio.Task] = None
        self.maxBot: Optional[libMax.MaxBotClient] = None

        self._tasks: MutableSet[asyncio.Task] = set[asyncio.Task]()
        self.maxTasks = 128

    async def postInit(self, *args, **kwargs):
        """Perform post-initialization tasks after bot client is created.

        This method is called after the Max bot client has been initialized and
        before the polling loop starts. It sets up the handler manager and starts
        the delayed message scheduler.

        Args:
            *args: Additional positional arguments (unused, for compatibility)
            **kwargs: Additional keyword arguments (unused, for compatibility)

        Raises:
            RuntimeError: If the Max bot client has not been initialized
        """
        if self.maxBot is None:
            raise RuntimeError("Client is not initialized")

        await self.handlerManager.initialize(self.maxBot)
        self._schedulerTask = asyncio.create_task(self.queueService.startDelayedScheduler(self.database))

        # TODO: set commands

    async def postStop(self, *args, **kwargs) -> None:
        """Handle application shutdown cleanup in a graceful manner.

        This method performs a multi-step shutdown process to ensure all resources
        are properly released and all pending tasks are completed before the
        application exits.

        Shutdown steps:
        1. Wait for all active tasks to complete
        2. Stop the handler manager
        3. Stop the delayed tasks scheduler
        4. Wait for the scheduler task to finish
        5. Destroy all rate limiters

        Args:
            *args: Additional positional arguments (unused, for compatibility)
            **kwargs: Additional keyword arguments (unused, for compatibility)

        Returns:
            None
        """

        logger.info("Application shutting down...")
        logger.info("Step 0: Awaiting for all tasks to complete...")
        while len(self._tasks) > 0:
            await asyncio.sleep(1)
            logger.info(f"{len(self._tasks)} tasks left...")

        logger.info("Step 1: Stopping HandlerManager...")
        await self.handlerManager.shutdown()
        logger.info("Step 2: Stopping Delayed Tasks Scheduler...")
        await self.queueService.beginShutdown()

        logger.info("Step 3: Waiting for delayed scheduler task...")
        if self._schedulerTask is not None:
            await self._schedulerTask

        # Destroy rate limiters
        # TODO: should we move it into doExit handler?
        logger.info("Step 4: Destroying rate limiters...")
        manager = RateLimiterManager.getInstance()
        await manager.destroy()
        logger.info("Rate limiters destroyed...")

    def run(self):
        """Start the Max Messenger bot application.

        This is the main entry point for running the Max bot. It validates the
        bot token, initializes the random number generator, and starts the
        async polling loop.

        Raises:
            SystemExit: If the bot token is not configured or is invalid
        """
        if self.botToken in ["", "YOUR_BOT_TOKEN_HERE"]:
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)

        random.seed()

        logger.info("Starting Gromozeka Max bot, dood!")

        # Start the bot
        asyncio.run(self._runPolling())

    async def maxHandler(self, update: maxModels.Update) -> None:
        """Handle incoming Max Messenger updates and route them to appropriate handlers.

        This method is the main entry point for processing updates from Max Messenger.
        It determines the type of update and routes it to the appropriate handler method
        in the handler manager.

        Supported update types:
        - MessageCreatedUpdate: New messages in chats
        - UserAddedToChatUpdate: Users added to groups/channels
        - UserRemovedFromChatUpdate: Users removed from groups/channels
        - MessageCallbackUpdate: Callback queries from inline keyboards

        Args:
            update: Max Messenger update object containing the event data

        Raises:
            RuntimeError: If the Max bot client has not been initialized

        Returns:
            None
        """
        logger.debug(f"Handling Update#{update.update_type}@{update.timestamp}")
        if self.maxBot is None:
            raise RuntimeError("Client is not initialized")

        if isinstance(update, maxModels.MessageCreatedUpdate):
            logger.debug("It's new message, processing...")
            ensuredMessage = EnsuredMessage.fromMaxMessage(update.message)

            return await self.handlerManager.handleNewMessage(ensuredMessage=ensuredMessage, updateObj=update)

        elif isinstance(update, maxModels.UserAddedToChatUpdate):
            logger.debug("It's new chat member, processing...")

            return await self.handlerManager.handleNewChatMember(
                targetChat=MessageRecipient(
                    id=update.chat_id,
                    chatType=ChatType.CHANNEL if update.is_channel else ChatType.GROUP,
                ),
                messageId=None,
                newMember=MessageSender.fromMaxUser(update.user),
                updateObj=update,
            )

        elif isinstance(update, maxModels.UserRemovedFromChatUpdate):
            logger.debug("It's removed chat member, processing...")

            return await self.handlerManager.handleLeftChatMember(
                targetChat=MessageRecipient(
                    id=update.chat_id,
                    chatType=ChatType.CHANNEL if update.is_channel else ChatType.GROUP,
                ),
                messageId=None,
                leftMember=MessageSender.fromMaxUser(update.user),
                updateObj=update,
            )

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

            return await self.handlerManager.handleCallback(
                ensuredMessage=ensuredMessage,
                data=payload,
                user=user,
                updateObj=update,
            )

        else:
            logger.debug(f"Unsupported Update: {update}, ignoring for now...")

    async def maxExceptionHandler(self, exception: Exception) -> None:
        """Handle exceptions from Max Messenger bot operations.

        This method is called when an exception occurs during bot operation,
        such as API errors or unexpected events. It logs the exception details
        for debugging and monitoring purposes.

        Args:
            exception: Exception that occurred during bot operation

        Returns:
            None
        """
        logger.error(f"Unhandled MAX exception {type(exception).__name__}")
        logger.exception(exception)

    async def _runPolling(self):
        """Run the Max Messenger bot polling loop.

        This method initializes the Max bot client, retrieves bot information,
        performs post-initialization setup, and starts the long polling loop
        to receive updates from Max Messenger.

        The polling loop runs indefinitely until interrupted, at which point
        it performs cleanup through the postStop method.

        Raises:
            Exception: Any exceptions that occur during polling are caught
                by the maxExceptionHandler

        Returns:
            None
        """

        self.maxBot = libMax.MaxBotClient(self.botToken)

        try:
            botInfo = await self.maxBot.getMyInfo()
            logger.debug(botInfo)

            await self.postInit()
            logger.info("Start MAX polling....")
            await self.maxBot.startPolling(
                handler=self.maxHandler,
                types=None,
                timeout=30,
                errorHandler=self.maxExceptionHandler,
            )

            # TODO: Somehow allow to await it properly
            if self.maxBot._pollingTask is not None:
                await self.maxBot._pollingTask
            logger.info("After polling...")
        finally:
            logger.info("Work is done, exiting...")
            await self.postStop()
            await self.maxBot.aclose()
