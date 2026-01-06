"""
Telegram bot application setup and management for Gromozeka.
"""

import asyncio
import logging
import random
import sys
from typing import Awaitable, Dict, List, Optional

import telegram
from telegram.ext import (
    Application,
    BaseUpdateProcessor,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from internal.bot.common.handlers import HandlersManager
from internal.bot.models import BotProvider, CommandPermission, EnsuredMessage, MessageSender
from internal.bot.models.ensured_message import MessageRecipient
from internal.config.manager import ConfigManager
from internal.database.wrapper import DatabaseWrapper
from internal.services.queue_service.service import QueueService
from lib import utils
from lib.ai import LLMManager
from lib.rate_limiter import RateLimiterManager

logger = logging.getLogger(__name__)


class PerTopicUpdateProcessor(BaseUpdateProcessor):
    """Update processor that processes updates parallel for each chatId + topicId"""

    async def initialize(self) -> None:
        """Initialize the update processor with empty chat-topic mapping."""
        self.chatTopicMap: Dict[str, asyncio.Semaphore] = {}

    async def shutdown(self) -> None:
        """Clean up resources when shutting down the processor."""
        pass

    async def do_process_update(self, update, coroutine: Awaitable) -> None:
        # This method is called for every update
        if not isinstance(update, telegram.Update):
            logger.error(f"Invalid update type: {type(update)}")
            await coroutine
            return

        chatId = None
        topicId = None
        if update.message:
            chatId = update.message.chat_id
            if update.message.is_topic_message:
                topicId = update.message.message_thread_id

        key = f"{chatId}:{topicId}"
        # logger.debug(f"Processing update for chatId: {chatId}, topicId: {topicId}")

        topicSemaphore = self.chatTopicMap.get(key, None)
        if not isinstance(topicSemaphore, asyncio.Semaphore):
            topicSemaphore = asyncio.BoundedSemaphore(1)
            self.chatTopicMap[key] = topicSemaphore

        async with topicSemaphore:
            # logger.debug(f"awaiting corutine for chatId: {chatId}, topicId: {topicId}")
            try:
                # Each request should be processed for at most 30 minutes
                # Just to workaround diffetent stucks in externat services\libs
                await asyncio.wait_for(coroutine, 60 * 30)
            except Exception as e:
                logger.error(f"Error during awaiting coroutine for {update}")
                logger.exception(e)


class TelegramBotApplication:
    """Manages Telegram bot application setup and execution."""

    def __init__(
        self,
        configManager: ConfigManager,
        botToken: str,
        database: DatabaseWrapper,
        llmManager: LLMManager,
    ):
        """Initialize Telegram bot application.

        Args:
            configManager: Configuration manager instance
            botToken: Telegram bot token for authentication
            database: Database wrapper for data persistence
            llmManager: LLM manager for language model operations
        """
        self.configManager = configManager
        self.botToken = botToken
        self.database = database
        self.llmManager = llmManager
        self.application = None
        self.handlerManager = HandlersManager(configManager, database, llmManager, BotProvider.TELEGRAM)
        self.queueService = QueueService.getInstance()
        self._schedulerTask: Optional[asyncio.Task] = None

    async def messageHandler(self, update: telegram.Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle regular text messages."""
        logger.debug(f"Handling Update#{update.update_id}")

        if update.message is not None:
            message = update.message
            if message.new_chat_members is not None:
                logger.debug(f"New chat members: {update}")
                targetChat = MessageRecipient.fromTelegramChat(message.chat)
                messageId = message.message_id
                for newMember in message.new_chat_members:

                    await self.handlerManager.handleNewChatMember(
                        targetChat=targetChat,
                        messageId=messageId,
                        newMember=MessageSender.fromTelegramUser(newMember),
                        updateObj=update,
                    )
                return

            # It's new message
            logger.debug(f"Message: {utils.dumpTelegramMessage(message)}")

            ensuredMessage: Optional[EnsuredMessage] = None
            try:
                ensuredMessage = EnsuredMessage.fromTelegramMessage(message)
            except Exception as e:
                logger.error(f"Error while ensuring message {message}")
                logger.exception(e)
                return

            return await self.handlerManager.handleNewMessage(ensuredMessage=ensuredMessage, updateObj=update)
        # elif ...
        else:
            logger.debug(f"Unsupported update: {update}, ignoring for now...")

    async def callbackHandler(self, update: telegram.Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button presses."""

        logger.debug(f"callback update: {update}")

        query = update.callback_query
        if query is None:
            logger.error(f"CallbackQuery is undefined in {update}")
            return

        # CallbackQueries need to be answered, even if no notification to the user is needed
        # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
        # await query.answer(text=query.data)
        # TODO: Answer something cool
        await query.answer()

        message = query.message
        if message is None:
            logger.error(f"Message is None in {query}")
            return

        if not isinstance(message, telegram.Message):
            logger.error(f"Message is not a Message in {query}")
            return

        if query.data is None:
            logger.error(f"CallbackQuery data undefined in {query}")
            return
        payload = utils.unpackDict(query.data)

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromTelegramMessage(message)
        except Exception as e:
            logger.error(f"Unable to ensure Telegram message {message}")
            logger.exception(e)
            return

        userUsername = ""
        if query.from_user.username:
            userUsername = f"@{query.from_user.username}"
        user = MessageSender(
            id=query.from_user.id,
            name=query.from_user.full_name,
            username=userUsername,
        )

        return await self.handlerManager.handleCallback(
            ensuredMessage=ensuredMessage, data=payload, user=user, updateObj=update
        )

    async def errorHandler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors."""
        logger.error(f"Unhandled exception while handling an update: {type(context.error).__name__}#{context.error}")
        logger.error(f"UpdateObj is: {update}")
        logger.exception(context.error)

    def setupHandlers(self):
        """Set up bot command and message handlers."""
        if not self.application:
            logger.error("Application not initialized!")
            return

        # self.handlers.initDelayedScheduler(self.application.bot)

        # Do not process commands separately, use MessageHandler
        # Command handlers
        # for commandInfo in self.handlerManager.getCommandHandlers():
        #     self.application.add_handler(CommandHandler(commandInfo.commands, commandInfo.handler))

        # Buttons
        self.application.add_handler(CallbackQueryHandler(self.callbackHandler))

        # Message handler for regular text messages
        # See
        # https://docs.python-telegram-bot.org/en/stable/telegram.ext.filters.html#module-telegram.ext.filters
        # for more information about filters
        # Read
        # https://github.com/python-telegram-bot/python-telegram-bot/wiki/Working-with-Files-and-Media
        # For more about working with media
        self.application.add_handler(MessageHandler(filters.ALL, self.messageHandler))

        # Error handler
        self.application.add_error_handler(self.errorHandler)

        logger.info("Bot handlers configured successfully")

    async def postInit(self, application: Application):
        """Perform post-initialization tasks.

        Args:
            application: Telegram application instance
        """
        if self.application is None:
            raise RuntimeError("Application not initialized")

        self.handlerManager.injectBot(application.bot)
        self._schedulerTask = asyncio.create_task(self.queueService.startDelayedScheduler(self.database))

        # Configure Commands
        DefaultCommands = []
        ChatCommands = []
        ChatAdminCommands = []
        PrivateCommands = []

        # Sort command handlers by order, then by command name
        sortedHandlers = sorted(
            self.handlerManager.getCommandHandlersDict().values(), key=lambda h: (h.helpOrder, h.commands[0])
        )

        for commandInfo in sortedHandlers:
            if CommandPermission.HIDDEN in commandInfo.visibility:
                continue

            botCommandList: List[telegram.BotCommand] = []
            description = commandInfo.shortDescription
            if len(description) > telegram.BotCommand.MAX_DESCRIPTION:
                description = description[: telegram.BotCommand.MAX_DESCRIPTION - 3] + "..."
            for command in commandInfo.commands:
                if utils.checkIfProperCommandName(command):
                    botCommandList.append(telegram.BotCommand(command, description))

            if CommandPermission.DEFAULT in commandInfo.visibility:
                DefaultCommands.extend(botCommandList)
                continue
            if CommandPermission.PRIVATE in commandInfo.visibility:
                PrivateCommands.extend(botCommandList)
            if CommandPermission.GROUP in commandInfo.visibility:
                ChatCommands.extend(botCommandList)
            if CommandPermission.ADMIN in commandInfo.visibility:
                ChatAdminCommands.extend(botCommandList)

        logger.debug(
            "Commands configured: "
            f"{len(DefaultCommands)} default, "
            f"{len(PrivateCommands)} private, "
            f"{len(ChatCommands)} group, "
            f"{len(ChatAdminCommands)} admin"
        )
        logger.debug(f"DefaultCommands: {DefaultCommands}")
        logger.debug(f"PrivateCommands: {PrivateCommands}")
        logger.debug(f"ChatCommands: {ChatCommands}")
        logger.debug(f"ChatAdminCommands: {ChatAdminCommands}")

        await self.application.bot.set_my_commands(
            commands=DefaultCommands,
            scope=telegram.BotCommandScopeDefault(),
        )
        await self.application.bot.set_my_commands(
            commands=DefaultCommands + PrivateCommands,
            scope=telegram.BotCommandScopeAllPrivateChats(),
        )
        await self.application.bot.set_my_commands(
            commands=DefaultCommands + ChatCommands,
            scope=telegram.BotCommandScopeAllGroupChats(),
        )
        await self.application.bot.set_my_commands(
            commands=DefaultCommands + ChatCommands + ChatAdminCommands,
            scope=telegram.BotCommandScopeAllChatAdministrators(),
        )
        # * :class:`telegram.BotCommandScopeAllChatAdministrators`

    async def postStop(self, application: Application) -> None:
        """Handle application shutdown cleanup.

        See https://docs.python-telegram-bot.org/en/stable/telegram.ext.applicationbuilder.html#telegram.ext.ApplicationBuilder.post_stop
        for details

        Args:
            application: Telegram application instance
        """  # noqa: E501

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
        """Start the Telegram bot application."""
        if self.botToken in ["", "YOUR_BOT_TOKEN_HERE"]:
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)

        random.seed()

        botConfig = self.configManager.getBotConfig()

        appBuilder = (
            Application.builder()
            .token(self.botToken)
            .concurrent_updates(PerTopicUpdateProcessor(128))
            .post_init(self.postInit)
            .post_stop(self.postStop)
            .local_mode(botConfig.get("localMode", False))
        )

        baseUrl = botConfig.get("baseUrl", None)
        if baseUrl is not None:
            appBuilder = appBuilder.base_url(baseUrl)
            logger.info(f"Base URL set to {baseUrl}")

        # Create application
        self.application = appBuilder.build()

        # Setup handlers
        self.setupHandlers()

        logger.info("Starting Gromozeka Telegram bot, dood!")

        # Start the bot
        self.application.run_polling(allowed_updates=telegram.Update.ALL_TYPES)
