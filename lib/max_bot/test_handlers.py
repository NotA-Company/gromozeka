"""
Unit tests for Max Bot Handlers

This module contains comprehensive unit tests for all handler classes,
testing handler registration, execution (sync and async), filter matching,
and handler priorities.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from .handlers import (
    BotEventHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    Handler,
    HandlerRegistry,
    MessageHandler,
    UpdateHandler,
    bot_event_handler,
    callback_query_handler,
    chat_member_handler,
    message_handler,
    update_handler,
)
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
    UpdateType,
)


class TestHandler:
    """Test suite for base Handler class."""

    def test_handler_initialization(self):
        """Test Handler base class initialization, dood!"""

        # Handler is abstract, create a concrete implementation
        class TestHandler(Handler):
            async def handle(self, update, **kwargs):
                return "handled"

        handler = TestHandler(priority=5)
        assert handler.priority == 5

    def test_handler_default_priority(self):
        """Test Handler default priority, dood!"""

        # Handler is abstract, create a concrete implementation
        class TestHandler(Handler):
            async def handle(self, update, **kwargs):
                return "handled"

        handler = TestHandler()
        assert handler.priority == 0

    async def test_handler_can_handle_default(self):
        """Test Handler default can_handle returns True, dood!"""

        # Handler is abstract, create a concrete implementation
        class TestHandler(Handler):
            async def handle(self, update, **kwargs):
                return "handled"

        handler = TestHandler()
        update = MagicMock()

        assert handler.can_handle(update) is True

    async def test_handler_handle_not_implemented(self):
        """Test Handler handle method raises NotImplementedError, dood!"""

        # Handler is abstract, create a concrete implementation
        class TestHandler(Handler):
            async def handle(self, update, **kwargs):
                return "handled"

        # The TestHandler implementation doesn't raise NotImplementedError
        # Let's test the base Handler class directly
        class AbstractHandler(Handler):
            pass

        # Can't instantiate abstract class without implementing handle method
        with pytest.raises(TypeError):
            AbstractHandler()  # type: ignore


class TestMessageHandler:
    """Test suite for MessageHandler class."""

    @pytest.fixture
    def sync_callback(self):
        """Create a synchronous callback function."""

        def callback(update, **kwargs):
            callback.called = True
            callback.update = update
            callback.kwargs = kwargs

        callback.called = False
        return callback

    @pytest.fixture
    def async_callback(self):
        """Create an asynchronous callback function."""

        async def callback(update, **kwargs):
            callback.called = True
            callback.update = update
            callback.kwargs = kwargs

        callback.called = False
        return callback

    def test_message_handler_initialization(self, sync_callback):
        """Test MessageHandler initialization, dood!"""
        handler = MessageHandler(sync_callback, ["message_new"], priority=3)
        assert handler.callback == sync_callback
        assert handler.message_types == ["message_new"]
        assert handler.priority == 3

    def test_message_handler_default_message_types(self, sync_callback):
        """Test MessageHandler with default message types, dood!"""
        handler = MessageHandler(sync_callback)
        assert handler.message_types == []

    def test_can_handle_message_new(self, sync_callback):
        """Test MessageHandler can handle message_new updates, dood!"""
        handler = MessageHandler(sync_callback, ["message_new"])
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {
                    "body": {"mid": "msg_123", "text": "Hello"},
                    "chat_id": 12345,
                },
            }
        )

        assert handler.can_handle(update) is True

    def test_can_handle_message_edit(self, sync_callback):
        """Test MessageHandler can handle message_edit updates, dood!"""
        handler = MessageHandler(sync_callback, ["message_edit"])
        update = MessageEditUpdate.from_dict(
            {
                "update_type": "message_edit",
                "message": {
                    "body": {"mid": "msg_123", "text": "Edited"},
                    "chat_id": 12345,
                },
            }
        )

        assert handler.can_handle(update) is True

    def test_can_handle_message_delete(self, sync_callback):
        """Test MessageHandler can handle message_delete updates, dood!"""
        handler = MessageHandler(sync_callback, ["message_delete"])
        update = MessageDeleteUpdate.from_dict(
            {
                "update_type": "message_delete",
                "message_id": "msg_123",
                "chat_id": 12345,
            }
        )

        assert handler.can_handle(update) is True

    def test_cannot_handle_non_message_update(self, sync_callback):
        """Test MessageHandler cannot handle non-message updates, dood!"""
        handler = MessageHandler(sync_callback, ["message_new"])
        update = CallbackQueryUpdate.from_dict(
            {
                "update_type": "callback_query",
                "query_id": "query_123",
                "data": "test",
            }
        )

        assert handler.can_handle(update) is False

    def test_cannot_handle_wrong_message_type(self, sync_callback):
        """Test MessageHandler cannot handle wrong message type, dood!"""
        handler = MessageHandler(sync_callback, ["message_new"])
        update = MessageEditUpdate.from_dict(
            {
                "update_type": "message_edit",
                "message": {
                    "body": {"mid": "msg_123", "text": "Edited"},
                    "chat_id": 12345,
                },
            }
        )

        assert handler.can_handle(update) is False

    def test_can_handle_all_message_types(self, sync_callback):
        """Test MessageHandler can handle all message types when not filtered, dood!"""
        handler = MessageHandler(sync_callback)  # No message_types filter

        message_new = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_1", "text": "New"}, "chat_id": 12345},
            }
        )
        message_edit = MessageEditUpdate.from_dict(
            {
                "update_type": "message_edit",
                "message": {"body": {"mid": "msg_2", "text": "Edit"}, "chat_id": 12345},
            }
        )
        message_delete = MessageDeleteUpdate.from_dict(
            {
                "update_type": "message_delete",
                "message_id": "msg_3",
                "chat_id": 12345,
            }
        )

        assert handler.can_handle(message_new) is True
        assert handler.can_handle(message_edit) is True
        assert handler.can_handle(message_delete) is True

    async def test_handle_sync_callback(self, sync_callback):
        """Test MessageHandler with synchronous callback, dood!"""
        handler = MessageHandler(sync_callback)
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_123", "text": "Hello"}, "chat_id": 12345},
            }
        )

        await handler.handle(update, test_param="test_value")

        assert sync_callback.called is True
        assert sync_callback.update == update
        assert sync_callback.kwargs == {"test_param": "test_value"}

    async def test_handle_async_callback(self, async_callback):
        """Test MessageHandler with asynchronous callback, dood!"""
        handler = MessageHandler(async_callback)
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_123", "text": "Hello"}, "chat_id": 12345},
            }
        )

        await handler.handle(update, test_param="test_value")

        assert async_callback.called is True
        assert async_callback.update == update
        assert async_callback.kwargs == {"test_param": "test_value"}

    async def test_handle_does_not_call_when_cannot_handle(self, sync_callback):
        """Test MessageHandler doesn't call callback when it cannot handle update, dood!"""
        handler = MessageHandler(sync_callback, ["message_new"])
        update = CallbackQueryUpdate.from_dict(
            {
                "update_type": "callback_query",
                "query_id": "query_123",
                "data": "test",
            }
        )

        await handler.handle(update)

        assert sync_callback.called is False


class TestCallbackQueryHandler:
    """Test suite for CallbackQueryHandler class."""

    @pytest.fixture
    def sync_callback(self):
        """Create a synchronous callback function."""

        def callback(update, **kwargs):
            callback.called = True
            callback.update = update

        callback.called = False
        return callback

    def test_callback_query_handler_initialization(self, sync_callback):
        """Test CallbackQueryHandler initialization, dood!"""
        handler = CallbackQueryHandler(sync_callback, pattern="test", priority=2)
        assert handler.callback == sync_callback
        assert handler.pattern == "test"
        assert handler.priority == 2

    def test_callback_query_handler_no_pattern(self, sync_callback):
        """Test CallbackQueryHandler without pattern, dood!"""
        handler = CallbackQueryHandler(sync_callback)
        assert handler.pattern is None

    def test_can_handle_callback_query(self, sync_callback):
        """Test CallbackQueryHandler can handle callback queries, dood!"""
        handler = CallbackQueryHandler(sync_callback)
        update = CallbackQueryUpdate.from_dict(
            {
                "update_type": "callback_query",
                "query_id": "query_123",
                "data": "test_data",
            }
        )

        assert handler.can_handle(update) is True

    def test_cannot_handle_non_callback_query(self, sync_callback):
        """Test CallbackQueryHandler cannot handle non-callback queries, dood!"""
        handler = CallbackQueryHandler(sync_callback)
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_123", "text": "Hello"}, "chat_id": 12345},
            }
        )

        assert handler.can_handle(update) is False

    def test_can_handle_with_pattern_match(self, sync_callback):
        """Test CallbackQueryHandler pattern matching, dood!"""
        handler = CallbackQueryHandler(sync_callback, pattern="button")
        update = CallbackQueryUpdate.from_dict(
            {
                "update_type": "callback_query",
                "query_id": "query_123",
                "data": "button_clicked",
            }
        )

        assert handler.can_handle(update) is True

    def test_cannot_handle_with_pattern_no_match(self, sync_callback):
        """Test CallbackQueryHandler pattern not matching, dood!"""
        handler = CallbackQueryHandler(sync_callback, pattern="button")
        update = CallbackQueryUpdate.from_dict(
            {
                "update_type": "callback_query",
                "query_id": "query_123",
                "data": "other_action",
            }
        )

        assert handler.can_handle(update) is False

    def test_can_handle_with_payload_field(self, sync_callback):
        """Test CallbackQueryHandler with payload field, dood!"""
        handler = CallbackQueryHandler(sync_callback, pattern="test")
        update = MagicMock(spec=CallbackQueryUpdate)
        setattr(update, "data", None)
        setattr(update, "payload", "test_payload")

        assert handler.can_handle(update) is True

    async def test_handle_callback_query(self, sync_callback):
        """Test CallbackQueryHandler handling, dood!"""
        handler = CallbackQueryHandler(sync_callback)
        update = CallbackQueryUpdate.from_dict(
            {
                "update_type": "callback_query",
                "query_id": "query_123",
                "data": "test_data",
            }
        )

        await handler.handle(update)

        assert sync_callback.called is True
        assert sync_callback.update == update


class TestChatMemberHandler:
    """Test suite for ChatMemberHandler class."""

    @pytest.fixture
    def sync_callback(self):
        """Create a synchronous callback function."""

        def callback(update, **kwargs):
            callback.called = True
            callback.update = update

        callback.called = False
        return callback

    def test_chat_member_handler_initialization(self, sync_callback):
        """Test ChatMemberHandler initialization, dood!"""
        handler = ChatMemberHandler(sync_callback, ["chat_member_new"], priority=1)
        assert handler.callback == sync_callback
        assert handler.member_types == ["chat_member_new"]
        assert handler.priority == 1

    def test_can_handle_chat_member_new(self, sync_callback):
        """Test ChatMemberHandler can handle chat_member_new updates, dood!"""
        handler = ChatMemberHandler(sync_callback, ["chat_member_new"])
        update = ChatMemberNewUpdate.from_dict(
            {
                "update_type": "chat_member_new",
                "chat_id": 12345,
                "user_id": 111,
            }
        )

        assert handler.can_handle(update) is True

    def test_can_handle_chat_member_edit(self, sync_callback):
        """Test ChatMemberHandler can handle chat_member_edit updates, dood!"""
        handler = ChatMemberHandler(sync_callback, ["chat_member_edit"])
        update = ChatMemberEditUpdate.from_dict(
            {
                "update_type": "chat_member_edit",
                "chat_id": 12345,
                "user_id": 111,
            }
        )

        assert handler.can_handle(update) is True

    def test_can_handle_chat_member_delete(self, sync_callback):
        """Test ChatMemberHandler can handle chat_member_delete updates, dood!"""
        handler = ChatMemberHandler(sync_callback, ["chat_member_delete"])
        update = ChatMemberDeleteUpdate.from_dict(
            {
                "update_type": "chat_member_delete",
                "chat_id": 12345,
                "user_id": 111,
            }
        )

        assert handler.can_handle(update) is True

    def test_cannot_handle_non_chat_member_update(self, sync_callback):
        """Test ChatMemberHandler cannot handle non-chat member updates, dood!"""
        handler = ChatMemberHandler(sync_callback, ["chat_member_new"])
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_123", "text": "Hello"}, "chat_id": 12345},
            }
        )

        assert handler.can_handle(update) is False

    async def test_handle_chat_member_update(self, sync_callback):
        """Test ChatMemberHandler handling, dood!"""
        handler = ChatMemberHandler(sync_callback)
        update = ChatMemberNewUpdate.from_dict(
            {
                "update_type": "chat_member_new",
                "chat_id": 12345,
                "user_id": 111,
            }
        )

        await handler.handle(update)

        assert sync_callback.called is True
        assert sync_callback.update == update


class TestBotEventHandler:
    """Test suite for BotEventHandler class."""

    @pytest.fixture
    def sync_callback(self):
        """Create a synchronous callback function."""

        def callback(update, **kwargs):
            callback.called = True
            callback.update = update

        callback.called = False
        return callback

    def test_bot_event_handler_initialization(self, sync_callback):
        """Test BotEventHandler initialization, dood!"""
        handler = BotEventHandler(sync_callback, ["bot_started"], priority=4)
        assert handler.callback == sync_callback
        assert handler.event_types == ["bot_started"]
        assert handler.priority == 4

    def test_can_handle_bot_started(self, sync_callback):
        """Test BotEventHandler can handle bot_started updates, dood!"""
        handler = BotEventHandler(sync_callback, ["bot_started"])
        update = BotStartedUpdate.from_dict(
            {
                "update_type": "bot_started",
                "user": {"user_id": 111, "first_name": "User"},
            }
        )

        assert handler.can_handle(update) is True

    def test_can_handle_bot_added(self, sync_callback):
        """Test BotEventHandler can handle bot_added updates, dood!"""
        handler = BotEventHandler(sync_callback, ["bot_added"])
        update = BotAddedUpdate.from_dict(
            {
                "update_type": "bot_added",
                "chat_id": 12345,
            }
        )

        assert handler.can_handle(update) is True

    def test_can_handle_bot_removed(self, sync_callback):
        """Test BotEventHandler can handle bot_removed updates, dood!"""
        handler = BotEventHandler(sync_callback, ["bot_removed"])
        update = BotRemovedUpdate.from_dict(
            {
                "update_type": "bot_removed",
                "chat_id": 12345,
            }
        )

        assert handler.can_handle(update) is True

    def test_cannot_handle_non_bot_event_update(self, sync_callback):
        """Test BotEventHandler cannot handle non-bot event updates, dood!"""
        handler = BotEventHandler(sync_callback, ["bot_started"])
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_123", "text": "Hello"}, "chat_id": 12345},
            }
        )

        assert handler.can_handle(update) is False

    async def test_handle_bot_event(self, sync_callback):
        """Test BotEventHandler handling, dood!"""
        handler = BotEventHandler(sync_callback)
        update = BotStartedUpdate.from_dict(
            {
                "update_type": "bot_started",
                "user": {"user_id": 111, "first_name": "User"},
            }
        )

        await handler.handle(update)

        assert sync_callback.called is True
        assert sync_callback.update == update


class TestUpdateHandler:
    """Test suite for UpdateHandler class."""

    @pytest.fixture
    def sync_callback(self):
        """Create a synchronous callback function."""

        def callback(update, **kwargs):
            callback.called = True
            callback.update = update

        callback.called = False
        return callback

    def test_update_handler_initialization(self, sync_callback):
        """Test UpdateHandler initialization, dood!"""
        handler = UpdateHandler(sync_callback, ["message_new"], priority=3)
        assert handler.callback == sync_callback
        assert handler.update_types == ["message_new"]
        assert handler.priority == 3

    def test_update_handler_with_update_type_enum(self, sync_callback):
        """Test UpdateHandler with UpdateType enum, dood!"""
        handler = UpdateHandler(sync_callback, [UpdateType.MESSAGE_NEW])
        assert handler.update_types == [UpdateType.MESSAGE_NEW]

    def test_can_handle_all_updates_no_filter(self, sync_callback):
        """Test UpdateHandler can handle all updates when not filtered, dood!"""
        handler = UpdateHandler(sync_callback)

        message_update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_1", "text": "New"}, "chat_id": 12345},
            }
        )
        callback_update = CallbackQueryUpdate.from_dict(
            {
                "update_type": "callback_query",
                "query_id": "query_123",
                "data": "test",
            }
        )

        assert handler.can_handle(message_update) is True
        assert handler.can_handle(callback_update) is True

    def test_can_handle_with_string_filter(self, sync_callback):
        """Test UpdateHandler with string type filter, dood!"""
        handler = UpdateHandler(sync_callback, ["message_new"])
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_123", "text": "Hello"}, "chat_id": 12345},
            }
        )

        assert handler.can_handle(update) is True

    def test_can_handle_with_enum_filter(self, sync_callback):
        """Test UpdateHandler with UpdateType enum filter, dood!"""
        handler = UpdateHandler(sync_callback, [UpdateType.MESSAGE_NEW])
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_123", "text": "Hello"}, "chat_id": 12345},
            }
        )

        assert handler.can_handle(update) is True

    def test_cannot_handle_wrong_type_string(self, sync_callback):
        """Test UpdateHandler cannot handle wrong string type, dood!"""
        handler = UpdateHandler(sync_callback, ["message_new"])
        update = CallbackQueryUpdate.from_dict(
            {
                "update_type": "callback_query",
                "query_id": "query_123",
                "data": "test",
            }
        )

        assert handler.can_handle(update) is False

    def test_cannot_handle_wrong_type_enum(self, sync_callback):
        """Test UpdateHandler cannot handle wrong enum type, dood!"""
        handler = UpdateHandler(sync_callback, [UpdateType.MESSAGE_NEW])
        update = CallbackQueryUpdate.from_dict(
            {
                "update_type": "callback_query",
                "query_id": "query_123",
                "data": "test",
            }
        )

        assert handler.can_handle(update) is False

    def test_can_handle_mixed_type_filters(self, sync_callback):
        """Test UpdateHandler with mixed string and enum filters, dood!"""
        handler = UpdateHandler(sync_callback, ["message_new", UpdateType.CALLBACK_QUERY])

        message_update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_1", "text": "New"}, "chat_id": 12345},
            }
        )
        callback_update = CallbackQueryUpdate.from_dict(
            {
                "update_type": "callback_query",
                "query_id": "query_123",
                "data": "test",
            }
        )

        assert handler.can_handle(message_update) is True
        assert handler.can_handle(callback_update) is True

    async def test_handle_update(self, sync_callback):
        """Test UpdateHandler handling, dood!"""
        handler = UpdateHandler(sync_callback)
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_123", "text": "Hello"}, "chat_id": 12345},
            }
        )

        await handler.handle(update)

        assert sync_callback.called is True
        assert sync_callback.update == update


class TestHandlerRegistry:
    """Test suite for HandlerRegistry class."""

    @pytest.fixture
    def registry(self):
        """Create a HandlerRegistry instance."""
        return HandlerRegistry()

    @pytest.fixture
    def mock_handler(self):
        """Create a mock handler."""
        handler = MagicMock()
        handler.priority = 5
        handler.can_handle.return_value = True
        handler.handle = AsyncMock()
        return handler

    async def test_registry_initialization(self, registry):
        """Test HandlerRegistry initialization, dood!"""
        assert registry.get_handler_count() == 0
        assert isinstance(registry._handlers, list)
        assert isinstance(registry._lock, asyncio.Lock)

    async def test_register_handler(self, registry, mock_handler):
        """Test handler registration, dood!"""
        await registry.register_handler(mock_handler)
        assert registry.get_handler_count() == 1
        assert mock_handler in registry._handlers

    async def test_register_multiple_handlers(self, registry):
        """Test registering multiple handlers, dood!"""
        handler1 = MagicMock(priority=3, can_handle=lambda x: True)
        handler1.handle = AsyncMock()
        handler2 = MagicMock(priority=5, can_handle=lambda x: True)
        handler2.handle = AsyncMock()

        await registry.register_handler(handler1)
        await registry.register_handler(handler2)

        assert registry.get_handler_count() == 2
        # Handlers should be sorted by priority (higher first)
        assert registry._handlers[0] == handler2
        assert registry._handlers[1] == handler1

    async def test_unregister_handler(self, registry, mock_handler):
        """Test handler unregistration, dood!"""
        await registry.register_handler(mock_handler)
        assert registry.get_handler_count() == 1

        result = await registry.unregister_handler(mock_handler)
        assert result is True
        assert registry.get_handler_count() == 0
        assert mock_handler not in registry._handlers

    async def test_unregister_nonexistent_handler(self, registry, mock_handler):
        """Test unregistering non-existent handler, dood!"""
        result = await registry.unregister_handler(mock_handler)
        assert result is False
        assert registry.get_handler_count() == 0

    async def test_get_handlers_for_update(self, registry):
        """Test getting handlers for specific update, dood!"""
        # Create handlers with different can_handle logic
        handler1 = MagicMock(priority=5)
        handler1.can_handle.return_value = True
        handler1.handle = AsyncMock()

        handler2 = MagicMock(priority=3)
        handler2.can_handle.return_value = False
        handler2.handle = AsyncMock()

        handler3 = MagicMock(priority=4)
        handler3.can_handle.return_value = True
        handler3.handle = AsyncMock()

        await registry.register_handler(handler1)
        await registry.register_handler(handler2)
        await registry.register_handler(handler3)

        update = MagicMock()
        handlers = await registry.get_handlers_for_update(update)

        # Should return handlers that can handle the update, sorted by priority
        assert len(handlers) == 2
        assert handlers[0] == handler1  # priority 5
        assert handlers[1] == handler3  # priority 4

    async def test_process_update_with_handlers(self, registry):
        """Test processing update with multiple handlers, dood!"""
        handler1 = MagicMock(priority=5)
        handler1.can_handle.return_value = True
        handler1.handle = AsyncMock()

        handler2 = MagicMock(priority=3)
        handler2.can_handle.return_value = True
        handler2.handle = AsyncMock()

        await registry.register_handler(handler1)
        await registry.register_handler(handler2)

        update = MagicMock()
        await registry.process_update(update, test_param="test")

        # Both handlers should be called
        handler1.handle.assert_called_once_with(update, test_param="test")
        handler2.handle.assert_called_once_with(update, test_param="test")

    async def test_process_update_no_handlers(self, registry):
        """Test processing update with no matching handlers, dood!"""
        handler = MagicMock(priority=5)
        handler.can_handle.return_value = False
        handler.handle = AsyncMock()

        await registry.register_handler(handler)

        update = MagicMock()
        await registry.process_update(update)

        # Handler should not be called
        handler.handle.assert_not_called()

    async def test_process_update_handler_error(self, registry):
        """Test processing update with handler error, dood!"""
        handler1 = MagicMock(priority=5)
        handler1.can_handle.return_value = True
        handler1.handle = AsyncMock(side_effect=Exception("Test error"))

        handler2 = MagicMock(priority=3)
        handler2.can_handle.return_value = True
        handler2.handle = AsyncMock()

        await registry.register_handler(handler1)
        await registry.register_handler(handler2)

        update = MagicMock()
        # Should not raise exception, but should log error
        await registry.process_update(update)

        # Both handlers should be attempted
        handler1.handle.assert_called_once()
        handler2.handle.assert_called_once()

    def test_clear_handlers(self, registry):
        """Test clearing all handlers, dood!"""
        handler1 = MagicMock(priority=5)
        handler2 = MagicMock(priority=3)

        # Add handlers directly (bypass async for test)
        registry._handlers.extend([handler1, handler2])

        assert registry.get_handler_count() == 2

        registry.clear_handlers()

        assert registry.get_handler_count() == 0
        assert len(registry._handlers) == 0

    def test_get_handler_count(self, registry):
        """Test getting handler count, dood!"""
        assert registry.get_handler_count() == 0

        # Add handlers directly (bypass async for test)
        registry._handlers.extend([MagicMock(), MagicMock(), MagicMock()])

        assert registry.get_handler_count() == 3


class TestHandlerDecorators:
    """Test suite for handler decorator functions."""

    def test_message_handler_decorator(self):
        """Test message_handler decorator, dood!"""

        @message_handler(["message_new"], priority=2)
        def handle_message(update, **kwargs):
            pass

        assert isinstance(handle_message, MessageHandler)
        assert handle_message.message_types == ["message_new"]
        assert handle_message.priority == 2

    def test_message_handler_decorator_no_params(self):
        """Test message_handler decorator without parameters, dood!"""

        @message_handler()
        def handle_message(update, **kwargs):
            pass

        assert isinstance(handle_message, MessageHandler)
        assert handle_message.message_types == []
        assert handle_message.priority == 0

    def test_callback_query_handler_decorator(self):
        """Test callback_query_handler decorator, dood!"""

        @callback_query_handler(pattern="test", priority=3)
        def handle_callback(update, **kwargs):
            pass

        assert isinstance(handle_callback, CallbackQueryHandler)
        assert handle_callback.pattern == "test"
        assert handle_callback.priority == 3

    def test_chat_member_handler_decorator(self):
        """Test chat_member_handler decorator, dood!"""

        @chat_member_handler(["chat_member_new"], priority=1)
        def handle_chat_member(update, **kwargs):
            pass

        assert isinstance(handle_chat_member, ChatMemberHandler)
        assert handle_chat_member.member_types == ["chat_member_new"]
        assert handle_chat_member.priority == 1

    def test_bot_event_handler_decorator(self):
        """Test bot_event_handler decorator, dood!"""

        @bot_event_handler(["bot_started"], priority=4)
        def handle_bot_event(update, **kwargs):
            pass

        assert isinstance(handle_bot_event, BotEventHandler)
        assert handle_bot_event.event_types == ["bot_started"]
        assert handle_bot_event.priority == 4

    def test_update_handler_decorator(self):
        """Test update_handler decorator, dood!"""

        @update_handler(["message_new", "callback_query"], priority=2)
        def handle_update(update, **kwargs):
            pass

        assert isinstance(handle_update, UpdateHandler)
        assert handle_update.update_types == ["message_new", "callback_query"]
        assert handle_update.priority == 2


class TestHandlerIntegration:
    """Integration tests for handler system."""

    async def test_complex_handler_scenario(self):
        """Test complex scenario with multiple handler types, dood!"""
        registry = HandlerRegistry()

        # Track calls
        calls = []

        # Create handlers
        async def message_handler_func(update, **kwargs):
            calls.append(f"message: {update.type}")

        async def callback_handler_func(update, **kwargs):
            calls.append(f"callback: {update.data}")

        async def generic_handler_func(update, **kwargs):
            calls.append(f"generic: {update.type}")

        message_handler = MessageHandler(message_handler_func, ["message_new"], priority=3)
        callback_handler = CallbackQueryHandler(callback_handler_func, pattern="button", priority=5)
        generic_handler = UpdateHandler(generic_handler_func, priority=1)

        # Register handlers
        await registry.register_handler(message_handler)
        await registry.register_handler(callback_handler)
        await registry.register_handler(generic_handler)

        # Process message update
        message_update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_1", "text": "Hello"}, "chat_id": 12345},
            }
        )
        await registry.process_update(message_update)

        # Process callback update
        callback_update = CallbackQueryUpdate.from_dict(
            {
                "update_type": "callback_query",
                "query_id": "query_123",
                "data": "button_clicked",
            }
        )
        await registry.process_update(callback_update)

        # Check calls (should be in priority order)
        assert len(calls) == 4
        assert calls[0] == "message: UpdateType.MESSAGE_NEW"
        assert calls[1] == "generic: UpdateType.MESSAGE_NEW"
        assert calls[2] == "callback: button_clicked"
        assert calls[3] == "generic: UpdateType.CALLBACK_QUERY"

    async def test_handler_priority_ordering(self):
        """Test that handlers are executed in priority order, dood!"""
        registry = HandlerRegistry()
        execution_order = []

        async def high_priority_handler(update, **kwargs):
            execution_order.append("high")

        async def medium_priority_handler(update, **kwargs):
            execution_order.append("medium")

        async def low_priority_handler(update, **kwargs):
            execution_order.append("low")

        high_handler = UpdateHandler(high_priority_handler, priority=10)
        medium_handler = UpdateHandler(medium_priority_handler, priority=5)
        low_handler = UpdateHandler(low_priority_handler, priority=1)

        # Register in random order
        await registry.register_handler(medium_handler)
        await registry.register_handler(low_handler)
        await registry.register_handler(high_handler)

        update = MagicMock()
        await registry.process_update(update)

        # Should execute in priority order (high to low)
        assert execution_order == ["high", "medium", "low"]

    async def test_concurrent_handler_registration(self):
        """Test concurrent handler registration, dood!"""
        registry = HandlerRegistry()

        async def register_handlers():
            for i in range(10):
                handler = UpdateHandler(lambda u: None, priority=i)
                await registry.register_handler(handler)

        # Run multiple registration tasks concurrently
        tasks = [register_handlers() for _ in range(5)]
        await asyncio.gather(*tasks)

        # Should have 50 handlers total
        assert registry.get_handler_count() == 50

        # Handlers should be sorted by priority
        priorities = [handler.priority for handler in registry._handlers]
        assert priorities == sorted(priorities, reverse=True)
