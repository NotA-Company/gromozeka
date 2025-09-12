"""
Telegram bot application setup and management for Gromozeka.
"""
import logging
import sys
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .handlers import BotHandlers

logger = logging.getLogger(__name__)


class BotApplication:
    """Manages Telegram bot application setup and execution."""
    
    def __init__(self, bot_token: str, database, llm_model):
        """Initialize bot application with token, database, and LLM model."""
        self.bot_token = bot_token
        self.database = database
        self.llm_model = llm_model
        self.application = None
        self.handlers = BotHandlers(database, llm_model)
    
    def setup_handlers(self):
        """Set up bot command and message handlers."""
        if not self.application:
            logger.error("Application not initialized!")
            return

        # Command handlers
        self.application.add_handler(CommandHandler("start", self.handlers.start_command))
        self.application.add_handler(CommandHandler("help", self.handlers.help_command))
        self.application.add_handler(CommandHandler("stats", self.handlers.stats_command))
        self.application.add_handler(CommandHandler("echo", self.handlers.echo_command))

        # Message handler for regular text messages
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handlers.handle_message))

        # Error handler
        self.application.add_error_handler(self.handlers.error_handler)

        logger.info("Bot handlers configured successfully")
    
    def run(self):
        """Start the bot."""
        if self.bot_token in ["", "YOUR_BOT_TOKEN_HERE"]:
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)

        # Create application
        self.application = Application.builder().token(self.bot_token).build()

        # Setup handlers
        self.setup_handlers()

        logger.info("Starting Gromozeka bot, dood!")

        # Start the bot
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)