"""
Telegram bot application setup and management for Gromozeka.
"""
import logging
import sys
from typing import Any, Dict
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from ai.manager import LLMManager
from config.manager import ConfigManager
from database.wrapper import DatabaseWrapper

from .handlers import BotHandlers

logger = logging.getLogger(__name__)


class BotApplication:
    """Manages Telegram bot application setup and execution."""

    def __init__(self, config: Dict[str, Any], botToken: str, database: DatabaseWrapper, llmManager: LLMManager):
        """Initialize bot application with token, database, and LLM model."""
        self.config = config
        self.botToken = botToken
        self.database = database
        self.llmManager = llmManager
        self.application = None
        self.handlers = BotHandlers(config, database, llmManager)

    def setupHandlers(self):
        """Set up bot command and message handlers."""
        if not self.application:
            logger.error("Application not initialized!")
            return
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.handlers.start_command))
        self.application.add_handler(CommandHandler("help", self.handlers.help_command))
        self.application.add_handler(CommandHandler("stats", self.handlers.stats_command))
        self.application.add_handler(CommandHandler("echo", self.handlers.echo_command))
        self.application.add_handler(CommandHandler("models", self.handlers.models_command))
        # Chat commands
        self.application.add_handler(CommandHandler("summary", self.handlers.summary_command))
        self.application.add_handler(CommandHandler("settings", self.handlers.chat_settings_command))
        self.application.add_handler(CommandHandler("set", self.handlers.set_chat_setting_command))
        self.application.add_handler(CommandHandler("unset", self.handlers.unset_chat_setting_command))

        # Message handler for regular text messages
        # See
        # https://docs.python-telegram-bot.org/en/stable/telegram.ext.filters.html#module-telegram.ext.filters
        # for more information about filters
        # PHOTO, VIDEO, AUDIO, DOCUMENT, Sticker.ALL, VOICE, ANIMATION
        self.application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO & ~filters.COMMAND, self.handlers.handle_message))
        #self.application.add_handler(MessageHandler(filters.PHOTO, self.handlers.handle_photo))
        self.application.add_handler(MessageHandler(filters.VIA_BOT, self.handlers.handle_bot))


        # Error handler
        self.application.add_error_handler(self.handlers.error_handler)

        logger.info("Bot handlers configured successfully")

    def run(self):
        """Start the bot."""
        if self.botToken in ["", "YOUR_BOT_TOKEN_HERE"]:
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)

        # Create application
        self.application = Application.builder().token(self.botToken).build()

        # Setup handlers
        self.setupHandlers()

        logger.info("Starting Gromozeka bot, dood!")

        # Start the bot
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)