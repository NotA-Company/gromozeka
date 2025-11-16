"""
Event handler system for Max Messenger Bot API.

This module provides a comprehensive event handling system with base handler classes,
specific handlers for different update types, and a registry to manage handlers.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, List, Optional, Union

from .models.update import (
    BotAddedUpdate,
    BotRemovedUpdate,
    BotStartedUpdate,
    CallbackQueryUpdate,
    ChatMemberDeleteUpdate,
    ChatMemberEditUpdate,
    ChatMemberNewUpdate,
    MessageDeleteUpdate,
    MessageEditUpdate,
    MessageNewUpdate,
    Update,
    UpdateType,
)

logger = logging.getLogger(__name__)


class Handler(ABC):
    """Base class for all event handlers.

    Provides the foundation for creating specific handlers for different types of updates.
    All handlers should inherit from this class and implement the handle method.
    """

    def __init__(self, priority: int = 0):
        """Initialize the handler.

        Args:
            priority: Handler priority (higher numbers = higher priority)
        """
        self.priority = priority

    @abstractmethod
    async def handle(self, update: Update, **kwargs: Any) -> None:
        """Handle an update.

        Args:
            update: The update to handle
            **kwargs: Additional context data
        """
        pass

    def can_handle(self, update: Update) -> bool:
        """Check if this handler can handle the given update.

        Args:
            update: The update to check

        Returns:
            True if this handler can handle the update
        """
        return True


class MessageHandler(Handler):
    """Handler for message events.

    Handles message_created, message_edited, and message_removed updates.
    """

    def __init__(
        self,
        callback: Union[Callable[[Update], None], Callable[[Update], Awaitable[None]]],
        message_types: Optional[List[str]] = None,
        priority: int = 0,
    ):
        """Initialize the message handler.

        Args:
            callback: Function to call when a message is received
            message_types: List of message types to handle (optional)
            priority: Handler priority
        """
        super().__init__(priority)
        self.callback = callback
        self.message_types = message_types or []

    def can_handle(self, update: Update) -> bool:
        """Check if this handler can handle the given update."""
        if not isinstance(update, (MessageNewUpdate, MessageEditUpdate, MessageDeleteUpdate)):
            return False

        if self.message_types:
            # Check if update type is in the allowed types
            update_type_str = update.type.value
            return update_type_str in self.message_types

        return True

    async def handle(self, update: Update, **kwargs: Any) -> None:
        """Handle a message update."""
        if self.can_handle(update):
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(update, **kwargs)
            else:
                self.callback(update, **kwargs)


class CallbackQueryHandler(Handler):
    """Handler for callback query events.

    Handles message_callback updates from inline keyboard buttons.
    """

    def __init__(
        self,
        callback: Union[Callable[[Update], None], Callable[[Update], Awaitable[None]]],
        pattern: Optional[str] = None,
        priority: int = 0,
    ):
        """Initialize the callback query handler.

        Args:
            callback: Function to call when a callback query is received
            pattern: Pattern to match against callback data (optional)
            priority: Handler priority
        """
        super().__init__(priority)
        self.callback = callback
        self.pattern = pattern

    def can_handle(self, update: Update) -> bool:
        """Check if this handler can handle the given update."""
        if not isinstance(update, CallbackQueryUpdate):
            return False

        if self.pattern:
            # Check if callback data matches the pattern
            callback_data = getattr(update, "data", "") or getattr(update, "payload", "")
            return self.pattern in callback_data

        return True

    async def handle(self, update: Update, **kwargs: Any) -> None:
        """Handle a callback query update."""
        if self.can_handle(update):
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(update, **kwargs)
            else:
                self.callback(update, **kwargs)


class ChatMemberHandler(Handler):
    """Handler for chat member events.

    Handles user_added_to_chat, user_removed_from_chat updates.
    """

    def __init__(
        self,
        callback: Union[Callable[[Update], None], Callable[[Update], Awaitable[None]]],
        member_types: Optional[List[str]] = None,
        priority: int = 0,
    ):
        """Initialize the chat member handler.

        Args:
            callback: Function to call when a chat member event occurs
            member_types: List of member event types to handle (optional)
            priority: Handler priority
        """
        super().__init__(priority)
        self.callback = callback
        self.member_types = member_types or []

    def can_handle(self, update: Update) -> bool:
        """Check if this handler can handle the given update."""
        if not isinstance(update, (ChatMemberNewUpdate, ChatMemberEditUpdate, ChatMemberDeleteUpdate)):
            return False

        if self.member_types:
            # Check if update type is in the allowed types
            update_type_str = update.type.value
            return update_type_str in self.member_types

        return True

    async def handle(self, update: Update, **kwargs: Any) -> None:
        """Handle a chat member update."""
        if self.can_handle(update):
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(update, **kwargs)
            else:
                self.callback(update, **kwargs)


class BotEventHandler(Handler):
    """Handler for bot lifecycle events.

    Handles bot_started, bot_added_to_chat, bot_removed_from_chat updates.
    """

    def __init__(
        self,
        callback: Union[Callable[[Update], None], Callable[[Update], Awaitable[None]]],
        event_types: Optional[List[str]] = None,
        priority: int = 0,
    ):
        """Initialize the bot event handler.

        Args:
            callback: Function to call when a bot event occurs
            event_types: List of bot event types to handle (optional)
            priority: Handler priority
        """
        super().__init__(priority)
        self.callback = callback
        self.event_types = event_types or []

    def can_handle(self, update: Update) -> bool:
        """Check if this handler can handle the given update."""
        if not isinstance(update, (BotStartedUpdate, BotAddedUpdate, BotRemovedUpdate)):
            return False

        if self.event_types:
            # Check if update type is in the allowed types
            update_type_str = update.type.value
            return update_type_str in self.event_types

        return True

    async def handle(self, update: Update, **kwargs: Any) -> None:
        """Handle a bot event update."""
        if self.can_handle(update):
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(update, **kwargs)
            else:
                self.callback(update, **kwargs)


class UpdateHandler(Handler):
    """Generic handler for any update type.

    This is a fallback handler that can handle any type of update.
    """

    def __init__(
        self,
        callback: Union[Callable[[Update], None], Callable[[Update], Awaitable[None]]],
        update_types: Optional[List[Union[str, UpdateType]]] = None,
        priority: int = 0,
    ):
        """Initialize the generic update handler.

        Args:
            callback: Function to call when an update is received
            update_types: List of update types to handle (optional)
            priority: Handler priority
        """
        super().__init__(priority)
        self.callback = callback
        self.update_types = update_types or []

    def can_handle(self, update: Update) -> bool:
        """Check if this handler can handle the given update."""
        if not self.update_types:
            return True

        # Check if update type is in the allowed types
        update_type_str = update.type.value
        for allowed_type in self.update_types:
            if isinstance(allowed_type, UpdateType):
                if update.type == allowed_type:
                    return True
            else:
                if update_type_str == allowed_type:
                    return True

        return False

    async def handle(self, update: Update, **kwargs: Any) -> None:
        """Handle any update."""
        if self.can_handle(update):
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(update, **kwargs)
            else:
                self.callback(update, **kwargs)


class HandlerRegistry:
    """Registry for managing event handlers.

    Provides methods to register, unregister, and retrieve handlers for different update types.
    """

    def __init__(self):
        """Initialize the handler registry."""
        self._handlers: List[Handler] = []
        self._lock = asyncio.Lock()

    async def register_handler(self, handler: Handler) -> None:
        """Register a new handler.

        Args:
            handler: The handler to register
        """
        async with self._lock:
            self._handlers.append(handler)
            # Sort handlers by priority (higher priority first)
            self._handlers.sort(key=lambda h: h.priority, reverse=True)
            logger.debug(f"Registered handler with priority {handler.priority}")

    async def unregister_handler(self, handler: Handler) -> bool:
        """Unregister a handler.

        Args:
            handler: The handler to unregister

        Returns:
            True if the handler was found and removed
        """
        async with self._lock:
            if handler in self._handlers:
                self._handlers.remove(handler)
                logger.debug("Unregistered handler")
                return True
            return False

    async def get_handlers_for_update(self, update: Update) -> List[Handler]:
        """Get all handlers that can handle the given update.

        Args:
            update: The update to get handlers for

        Returns:
            List of handlers that can handle the update
        """
        async with self._lock:
            return [handler for handler in self._handlers if handler.can_handle(update)]

    async def process_update(self, update: Update, **kwargs: Any) -> None:
        """Process an update with all applicable handlers.

        Args:
            update: The update to process
            **kwargs: Additional context data to pass to handlers
        """
        handlers = await self.get_handlers_for_update(update)

        if not handlers:
            logger.debug(f"No handlers found for update type: {update.type}")
            return

        logger.debug(f"Processing update {update.type} with {len(handlers)} handlers")

        for handler in handlers:
            try:
                await handler.handle(update, **kwargs)
            except Exception as e:
                logger.error(f"Error in handler {handler.__class__.__name__}: {e}")

    def clear_handlers(self) -> None:
        """Clear all registered handlers."""
        self._handlers.clear()
        logger.debug("Cleared all handlers")

    def get_handler_count(self) -> int:
        """Get the number of registered handlers.

        Returns:
            Number of registered handlers
        """
        return len(self._handlers)


# Decorator functions for easy handler registration
def message_handler(
    message_types: Optional[List[str]] = None,
    priority: int = 0,
    registry: Optional[HandlerRegistry] = None,
):
    """Decorator for creating message handlers.

    Args:
        message_types: List of message types to handle (optional)
        priority: Handler priority
        registry: Handler registry to register with (optional)

    Returns:
        Decorator function
    """

    def decorator(func: Callable[[Update], None]) -> MessageHandler:
        handler = MessageHandler(func, message_types, priority)
        if registry:
            asyncio.create_task(registry.register_handler(handler))
        return handler

    return decorator


def callback_query_handler(
    pattern: Optional[str] = None,
    priority: int = 0,
    registry: Optional[HandlerRegistry] = None,
):
    """Decorator for creating callback query handlers.

    Args:
        pattern: Pattern to match against callback data (optional)
        priority: Handler priority
        registry: Handler registry to register with (optional)

    Returns:
        Decorator function
    """

    def decorator(func: Callable[[Update], None]) -> CallbackQueryHandler:
        handler = CallbackQueryHandler(func, pattern, priority)
        if registry:
            asyncio.create_task(registry.register_handler(handler))
        return handler

    return decorator


def chat_member_handler(
    member_types: Optional[List[str]] = None,
    priority: int = 0,
    registry: Optional[HandlerRegistry] = None,
):
    """Decorator for creating chat member handlers.

    Args:
        member_types: List of member event types to handle (optional)
        priority: Handler priority
        registry: Handler registry to register with (optional)

    Returns:
        Decorator function
    """

    def decorator(func: Callable[[Update], None]) -> ChatMemberHandler:
        handler = ChatMemberHandler(func, member_types, priority)
        if registry:
            asyncio.create_task(registry.register_handler(handler))
        return handler

    return decorator


def bot_event_handler(
    event_types: Optional[List[str]] = None,
    priority: int = 0,
    registry: Optional[HandlerRegistry] = None,
):
    """Decorator for creating bot event handlers.

    Args:
        event_types: List of bot event types to handle (optional)
        priority: Handler priority
        registry: Handler registry to register with (optional)

    Returns:
        Decorator function
    """

    def decorator(func: Callable[[Update], None]) -> BotEventHandler:
        handler = BotEventHandler(func, event_types, priority)
        if registry:
            asyncio.create_task(registry.register_handler(handler))
        return handler

    return decorator


def update_handler(
    update_types: Optional[List[Union[str, UpdateType]]] = None,
    priority: int = 0,
    registry: Optional[HandlerRegistry] = None,
):
    """Decorator for creating generic update handlers.

    Args:
        update_types: List of update types to handle (optional)
        priority: Handler priority
        registry: Handler registry to register with (optional)

    Returns:
        Decorator function
    """

    def decorator(func: Callable[[Update], None]) -> UpdateHandler:
        handler = UpdateHandler(func, update_types, priority)
        if registry:
            asyncio.create_task(registry.register_handler(handler))
        return handler

    return decorator
