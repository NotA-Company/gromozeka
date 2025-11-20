"""
Gromozeka - A minimal Telegram bot with TOML configuration and SQLite database.
Refactored modular version.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import List, Optional

from internal.bot.max.application import MaxBotApplication
from internal.bot.telegram.application import TelegramBotApplication
from internal.config.manager import ConfigManager
from internal.database.manager import DatabaseManager
from lib.ai.manager import LLMManager
from lib.logging_utils import initLogging
from lib.rate_limiter import RateLimiterManager

# Configure basic logging first
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class GromozekBot:
    """Main bot orchestrator that coordinates all components."""

    def __init__(self, configPath: str = "config.toml", config_dirs: Optional[List[str]] = None):
        """Initialize bot with all components."""
        # Initialize configuration
        self.configManager = ConfigManager(configPath, config_dirs)

        # Initialize logging with config
        initLogging(self.configManager.getLoggingConfig())

        # Initialize database
        self.database_manager = DatabaseManager(self.configManager.getDatabaseConfig())

        # Initialize LLM Manager
        self.llmManager = LLMManager(self.configManager.getModelsConfig())

        # Initialize rate limiter manager
        self.rateLimiterManager = RateLimiterManager.getInstance()
        asyncio.run(self.rateLimiterManager.loadConfig(self.configManager.getRateLimiterConfig()))

        # Initialize bot application
        botConfig = self.configManager.getBotConfig()
        self.botMode = botConfig.get("mode", "telegram")

        match self.botMode:
            case "telegram":
                self.botApp = TelegramBotApplication(
                    configManager=self.configManager,
                    botToken=self.configManager.getBotToken(),
                    database=self.database_manager.getDatabase(),
                    llmManager=self.llmManager,
                )
            case "max":
                self.botApp = MaxBotApplication(
                    configManager=self.configManager,
                    botToken=self.configManager.getBotToken(),
                    database=self.database_manager.getDatabase(),
                    llmManager=self.llmManager,
                )
            case _:
                raise ValueError(f"Unknown bot mode: {self.botMode}")

    def run(self):
        """Start the bot."""
        self.botApp.run()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Gromozeka - A minimal Telegram bot with TOML configuration and SQLite database, dood!"
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.toml",
        help="Path to configuration file (default: config.toml)",
    )
    parser.add_argument(
        "--config-dir",
        action="append",
        help="Directory to search for .toml config files recursively (can be specified multiple times), dood!",
    )
    parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Run bot in background (daemon mode), dood!",
    )
    parser.add_argument(
        "--pid-file",
        default="gromozeka.pid",
        help="PID file path for daemon mode (default: gromozeka.pid)",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Pretty-print loaded configuration and exit, dood!",
    )
    args = parser.parse_args()
    # Convert relative paths to absolute paths before daemon mode changes working directory
    args.config = os.path.abspath(args.config)
    args.pid_file = os.path.abspath(args.pid_file)

    # Convert config directories to absolute paths
    if args.config_dir:
        args.config_dir = [os.path.abspath(dir_path) for dir_path in args.config_dir]

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
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))
        logger.info(f"Daemon started with PID {os.getpid()}, dood!")
    except Exception as e:
        logger.error(f"Failed to write PID file: {e}")

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    # Redirect to /dev/null
    with open(os.devnull, "r") as dev_null_r:
        os.dup2(dev_null_r.fileno(), sys.stdin.fileno())
    with open(os.devnull, "w") as dev_null_w:
        os.dup2(dev_null_w.fileno(), sys.stdout.fileno())
        os.dup2(dev_null_w.fileno(), sys.stderr.fileno())


def prettyPrintConfig(config_manager: ConfigManager):
    """Pretty-print the loaded configuration and exit, dood!"""
    print("=== Gromozeka Configuration ===")
    print()

    # Get the raw config dictionary
    config = config_manager.config

    # Pretty-print as JSON for better readability
    try:
        config_json = json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True)
        print(config_json)
    except (TypeError, ValueError) as e:
        # Fallback to basic dict representation if JSON serialization fails
        logger.warning(f"Could not serialize config as JSON: {e}")
        print("Raw configuration:")
        for key, value in sorted(config.items()):
            print(f"{key}: {value}")

    print()
    print("=== Configuration loaded successfully, dood! ===")


def main():
    """Main entry point."""
    args = parse_arguments()

    try:
        # Handle --print-config argument first
        if args.print_config:
            # Initialize only the config manager to load and print config
            config_manager = ConfigManager(config_path=args.config, config_dirs=args.config_dir)
            prettyPrintConfig(config_manager)
            sys.exit(0)

        # Fork to background if daemon mode requested
        if args.daemon:
            daemonize(args.pid_file)

        # Initialize bot with custom config path and directories
        bot = GromozekBot(configPath=args.config, config_dirs=args.config_dir)
        bot.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
