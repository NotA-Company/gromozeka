"""
Telegram bot application setup and management for Gromozeka.
"""

import asyncio
import logging
import random
import sys
from typing import Any, Awaitable, Dict, Optional
from telegram import Update
import telegram
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    BaseUpdateProcessor,
    CallbackQueryHandler,
)

from lib.ai.manager import LLMManager
from internal.database.wrapper import DatabaseWrapper
from .handlers import BotHandlers

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
        config: Dict[str, Any],
        botToken: str,
        database: DatabaseWrapper,
        llmManager: LLMManager,
    ):
        """Initialize bot application with token, database, and LLM model."""
        self.config = config
        self.botToken = botToken
        self.database = database
        self.llmManager = llmManager
        self.application = None
        self.handlers = BotHandlers(config, database, llmManager)
        self._schedulerTask: Optional[asyncio.Task] = None

    def setupHandlers(self):
        """Set up bot command and message handlers."""
        if not self.application:
            logger.error("Application not initialized!")
            return

        # self.handlers.initDelayedScheduler(self.application.bot)

        # Command handlers
        self.application.add_handler(CommandHandler("start", self.handlers.start_command))
        self.application.add_handler(CommandHandler("help", self.handlers.help_command))
        self.application.add_handler(CommandHandler("echo", self.handlers.echo_command))
        self.application.add_handler(CommandHandler("test", self.handlers.test_command))
        self.application.add_handler(CommandHandler("pretrain_bayes", self.handlers.pretrain_bayes_command))
        self.application.add_handler(CommandHandler("list_chats", self.handlers.list_chats_command))
        self.application.add_handler(CommandHandler(["learn_spam", "learn_ham"], self.handlers.learn_spam_ham_command))
        self.application.add_handler(CommandHandler("get_spam_score", self.handlers.get_spam_score_command))

        self.application.add_handler(CommandHandler(["summary", "topic_summary"], self.handlers.summary_command))
        self.application.add_handler(CommandHandler("analyze", self.handlers.analyze_command))
        self.application.add_handler(CommandHandler("draw", self.handlers.draw_command))
        self.application.add_handler(CommandHandler("remind", self.handlers.remind_command))

        self.application.add_handler(CommandHandler("get_my_data", self.handlers.get_my_data_command))
        self.application.add_handler(CommandHandler("delete_my_data", self.handlers.delete_my_data_command))
        self.application.add_handler(CommandHandler("clear_my_data", self.handlers.clear_my_data_command))

        self.application.add_handler(CommandHandler("spam", self.handlers.spam_command))

        self.application.add_handler(CommandHandler("models", self.handlers.models_command))
        self.application.add_handler(CommandHandler("settings", self.handlers.chat_settings_command))
        self.application.add_handler(CommandHandler(["set", "unset"], self.handlers.set_or_unset_chat_setting_command))
        self.application.add_handler(CommandHandler("configure", self.handlers.configure_command))
        self.application.add_handler(CallbackQueryHandler(self.handlers.handle_button))

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
        self.application.add_handler(
            MessageHandler(
                filters.TEXT | filters.PHOTO | filters.Sticker.ALL & ~filters.COMMAND,
                self.handlers.handle_message,
            )
        )
        # self.application.add_handler(MessageHandler(filters.PHOTO, self.handlers.handle_photo))
        self.application.add_handler(MessageHandler(filters.VIA_BOT, self.handlers.handle_bot))

        # Error handler
        self.application.add_error_handler(self.handlers.error_handler)

        logger.info("Bot handlers configured successfully")

    async def postInit(self, application: Application):
        """Post-initialization tasks."""
        if self.application is None:
            raise RuntimeError("Application not initialized")

        self._schedulerTask = asyncio.create_task(self.handlers.initDelayedScheduler(self.application.bot))

        # Configure Commands
        DefaultCommands = []
        ChatCommands = []
        ChatAdminCommands = [
            ("/spam", "Mark message as spam"),
        ]
        PrivateCommands = [
            ("/configure", "Start bot configuration"),
            ("/help", "Print help"),
            ("/start", "Start bot interaction"),
            ("/draw", "Generate image by given prompt"),
            ("/analyze", "Analyze media in answered message by given prompt"),
            ("/remind", "Remind after given time (HH:MM[:SS] or DDdHHhMMmSSs)"),
            ("/summary", "Summarisation of chat's messages for a day"),
            ("/topic_summary", "Summarisation of topic's messages for a day"),
            ("/list_chats", "List known chats"),
            ("/get_spam_score", "Check if bot think this message is spam or not"),
        ]

        await self.application.bot.set_my_commands(commands=DefaultCommands, scope=telegram.BotCommandScopeDefault())
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
        await self.handlers.initExit()
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
