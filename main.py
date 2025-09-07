"""
Gromozeka - A minimal Telegram bot with TOML configuration and SQLite database.
"""

import logging
import sys
from pathlib import Path
from typing import Dict, Any

try:
    import tomli
except ImportError:
    print("Error: tomli library not found. Please install it with: pip install tomli")
    sys.exit(1)

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from database import DatabaseWrapper

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class GromozekBot:
    """Main bot class that handles configuration, database, and bot logic."""
    
    def __init__(self, config_path: str = "config.toml"):
        self.config = self._load_config(config_path)
        self.db = self._init_database()
        self.application = None
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from TOML file."""
        config_file = Path(config_path)
        if not config_file.exists():
            logger.error(f"Configuration file {config_path} not found!")
            sys.exit(1)
        
        try:
            with open(config_file, "rb") as f:
                config = tomli.load(f)
            
            # Validate required configuration
            if not config.get("bot", {}).get("token"):
                logger.error("Bot token not found in configuration!")
                sys.exit(1)
            
            logger.info("Configuration loaded successfully")
            return config
        
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            sys.exit(1)
    
    def _init_database(self) -> DatabaseWrapper:
        """Initialize database connection."""
        db_config = self.config.get("database", {})
        db_path = db_config.get("path", "bot_data.db")
        max_connections = db_config.get("max_connections", 5)
        timeout = db_config.get("timeout", 30)
        
        try:
            db = DatabaseWrapper(db_path, max_connections, timeout)
            logger.info(f"Database initialized: {db_path}")
            return db
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            sys.exit(1)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command."""
        user = update.effective_user
        
        # Save user to database
        self.db.save_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        
        welcome_message = (
            f"Hello {user.first_name}! 👋\n\n"
            "I'm Gromozeka, your friendly Telegram bot, dood!\n\n"
            "Available commands:\n"
            "/start - Show this welcome message\n"
            "/help - Get help information\n"
            "/stats - Show your statistics\n"
            "/echo <message> - Echo your message back\n\n"
            "Just send me any message and I'll respond, dood!"
        )
        
        await update.message.reply_text(welcome_message)
        logger.info(f"User {user.id} ({user.username}) started the bot")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /help command."""
        help_text = (
            "🤖 *Gromozeka Bot Help*\n\n"
            "*Commands:*\n"
            "/start - Welcome message and bot introduction\n"
            "/help - Show this help message\n"
            "/stats - Display your usage statistics\n"
            "/echo <message> - Echo your message back\n\n"
            "*Features:*\n"
            "• Message logging and statistics\n"
            "• User data persistence\n"
            "• Simple conversation handling\n\n"
            "Just send me any text message and I'll respond, dood!"
        )
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /stats command."""
        user = update.effective_user
        
        # Get user data from database
        user_data = self.db.get_user(user.id)
        messages = self.db.get_user_messages(user.id, limit=100)
        
        if user_data:
            stats_text = (
                f"📊 *Your Statistics*\n\n"
                f"👤 *User:* {user_data['first_name']}\n"
                f"🆔 *ID:* {user_data['user_id']}\n"
                f"📅 *Joined:* {user_data['created_at'][:10]}\n"
                f"💬 *Messages sent:* {len(messages)}\n"
            )
        else:
            stats_text = "No statistics available. Send me a message first!"
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    
    async def echo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /echo command."""
        if context.args:
            echo_text = " ".join(context.args)
            await update.message.reply_text(f"🔄 Echo: {echo_text}")
        else:
            await update.message.reply_text("Please provide a message to echo!\nUsage: /echo <your message>")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle regular text messages."""
        user = update.effective_user
        message_text = update.message.text
        
        # Save user and message to database
        self.db.save_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        self.db.save_message(user.id, message_text)
        
        # Simple response logic
        responses = [
            f"Thanks for your message, {user.first_name}, dood! 🎮",
            f"I heard you loud and clear, dood! 👂",
            f"Interesting message, {user.first_name}! Tell me more, dood! 🤔",
            f"Got it, dood! Anything else you'd like to share? 💭",
            f"Message received and logged, dood! 📝"
        ]
        
        # Simple response based on message length
        if len(message_text) > 50:
            response = f"Wow, that's a long message, dood! I appreciate the detail! 📚"
        elif "hello" in message_text.lower() or "hi" in message_text.lower():
            response = f"Hello there, {user.first_name}! Nice to meet you, dood! 👋"
        elif "?" in message_text:
            response = f"That's a great question, dood! Let me think about it... 🤔"
        else:
            import random
            response = random.choice(responses)
        
        await update.message.reply_text(response)
        logger.info(f"Handled message from {user.id}: {message_text[:50]}...")
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors."""
        logger.error(f"Exception while handling an update: {context.error}")
    
    def setup_handlers(self):
        """Set up bot command and message handlers."""
        if not self.application:
            logger.error("Application not initialized!")
            return
        
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("echo", self.echo_command))
        
        # Message handler for regular text messages
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Error handler
        self.application.add_error_handler(self.error_handler)
        
        logger.info("Bot handlers configured successfully")
    
    def run(self):
        """Start the bot."""
        token = self.config["bot"]["token"]
        
        if token == "YOUR_BOT_TOKEN_HERE":
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)
        
        # Create application
        self.application = Application.builder().token(token).build()
        
        # Setup handlers
        self.setup_handlers()
        
        logger.info("Starting Gromozeka bot, dood!")
        
        # Start the bot
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Main entry point."""
    try:
        bot = GromozekBot()
        bot.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()