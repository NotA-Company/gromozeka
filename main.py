"""
Gromozeka - A minimal Telegram bot with TOML configuration and SQLite database.
Refactored modular version.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from config.manager import ConfigManager
from database.manager import DatabaseManager
from llm.yandex_ml import YandexMLManager
from bot.application import BotApplication
from lib.logging_utils import init_logger

# Configure basic logging first
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class GromozekBot:
    """Main bot orchestrator that coordinates all components."""

    def __init__(self, config_path: str = "config.toml"):
        """Initialize bot with all components."""
        # Initialize configuration
        self.config_manager = ConfigManager(config_path)

        # Initialize logging with config
        init_logger(self.config_manager.get_logging_config())

        # Initialize database
        self.database_manager = DatabaseManager(self.config_manager.get_database_config())

        # Initialize LLM
        self.llm_manager = YandexMLManager(self.config_manager.get_yc_ml_config())

        # Initialize bot application
        self.bot_app = BotApplication(
            config_manager=self.config_manager,
            bot_token=self.config_manager.get_bot_token(),
            database=self.database_manager.get_database(),
            llm_model=self.llm_manager.get_model(),
            llm_manager=self.llm_manager,
        )

    def run(self):
        """Start the bot."""
        self.bot_app.run()


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