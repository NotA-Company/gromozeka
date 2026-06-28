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
from typing import Optional

from internal.bot.max.application import MaxBotApplication
from internal.bot.models.enums import BotProvider
from internal.bot.telegram.application import TelegramBotApplication
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.stats_storage import DatabaseStatsStorage
from internal.services.llm import LLMService
from internal.services.proxy import ProxyService
from internal.services.queue_service import QueueService
from lib.ai.manager import LLMManager
from lib.logging_utils import initLogging
from lib.rate_limiter import RateLimiterManager
from lib.stats import StatsStorage

# Configure basic logging first
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class GromozekBot:
    """Main bot orchestrator that coordinates all components."""

    def __init__(self, configManager: ConfigManager, loop: asyncio.AbstractEventLoop):
        """Initialize bot with all components.

        Args:
            configManager: The application configuration manager.
            loop: The shared asyncio event loop for background tasks and polling.
        """
        self.configManager = configManager
        self._loop = loop

        self._schedulerTask: Optional[asyncio.Task] = None

        # Initialize logging with config
        initLogging(self.configManager.getLoggingConfig())

        # Initialize database
        self.database = Database(
            self.configManager.getDatabaseConfig(),  # pyright: ignore[reportArgumentType]
        )

        # Start the delayed task scheduler as a background task on the shared loop.
        # This creates the coroutine so the scheduler registers its built-in
        # DO_EXIT handler (_doExitHandler) before ProxyService does. On
        # shutdown the handlers run in registration order — the queue drain
        # runs first (proxy still available for HTTP/LLM calls), then proxy
        # processes stop.
        self._schedulerTask = loop.create_task(
            QueueService.getInstance().startDelayedScheduler(self.database),
            name="delayed-scheduler",
        )

        # Initialize stats storage for LLM usage tracking
        llmStatsStorage: Optional[StatsStorage] = None
        statsConfig = self.configManager.getStatsConfig()
        if statsConfig.get("enabled", False):
            llmStatsStorage = DatabaseStatsStorage(
                db=self.database,
                eventType="llm_request",
                dataSource=statsConfig.get("llm-stats-data-source", self.database.manager.default),
            )

        # Initialize LLM Manager
        self.llmManager = LLMManager(
            self.configManager.getModelsConfig(),
            statsStorage=llmStatsStorage,
        )
        LLMService.getInstance().injectLLMManager(self.llmManager)

        # Initialize rate limiter manager
        self.rateLimiterManager = RateLimiterManager.getInstance()
        loop.run_until_complete(self.rateLimiterManager.loadConfig(self.configManager.getRateLimiterConfig()))

        # Initialize proxy lifecycle management AFTER the scheduler task has
        # started (loop.run_until_complete above drives the event loop, which
        # runs the scheduler coroutine created earlier). This ensures
        # QueueService._doExitHandler registers before ProxyService._dtOnExit,
        # so on shutdown the queue drains background tasks (needing the proxy)
        # before proxy processes are stopped.
        ProxyService.getInstance().initialize(self.configManager.getProxyConfig(), loop=loop)

        # Initialize bot application
        botConfig = self.configManager.getBotConfig()
        self.botMode = BotProvider(botConfig.get("mode", BotProvider.TELEGRAM))

        match self.botMode:
            case BotProvider.TELEGRAM:
                self.botApp = TelegramBotApplication(
                    configManager=self.configManager,
                    botToken=self.configManager.getBotToken(),
                    database=self.database,
                )
            case BotProvider.MAX:
                self.botApp = MaxBotApplication(
                    configManager=self.configManager,
                    botToken=self.configManager.getBotToken(),
                    database=self.database,
                )
            case _:
                raise ValueError(f"Unknown bot mode: {self.botMode}")

    async def _shutdown(self) -> None:
        """Gracefully shut down resources in correct order.

        Stops the scheduler first so DO_EXIT handlers (including proxy
        stop commands) complete before closing HTTP and DB connections.
        Each step runs even if the previous one raises, to maximize
        resource cleanup.
        """
        try:
            queueService = QueueService.getInstance()
            logger.info("Step 2.1: Stopping Delayed Tasks Scheduler...")
            await queueService.beginShutdown()
            logger.info("Step 2.2: Waiting for delayed scheduler task...")
            if self._schedulerTask is not None:
                await self._schedulerTask
        except Exception:
            logger.exception("Error during scheduler shutdown")

        logger.info("Step 2.3: Destroying rate limiters...")
        await RateLimiterManager.getInstance().destroy()
        logger.info("Rate limiters destroyed...")

        try:
            logger.info("Step 2.4: Closing LLM manager...")
            await self.llmManager.aclose()
            logger.info("LLM manager closed...")
        except Exception:
            logger.exception("Error closing LLM manager during shutdown")

        try:
            logger.info("Step 2.5: Closing database...")
            await self.database.manager.closeAll()
            logger.info("Database closed...")
        except Exception:
            logger.exception("Error closing database during shutdown")

    def run(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Start the bot.

        Args:
            loop: The shared asyncio event loop.
        """

        if loop is None:
            loop = self._loop
        try:
            self.botApp.run(loop)
        except Exception as e:
            logger.exception(e)
            raise
        finally:
            loop.run_until_complete(self._shutdown())


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
    parser.add_argument(
        "--dotenv-file",
        default=".env",
        help="Path to .env file with env variables for substitute in configs",
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
    configManager = ConfigManager(
        configPath=args.config,
        configDirs=args.config_dir,
        dotEnvFile=args.dotenv_file,
    )

    try:
        # Handle --print-config argument first
        if args.print_config:
            # Initialize only the config manager to load and print config

            prettyPrintConfig(configManager)
            sys.exit(0)

        # Fork to background if daemon mode requested
        if args.daemon:
            daemonize(args.pid_file)

        # Create the single shared event loop for the application lifecycle
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Initialize bot with shared loop
            bot = GromozekBot(configManager, loop)
            bot.run(loop)
        finally:
            loop.close()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
