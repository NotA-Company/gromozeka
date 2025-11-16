#!/usr/bin/env python3
"""
Advanced Bot Example

This example demonstrates advanced features of the Max Bot client library, including
custom filters, middleware, comprehensive error handling, logging, monitoring, and
performance optimization techniques.

Features demonstrated:
- Custom message filters
- Middleware for request/response processing
- Advanced error handling and recovery
- Comprehensive logging and monitoring
- Performance metrics and optimization
- Rate limiting and throttling
- Request/response interceptors
from typing import Any, Callable, Dict, List, Optional, cast
- Custom decorators and utilities

Run this example:
    python advanced_bot.py

Requirements:
    - Set MAX_BOT_TOKEN environment variable with your bot access token
    - Optional: Set LOG_LEVEL environment variable (DEBUG, INFO, WARNING, ERROR)
"""

import asyncio
import logging
import os
import sys
import time
import traceback
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, cast

# Add the parent directory to the path so we can import lib.max_bot
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib.max_bot import (  # noqa: E402
    AuthenticationError,
    MaxBotClient,
    MaxBotError,
    RateLimitError,
    UpdateType,
)
from lib.max_bot.models import TextFormat  # noqa: E402


def setup_logging() -> None:
    """Configure advanced logging for the bot."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    # Create detailed formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # File handler for detailed logs
    file_handler = logging.FileHandler("advanced_bot.log")
    file_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Set specific logger level for the max_bot library
    logging.getLogger("lib.max_bot").setLevel(logging.DEBUG)

    logging.info(f"🔧 Logging configured with level: {log_level}")


def get_token() -> str:
    """Get the bot token from environment variables."""
    token = os.getenv("MAX_BOT_TOKEN")
    if not token:
        print("❌ Error: MAX_BOT_TOKEN environment variable is not set!")
        print("Please set your bot token:")
        print("export MAX_BOT_TOKEN='your_access_token_here'")
        sys.exit(1)
    return token


class PerformanceMonitor:
    """Monitor bot performance and metrics."""

    def __init__(self):
        """Initialize the performance monitor."""
        self.metrics = {
            "total_updates": 0,
            "processed_updates": 0,
            "failed_updates": 0,
            "response_times": [],
            "error_counts": {},
            "start_time": time.time(),
            "last_update_time": None,
        }

    def record_update(self, update_type: str) -> None:
        """Record an incoming update.

        Args:
            update_type: Type of update received
        """
        self.metrics["total_updates"] += 1
        self.metrics["last_update_time"] = time.time()

    def record_processed_update(self, response_time: float) -> None:
        """Record a successfully processed update.

        Args:
            response_time: Time taken to process the update
        """
        self.metrics["processed_updates"] += 1
        self.metrics["response_times"].append(response_time)

        # Keep only last 100 response times
        if len(self.metrics["response_times"]) > 100:
            self.metrics["response_times"] = self.metrics["response_times"][-100:]

    def record_error(self, error_type: str) -> None:
        """Record an error.

        Args:
            error_type: Type of error that occurred
        """
        self.metrics["failed_updates"] += 1
        self.metrics["error_counts"][error_type] = self.metrics["error_counts"].get(error_type, 0) + 1

    def get_stats(self) -> Dict[str, Any]:
        """Get current performance statistics.

        Returns:
            Dictionary of performance metrics
        """
        current_time = time.time()
        uptime = current_time - self.metrics["start_time"]

        response_times = self.metrics["response_times"]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0

        return {
            "uptime_seconds": uptime,
            "total_updates": self.metrics["total_updates"],
            "processed_updates": self.metrics["processed_updates"],
            "failed_updates": self.metrics["failed_updates"],
            "success_rate": (
                (self.metrics["processed_updates"] / self.metrics["total_updates"] * 100)
                if self.metrics["total_updates"] > 0
                else 0
            ),
            "avg_response_time": avg_response_time,
            "updates_per_second": self.metrics["total_updates"] / uptime if uptime > 0 else 0,
            "error_counts": self.metrics["error_counts"].copy(),
            "last_update_time": self.metrics["last_update_time"],
        }


class MessageFilter:
    """Base class for message filters."""

    def __init__(self, name: str):
        """Initialize the filter.

        Args:
            name: Name of the filter
        """
        self.name = name
        self.passed_count = 0
        self.failed_count = 0

    def check(self, update) -> bool:
        """Check if the update passes the filter.

        Args:
            update: The update to check

        Returns:
            True if the update passes the filter
        """
        raise NotImplementedError("Subclasses must implement check method")

    def get_stats(self) -> Dict[str, Any]:
        """Get filter statistics.

        Returns:
            Dictionary of filter metrics
        """
        total = self.passed_count + self.failed_count
        return {
            "name": self.name,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "total": total,
            "pass_rate": (self.passed_count / total * 100) if total > 0 else 0,
        }


class TextLengthFilter(MessageFilter):
    """Filter messages based on text length."""

    def __init__(self, min_length: int = 1, max_length: int = 1000):
        """Initialize the text length filter.

        Args:
            min_length: Minimum text length
            max_length: Maximum text length
        """
        super().__init__(f"TextLength({min_length}-{max_length})")
        self.min_length = min_length
        self.max_length = max_length

    def check(self, update) -> bool:
        """Check if message text length is within bounds.

        Args:
            update: The update to check

        Returns:
            True if text length is within bounds
        """
        if update.updateType != UpdateType.MESSAGE_CREATED:
            self.failed_count += 1
            return False

        text = update.message.body.text or ""
        length = len(text)

        if self.min_length <= length <= self.max_length:
            self.passed_count += 1
            return True
        else:
            self.failed_count += 1
            return False


class UserFilter(MessageFilter):
    """Filter messages from specific users."""

    def __init__(self, allowed_users: List[int]):
        """Initialize the user filter.

        Args:
            allowed_users: List of allowed user IDs
        """
        super().__init__(f"UserFilter({len(allowed_users)} users)")
        self.allowed_users = set(allowed_users)

    def check(self, update) -> bool:
        """Check if message is from allowed user.

        Args:
            update: The update to check

        Returns:
            True if user is allowed
        """
        user_id = None

        if update.updateType == UpdateType.MESSAGE_CREATED:
            user_id = update.message.sender.user_id
        elif update.updateType == UpdateType.MESSAGE_CALLBACK:
            user_id = update.callbackQuery.sender.user_id

        if user_id and user_id in self.allowed_users:
            self.passed_count += 1
            return True
        else:
            self.failed_count += 1
            return False


class ContentTypeFilter(MessageFilter):
    """Filter messages based on content type."""

    def __init__(self, allowed_types: List[str]):
        """Initialize the content type filter.

        Args:
            allowed_types: List of allowed content types
        """
        super().__init__(f"ContentType({', '.join(allowed_types)})")
        self.allowed_types = set(allowed_types)

    def check(self, update) -> bool:
        """Check if message has allowed content type.

        Args:
            update: The update to check

        Returns:
            True if content type is allowed
        """
        if update.updateType != UpdateType.MESSAGE_CREATED:
            self.failed_count += 1
            return False

        message = update.message

        # Check for text content
        if "text" in self.allowed_types and message.body.text:
            self.passed_count += 1
            return True

        # Check for attachments
        if message.body.attachments:
            for attachment in message.body.attachments:
                if attachment.type.value in self.allowed_types:
                    self.passed_count += 1
                    return True

        self.failed_count += 1
        return False


class Middleware:
    """Base class for middleware."""

    def __init__(self, name: str):
        """Initialize the middleware.

        Args:
            name: Name of the middleware
        """
        self.name = name
        self.processed_count = 0

    async def process(self, update, next_handler: Callable) -> Any:
        """Process the update and call next handler.

        Args:
            update: The update to process
            next_handler: The next handler in the chain

        Returns:
            Result from the next handler
        """
        raise NotImplementedError("Subclasses must implement process method")

    def get_stats(self) -> Dict[str, Any]:
        """Get middleware statistics.

        Returns:
            Dictionary of middleware metrics
        """
        return {"name": self.name, "processed_count": self.processed_count}


class LoggingMiddleware(Middleware):
    """Middleware for logging updates."""

    def __init__(self, log_level: str = "INFO"):
        """Initialize the logging middleware.

        Args:
            log_level: Logging level for updates
        """
        super().__init__("LoggingMiddleware")
        self.log_level = getattr(logging, log_level.upper())

    async def process(self, update, next_handler: Callable) -> Any:
        """Log the update and call next handler.

        Args:
            update: The update to process
            next_handler: The next handler in the chain

        Returns:
            Result from the next handler
        """
        self.processed_count += 1

        logging.log(self.log_level, f"📨 Processing update: {update.updateType}")

        try:
            result = await next_handler(update)
            logging.log(self.log_level, f"✅ Update processed successfully: {update.updateType}")
            return result
        except Exception as e:
            logging.error(f"❌ Error processing update {update.updateType}: {e}")
            raise


class RateLimitMiddleware(Middleware):
    """Middleware for rate limiting."""

    def __init__(self, max_requests: int = 10, time_window: int = 60):
        """Initialize the rate limit middleware.

        Args:
            max_requests: Maximum requests per time window
            time_window: Time window in seconds
        """
        super().__init__(f"RateLimit({max_requests}/{time_window}s)")
        self.max_requests = max_requests
        self.time_window = time_window
        self.user_requests: Dict[int, List[float]] = {}

    async def process(self, update, next_handler: Callable) -> Any:
        """Check rate limit and call next handler.

        Args:
            update: The update to process
            next_handler: The next handler in the chain

        Returns:
            Result from the next handler
        """
        self.processed_count += 1

        # Get user ID
        user_id = None
        if update.updateType == UpdateType.MESSAGE_CREATED:
            user_id = update.message.sender.user_id
        elif update.updateType == UpdateType.MESSAGE_CALLBACK:
            user_id = update.callbackQuery.sender.user_id

        if not user_id:
            return await next_handler(update)

        current_time = time.time()

        # Clean old requests
        if user_id in self.user_requests:
            self.user_requests[user_id] = [
                req_time for req_time in self.user_requests[user_id] if current_time - req_time < self.time_window
            ]
        else:
            self.user_requests[user_id] = []

        # Check rate limit
        if len(self.user_requests[user_id]) >= self.max_requests:
            logging.warning(f"🚫 Rate limit exceeded for user {user_id}")
            raise RateLimitError("Rate limit exceeded. Please try again later.")

        # Add current request
        self.user_requests[user_id].append(current_time)

        return await next_handler(update)


def error_handler(func: Callable) -> Callable:
    """Decorator for error handling.

    Args:
        func: Function to decorate

    Returns:
        Decorated function with error handling
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        """Wrapper function with error handling."""
        try:
            return await func(*args, **kwargs)
        except AuthenticationError as e:
            logging.error(f"🔐 Authentication error in {func.__name__}: {e}")
            raise
        except RateLimitError as e:
            logging.warning(f"🚫 Rate limit error in {func.__name__}: {e}")
            raise
        except MaxBotError as e:
            logging.error(f"❌ Max Bot error in {func.__name__}: {e}")
            raise
        except Exception as e:
            logging.error(f"💥 Unexpected error in {func.__name__}: {e}")
            logging.error(f"💥 Traceback: {traceback.format_exc()}")
            raise MaxBotError(f"Unexpected error in {func.__name__}: {e}")

    return wrapper


def performance_monitor(monitor: PerformanceMonitor):
    """Decorator for performance monitoring.

    Args:
        monitor: PerformanceMonitor instance

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        """Decorator function."""

        @wraps(func)
        async def wrapper(update, *args, **kwargs):
            """Wrapper function with performance monitoring."""
            start_time = time.time()

            try:
                result = await func(update, *args, **kwargs)

                response_time = time.time() - start_time
                monitor.record_processed_update(response_time)

                logging.debug(f"⏱️ {func.__name__} completed in {response_time:.3f}s")

                return result

            except Exception as e:
                response_time = time.time() - start_time
                monitor.record_error(type(e).__name__)

                logging.debug(f"⏱️ {func.__name__} failed in {response_time:.3f}s")
                raise

        return wrapper

    return decorator


class AdvancedBot:
    """An advanced bot demonstrating sophisticated features."""

    def __init__(self, client: MaxBotClient):
        """Initialize the advanced bot.

        Args:
            client: The MaxBotClient instance
        """
        self.client = client
        self.monitor = PerformanceMonitor()
        self.filters = self.setup_filters()
        self.middleware = self.setup_middleware()
        self.admin_users = []  # Will be populated from environment

        # Load admin users from environment
        admin_users_str = os.getenv("ADMIN_USERS", "")
        if admin_users_str:
            self.admin_users = [int(uid.strip()) for uid in admin_users_str.split(",")]
            logging.info(f"👑 Admin users loaded: {self.admin_users}")

    def setup_filters(self) -> List[MessageFilter]:
        """Set up message filters.

        Returns:
            List of configured filters
        """
        filters = [
            TextLengthFilter(min_length=1, max_length=2000),
            ContentTypeFilter(["text", "photo", "video", "audio", "file"]),
        ]

        # Add user filter if admin users are specified
        if self.admin_users:
            filters.append(UserFilter(self.admin_users))

        logging.info(f"🔍 {len(filters)} filters configured")
        return filters

    def setup_middleware(self) -> List[Middleware]:
        """Set up middleware chain.

        Returns:
            List of configured middleware
        """
        middleware = [LoggingMiddleware("DEBUG"), RateLimitMiddleware(max_requests=5, time_window=60)]

        logging.info(f"🔧 {len(middleware)} middleware configured")
        return middleware

    def create_admin_keyboard(self) -> List[List[Dict]]:
        """Create admin keyboard with advanced options.

        Returns:
            List of keyboard rows with buttons
        """
        return [
            [
                {"type": "callback", "text": "📊 Performance Stats", "payload": "perf_stats"},
                {"type": "callback", "text": "🔍 Filter Stats", "payload": "filter_stats"},
            ],
            [
                {"type": "callback", "text": "🔧 Middleware Stats", "payload": "middleware_stats"},
                {"type": "callback", "text": "🧹 Clear Stats", "payload": "clear_stats"},
            ],
            [
                {"type": "callback", "text": "📝 System Info", "payload": "system_info"},
                {"type": "callback", "text": "❌ Close", "payload": "close"},
            ],
        ]

    def create_user_keyboard(self) -> List[List[Dict]]:
        """Create user keyboard with basic options.

        Returns:
            List of keyboard rows with buttons
        """
        return [
            [
                {"type": "callback", "text": "ℹ️ Bot Info", "payload": "bot_info"},
                {"type": "callback", "text": "📊 Stats", "payload": "user_stats"},
            ],
            [
                {"type": "callback", "text": "🔍 Test Filters", "payload": "test_filters"},
                {"type": "callback", "text": "❌ Close", "payload": "close"},
            ],
        ]

    async def apply_filters(self, update) -> bool:
        """Apply all filters to the update.

        Args:
            update: The update to filter

        Returns:
            True if update passes all filters
        """
        for filter_obj in self.filters:
            if not filter_obj.check(update):
                logging.debug(f"🚫 Update rejected by filter: {filter_obj.name}")
                return False

        return True

    async def apply_middleware(self, update, handler: Callable) -> Any:
        """Apply middleware chain to the update.

        Args:
            update: The update to process
            handler: The final handler to call

        Returns:
            Result from the handler
        """

        async def create_handler_chain(index: int) -> Callable:
            """Create handler chain for middleware."""
            if index >= len(self.middleware):
                return handler

            middleware = self.middleware[index]

            async def next_handler(update):
                handler = await create_handler_chain(index + 1)
                return await handler(update)

            return lambda upd: middleware.process(upd, next_handler)

        chain_handler = await create_handler_chain(0)
        return await chain_handler(update)

    @error_handler
    @performance_monitor(monitor=None)  # type: ignore
    async def process_update(self, update) -> None:
        """Process an update with filters and middleware.

        Args:
            update: The update to process
        """
        # Record update
        self.monitor.record_update(update.updateType)

        # Apply filters
        if not await self.apply_filters(update):
            return

        # Apply middleware and process
        await self.apply_middleware(update, self.handle_update)

    @error_handler
    async def handle_update(self, update) -> None:
        """Handle the update after filters and middleware.

        Args:
            update: The update to handle
        """
        if update.updateType == UpdateType.MESSAGE_CREATED:
            await self.handle_message(update)
        elif update.updateType == UpdateType.MESSAGE_CALLBACK:
            await self.handle_callback(update)
        elif update.updateType == UpdateType.BOT_ADDED_TO_CHAT:
            await self.handle_bot_added(update)
        elif update.updateType == UpdateType.BOT_STARTED:
            await self.handle_bot_started(update)
        else:
            logging.debug(f"🔄 Unhandled update type: {update.updateType}")

    async def handle_message(self, update) -> None:
        """Handle message updates.

        Args:
            update: The message update
        """
        message = update.message
        chat_id = message.recipient.chat_id
        user_id = message.sender.user_id
        user_name = message.sender.first_name or "User"
        text = message.body.text or ""

        logging.info(f"💬 Message from {user_name} ({user_id}): {text[:50]}...")

        # Check if user is admin
        is_admin = user_id in self.admin_users

        # Handle commands
        if text.startswith("/"):
            await self.handle_command(chat_id, user_id, user_name, text, is_admin)
        else:
            await self.handle_text_message(chat_id, user_name, text, is_admin)

    async def handle_callback(self, update) -> None:
        """Handle callback updates.

        Args:
            update: The callback update
        """
        callback = update.callbackQuery
        chat_id = callback.message.recipient.chat_id
        user_id = callback.sender.user_id
        user_name = callback.sender.first_name or "User"
        payload = callback.payload

        logging.info(f"🔘 Callback from {user_name} ({user_id}): {payload}")

        try:
            if payload == "perf_stats":
                await self.show_performance_stats(chat_id, callback.query_id)
            elif payload == "filter_stats":
                await self.show_filter_stats(chat_id, callback.query_id)
            elif payload == "middleware_stats":
                await self.show_middleware_stats(chat_id, callback.query_id)
            elif payload == "clear_stats":
                await self.clear_stats(chat_id, callback.query_id)
            elif payload == "system_info":
                await self.show_system_info(chat_id, callback.query_id)
            elif payload == "bot_info":
                await self.show_bot_info(chat_id, callback.query_id)
            elif payload == "user_stats":
                await self.show_user_stats(chat_id, callback.query_id, user_id)
            elif payload == "test_filters":
                await self.test_filters(chat_id, callback.query_id)
            elif payload == "close":
                await self.close_menu(chat_id, callback.query_id, callback.message.body.mid)
            else:
                await self.client.answerCallbackQuery(
                    queryId=callback.query_id, text=f"❓ Unknown action: {payload}", showAlert=True
                )

        except Exception as e:
            logging.error(f"❌ Error handling callback: {e}")
            await self.client.answerCallbackQuery(
                queryId=callback.query_id, text="❌ Error occurred while processing your request", showAlert=True
            )

    async def handle_command(self, chat_id: int, user_id: int, user_name: str, command: str, is_admin: bool) -> None:
        """Handle bot commands.

        Args:
            chat_id: The chat ID
            user_id: The user ID
            user_name: The user's name
            command: The command text
            is_admin: Whether the user is an admin
        """
        try:
            if command.lower() == "/start":
                await self.send_welcome_message(chat_id, user_name, is_admin)
            elif command.lower() == "/help":
                await self.send_help_message(chat_id, is_admin)
            elif command.lower() == "/stats" and is_admin:
                await self.show_performance_stats(chat_id)
            elif command.lower() == "/filters" and is_admin:
                await self.show_filter_stats(chat_id)
            elif command.lower() == "/middleware" and is_admin:
                await self.show_middleware_stats(chat_id)
            else:
                await self.client.sendMessage(
                    chatId=chat_id, text=f"❓ Unknown command: {command}\nType /help for available commands."
                )

        except Exception as e:
            logging.error(f"❌ Error handling command: {e}")

    async def handle_text_message(self, chat_id: int, user_name: str, text: str, is_admin: bool) -> None:
        """Handle regular text messages.

        Args:
            chat_id: The chat ID
            user_name: The user's name
            text: The message text
            is_admin: Whether the user is an admin
        """
        try:
            # Simulate processing time
            await asyncio.sleep(0.1)

            response_text = f"📨 Message received: {text[:100]}{'...' if len(text) > 100 else ''}"

            if is_admin:
                response_text += "\n\n👑 Admin privileges detected!"

            await self.client.sendMessage(chatId=chat_id, text=response_text)

        except Exception as e:
            logging.error(f"❌ Error handling text message: {e}")

    async def handle_bot_added(self, update) -> None:
        """Handle bot added to chat.

        Args:
            update: The bot added update
        """
        chat_id = update.chat.chat_id
        chat_title = update.chat.title or "Chat"

        logging.info(f"🤖 Bot added to chat: {chat_title}")

        await self.client.sendMessage(
            chatId=chat_id,
            text="🤖 *Advanced Bot Added!*\n\n"
            "Hello everyone! 👋\n\n"
            "I'm an advanced bot with:\n"
            "• 🔍 Custom filters\n"
            "• 🔧 Middleware processing\n"
            "• 📊 Performance monitoring\n"
            "• 🛡️ Error handling\n"
            "• 🚫 Rate limiting\n\n"
            "Type /start to see available features!",
            format=cast(TextFormat, TextFormat.MARKDOWN),
        )

    async def handle_bot_started(self, update) -> None:
        """Handle bot started.

        Args:
            update: The bot started update
        """
        chat_id = update.user.user_id
        user_id = update.user.user_id
        user_name = update.user.first_name or "User"

        logging.info(f"🤖 Bot started by: {user_name}")

        is_admin = user_id in self.admin_users
        await self.send_welcome_message(chat_id, user_name, is_admin)

    async def send_welcome_message(self, chat_id: int, user_name: str, is_admin: bool) -> None:
        """Send welcome message.

        Args:
            chat_id: The chat ID
            user_name: The user's name
            is_admin: Whether the user is an admin
        """
        welcome_text = (
            f"👋 Hello, {user_name}!\n\n"
            "🚀 *Advanced Bot Demo*\n\n"
            "This bot demonstrates advanced features:\n"
            "• 🔍 Custom message filters\n"
            "• 🔧 Middleware processing chain\n"
            "• 📊 Performance monitoring\n"
            "• 🛡️ Comprehensive error handling\n"
            "• 🚫 Rate limiting\n"
            "• 📝 Detailed logging\n"
            "• ⏱️ Performance metrics\n\n"
        )

        if is_admin:
            welcome_text += "👑 *Admin privileges detected!*\n\n"

        welcome_text += "Choose an option below:"

        keyboard = self.client.createInlineKeyboard(
            self.create_admin_keyboard() if is_admin else self.create_user_keyboard()
        )

        await self.client.sendMessage(
            chatId=chat_id, text=welcome_text, format=cast(TextFormat, TextFormat.MARKDOWN), inlineKeyboard=keyboard
        )

    async def send_help_message(self, chat_id: int, is_admin: bool) -> None:
        """Send help message.

        Args:
            chat_id: The chat ID
            is_admin: Whether the user is an admin
        """
        help_text = (
            "🤖 *Advanced Bot Help*\n\n"
            "Available commands:\n"
            "• `/start` - Show welcome message\n"
            "• `/help` - Show this help message\n"
        )

        if is_admin:
            help_text += (
                "• `/stats` - Show performance statistics\n"
                "• `/filters` - Show filter statistics\n"
                "• `/middleware` - Show middleware statistics\n"
            )

        help_text += (
            "\n**Features:**\n"
            "• 🔍 Custom filters for message processing\n"
            "• 🔧 Middleware chain for request handling\n"
            "• 📊 Real-time performance monitoring\n"
            "• 🛡️ Advanced error handling and recovery\n"
            "• 🚫 Rate limiting per user\n"
            "• 📝 Comprehensive logging system\n"
            "• ⏱️ Response time tracking"
        )

        await self.client.sendMessage(chatId=chat_id, text=help_text, format=cast(TextFormat, TextFormat.MARKDOWN))

    async def show_performance_stats(self, chat_id: int, callback_query_id: Optional[str] = None) -> None:
        """Show performance statistics.

        Args:
            chat_id: The chat ID
            callback_query_id: Optional callback query ID to answer
        """
        stats = self.monitor.get_stats()

        stats_text = (
            "📊 *Performance Statistics*\n\n"
            f"⏱️ **Uptime:** {stats['uptime_seconds']:.0f}s\n"
            f"📈 **Total Updates:** {stats['total_updates']}\n"
            f"✅ **Processed:** {stats['processed_updates']}\n"
            f"❌ **Failed:** {stats['failed_updates']}\n"
            f"📊 **Success Rate:** {stats['success_rate']:.1f}%\n"
            f"⚡ **Avg Response Time:** {stats['avg_response_time']:.3f}s\n"
            f"🚀 **Updates/Second:** {stats['updates_per_second']:.2f}\n\n"
        )

        if stats["error_counts"]:
            stats_text += "**Error Counts:**\n"
            for error_type, count in stats["error_counts"].items():
                stats_text += f"• {error_type}: {count}\n"

        await self.client.sendMessage(chatId=chat_id, text=stats_text, format=cast(TextFormat, TextFormat.MARKDOWN))

        if callback_query_id:
            await self.client.answerCallbackQuery(queryId=callback_query_id, text="📊 Statistics loaded")

    async def show_filter_stats(self, chat_id: int, callback_query_id: Optional[str] = None) -> None:
        """Show filter statistics.

        Args:
            chat_id: The chat ID
            callback_query_id: Optional callback query ID to answer
        """
        stats_text = "🔍 *Filter Statistics*\n\n"

        for filter_obj in self.filters:
            stats = filter_obj.get_stats()
            stats_text += (
                f"**{stats['name']}**\n"
                f"• Passed: {stats['passed']}\n"
                f"• Failed: {stats['failed']}\n"
                f"• Pass Rate: {stats['pass_rate']:.1f}%\n\n"
            )

        await self.client.sendMessage(chatId=chat_id, text=stats_text, format=cast(TextFormat, TextFormat.MARKDOWN))

        if callback_query_id:
            await self.client.answerCallbackQuery(queryId=callback_query_id, text="🔍 Filter stats loaded")

    async def show_middleware_stats(self, chat_id: int, callback_query_id: Optional[str] = None) -> None:
        """Show middleware statistics.

        Args:
            chat_id: The chat ID
            callback_query_id: Optional callback query ID to answer
        """
        stats_text = "🔧 *Middleware Statistics*\n\n"

        for middleware in self.middleware:
            stats = middleware.get_stats()
            stats_text += f"**{stats['name']}**\n" f"• Processed: {stats['processed_count']}\n\n"

        await self.client.sendMessage(chatId=chat_id, text=stats_text, format=cast(TextFormat, TextFormat.MARKDOWN))

        if callback_query_id:
            await self.client.answerCallbackQuery(queryId=callback_query_id, text="🔧 Middleware stats loaded")

    async def clear_stats(self, chat_id: int, callback_query_id: Optional[str] = None) -> None:
        """Clear all statistics.

        Args:
            chat_id: The chat ID
            callback_query_id: Optional callback query ID to answer
        """
        # Reset monitor
        self.monitor = PerformanceMonitor()

        # Reset filter stats
        for filter_obj in self.filters:
            filter_obj.passed_count = 0
            filter_obj.failed_count = 0

        # Reset middleware stats
        for middleware in self.middleware:
            middleware.processed_count = 0

        await self.client.sendMessage(
            chatId=chat_id, text="🧹 *Statistics Cleared*\n\n" "All performance metrics have been reset!"
        )

        if callback_query_id:
            await self.client.answerCallbackQuery(queryId=callback_query_id, text="🧹 Statistics cleared")

    async def show_system_info(self, chat_id: int, callback_query_id: Optional[str] = None) -> None:
        """Show system information.

        Args:
            chat_id: The chat ID
            callback_query_id: Optional callback query ID to answer
        """
        # import psutil  # Not installed, commented out

        # System information (psutil not available)
        system_text = (
            "📝 *System Information*\n\n"
            f"💻 **CPU Usage:** N/A%\n"
            f"🧠 **Memory Usage:** N/A%\n"
            f"💾 **Disk Usage:** N/A%\n"
            f"🔀 **Active Threads:** N/A\n"
            f"⚙️ **Python Version:** {sys.version.split()[0]}\n\n"
            f"🤖 **Bot Features:**\n"
            f"• Filters: {len(self.filters)}\n"
            f"• Middleware: {len(self.middleware)}\n"
            f"• Admin Users: {len(self.admin_users)}"
        )

        await self.client.sendMessage(chatId=chat_id, text=system_text, format=cast(TextFormat, TextFormat.MARKDOWN))

        if callback_query_id:
            await self.client.answerCallbackQuery(queryId=callback_query_id, text="📝 System info loaded")

    async def show_bot_info(self, chat_id: int, callback_query_id: Optional[str] = None) -> None:
        """Show bot information.

        Args:
            chat_id: The chat ID
            callback_query_id: Optional callback query ID to answer
        """
        try:
            bot_info = await self.client.getMyInfo()

            info_text = (
                "ℹ️ *Bot Information*\n\n"
                f"🤖 **Name:** {bot_info.first_name}\n"
                f"🆔 **ID:** {bot_info.user_id}\n"
                f"📝 **Description:** {bot_info.description or 'No description'}\n"
                f"🔗 **Commands:** {len(bot_info.commands) if bot_info.commands else 0}\n\n"
                f"🚀 **Advanced Features Enabled:**\n"
                f"• ✅ Custom filters\n"
                f"• ✅ Middleware processing\n"
                f"• ✅ Performance monitoring\n"
                f"• ✅ Error handling\n"
                f"• ✅ Rate limiting"
            )

            await self.client.sendMessage(chatId=chat_id, text=info_text, format=cast(TextFormat, TextFormat.MARKDOWN))

        except Exception as e:
            await self.client.sendMessage(chatId=chat_id, text=f"❌ Error getting bot info: {e}")

        if callback_query_id:
            await self.client.answerCallbackQuery(queryId=callback_query_id, text="ℹ️ Bot info loaded")

    async def show_user_stats(self, chat_id: int, callback_query_id: Optional[str], user_id: int) -> None:
        """Show user-specific statistics.

        Args:
            chat_id: The chat ID
            callback_query_id: Optional callback query ID to answer
            user_id: The user's ID
        """
        stats = self.monitor.get_stats()

        user_text = (
            f"📊 *Your Statistics*\n\n"
            f"👤 **User ID:** {user_id}\n"
            f"📈 **Total Updates:** {stats['total_updates']}\n"
            f"✅ **Success Rate:** {stats['success_rate']:.1f}%\n"
            f"⚡ **Avg Response Time:** {stats['avg_response_time']:.3f}s\n\n"
            f"🔍 **Filter Status:** Active\n"
            f"🔧 **Middleware Status:** Active"
        )

        await self.client.sendMessage(chatId=chat_id, text=user_text, format=cast(TextFormat, TextFormat.MARKDOWN))

        if callback_query_id:
            await self.client.answerCallbackQuery(queryId=callback_query_id, text="📊 Your stats loaded")

    async def test_filters(self, chat_id: int, callback_query_id: Optional[str] = None) -> None:
        """Test filter functionality.

        Args:
            chat_id: The chat ID
            callback_query_id: Optional callback query ID to answer
        """
        test_text = "🔍 *Filter Test Results*\n\n" "Testing all active filters:\n\n"

        for filter_obj in self.filters:
            stats = filter_obj.get_stats()
            status = "✅ Active" if stats["total"] > 0 else "⏸️ Waiting"
            test_text += f"• {filter_obj.name}: {status}\n"

        test_text += (
            "\n💡 **Tip:** Send different types of messages to test filters!\n"
            "• Text messages of various lengths\n"
            "• Messages with attachments\n"
            "• Messages from different users"
        )

        await self.client.sendMessage(chatId=chat_id, text=test_text, format=cast(TextFormat, TextFormat.MARKDOWN))

        if callback_query_id:
            await self.client.answerCallbackQuery(queryId=callback_query_id, text="🔍 Filter test completed")

    async def close_menu(self, chat_id: int, callback_query_id: Optional[str], message_id: str) -> None:
        """Close the menu.

        Args:
            chat_id: The chat ID
            callback_query_id: Optional callback query ID to answer
            message_id: The message ID to edit
        """
        await self.client.editMessage(messageId=message_id, text="👋 Menu closed!\n\nType /start to show it again.")

        if callback_query_id:
            await self.client.answerCallbackQuery(queryId=callback_query_id, text="❌ Menu closed")


async def run_bot() -> None:
    """Main bot function that handles the bot lifecycle."""
    token = get_token()

    logging.info("🚀 Starting Advanced Bot...")

    try:
        # Initialize the client
        async with MaxBotClient(token) as client:
            # Create bot instance
            bot = AdvancedBot(client)

            # Get bot information
            bot_info = await client.getMyInfo()
            logging.info(f"✅ Bot started successfully: {bot_info.first_name}")
            logging.info(f"🆔 Bot ID: {bot_info.user_id}")

            # Health check
            if await client.healthCheck():
                logging.info("✅ API health check passed")
            else:
                logging.warning("⚠️ API health check failed")

            # Start polling for updates
            logging.info("🔄 Starting to poll for updates...")
            logging.info("📱 Send /start to your bot to try the advanced features!")
            logging.info("⏹️ Press Ctrl+C to stop the bot")

            update_count = 0

            # Create a simple polling loop
            last_event_id = None
            while True:
                updates = await client.getUpdates(lastEventId=last_event_id)
                for update in updates.updates:
                    update_count += 1
                    logging.debug(f"📨 Processing update #{update_count}")

                    # Process the update with advanced features
                    await bot.process_update(update)

                # Update the last event ID for next polling
                if updates.marker:
                    last_event_id = updates.marker

    except AuthenticationError:
        logging.error("❌ Authentication failed! Please check your bot token.")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("⏹️ Bot stopped by user")
    except Exception as e:
        logging.error(f"❌ Fatal error: {e}")
        sys.exit(1)


def main() -> None:
    """Entry point for the bot."""
    setup_logging()

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logging.info("👋 Goodbye!")
    except Exception as e:
        logging.error(f"❌ Fatal error in main: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
