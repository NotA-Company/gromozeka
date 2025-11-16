"""
Update dispatcher for Max Messenger Bot API.

This module provides a comprehensive update dispatching system that routes updates
to appropriate handlers based on update types, filters, and priorities.
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from .handlers import Handler, HandlerRegistry
from .models.update import Update

logger = logging.getLogger(__name__)


class Middleware:
    """Base class for middleware.

    Middleware can process updates before they reach handlers and can modify
    the context or stop the processing chain.
    """

    def __init__(self, priority: int = 0):
        """Initialize the middleware.

        Args:
            priority: Middleware priority (higher numbers = higher priority)
        """
        self.priority = priority

    async def process(self, update: Update, context: Dict[str, Any]) -> bool:
        """Process an update.

        Args:
            update: The update to process
            context: Processing context that can be modified

        Returns:
            True to continue processing, False to stop the chain
        """
        return True


class Dispatcher:
    """Update dispatcher that routes updates to handlers.

    Provides a comprehensive system for dispatching updates to appropriate handlers
    based on update types, filters, and priorities. Supports middleware and error handling.
    """

    def __init__(self, handler_registry: Optional[HandlerRegistry] = None):
        """Initialize the dispatcher.

        Args:
            handler_registry: Handler registry to use (creates new one if not provided)
        """
        self.handlerRegistry = handler_registry or HandlerRegistry()
        self.middleware: List[Middleware] = []
        self.errorHandlers: List[
            Union[
                Callable[[Exception, Update, Dict[str, Any]], None],
                Callable[[Exception, Update, Dict[str, Any]], Awaitable[None]],
            ]
        ] = []
        self._lock = asyncio.Lock()
        self._stats = {
            "updates_processed": 0,
            "handlers_executed": 0,
            "errors_occurred": 0,
        }

    async def register_handler(self, handler: Handler) -> None:
        """Register a new handler.

        Args:
            handler: The handler to register
        """
        await self.handlerRegistry.register_handler(handler)
        logger.debug(f"Dispatcher registered handler: {handler.__class__.__name__}")

    async def unregister_handler(self, handler: Handler) -> bool:
        """Unregister a handler.

        Args:
            handler: The handler to unregister

        Returns:
            True if the handler was found and removed
        """
        result = await self.handlerRegistry.unregister_handler(handler)
        if result:
            logger.debug(f"Dispatcher unregistered handler: {handler.__class__.__name__}")
        return result

    def add_middleware(self, middleware: Middleware) -> None:
        """Add middleware to the processing chain.

        Args:
            middleware: The middleware to add
        """
        self.middleware.append(middleware)
        # Sort middleware by priority (higher priority first)
        self.middleware.sort(key=lambda m: m.priority, reverse=True)
        logger.debug(f"Added middleware: {middleware.__class__.__name__}")

    def remove_middleware(self, middleware: Middleware) -> bool:
        """Remove middleware from the processing chain.

        Args:
            middleware: The middleware to remove

        Returns:
            True if the middleware was found and removed
        """
        if middleware in self.middleware:
            self.middleware.remove(middleware)
            logger.debug(f"Removed middleware: {middleware.__class__.__name__}")
            return True
        return False

    def add_error_handler(
        self,
        handler: Union[
            Callable[[Exception, Update, Dict[str, Any]], None],
            Callable[[Exception, Update, Dict[str, Any]], Awaitable[None]],
        ],
    ) -> None:
        """Add an error handler.

        Args:
            handler: Function to call when an error occurs
        """
        self.errorHandlers.append(handler)
        logger.debug("Added error handler")

    def remove_error_handler(self, handler: Callable[[Exception, Update, Dict[str, Any]], None]) -> bool:
        """Remove an error handler.

        Args:
            handler: The error handler to remove

        Returns:
            True if the handler was found and removed
        """
        if handler in self.errorHandlers:
            self.errorHandlers.remove(handler)
            logger.debug("Removed error handler")
            return True
        return False

    async def process_update(self, update: Update, **context: Any) -> None:
        """Process an update through the middleware chain and handlers.

        Args:
            update: The update to process
            **context: Additional context data
        """
        async with self._lock:
            self._stats["updates_processed"] += 1

        # Create processing context
        processing_context = {
            "update": update,
            "dispatcher": self,
            "handlers_executed": 0,
            "middleware_executed": 0,
            **context,
        }

        try:
            # Process through middleware chain
            if not await self._process_middleware(update, processing_context):
                logger.debug("Middleware chain stopped processing")
                return

            # Get applicable handlers
            handlers = await self.handlerRegistry.get_handlers_for_update(update)

            if not handlers:
                logger.debug(f"No handlers found for update type: {update.update_type}")
                return

            logger.debug(f"Dispatching update {update.update_type} to {len(handlers)} handlers")

            # Execute handlers
            for handler in handlers:
                try:
                    await handler.handle(update, **processing_context)
                    async with self._lock:
                        self._stats["handlers_executed"] += 1
                        processing_context["handlers_executed"] += 1

                except Exception as e:
                    logger.error(f"Error in handler {handler.__class__.__name__}: {e}")
                    await self._handle_error(e, update, processing_context)

        except Exception as e:
            logger.error(f"Error processing update: {e}")
            await self._handle_error(e, update, processing_context)

    async def _process_middleware(self, update: Update, context: Dict[str, Any]) -> bool:
        """Process update through middleware chain.

        Args:
            update: The update to process
            context: Processing context

        Returns:
            True to continue processing, False to stop
        """
        for middleware in self.middleware:
            try:
                should_continue = await middleware.process(update, context)
                context["middleware_executed"] += 1

                if not should_continue:
                    return False

            except Exception as e:
                logger.error(f"Error in middleware {middleware.__class__.__name__}: {e}")
                await self._handle_error(e, update, context)
                return False

        return True

    async def _handle_error(self, error: Exception, update: Update, context: Dict[str, Any]) -> None:
        """Handle errors that occur during processing.

        Args:
            error: The error that occurred
            update: The update being processed
            context: Processing context
        """
        async with self._lock:
            self._stats["errors_occurred"] += 1

        # Call all error handlers
        for error_handler in self.errorHandlers:
            try:
                if asyncio.iscoroutinefunction(error_handler):
                    await error_handler(error, update, context)
                else:
                    error_handler(error, update, context)
            except Exception as handler_error:
                logger.error(f"Error in error handler: {handler_error}")

    async def process_updates_batch(self, updates: List[Update], **context: Any) -> None:
        """Process multiple updates concurrently.

        Args:
            updates: List of updates to process
            **context: Additional context data
        """
        if not updates:
            return

        logger.debug(f"Processing batch of {len(updates)} updates")

        # Create tasks for concurrent processing
        tasks = [self.process_update(update, **context) for update in updates]

        # Wait for all tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)

    def get_stats(self) -> Dict[str, int]:
        """Get dispatcher statistics.

        Returns:
            Dictionary with processing statistics
        """
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset dispatcher statistics."""
        self._stats = {
            "updates_processed": 0,
            "handlers_executed": 0,
            "errors_occurred": 0,
        }
        logger.debug("Reset dispatcher statistics")

    def clear_handlers(self) -> None:
        """Clear all registered handlers."""
        self.handlerRegistry.clear_handlers()
        logger.debug("Cleared all handlers from dispatcher")

    def clear_middleware(self) -> None:
        """Clear all middleware."""
        self.middleware.clear()
        logger.debug("Cleared all middleware from dispatcher")

    def clear_error_handlers(self) -> None:
        """Clear all error handlers."""
        self.errorHandlers.clear()
        logger.debug("Cleared all error handlers from dispatcher")

    async def shutdown(self) -> None:
        """Shutdown the dispatcher and cleanup resources."""
        logger.info("Shutting down dispatcher")

        # Clear all components
        self.clear_handlers()
        self.clear_middleware()
        self.clear_error_handlers()

        # Reset stats
        self.reset_stats()

        logger.info("Dispatcher shutdown complete")


# Built-in middleware implementations
class LoggingMiddleware(Middleware):
    """Middleware that logs update processing."""

    def __init__(self, log_level: int = logging.DEBUG, priority: int = -100):
        """Initialize the logging middleware.

        Args:
            log_level: Logging level to use
            priority: Middleware priority
        """
        super().__init__(priority)
        self.logLevel = log_level

    async def process(self, update: Update, context: Dict[str, Any]) -> bool:
        """Log the update and continue processing."""
        logger.log(
            self.logLevel, f"Processing update: {update.update_type} (ID: {getattr(update, 'update_id', 'N/A')})"
        )
        return True


class ContextMiddleware(Middleware):
    """Middleware that adds common context data."""

    def __init__(self, additional_context: Optional[Dict[str, Any]] = None, priority: int = -50):
        """Initialize the context middleware.

        Args:
            additional_context: Additional context to add
            priority: Middleware priority
        """
        super().__init__(priority)
        self.additionalContext = additional_context or {}

    async def process(self, update: Update, context: Dict[str, Any]) -> bool:
        """Add common context data."""
        # Add timestamp
        import time

        context["processed_at"] = time.time()

        # Add update-specific context
        message = getattr(update, "message", None)
        if message:
            recipient = getattr(message, "recipient", None)
            if recipient:
                context["chat_id"] = getattr(recipient, "chat_id", None)
            sender = getattr(message, "sender", None)
            if sender:
                context["user_id"] = getattr(sender, "user_id", None)

        # Add additional context
        context.update(self.additionalContext)

        return True


class RateLimitMiddleware(Middleware):
    """Middleware that implements rate limiting."""

    def __init__(self, max_requests: int = 10, time_window: int = 60, priority: int = 0):
        """Initialize the rate limit middleware.

        Args:
            max_requests: Maximum requests per time window
            time_window: Time window in seconds
            priority: Middleware priority
        """
        super().__init__(priority)
        self.maxRequests = max_requests
        self.timeWindow = time_window
        self._requests: Dict[str, List[float]] = {}

    async def process(self, update: Update, context: Dict[str, Any]) -> bool:
        """Check rate limits."""
        import time

        # Get identifier for rate limiting (chat_id or user_id)
        identifier = context.get("chat_id") or context.get("user_id") or "global"
        current_time = time.time()

        # Clean old requests
        if identifier not in self._requests:
            self._requests[identifier] = []

        # Remove requests outside the time window
        self._requests[identifier] = [
            req_time for req_time in self._requests[identifier] if current_time - req_time < self.timeWindow
        ]

        # Check if rate limit exceeded
        if len(self._requests[identifier]) >= self.maxRequests:
            logger.warning(f"Rate limit exceeded for {identifier}")
            return False

        # Add current request
        self._requests[identifier].append(current_time)
        return True
