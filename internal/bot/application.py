"""
Telegram bot application setup and management for Gromozeka.
"""

import asyncio
import logging
import random
import sys
from typing import Awaitable, Dict, List, Optional

import telegram
from telegram import Update
from telegram.ext import (
    Application,
    BaseUpdateProcessor,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from internal.bot.models import CommandCategory
from internal.services.queue.service import QueueService
from lib.ai.manager import LLMManager

from ..config.manager import ConfigManager
from ..database.wrapper import DatabaseWrapper
from .handlers import HandlersManager

logger = logging.getLogger(__name__)


class PerTopicUpdateProcessor(BaseUpdateProcessor):
    """Update processor that processes updates parallel for each chatId + topicId"""

    async def initialize(self) -> None:
        self.chatTopicMap: Dict[str, asyncio.Semaphore] = {}

    async def shutdown(self) -> None:
        pass

    async def do_process_update(self, update, coroutine: Awaitable) -> None:
        # This method is called for every update
        if not isinstance(update, Update):
            logger.error(f"Invalid update type: {type(update)}")
            await coroutine
            return

        chatId = None
        topicId = None
        if update.message:
            chatId = update.message.chat_id
            if update.message.is_topic_message:
                topicId = update.message.message_thread_id

        key = f"{chatId}_{topicId}"
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


class BotApplication:
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
        self.handlerManager = HandlersManager(configManager, database, llmManager)
        self.queueService = QueueService.getInstance()
        self._schedulerTask: Optional[asyncio.Task] = None

    def setupHandlers(self):
        """Set up bot command and message handlers."""
        if not self.application:
            logger.error("Application not initialized!")
            return

        # self.handlers.initDelayedScheduler(self.application.bot)

        # Command handlers
        for commandInfo in self.handlerManager.getCommandHandlers():
            self.application.add_handler(CommandHandler(commandInfo.commands, commandInfo.handler))

        # Buttons
        self.application.add_handler(CallbackQueryHandler(self.handlerManager.handle_button))

        # Message handler for regular text messages
        # See
        # https://docs.python-telegram-bot.org/en/stable/telegram.ext.filters.html#module-telegram.ext.filters
        # for more information about filters
        # Read
        # https://github.com/python-telegram-bot/python-telegram-bot/wiki/Working-with-Files-and-Media
        # For more about working with media
        # Usefull filters
        # PHOTO, VIDEO, AUDIO, DOCUMENT, Sticker.ALL, VOICE, ANIMATION
        # ANIMATION  - https://docs.python-telegram-bot.org/en/stable/telegram.animation.html#telegram.Animation
        # AUDIO      - https://docs.python-telegram-bot.org/en/stable/telegram.audio.html#telegram.Audio
        # CHAT_PHOTO - https://docs.python-telegram-bot.org/en/stable/telegram.chatphoto.html#telegram.ChatPhoto
        # DOCUMENT   - https://docs.python-telegram-bot.org/en/stable/telegram.document.html#telegram.Document
        # PHOTO      - https://docs.python-telegram-bot.org/en/stable/telegram.photosize.html#telegram.PhotoSize
        # STICKER    - https://docs.python-telegram-bot.org/en/stable/telegram.sticker.html#telegram.Sticker
        # VIDEO      - https://docs.python-telegram-bot.org/en/stable/telegram.video.html#telegram.Video
        # VideoNote  - https://docs.python-telegram-bot.org/en/stable/telegram.videonote.html#telegram.VideoNote
        # VOICE      - https://docs.python-telegram-bot.org/en/stable/telegram.voice.html#telegram.Voice
        self.application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, self.handlerManager.handle_message))

        # self.application.add_handler(MessageHandler(filters.VIA_BOT, self.handlers.handle_bot))

        # Error handler
        self.application.add_error_handler(self.handlerManager.error_handler)

        logger.info("Bot handlers configured successfully")

    async def postInit(self, application: Application):
        """Post-initialization tasks."""
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
        sortedHandlers = sorted(self.handlerManager.getCommandHandlers(), key=lambda h: (h.order, h.commands[0]))

        for commandInfo in sortedHandlers:
            if CommandCategory.HIDDEN in commandInfo.categories:
                continue

            botCommandList: List[telegram.BotCommand] = []
            description = commandInfo.shortDescription
            if len(description) > telegram.BotCommand.MAX_DESCRIPTION:
                description = description[: telegram.BotCommand.MAX_DESCRIPTION - 3] + "..."
            for command in commandInfo.commands:
                botCommandList.append(telegram.BotCommand(command, description))

            if CommandCategory.DEFAULT in commandInfo.categories:
                DefaultCommands.extend(botCommandList)
                continue
            if CommandCategory.PRIVATE in commandInfo.categories:
                PrivateCommands.extend(botCommandList)
            if CommandCategory.GROUP in commandInfo.categories:
                ChatCommands.extend(botCommandList)
            if CommandCategory.ADMIN in commandInfo.categories:
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

        await self.application.bot.set_my_commands(commands=DefaultCommands, scope=telegram.BotCommandScopeDefault())
        await application.bot.set_my_commands(commands=DefaultCommands, scope=telegram.BotCommandScopeDefault())
        await self.application.bot.set_my_commands(
            commands=DefaultCommands + PrivateCommands, scope=telegram.BotCommandScopeAllPrivateChats()
        )
        await self.application.bot.set_my_commands(
            commands=DefaultCommands + ChatCommands, scope=telegram.BotCommandScopeAllGroupChats()
        )
        await self.application.bot.set_my_commands(
            commands=DefaultCommands + ChatCommands + ChatAdminCommands,
            scope=telegram.BotCommandScopeAllChatAdministrators(),
        )
        # * :class:`telegram.BotCommandScopeAllChatAdministrators`

    async def postStop(self, application: Application) -> None:
        """
        See https://docs.python-telegram-bot.org/en/stable/telegram.ext.applicationbuilder.html#telegram.ext.ApplicationBuilder.post_stop
        for details
        """  # noqa: E501

        logger.info("Application stopping, stopping Delayed Tasks Scheduler...")
        await self.queueService.beginShutdown()
        logger.info("Step 1 of shutdown is done...")
        if self._schedulerTask is not None:
            await self._schedulerTask
        logger.info("Step 2 of shutdown is done...")

    def run(self):
        """Start the bot."""
        if self.botToken in ["", "YOUR_BOT_TOKEN_HERE"]:
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)

        random.seed()

        # Create application
        self.application = (
            Application.builder()
            .token(self.botToken)
            .concurrent_updates(PerTopicUpdateProcessor(128))
            .post_init(self.postInit)
            .post_stop(self.postStop)
            .build()
        )

        # Setup handlers
        self.setupHandlers()

        logger.info("Starting Gromozeka bot, dood!")

        # Start the bot
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)
