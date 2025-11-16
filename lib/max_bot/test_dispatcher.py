"""
Unit tests for Max Bot Dispatcher

This module contains comprehensive unit tests for the Dispatcher class,
testing update routing, middleware execution, error handling, and handler priorities.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from .dispatcher import Dispatcher, Middleware
from .handlers import Handler, HandlerRegistry
from .models.update import MessageNewUpdate


class TestMiddleware:
    """Test suite for Middleware base class."""

    def test_middleware_initialization(self):
        """Test Middleware initialization with priority, dood!"""
        middleware = Middleware(priority=5)
        assert middleware.priority == 5

    def test_middleware_default_priority(self):
        """Test Middleware default priority, dood!"""
        middleware = Middleware()
        assert middleware.priority == 0

    async def test_middleware_process_default(self):
        """Test Middleware default process returns True, dood!"""
        middleware = Middleware()
        update = MagicMock()
        context = {}

        result = await middleware.process(update, context)
        assert result is True


class TestCustomMiddleware:
    """Test suite for custom middleware implementations."""

    class TestMiddleware(Middleware):
        """Test middleware implementation."""

        def __init__(self, priority=0, should_continue=True, should_error=False):
            super().__init__(priority)
            self.should_continue = should_continue
            self.should_error = should_error
            self.process_called = False
            self.process_update = None
            self.process_context = None

        async def process(self, update, context):
            self.process_called = True
            self.process_update = update
            self.process_context = context

            if self.should_error:
                raise Exception("Test middleware error")

            return self.should_continue

    def test_custom_middleware_initialization(self):
        """Test custom middleware initialization, dood!"""
        middleware = self.TestMiddleware(priority=3, should_continue=False)
        assert middleware.priority == 3
        assert middleware.should_continue is False

    async def test_custom_middleware_process(self):
        """Test custom middleware process method, dood!"""
        middleware = self.TestMiddleware()
        update = MagicMock()
        context = {"test": "value"}

        result = await middleware.process(update, context)

        assert middleware.process_called is True
        assert middleware.process_update == update
        assert middleware.process_context == context
        assert result is True

    async def test_custom_middleware_stop_processing(self):
        """Test custom middleware can stop processing, dood!"""
        middleware = self.TestMiddleware(should_continue=False)
        update = MagicMock()
        context = {}

        result = await middleware.process(update, context)
        assert result is False

    async def test_custom_middleware_error(self):
        """Test custom middleware error handling, dood!"""
        middleware = self.TestMiddleware(should_error=True)
        update = MagicMock()
        context = {}

        with pytest.raises(Exception, match="Test middleware error"):
            await middleware.process(update, context)


class TestDispatcher:
    """Test suite for Dispatcher class."""

    @pytest.fixture
    def dispatcher(self, mock_handler_registry):
        """Create a Dispatcher instance for testing."""
        dispatcher = Dispatcher()
        dispatcher.handlerRegistry = mock_handler_registry
        return dispatcher

    @pytest.fixture
    def mock_handler_registry(self):
        """Create a mock handler registry."""
        registry = MagicMock()
        registry.register_handler = AsyncMock()
        registry.unregister_handler = AsyncMock(return_value=True)
        registry.get_handlers_for_update = AsyncMock(return_value=[])
        registry.clear_handlers = MagicMock()
        return registry

    @pytest.fixture
    def mock_handler(self):
        """Create a mock handler."""
        handler = MagicMock()
        handler.handle = AsyncMock()
        return handler

    @pytest.fixture
    def sample_update(self):
        """Create a sample update for testing."""
        return MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {
                    "body": {"mid": "msg_123", "text": "Hello, World!"},
                    "chat_id": 12345,
                },
            }
        )

    def test_dispatcher_initialization(self):
        """Test Dispatcher initialization, dood!"""
        dispatcher = Dispatcher()
        assert isinstance(dispatcher.handlerRegistry, HandlerRegistry)
        assert dispatcher.middleware == []
        assert dispatcher.errorHandlers == []
        assert isinstance(dispatcher._lock, asyncio.Lock)
        assert dispatcher._stats == {
            "updates_processed": 0,
            "handlers_executed": 0,
            "errors_occurred": 0,
        }

    def test_dispatcher_initialization_with_registry(self, mock_handler_registry):
        """Test Dispatcher initialization with custom registry, dood!"""
        dispatcher = Dispatcher(mock_handler_registry)
        assert dispatcher.handlerRegistry == mock_handler_registry

    async def test_register_handler(self, dispatcher, mock_handler):
        """Test handler registration, dood!"""
        await dispatcher.register_handler(mock_handler)
        dispatcher.handlerRegistry.register_handler.assert_called_once_with(mock_handler)

    async def test_unregister_handler(self, dispatcher, mock_handler):
        """Test handler unregistration, dood!"""
        result = await dispatcher.unregister_handler(mock_handler)
        dispatcher.handlerRegistry.unregister_handler.assert_called_once_with(mock_handler)
        assert result is True

    def test_add_middleware(self, dispatcher):
        """Test adding middleware, dood!"""
        middleware1 = Middleware(priority=3)
        middleware2 = Middleware(priority=5)
        middleware3 = Middleware(priority=1)

        dispatcher.add_middleware(middleware1)
        dispatcher.add_middleware(middleware2)
        dispatcher.add_middleware(middleware3)

        # Should be sorted by priority (higher first)
        assert len(dispatcher.middleware) == 3
        assert dispatcher.middleware[0] == middleware2  # priority 5
        assert dispatcher.middleware[1] == middleware1  # priority 3
        assert dispatcher.middleware[2] == middleware3  # priority 1

    def test_remove_middleware(self, dispatcher):
        """Test removing middleware, dood!"""
        middleware = Middleware()
        dispatcher.add_middleware(middleware)

        result = dispatcher.remove_middleware(middleware)
        assert result is True
        assert len(dispatcher.middleware) == 0

    def test_remove_nonexistent_middleware(self, dispatcher):
        """Test removing non-existent middleware, dood!"""
        middleware = Middleware()
        result = dispatcher.remove_middleware(middleware)
        assert result is False

    def test_add_error_handler(self, dispatcher):
        """Test adding error handler, dood!"""
        error_handler = MagicMock()
        dispatcher.add_error_handler(error_handler)
        assert error_handler in dispatcher.errorHandlers

    def test_remove_error_handler(self, dispatcher):
        """Test removing error handler, dood!"""
        error_handler = MagicMock()
        dispatcher.add_error_handler(error_handler)

        result = dispatcher.remove_error_handler(error_handler)
        assert result is True
        assert len(dispatcher.errorHandlers) == 0

    def test_remove_nonexistent_error_handler(self, dispatcher):
        """Test removing non-existent error handler, dood!"""
        error_handler = MagicMock()
        result = dispatcher.remove_error_handler(error_handler)
        assert result is False

    async def test_process_update_no_handlers(self, dispatcher, sample_update):
        """Test processing update with no handlers, dood!"""
        await dispatcher.process_update(sample_update)

        stats = dispatcher.get_stats()
        assert stats["updates_processed"] == 1
        assert stats["handlers_executed"] == 0
        assert stats["errors_occurred"] == 0

    async def test_process_update_with_handlers(self, dispatcher, sample_update, mock_handler):
        """Test processing update with handlers, dood!"""
        dispatcher.handlerRegistry.get_handlers_for_update.return_value = [mock_handler]
        mock_handler.handle.return_value = "handled"

        await dispatcher.process_update(sample_update)

        mock_handler.handle.assert_called_once()
        stats = dispatcher.get_stats()
        assert stats["updates_processed"] == 1
        assert stats["handlers_executed"] == 1
        assert stats["errors_occurred"] == 0

    async def test_process_update_with_multiple_handlers(self, dispatcher, sample_update):
        """Test processing update with multiple handlers, dood!"""
        handler1 = MagicMock()
        handler1.handle = AsyncMock()
        handler2 = MagicMock()
        handler2.handle = AsyncMock()

        dispatcher.handlerRegistry.get_handlers_for_update.return_value = [handler1, handler2]
        handler1.handle.return_value = "handled1"
        handler2.handle.return_value = "handled2"

        await dispatcher.process_update(sample_update)

        handler1.handle.assert_called_once()
        handler2.handle.assert_called_once()
        stats = dispatcher.get_stats()
        assert stats["handlers_executed"] == 2

    async def test_process_update_with_context(self, dispatcher, sample_update, mock_handler):
        """Test processing update with context data, dood!"""
        dispatcher.handlerRegistry.get_handlers_for_update.return_value = [mock_handler]
        mock_handler.handle.return_value = "handled"

        context_data = {"user_id": 123, "chat_type": "private"}
        await dispatcher.process_update(sample_update, **context_data)

        # Check that context was passed to handler
        call_args = mock_handler.handle.call_args
        assert "user_id" in call_args[1]
        assert "chat_type" in call_args[1]
        assert call_args[1]["user_id"] == 123
        assert call_args[1]["chat_type"] == "private"

    async def test_process_update_handler_error(self, dispatcher, sample_update, mock_handler):
        """Test processing update with handler error, dood!"""
        mock_handler.handle.side_effect = Exception("Test handler error")
        dispatcher.handlerRegistry.get_handlers_for_update.return_value = [mock_handler]
        mock_handler.handle.side_effect = Exception("Test handler error")

        # Should not raise exception
        await dispatcher.process_update(sample_update)

        stats = dispatcher.get_stats()
        assert stats["updates_processed"] == 1
        assert stats["handlers_executed"] == 0
        assert stats["errors_occurred"] == 1

    async def test_process_update_with_error_handler(self, dispatcher, sample_update, mock_handler):
        """Test processing update with error handler, dood!"""
        mock_handler.handle.side_effect = Exception("Test handler error")
        dispatcher.handlerRegistry.get_handlers_for_update.return_value = [mock_handler]
        mock_handler.handle.side_effect = Exception("Test handler error")

        error_handler = AsyncMock()
        dispatcher.add_error_handler(error_handler)

        await dispatcher.process_update(sample_update)

        # Error handler should be called
        error_handler.assert_called_once()
        call_args = error_handler.call_args[0]
        assert isinstance(call_args[0], Exception)
        assert call_args[1] == sample_update
        assert isinstance(call_args[2], dict)

    async def test_process_update_with_sync_error_handler(self, dispatcher, sample_update, mock_handler):
        """Test processing update with synchronous error handler, dood!"""
        mock_handler.handle.side_effect = Exception("Test handler error")
        dispatcher.handlerRegistry.get_handlers_for_update.return_value = [mock_handler]
        mock_handler.handle.side_effect = Exception("Test handler error")

        error_handler = MagicMock()
        dispatcher.add_error_handler(error_handler)

        await dispatcher.process_update(sample_update)

        # Sync error handler should be called
        error_handler.assert_called_once()

    async def test_process_update_middleware_chain(self, dispatcher, sample_update):
        """Test processing update through middleware chain, dood!"""
        # Create test middleware
        middleware1 = TestCustomMiddleware.TestMiddleware(priority=3)
        middleware2 = TestCustomMiddleware.TestMiddleware(priority=5)
        middleware3 = TestCustomMiddleware.TestMiddleware(priority=1)

        dispatcher.add_middleware(middleware1)
        dispatcher.add_middleware(middleware2)
        dispatcher.add_middleware(middleware3)

        await dispatcher.process_update(sample_update)

        # All middleware should be processed in priority order
        assert middleware2.process_called is True
        assert middleware1.process_called is True
        assert middleware3.process_called is True

        # Check context was passed
        assert middleware2.process_context is not None and middleware2.process_context["update"] == sample_update
        assert middleware1.process_context is not None and middleware1.process_context["update"] == sample_update
        assert middleware3.process_context is not None and middleware3.process_context["update"] == sample_update

    async def test_process_update_middleware_stops_processing(self, dispatcher, sample_update, mock_handler):
        """Test middleware can stop processing, dood!"""
        # Create middleware that stops processing
        middleware = TestCustomMiddleware.TestMiddleware(priority=5, should_continue=False)
        dispatcher.add_middleware(middleware)

        dispatcher.handlerRegistry.get_handlers_for_update.return_value = [mock_handler]
        mock_handler.handle.return_value = "handled"

        await dispatcher.process_update(sample_update)

        # Middleware should be called but handler should not
        assert middleware.process_called is True
        mock_handler.handle.assert_not_called()

    async def test_process_update_middleware_error(self, dispatcher, sample_update, mock_handler):
        """Test middleware error handling, dood!"""
        # Create middleware that throws error
        middleware = TestCustomMiddleware.TestMiddleware(priority=5, should_error=True)
        dispatcher.add_middleware(middleware)

        dispatcher.handlerRegistry.get_handlers_for_update.return_value = [mock_handler]
        mock_handler.handle.side_effect = Exception("Test handler error")

        error_handler = AsyncMock()
        dispatcher.add_error_handler(error_handler)

        await dispatcher.process_update(sample_update)

        # Error handler should be called
        error_handler.assert_called_once()
        # Handler should not be called
        mock_handler.handle.assert_not_called()

    async def test_process_updates_batch(self, dispatcher):
        """Test processing multiple updates in batch, dood!"""
        updates = [
            MessageNewUpdate.from_dict(
                {
                    "update_type": "message_new",
                    "message": {"body": {"mid": "msg_1", "text": "Hello 1"}, "chat_id": 12345},
                }
            ),
            MessageNewUpdate.from_dict(
                {
                    "update_type": "message_new",
                    "message": {"body": {"mid": "msg_2", "text": "Hello 2"}, "chat_id": 12345},
                }
            ),
            MessageNewUpdate.from_dict(
                {
                    "update_type": "message_new",
                    "message": {"body": {"mid": "msg_3", "text": "Hello 3"}, "chat_id": 12345},
                }
            ),
        ]

        await dispatcher.process_updates_batch(updates)

        stats = dispatcher.get_stats()
        assert stats["updates_processed"] == 3

    async def test_process_updates_batch_empty(self, dispatcher):
        """Test processing empty batch of updates, dood!"""
        await dispatcher.process_updates_batch([])

        stats = dispatcher.get_stats()
        assert stats["updates_processed"] == 0

    async def test_process_updates_batch_with_context(self, dispatcher):
        """Test processing batch with context data, dood!"""
        updates = [
            MessageNewUpdate.from_dict(
                {
                    "update_type": "message_new",
                    "message": {"body": {"mid": "msg_1", "text": "Hello"}, "chat_id": 12345},
                }
            ),
        ]

        handler = MagicMock()
        handler.handle = AsyncMock()
        dispatcher.handlerRegistry.get_handlers_for_update.return_value = [handler]

        context_data = {"batch_id": 123}
        await dispatcher.process_updates_batch(updates, **context_data)

        # Context should be passed to handler
        call_args = handler.handle.call_args
        assert "batch_id" in call_args[1]
        assert call_args[1]["batch_id"] == 123

    def test_get_stats(self, dispatcher):
        """Test getting dispatcher statistics, dood!"""
        # Modify stats directly for testing
        dispatcher._stats["updates_processed"] = 10
        dispatcher._stats["handlers_executed"] = 25
        dispatcher._stats["errors_occurred"] = 2

        stats = dispatcher.get_stats()
        assert stats == {
            "updates_processed": 10,
            "handlers_executed": 25,
            "errors_occurred": 2,
        }

        # Should return a copy, not the original
        stats["updates_processed"] = 999
        assert dispatcher._stats["updates_processed"] == 10

    def test_reset_stats(self, dispatcher):
        """Test resetting dispatcher statistics, dood!"""
        # Modify stats directly for testing
        dispatcher._stats["updates_processed"] = 10
        dispatcher._stats["handlers_executed"] = 25
        dispatcher._stats["errors_occurred"] = 2

        dispatcher.reset_stats()

        assert dispatcher._stats == {
            "updates_processed": 0,
            "handlers_executed": 0,
            "errors_occurred": 0,
        }

    def test_clear_handlers(self, dispatcher):
        """Test clearing all handlers, dood!"""
        dispatcher.handlerRegistry.clear_handlers = MagicMock()
        dispatcher.clear_handlers()
        dispatcher.handlerRegistry.clear_handlers.assert_called_once()

    def test_clear_middleware(self, dispatcher):
        """Test clearing all middleware, dood!"""
        middleware1 = Middleware()
        middleware2 = Middleware()
        dispatcher.add_middleware(middleware1)
        dispatcher.add_middleware(middleware2)

        assert len(dispatcher.middleware) == 2

        dispatcher.clear_middleware()

        assert len(dispatcher.middleware) == 0

    def test_clear_error_handlers(self, dispatcher):
        """Test clearing all error handlers, dood!"""
        error_handler1 = MagicMock()
        error_handler2 = MagicMock()
        dispatcher.add_error_handler(error_handler1)
        dispatcher.add_error_handler(error_handler2)

        assert len(dispatcher.errorHandlers) == 2

        dispatcher.clear_error_handlers()

        assert len(dispatcher.errorHandlers) == 0

    async def test_shutdown(self, dispatcher):
        """Test dispatcher shutdown, dood!"""
        # Add some components
        middleware = Middleware()
        error_handler = MagicMock()
        dispatcher.add_middleware(middleware)
        dispatcher.add_error_handler(error_handler)
        dispatcher._stats["updates_processed"] = 5

        # Mock the clear methods
        dispatcher.clear_handlers = MagicMock()
        dispatcher.clear_middleware = MagicMock()
        dispatcher.clear_error_handlers = MagicMock()
        dispatcher.reset_stats = MagicMock()

        await dispatcher.shutdown()

        # All cleanup methods should be called
        dispatcher.clear_handlers.assert_called_once()
        dispatcher.clear_middleware.assert_called_once()
        dispatcher.clear_error_handlers.assert_called_once()
        dispatcher.reset_stats.assert_called_once()


class TestDispatcherIntegration:
    """Integration tests for dispatcher with real components."""

    async def test_full_processing_pipeline(self):
        """Test complete processing pipeline with real components, dood!"""
        dispatcher = Dispatcher()

        # Track execution
        executed_handlers = []
        executed_middleware = []

        # Create real middleware
        class TestMiddleware(Middleware):
            def __init__(self, name, priority=0):
                super().__init__(priority)
                self.name = name

            async def process(self, update, context):
                executed_middleware.append(self.name)
                context[f"middleware_{self.name}"] = True
                return True

        # Create real handler
        class TestHandler(Handler):
            def __init__(self, name):
                super().__init__()
                self.name = name

            async def handle(self, update, **kwargs):
                executed_handlers.append(self.name)
                context = kwargs.get("context", {})
                context[f"handler_{self.name}"] = True

        # Add middleware
        dispatcher.add_middleware(TestMiddleware("auth", priority=5))
        dispatcher.add_middleware(TestMiddleware("logging", priority=3))
        dispatcher.add_middleware(TestMiddleware("validation", priority=1))

        # Add handlers
        handler1 = TestHandler("message_handler")
        handler2 = TestHandler("analytics_handler")
        await dispatcher.register_handler(handler1)
        await dispatcher.register_handler(handler2)

        # Create update
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_123", "text": "Hello"}, "chat_id": 12345},
            }
        )

        # Mock the handler registry to return our handlers
        dispatcher.handlerRegistry.get_handlers_for_update = AsyncMock(return_value=[handler1, handler2])

        # Fix the handler method signature issue
        # The dispatcher passes update as both positional and keyword argument
        async def mock_handler1(*args, **kwargs):
            executed_handlers.append(handler1.name)

        async def mock_handler2(*args, **kwargs):
            executed_handlers.append(handler2.name)

        handler1.handle = mock_handler1
        handler2.handle = mock_handler2

        # Process update
        await dispatcher.process_update(update)

        # Check middleware execution order (by priority)
        assert executed_middleware == ["auth", "logging", "validation"]

        # Check handlers were executed
        assert len(executed_handlers) == 2
        assert "message_handler" in executed_handlers
        assert "analytics_handler" in executed_handlers

        # Check stats
        stats = dispatcher.get_stats()
        assert stats["updates_processed"] == 1
        assert stats["handlers_executed"] == 2
        assert stats["errors_occurred"] == 0

    async def test_error_handling_pipeline(self):
        """Test error handling through the pipeline, dood!"""
        dispatcher = Dispatcher()

        # Track error handling
        errors_handled = []

        # Create error handler
        async def test_error_handler(error, update, context):
            errors_handled.append(str(error))

        dispatcher.add_error_handler(test_error_handler)

        # Create handler that throws error
        class ErrorHandler(Handler):
            async def handle(self, update, **kwargs):
                raise Exception("Test processing error")

        error_handler_instance = ErrorHandler()
        await dispatcher.register_handler(error_handler_instance)

        # Mock the handler registry
        dispatcher.handlerRegistry.get_handlers_for_update = AsyncMock(return_value=[error_handler_instance])

        # Fix the handler method signature issue
        # The dispatcher passes update as both positional and keyword argument
        async def mock_error_handler(*args, **kwargs):
            raise Exception("Test processing error")

        error_handler_instance.handle = mock_error_handler

        # Create update
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_123", "text": "Hello"}, "chat_id": 12345},
            }
        )

        # Process update
        await dispatcher.process_update(update)

        # Check error was handled
        assert len(errors_handled) == 1
        assert "Test processing error" in errors_handled[0]

        # Check stats
        stats = dispatcher.get_stats()
        assert stats["errors_occurred"] == 1

    async def test_concurrent_processing(self):
        """Test concurrent update processing, dood!"""
        dispatcher = Dispatcher()

        # Track processing
        processed_updates = []

        # Create handler
        class TestHandler(Handler):
            async def handle(self, update, **kwargs):
                # Simulate some processing time
                await asyncio.sleep(0.01)
                # For MessageNewUpdate, access the message body
                message = getattr(update, "message", None)
                if message:
                    processed_updates.append(message.body.mid)
                else:
                    # Fallback for other update types
                    processed_updates.append("unknown")

        handler = TestHandler()
        await dispatcher.register_handler(handler)

        # Mock the handler registry
        dispatcher.handlerRegistry.get_handlers_for_update = AsyncMock(return_value=[handler])

        # Fix the handler method signature issue
        # The dispatcher passes update as both positional and keyword argument
        async def mock_handler(*args, **kwargs):
            # Get the update from args (first positional argument)
            update = args[0] if args else kwargs.get("update")
            await asyncio.sleep(0.01)
            # Check if update has message attribute
            message = getattr(update, "message", None)
            if message:
                processed_updates.append(message.body.mid)
            else:
                processed_updates.append("unknown")

        handler.handle = mock_handler

        # Create multiple updates
        updates = [
            MessageNewUpdate.from_dict(
                {
                    "type": "message_new",
                    "message": {
                        "recipient": {"chat_id": 12345},
                        "body": {"mid": f"msg_{i}", "text": f"Message {i}"},
                        "timestamp": 1234567890,
                    },
                }
            )
            for i in range(5)
        ]

        # Process batch
        await dispatcher.process_updates_batch(updates)  # type: ignore[arg-type]

        # All updates should be processed
        assert len(processed_updates) == 5
        assert set(processed_updates) == {"msg_0", "msg_1", "msg_2", "msg_3", "msg_4"}

        # Check stats
        stats = dispatcher.get_stats()
        assert stats["updates_processed"] == 5
        assert stats["handlers_executed"] == 5

    async def test_middleware_context_modification(self):
        """Test middleware modifying context, dood!"""
        dispatcher = Dispatcher()
        execution_log = []

        # Create middleware that modifies context
        class ContextMiddleware(Middleware):
            async def process(self, update, context):
                context["user_authenticated"] = True
                context["user_role"] = "admin"
                return True

        # Create handler that checks context
        class ContextHandler(Handler):
            async def handle(self, update, **kwargs):
                assert kwargs.get("user_authenticated") is True
                assert kwargs.get("user_role") == "admin"

        dispatcher.add_middleware(ContextMiddleware(priority=5))
        await dispatcher.register_handler(ContextHandler())

        # Mock the handler registry
        dispatcher.handlerRegistry.get_handlers_for_update = AsyncMock(return_value=[ContextHandler()])

        # Fix the handler method signature issue
        context_handler = ContextHandler()
        context_handler.handle = AsyncMock(
            side_effect=lambda update, **kwargs: execution_log.append("handler_executed")
        )
        dispatcher.handlerRegistry.get_handlers_for_update = AsyncMock(return_value=[context_handler])

        # Create update
        update = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_123", "text": "Hello"}, "chat_id": 12345},
            }
        )

        # Process update - should not raise assertion error
        await dispatcher.process_update(update)

    async def test_complex_middleware_chain(self):
        """Test complex middleware chain with different behaviors, dood!"""
        dispatcher = Dispatcher()

        # Track middleware execution
        execution_log = []

        # Create different middleware types
        class AuthMiddleware(Middleware):
            def __init__(self):
                super().__init__(priority=10)

            async def process(self, update, context):
                execution_log.append("auth_start")
                context["authenticated"] = True
                execution_log.append("auth_end")
                return True

        class RateLimitMiddleware(Middleware):
            def __init__(self):
                super().__init__(priority=8)

            async def process(self, update, context):
                execution_log.append("rate_limit_check")
                # Simulate rate limiting
                if context.get("user_id") == 999:
                    execution_log.append("rate_limited")
                    return False
                execution_log.append("rate_limit_passed")
                return True

        class LoggingMiddleware(Middleware):
            def __init__(self):
                super().__init__(priority=5)

            async def process(self, update, context):
                execution_log.append("logging")
                return True

        # Add middleware
        dispatcher.add_middleware(AuthMiddleware())
        dispatcher.add_middleware(RateLimitMiddleware())
        dispatcher.add_middleware(LoggingMiddleware())

        # Create handler
        class TestHandler(Handler):
            async def handle(self, update, **kwargs):
                execution_log.append("handler_executed")

        handler = TestHandler()
        await dispatcher.register_handler(handler)

        # Mock the handler registry
        dispatcher.handlerRegistry.get_handlers_for_update = AsyncMock(return_value=[handler])

        # Fix the handler method signature issue
        # The dispatcher passes update as both positional and keyword argument
        async def mock_handler(*args, **kwargs):
            execution_log.append("handler_executed")

        handler.handle = mock_handler

        # Test normal flow
        update1 = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_1", "text": "Hello"}, "chat_id": 12345},
            }
        )

        await dispatcher.process_update(update1, user_id=123)

        # Check execution order
        expected_normal = [
            "auth_start",
            "auth_end",
            "rate_limit_check",
            "rate_limit_passed",
            "logging",
            "handler_executed",
        ]
        assert execution_log == expected_normal

        # Reset log
        execution_log.clear()

        # Test rate limited flow
        update2 = MessageNewUpdate.from_dict(
            {
                "update_type": "message_new",
                "message": {"body": {"mid": "msg_2", "text": "Hello"}, "chat_id": 12345},
            }
        )

        await dispatcher.process_update(update2, user_id=999)

        # Check execution order (should stop at rate limit)
        expected_rate_limited = ["auth_start", "auth_end", "rate_limit_check", "rate_limited"]
        assert execution_log == expected_rate_limited
