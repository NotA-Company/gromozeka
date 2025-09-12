"""
Gromozeka - A minimal Telegram bot with TOML configuration and SQLite database.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any

from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import YandexCloudCLIAuth




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
        self._init_logger()
        self.db = self._init_database()
        self.application = None
        self.ycML = self._init_yc_ml_sdk()
        self.ycModel = self._init_ycModel()


    def _init_logger(self) -> None:
        """Configure logging from config file settings."""
        logging_config = self.config.get("logging", {})
        
        # Get log level from config (default to INFO)
        log_level = logging_config.get("level", "INFO").upper()
        try:
            level = getattr(logging, log_level)
        except AttributeError:
            logger.warning(f"Invalid log level '{log_level}', using INFO")
            level = logging.INFO
        
        # Get log format from config (use existing default if not specified)
        log_format = logging_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        
        # Get log file path from config (optional)
        log_file = logging_config.get("file")
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(level)
        
        # Clear existing handlers to avoid duplicates
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Create formatter
        formatter = logging.Formatter(log_format)
        
        # Add console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
        # Add file handler if specified
        if log_file:
            try:
                # Create log directory if it doesn't exist
                log_path = Path(log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                
                file_handler = logging.FileHandler(log_file)
                file_handler.setLevel(level)
                file_handler.setFormatter(formatter)
                root_logger.addHandler(file_handler)
                logger.info(f"Logging to file: {log_file}")
            except Exception as e:
                logger.error(f"Failed to setup file logging: {e}")
        
        # Set higher logging level for httpx to avoid all GET and POST requests being logged
        logging.getLogger("httpx").setLevel(logging.WARNING)
        
        logger.info(f"Logging configured: level={log_level}, format='{log_format}'" +
                   (f", file={log_file}" if log_file else ""))
        
        
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

    def _init_yc_ml_sdk(self):
        """Initialize Yandex Cloud ML SDK."""
        yc_ml_config = self.config.get("yc-ml", {})
        folder_id = yc_ml_config.get("folder_id")

        try:
            yc_ml = YCloudML(
                folder_id=folder_id,
                auth=YandexCloudCLIAuth(),
                yc_profile=yc_ml_config.get("yc_profile", None),
            )
            logger.info("Yandex Cloud ML SDK initialized")
            return yc_ml
        except Exception as e:
            logger.error(f"Failed to initialize Yandex Cloud ML SDK: {e}")
            sys.exit(1)

    def _init_ycModel(self):
        """Initialize Yandex Cloud ML model."""
        yc_ml_config = self.config.get("yc-ml", {})
        model_id = yc_ml_config.get("model_id", "yandexgpt-5-lite")

        try:
            yc_model = self.ycML.models.completions(model_id).configure(temperature=yc_ml_config.get("temperature", 0.5))
            logger.info(f"Yandex Cloud ML model initialized: {model_id}")
            return yc_model
        except Exception as e:
            logger.error(f"Failed to initialize Yandex Cloud ML model: {e}")
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
        if not user or not update.message:
            logging.error("User or message undefined")
            return

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
        if not update.message:
            logging.error("Message undefined")
            return
            
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
        if not user or not update.message:
            logging.error("User or message undefined")
            return

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
        if not update.message:
            logging.error("Message undefined")
            return
            
        if context.args:
            echo_text = " ".join(context.args)
            await update.message.reply_text(f"🔄 Echo: {echo_text}")
        else:
            await update.message.reply_text("Please provide a message to echo!\nUsage: /echo <your message>")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle regular text messages."""
        user = update.effective_user
        if not user or not update.message:
            logging.error("User or message undefined")
            return
            
        message_text = update.message.text
        if not message_text:
            logging.error("Message text undefined")
            return

        # Save user and message to database
        self.db.save_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        messages = self.db.get_user_messages(user.id, limit=10)
        reqMessages = [
            {
                "role": "system",
                "text": "Ты - Prinny - вайбовый, но умный пингвин из Disgaea. При ответе ты можешь использовать Markdown форматирование",
            },
        ]

        for message in reversed(messages):
            reqMessages.append({
                "role": "user",
                "text": message["message_text"],
            })
            if message["reply_text"]:
                reqMessages.append({
                    "role": "assistant",
                    "text": message["reply_text"],
                })
        reqMessages.append({
            "role": "user",
            "text": message_text,
        })
        
        logging.info(f"LLM Request messages: {reqMessages}")
        mlRet = self.ycModel.run(reqMessages)
        logging.info(f"LLM Response: {mlRet}")
        reply = mlRet.alternatives[0].text
        self.db.save_message(user.id, message_text, reply_text=reply)
        
        #response = mlRet.

        try:
            await update.message.reply_markdown(reply, reply_to_message_id=update.message.message_id)
            logger.info(f"Replied to message from {user.id}: {message_text[:50]}...")
        except Exception as e:
            logger.error(f"Error while replying to message: {type(e).__name__}#{e}")
            # Probably error in markdown formatting, fallback to raw text
            await update.message.reply_text(reply, reply_to_message_id=update.message.message_id)
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
        token = self.config.get("bot", {}).get("token", "")

        if token in ["", "YOUR_BOT_TOKEN_HERE"]:
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)

        # Create application
        self.application = Application.builder().token(token).build()

        # Setup handlers
        self.setup_handlers()

        logger.info("Starting Gromozeka bot, dood!")

        # Start the bot
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Gromozeka - A minimal Telegram bot with TOML configuration and SQLite database, dood!"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.toml",
        help="Path to configuration file (default: config.toml)"
    )
    parser.add_argument(
        "-d", "--daemon",
        action="store_true",
        help="Run bot in background (daemon mode), dood!"
    )
    parser.add_argument(
        "--pid-file",
        default="gromozeka.pid",
        help="PID file path for daemon mode (default: gromozeka.pid)"
    )
    args = parser.parse_args()
    # Convert relative paths to absolute paths before daemon mode changes working directory
    args.config = os.path.abspath(args.config)
    args.pid_file = os.path.abspath(args.pid_file)

    return args


def daemonize(pid_file: str):
    """Fork the process to run in background, dood!
    
    Uses the double fork pattern to create a proper daemon process.
    For detailed explanation, see: docs/reports/double-fork-daemon-pattern.md
    """
    try:
        # First fork
        pid = os.fork()
        if pid > 0:
            # Parent process, exit
            sys.exit(0)
    except OSError as e:
        logger.error(f"First fork failed: {e}")
        sys.exit(1)

    # Decouple from parent environment
    os.chdir("/")
    os.setsid()
    os.umask(0)

    try:
        # Second fork
        pid = os.fork()
        if pid > 0:
            # Parent process, exit
            sys.exit(0)
    except OSError as e:
        logger.error(f"Second fork failed: {e}")
        sys.exit(1)

    # Write PID file
    try:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"Daemon started with PID {os.getpid()}, dood!")
    except Exception as e:
        logger.error(f"Failed to write PID file: {e}")

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()
    
    # Redirect to /dev/null
    with open(os.devnull, 'r') as dev_null_r:
        os.dup2(dev_null_r.fileno(), sys.stdin.fileno())
    with open(os.devnull, 'w') as dev_null_w:
        os.dup2(dev_null_w.fileno(), sys.stdout.fileno())
        os.dup2(dev_null_w.fileno(), sys.stderr.fileno())


def main():
    """Main entry point."""
    args = parse_arguments()
    
    try:
        # Fork to background if daemon mode requested
        if args.daemon:
            daemonize(args.pid_file)
        
        # Initialize bot with custom config path
        bot = GromozekBot(config_path=args.config)
        bot.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
