"""
Comprehensive tests for the Handlers Manager, dood!

This module tests the HandlersManager class which coordinates all bot handlers
and routes messages to appropriate handlers. Tests cover initialization, handler
registration, message routing, command handling, error handling, and integration
with various handler types.
"""

from unittest.mock import Mock, patch

import pytest
from telegram import Chat

from internal.bot.handlers.base import BaseBotHandler, HandlerResultStatus
from internal.bot.handlers.manager import HandlersManager
from internal.bot.models import CommandHandlerInfo, EnsuredMessage
from internal.config.manager import ConfigManager
from internal.database.wrapper import DatabaseWrapper
from lib.ai.manager import LLMManager
from tests.fixtures.telegram_mocks import (
    createMockBot,
    createMockCallbackQuery,
    createMockContext,
)
from tests.utils import createAsyncMock, createMockUpdate

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mockConfigManager():
    """Create a mock ConfigManager with default bot config, dood!"""
    mock = Mock(spec=ConfigManager)
    mock.getBotConfig.return_value = {
        "bot_owners": ["owner1", "owner2"],
        "defaults": {
            "model": "gpt-4",
            "temperature": 0.7,
        },
    }
    mock.getOpenWeatherMapConfig.return_value = {
        "enabled": False,
    }
    return mock


@pytest.fixture
def mockDatabase():
    """Create a mock DatabaseWrapper, dood!"""
    mock = Mock(spec=DatabaseWrapper)
    mock.getChatSettings.return_value = {}
    mock.getChatUser.return_value = None
    mock.getChatMessageByMessageId.return_value = None
    mock.saveChatMessage = Mock()
    mock.updateChatUser = Mock()
    return mock


@pytest.fixture
def mockLlmManager():
    """Create a mock LLMManager, dood!"""
    mock = Mock(spec=LLMManager)
    mock.getModel.return_value = None
    return mock


@pytest.fixture
def mockBot():
    """Create a mock bot instance, dood!"""
    return createMockBot(username="test_bot")


@pytest.fixture
@patch("internal.bot.handlers.manager.CacheService")
@patch("internal.bot.handlers.manager.QueueService")
def handlersManager(
    mockQueueService,
    mockCacheService,
    mockConfigManager,
    mockDatabase,
    mockLlmManager,
):
    """Create a HandlersManager instance with mocked dependencies, dood!"""
    # Mock singleton instances
    mockCache = Mock()
    mockCache.injectDatabase = Mock()
    mockCache.getChatUserData.return_value = {}
    mockCacheService.getInstance.return_value = mockCache

    mockQueue = Mock()
    mockQueueService.getInstance.return_value = mockQueue

    manager = HandlersManager(mockConfigManager, mockDatabase, mockLlmManager)
    return manager


@pytest.fixture
def mockContext():
    """Create a mock context, dood!"""
    return createMockContext()


@pytest.fixture
def mockEnsuredMessage():
    """Create a mock EnsuredMessage, dood!"""
    mock = Mock(spec=EnsuredMessage)
    mock.chat = Mock()
    mock.chat.id = 123
    mock.chat.type = Chat.PRIVATE
    mock.user = Mock()
    mock.user.id = 456
    mock.messageId = 1
    mock.messageText = "test message"
    mock.sender = "Test User"
    mock.setUserData = Mock()
    return mock


# ============================================================================
# Initialization Tests
# ============================================================================


class TestInitialization:
    """Test HandlersManager initialization, dood!"""

    @patch("internal.bot.handlers.manager.CacheService")
    @patch("internal.bot.handlers.manager.QueueService")
    def testManagerInitialization(
        self,
        mockQueueService,
        mockCacheService,
        mockConfigManager,
        mockDatabase,
        mockLlmManager,
    ):
        """Test that HandlersManager initializes correctly, dood!"""
        # Mock singleton instances
        mockCache = Mock()
        mockCache.injectDatabase = Mock()
        mockCacheService.getInstance.return_value = mockCache

        mockQueue = Mock()
        mockQueueService.getInstance.return_value = mockQueue

        manager = HandlersManager(mockConfigManager, mockDatabase, mockLlmManager)

        # Verify manager attributes
        assert manager.configManager == mockConfigManager
        assert manager.db == mockDatabase
        assert manager.llmManager == mockLlmManager
        assert manager.cache == mockCache
        assert manager.queueService == mockQueue

        # Verify cache was injected with database
        mockCache.injectDatabase.assert_called_once_with(mockDatabase)

    @patch("internal.bot.handlers.manager.CacheService")
    @patch("internal.bot.handlers.manager.QueueService")
    def testHandlerRegistrationDuringInit(
        self,
        mockQueueService,
        mockCacheService,
        mockConfigManager,
        mockDatabase,
        mockLlmManager,
    ):
        """Test that all handlers are registered during initialization, dood!"""
        mockCache = Mock()
        mockCache.injectDatabase = Mock()
        mockCacheService.getInstance.return_value = mockCache

        mockQueue = Mock()
        mockQueueService.getInstance.return_value = mockQueue

        manager = HandlersManager(mockConfigManager, mockDatabase, mockLlmManager)

        # Verify handlers list is populated
        assert len(manager.handlers) > 0
        assert all(isinstance(h, BaseBotHandler) for h in manager.handlers)

    @patch("internal.bot.handlers.manager.CacheService")
    @patch("internal.bot.handlers.manager.QueueService")
    def testHandlerOrderDuringInit(
        self,
        mockQueueService,
        mockCacheService,
        mockConfigManager,
        mockDatabase,
        mockLlmManager,
    ):
        """Test that handlers are registered in correct priority order, dood!"""
        mockCache = Mock()
        mockCache.injectDatabase = Mock()
        mockCacheService.getInstance.return_value = mockCache

        mockQueue = Mock()
        mockQueueService.getInstance.return_value = mockQueue

        manager = HandlersManager(mockConfigManager, mockDatabase, mockLlmManager)

        # Verify SpamHandlers is first
        from internal.bot.handlers.spam import SpamHandler

        assert isinstance(manager.handlers[0], SpamHandler)

        # Verify LLMMessageHandler is last
        from internal.bot.handlers.llm_messages import LLMMessageHandler

        assert isinstance(manager.handlers[-1], LLMMessageHandler)

    @patch("internal.bot.handlers.manager.CacheService")
    @patch("internal.bot.handlers.manager.QueueService")
    def testDependencyInjectionToHandlers(
        self,
        mockQueueService,
        mockCacheService,
        mockConfigManager,
        mockDatabase,
        mockLlmManager,
    ):
        """Test that dependencies are properly injected to all handlers, dood!"""
        mockCache = Mock()
        mockCache.injectDatabase = Mock()
        mockCacheService.getInstance.return_value = mockCache

        mockQueue = Mock()
        mockQueueService.getInstance.return_value = mockQueue

        manager = HandlersManager(mockConfigManager, mockDatabase, mockLlmManager)

        # Verify all handlers have correct dependencies
        for handler in manager.handlers:
            assert handler.configManager == mockConfigManager
            assert handler.db == mockDatabase
            assert handler.llmManager == mockLlmManager

    @patch("internal.bot.handlers.manager.CacheService")
    @patch("internal.bot.handlers.manager.QueueService")
    def testWeatherHandlerConditionalRegistration(
        self,
        mockQueueService,
        mockCacheService,
        mockConfigManager,
        mockDatabase,
        mockLlmManager,
    ):
        """Test that WeatherHandler is only registered when enabled, dood!"""
        mockCache = Mock()
        mockCache.injectDatabase = Mock()
        mockCacheService.getInstance.return_value = mockCache

        mockQueue = Mock()
        mockQueueService.getInstance.return_value = mockQueue

        # Test with weather disabled
        mockConfigManager.getOpenWeatherMapConfig.return_value = {"enabled": False}
        manager = HandlersManager(mockConfigManager, mockDatabase, mockLlmManager)

        from internal.bot.handlers.weather import WeatherHandler

        weatherHandlers = [h for h in manager.handlers if isinstance(h, WeatherHandler)]
        assert len(weatherHandlers) == 0

        # Test with weather enabled (with required api-key)
        mockConfigManager.getOpenWeatherMapConfig.return_value = {
            "enabled": True,
            "api-key": "test_api_key",
        }
        manager2 = HandlersManager(mockConfigManager, mockDatabase, mockLlmManager)

        weatherHandlers2 = [h for h in manager2.handlers if isinstance(h, WeatherHandler)]
        assert len(weatherHandlers2) == 1


# ============================================================================
# Handler Registration Tests
# ============================================================================


class TestHandlerRegistration:
    """Test handler registration and management, dood!"""

    def testGetCommandHandlers(self, handlersManager):
        """Test retrieving all command handlers from registered handlers, dood!"""
        commandHandlers = handlersManager.getCommandHandlers()

        # Should return a sequence
        assert isinstance(commandHandlers, (list, tuple))

        # All items should be CommandHandlerInfo
        for handler in commandHandlers:
            assert isinstance(handler, CommandHandlerInfo)

    def testInjectBot(self, handlersManager, mockBot):
        """Test bot injection to all handlers, dood!"""
        handlersManager.injectBot(mockBot)

        # Verify all handlers received the bot
        for handler in handlersManager.handlers:
            assert handler._bot == mockBot

    def testHandlerListNotEmpty(self, handlersManager):
        """Test that handlers list is not empty after initialization, dood!"""
        assert len(handlersManager.handlers) > 0

    def testAllHandlersAreBaseBotHandler(self, handlersManager):
        """Test that all registered handlers inherit from BaseBotHandler, dood!"""
        for handler in handlersManager.handlers:
            assert isinstance(handler, BaseBotHandler)


# ============================================================================
# Message Routing Tests
# ============================================================================


class TestMessageRouting:
    """Test message routing to appropriate handlers, dood!"""

    @pytest.mark.asyncio
    async def testRoutingToCorrectHandler(self, handlersManager, mockContext):
        """Test that messages are routed to correct handler based on type, dood!"""
        update = createMockUpdate(text="/help")

        # Mock handler responses
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.SKIPPED)

        # Set one handler to return FINAL
        handlersManager.handlers[0].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)

        await handlersManager.handle_message(update, mockContext)

        # Verify first handler was called
        handlersManager.handlers[0].messageHandler.assert_called_once()

    @pytest.mark.asyncio
    async def testCommandMessageRouting(self, handlersManager, mockContext):
        """Test routing of command messages, dood!"""
        update = createMockUpdate(text="/start")

        # Mock all handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers were called
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    async def testTextMessageRouting(self, handlersManager, mockContext):
        """Test routing of regular text messages, dood!"""
        update = createMockUpdate(text="Hello bot!")

        # Mock all handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers were called
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    async def testMediaMessageRouting(self, handlersManager, mockContext):
        """Test routing of media messages, dood!"""
        update = createMockUpdate(hasPhoto=True, text="Check this out")

        # Mock all handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers were called
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    async def testCallbackQueryRouting(self, handlersManager, mockContext):
        """Test routing of callback queries, dood!"""
        query = createMockCallbackQuery(data='{"action": "test"}')
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Mock all handlers
        for handler in handlersManager.handlers:
            handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_button(update, mockContext)

        # Verify query was answered
        query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def testHandlerChainExecution(self, handlersManager, mockContext):
        """Test that handler chain executes in order until FINAL, dood!"""
        update = createMockUpdate(text="test")

        # Mock handlers to return NEXT except the 3rd one returns FINAL
        for i, handler in enumerate(handlersManager.handlers):
            if i == 2:
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)
            else:
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify first 3 handlers were called
        for i in range(3):
            handlersManager.handlers[i].messageHandler.assert_called_once()

        # Verify remaining handlers were not called
        for i in range(3, len(handlersManager.handlers)):
            handlersManager.handlers[i].messageHandler.assert_not_called()


# ============================================================================
# Command Handler Tests
# ============================================================================


class TestCommandHandling:
    """Test command detection and handling, dood!"""

    @pytest.mark.asyncio
    async def testCommandDetection(self, handlersManager, mockContext):
        """Test that commands are properly detected, dood!"""
        update = createMockUpdate(text="/help")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify message was processed
        assert handlersManager.handlers[0].messageHandler.called

    @pytest.mark.asyncio
    async def testCommandWithParameters(self, handlersManager, mockContext):
        """Test handling commands with parameters, dood!"""
        update = createMockUpdate(text="/weather Moscow")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers were called with update containing command
        for handler in handlersManager.handlers:
            if handler.messageHandler.called:
                args = handler.messageHandler.call_args[0]
                assert args[0] == update

    @pytest.mark.asyncio
    async def testUnknownCommandHandling(self, handlersManager, mockContext):
        """Test handling of unknown commands, dood!"""
        update = createMockUpdate(text="/unknowncommand")

        # Mock handlers to return NEXT (no handler handles it)
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify all handlers were called (chain completed)
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    async def testCommandHandlerSelection(self, handlersManager, mockContext):
        """Test that correct handler is selected for command, dood!"""
        update = createMockUpdate(text="/help")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.SKIPPED)

        # Make help handler return FINAL
        from internal.bot.handlers.help_command import HelpHandler

        for handler in handlersManager.handlers:
            if isinstance(handler, HelpHandler):
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)

        await handlersManager.handle_message(update, mockContext)

        # Verify help handler was called
        helpHandler = next(h for h in handlersManager.handlers if isinstance(h, HelpHandler))
        helpHandler.messageHandler.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def testCommandPermissions(self, handlersManager, mockContext):
        """Test that command permissions are respected, dood!"""
        update = createMockUpdate(text="/admin_command")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers processed the message
        assert any(h.messageHandler.called for h in handlersManager.handlers)


# ============================================================================
# Message Preprocessor Tests
# ============================================================================


class TestMessagePreprocessor:
    """Test message preprocessing pipeline, dood!"""

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testMessagePreprocessing(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test that messages go through preprocessing, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test message")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify EnsuredMessage was created
        mockFromMessage.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testUserValidation(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test user validation during preprocessing, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify user data was set
        mockEnsuredMessage.setUserData.assert_called_once()

    @pytest.mark.asyncio
    async def testMessageFiltering(self, handlersManager, mockContext):
        """Test message filtering in preprocessing, dood!"""
        update = createMockUpdate(text="test")
        update.message = None  # No message to process

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers were called with None ensuredMessage (manager still processes)
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()
            # Verify ensuredMessage is None
            args = handler.messageHandler.call_args[0]
            assert args[2] is None  # ensuredMessage should be None

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testSpamDetectionIntegration(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test spam detection integration in preprocessing, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="spam message")

        # Mock spam handler to return FINAL (blocks message)
        from internal.bot.handlers.spam import SpamHandler

        for handler in handlersManager.handlers:
            if isinstance(handler, SpamHandler):
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)
            else:
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify spam handler was called
        spamHandler = next(h for h in handlersManager.handlers if isinstance(h, SpamHandler))
        spamHandler.messageHandler.assert_called_once()  # type: ignore[attr-defined]

        # Verify other handlers were not called (spam blocked)
        for handler in handlersManager.handlers:
            if not isinstance(handler, SpamHandler):
                handler.messageHandler.assert_not_called()


# ============================================================================
# Handler Priority Tests
# ============================================================================


class TestHandlerPriority:
    """Test handler execution priority, dood!"""

    @pytest.mark.asyncio
    async def testHandlersExecuteInOrder(self, handlersManager, mockContext):
        """Test that handlers execute in correct order, dood!"""
        update = createMockUpdate(text="test")

        callOrder = []

        # Mock handlers to track call order
        for i, handler in enumerate(handlersManager.handlers):

            def makeCallback(index):
                async def callback(*args, **kwargs):
                    callOrder.append(index)
                    return HandlerResultStatus.NEXT

                return callback

            handler.messageHandler = createAsyncMock(sideEffect=makeCallback(i))

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers were called in order
        assert callOrder == list(range(len(handlersManager.handlers)))

    @pytest.mark.asyncio
    async def testHighPriorityHandlersRunFirst(self, handlersManager, mockContext):
        """Test that high priority handlers run before others, dood!"""
        update = createMockUpdate(text="test")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify SpamHandlers (first) was called before others
        from internal.bot.handlers.spam import SpamHandler

        spamHandler = handlersManager.handlers[0]
        assert isinstance(spamHandler, SpamHandler)
        spamHandler.messageHandler.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def testHandlerChainInterruption(self, handlersManager, mockContext):
        """Test that FINAL status interrupts handler chain, dood!"""
        update = createMockUpdate(text="test")

        # Mock first handler to return FINAL
        handlersManager.handlers[0].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)

        # Mock remaining handlers
        for handler in handlersManager.handlers[1:]:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify only first handler was called
        handlersManager.handlers[0].messageHandler.assert_called_once()
        for handler in handlersManager.handlers[1:]:
            handler.messageHandler.assert_not_called()

    @pytest.mark.asyncio
    async def testFallbackHandlerExecution(self, handlersManager, mockContext):
        """Test that fallback handler executes when others skip, dood!"""
        update = createMockUpdate(text="test")

        # Mock all handlers except last to return SKIPPED
        for handler in handlersManager.handlers[:-1]:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.SKIPPED)

        # Last handler (LLM) returns FINAL
        handlersManager.handlers[-1].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)

        await handlersManager.handle_message(update, mockContext)

        # Verify last handler was called
        handlersManager.handlers[-1].messageHandler.assert_called_once()


# ============================================================================
# Callback Query Handling Tests
# ============================================================================


class TestCallbackQueryHandling:
    """Test callback query handling, dood!"""

    @pytest.mark.asyncio
    async def testCallbackQueryRouting(self, handlersManager, mockContext):
        """Test that callback queries are routed correctly, dood!"""
        query = createMockCallbackQuery(data='{"action": "test"}')
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_button(update, mockContext)

        # Verify handlers were called
        for handler in handlersManager.handlers:
            handler.buttonHandler.assert_called_once()

    @pytest.mark.asyncio
    async def testCallbackDataParsing(self, handlersManager, mockContext):
        """Test that callback data is parsed correctly, dood!"""
        query = createMockCallbackQuery(data='{"action": "test", "value": 123}')
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_button(update, mockContext)

        # Verify query was answered
        query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def testCallbackHandlerExecution(self, handlersManager, mockContext):
        """Test callback handler execution, dood!"""
        query = createMockCallbackQuery(data='{"action": "button_click"}')
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Mock one handler to handle the callback
        handlersManager.handlers[0].buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)

        for handler in handlersManager.handlers[1:]:
            handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_button(update, mockContext)

        # Verify first handler was called
        handlersManager.handlers[0].buttonHandler.assert_called_once()

    @pytest.mark.asyncio
    async def testCallbackErrorHandling(self, handlersManager, mockContext):
        """Test error handling in callback queries, dood!"""
        query = createMockCallbackQuery(data="invalid json")
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        # Should not raise exception
        await handlersManager.handle_button(update, mockContext)

        # Verify query was answered
        query.answer.assert_called_once()


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling in HandlersManager, dood!"""

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testHandlerExceptionCatching(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test that handler exceptions are caught, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock first handler to raise exception
        async def raiseError(*args, **kwargs):
            raise Exception("Test error")

        handlersManager.handlers[0].messageHandler = createAsyncMock(sideEffect=raiseError)

        # Mock remaining handlers
        for handler in handlersManager.handlers[1:]:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        # Should raise exception (manager doesn't catch handler exceptions)
        with pytest.raises(Exception, match="Test error"):
            await handlersManager.handle_message(update, mockContext)

    @pytest.mark.asyncio
    async def testErrorRecovery(self, handlersManager, mockContext):
        """Test error recovery and continuation, dood!"""
        update = createMockUpdate(text="test")

        # Mock handler to return ERROR status
        handlersManager.handlers[0].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.ERROR)

        # Mock remaining handlers
        for handler in handlersManager.handlers[1:]:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify processing continued after error
        for handler in handlersManager.handlers[1:]:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    async def testFallbackOnHandlerFailure(self, handlersManager, mockContext):
        """Test fallback when handler fails, dood!"""
        update = createMockUpdate(text="test")

        # Mock handler to return FATAL
        handlersManager.handlers[0].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FATAL)

        # Mock remaining handlers
        for handler in handlersManager.handlers[1:]:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify processing stopped after FATAL
        for handler in handlersManager.handlers[1:]:
            handler.messageHandler.assert_not_called()

    @pytest.mark.asyncio
    async def testErrorLogging(self, handlersManager, mockContext):
        """Test that errors are properly logged, dood!"""
        context = mockContext
        context.error = Exception("Test error")
        update = createMockUpdate(text="test")

        # Error handler should log the error
        await handlersManager.error_handler(update, context)

        # Verify error was logged (error_handler doesn't raise)
        assert context.error is not None


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Test full integration scenarios, dood!"""

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testFullMessageFlow(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test complete message flow through manager, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="Hello bot!")

        # Mock handlers to simulate real flow
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        # Last handler returns FINAL
        handlersManager.handlers[-1].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)

        await handlersManager.handle_message(update, mockContext)

        # Verify all handlers were called
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testMultiHandlerProcessing(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test multiple handlers processing same message, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        processedBy = []

        # Mock handlers to track processing
        for i, handler in enumerate(handlersManager.handlers):

            def makeCallback(index):
                async def callback(*args, **kwargs):
                    processedBy.append(index)
                    return HandlerResultStatus.NEXT

                return callback

            handler.messageHandler = createAsyncMock(sideEffect=makeCallback(i))

        await handlersManager.handle_message(update, mockContext)

        # Verify multiple handlers processed the message
        assert len(processedBy) == len(handlersManager.handlers)

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testHandlerCoordination(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test coordination between handlers, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="/help")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers received the same update
        for handler in handlersManager.handlers:
            if handler.messageHandler.called:
                args = handler.messageHandler.call_args[0]
                assert args[0] == update

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testStateManagementAcrossHandlers(
        self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage
    ):
        """Test state management across multiple handlers, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify ensured message was passed to all handlers
        for handler in handlersManager.handlers:
            if handler.messageHandler.called:
                args = handler.messageHandler.call_args[0]
                assert args[2] == mockEnsuredMessage


# ============================================================================
# Handler Lifecycle Tests
# ============================================================================


class TestHandlerLifecycle:
    """Test handler lifecycle management, dood!"""

    @patch("internal.bot.handlers.manager.CacheService")
    @patch("internal.bot.handlers.manager.QueueService")
    def testHandlerInitialization(
        self,
        mockQueueService,
        mockCacheService,
        mockConfigManager,
        mockDatabase,
        mockLlmManager,
    ):
        """Test handler initialization during manager creation, dood!"""
        mockCache = Mock()
        mockCache.injectDatabase = Mock()
        mockCacheService.getInstance.return_value = mockCache

        mockQueue = Mock()
        mockQueueService.getInstance.return_value = mockQueue

        manager = HandlersManager(mockConfigManager, mockDatabase, mockLlmManager)

        # Verify all handlers are initialized
        for handler in manager.handlers:
            assert handler.configManager is not None
            assert handler.db is not None
            assert handler.llmManager is not None

    def testHandlerCleanup(self, handlersManager):
        """Test handler cleanup operations, dood!"""
        # Handlers should be accessible
        assert len(handlersManager.handlers) > 0

        # Verify handlers can be accessed
        for handler in handlersManager.handlers:
            assert isinstance(handler, BaseBotHandler)

    def testHandlerStatePersistence(self, handlersManager):
        """Test that handler state persists across calls, dood!"""
        # Handlers should maintain their configuration
        for handler in handlersManager.handlers:
            assert handler.configManager == handlersManager.configManager
            assert handler.db == handlersManager.db

    def testHandlerReconfiguration(self, handlersManager, mockBot):
        """Test handler reconfiguration with new bot, dood!"""
        # Inject bot
        handlersManager.injectBot(mockBot)

        # Verify all handlers received the bot
        for handler in handlersManager.handlers:
            assert handler._bot == mockBot

        # Inject new bot
        newBot = createMockBot(username="new_bot")
        handlersManager.injectBot(newBot)

        # Verify all handlers received the new bot
        for handler in handlersManager.handlers:
            assert handler._bot == newBot


# ============================================================================
# Spam Handler Integration Tests
# ============================================================================


class TestSpamHandlerIntegration:
    """Test spam handler integration, dood!"""

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testSpamDetectionWorkflow(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test spam detection workflow, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="spam spam spam")

        # Mock spam handler to detect spam
        from internal.bot.handlers.spam import SpamHandler

        for handler in handlersManager.handlers:
            if isinstance(handler, SpamHandler):
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)
            else:
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify spam handler blocked the message
        spamHandler = next(h for h in handlersManager.handlers if isinstance(h, SpamHandler))
        spamHandler.messageHandler.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testSpamUserBlocking(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test spam user blocking, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="spam")

        # Mock spam handler
        from internal.bot.handlers.spam import SpamHandler

        for handler in handlersManager.handlers:
            if isinstance(handler, SpamHandler):
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)
            else:
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify message was blocked
        spamHandler = next(h for h in handlersManager.handlers if isinstance(h, SpamHandler))
        spamHandler.messageHandler.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testSpamMessageHandling(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test spam message handling, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="legitimate message")

        # Mock spam handler to allow message
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify all handlers processed the message
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testFalsePositiveHandling(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test false positive handling in spam detection, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="normal message")

        # Mock handlers to allow message through
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify message was processed normally
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()


# ============================================================================
# LLM Handler Integration Tests
# ============================================================================


class TestLlmHandlerIntegration:
    """Test LLM handler integration, dood!"""

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testLlmMessageRouting(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test LLM message routing, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="Tell me a joke")

        # Mock all handlers except LLM to skip
        from internal.bot.handlers.llm_messages import LLMMessageHandler

        for handler in handlersManager.handlers:
            if isinstance(handler, LLMMessageHandler):
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)
            else:
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.SKIPPED)

        await handlersManager.handle_message(update, mockContext)

        # Verify LLM handler was called
        llmHandler = next(h for h in handlersManager.handlers if isinstance(h, LLMMessageHandler))
        llmHandler.messageHandler.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testConversationContextManagement(
        self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage
    ):
        """Test conversation context management, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="Continue our conversation")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify ensured message has user data
        mockEnsuredMessage.setUserData.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testToolCallingIntegration(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test tool calling integration, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="What's the weather?")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers were called
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testLlmResponseHandling(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test LLM response handling, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="Hello AI")

        # Mock LLM handler to return FINAL
        from internal.bot.handlers.llm_messages import LLMMessageHandler

        for handler in handlersManager.handlers:
            if isinstance(handler, LLMMessageHandler):
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)
            else:
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify LLM handler processed the message
        llmHandler = next(h for h in handlersManager.handlers if isinstance(h, LLMMessageHandler))
        llmHandler.messageHandler.assert_called_once()  # type: ignore[attr-defined]


# ============================================================================
# Media Handler Integration Tests
# ============================================================================


class TestMediaHandlerIntegration:
    """Test media handler integration, dood!"""

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testPhotoHandling(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test photo handling, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(hasPhoto=True, text="Check this photo")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers processed the photo message
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testDocumentHandling(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test document handling, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(hasDocument=True, text="Here's a document")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers processed the document message
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testMediaStorage(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test media storage, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(hasPhoto=True)

        # Mock media handler
        from internal.bot.handlers.media import MediaHandler

        for handler in handlersManager.handlers:
            if isinstance(handler, MediaHandler):
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)
            else:
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify media handler was called
        mediaHandler = next((h for h in handlersManager.handlers if isinstance(h, MediaHandler)), None)
        if mediaHandler:
            mediaHandler.messageHandler.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testMediaProcessing(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test media processing, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(hasPhoto=True, text="Process this")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify message was processed
        assert any(h.messageHandler.called for h in handlersManager.handlers)


# ============================================================================
# Performance Tests
# ============================================================================


class TestPerformance:
    """Test performance characteristics, dood!"""

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testConcurrentMessageHandling(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test concurrent message handling, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        # Process multiple messages
        updates = [createMockUpdate(text=f"Message {i}") for i in range(5)]

        import asyncio

        tasks = [handlersManager.handle_message(update, mockContext) for update in updates]
        await asyncio.gather(*tasks)

        # Verify all messages were processed
        for handler in handlersManager.handlers:
            assert handler.messageHandler.call_count == 5

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testHandlerExecutionTime(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test handler execution time, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock handlers with fast responses
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        import time

        startTime = time.time()
        await handlersManager.handle_message(update, mockContext)
        executionTime = time.time() - startTime

        # Execution should be fast (< 1 second for mocked handlers)
        assert executionTime < 1.0

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testMemoryUsage(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test memory usage during message processing, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        # Process multiple messages
        for i in range(10):
            update = createMockUpdate(text=f"Message {i}")
            await handlersManager.handle_message(update, mockContext)

        # Verify handlers are still accessible (no memory issues)
        assert len(handlersManager.handlers) > 0

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testHandlerScalability(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test handler scalability with many messages, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        # Process many messages
        messageCount = 20
        for i in range(messageCount):
            update = createMockUpdate(text=f"Message {i}")
            await handlersManager.handle_message(update, mockContext)

        # Verify all messages were processed
        for handler in handlersManager.handlers:
            assert handler.messageHandler.call_count == messageCount


# ============================================================================
# Edge Cases and Special Scenarios
# ============================================================================


class TestEdgeCases:
    """Test edge cases and special scenarios, dood!"""

    @pytest.mark.asyncio
    async def testEmptyUpdate(self, handlersManager, mockContext):
        """Test handling of empty update, dood!"""
        update = createMockUpdate()
        update.message = None

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        # Should not raise exception
        await handlersManager.handle_message(update, mockContext)

        # Handlers are still called with None ensuredMessage (manager processes all updates)
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()
            # Verify ensuredMessage is None
            args = handler.messageHandler.call_args[0]
            assert args[2] is None

    @pytest.mark.asyncio
    async def testCallbackQueryWithoutData(self, handlersManager, mockContext):
        """Test callback query without data, dood!"""
        query = createMockCallbackQuery()
        query.data = None
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Should not raise exception
        await handlersManager.handle_button(update, mockContext)

        # Query should still be answered
        query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def testCallbackQueryWithoutMessage(self, handlersManager, mockContext):
        """Test callback query without message, dood!"""
        query = createMockCallbackQuery()
        query.message = None
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Should not raise exception
        await handlersManager.handle_button(update, mockContext)

        # Query should still be answered
        query.answer.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testEnsuredMessageCreationFailure(self, mockFromMessage, handlersManager, mockContext):
        """Test handling when EnsuredMessage creation fails, dood!"""
        mockFromMessage.side_effect = Exception("Creation failed")
        update = createMockUpdate(text="test")

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        # Should not raise exception (error is caught and logged)
        await handlersManager.handle_message(update, mockContext)

        # Handlers are still called with None ensuredMessage (manager continues processing)
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()
            # Verify ensuredMessage is None
            args = handler.messageHandler.call_args[0]
            assert args[2] is None

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testAllHandlersReturnSkipped(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test when all handlers return SKIPPED, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock all handlers to return SKIPPED
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.SKIPPED)

        await handlersManager.handle_message(update, mockContext)

        # All handlers should have been called
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testAllHandlersReturnError(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test when all handlers return ERROR, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock all handlers to return ERROR
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.ERROR)

        await handlersManager.handle_message(update, mockContext)

        # All handlers should have been called
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()


# ============================================================================
# Handler Result Status Processing Tests
# ============================================================================


class TestHandlerResultStatusProcessing:
    """Test handler result status processing logic, dood!"""

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testSkippedStatusContinuesChain(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test that SKIPPED status allows chain to continue, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock handlers: first returns SKIPPED, second returns FINAL
        handlersManager.handlers[0].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.SKIPPED)
        handlersManager.handlers[1].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)

        for handler in handlersManager.handlers[2:]:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify first two handlers were called
        handlersManager.handlers[0].messageHandler.assert_called_once()
        handlersManager.handlers[1].messageHandler.assert_called_once()

        # Verify remaining handlers were not called (FINAL stopped chain)
        for handler in handlersManager.handlers[2:]:
            handler.messageHandler.assert_not_called()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testNextStatusContinuesChain(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test that NEXT status allows chain to continue, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock all handlers to return NEXT
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify all handlers were called
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testFinalStatusStopsChain(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test that FINAL status stops handler chain, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock first handler to return FINAL
        handlersManager.handlers[0].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)

        for handler in handlersManager.handlers[1:]:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify only first handler was called
        handlersManager.handlers[0].messageHandler.assert_called_once()

        for handler in handlersManager.handlers[1:]:
            handler.messageHandler.assert_not_called()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testErrorStatusContinuesChain(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test that ERROR status allows chain to continue, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock first handler to return ERROR, rest return NEXT
        handlersManager.handlers[0].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.ERROR)

        for handler in handlersManager.handlers[1:]:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify all handlers were called (ERROR doesn't stop chain)
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testFatalStatusStopsChain(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test that FATAL status stops handler chain, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock first handler to return FATAL
        handlersManager.handlers[0].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FATAL)

        for handler in handlersManager.handlers[1:]:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify only first handler was called
        handlersManager.handlers[0].messageHandler.assert_called_once()

        for handler in handlersManager.handlers[1:]:
            handler.messageHandler.assert_not_called()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testMixedStatusesInChain(self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage):
        """Test mixed handler statuses in chain, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock handlers with different statuses
        if len(handlersManager.handlers) >= 5:
            handlersManager.handlers[0].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.SKIPPED)
            handlersManager.handlers[1].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)
            handlersManager.handlers[2].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.ERROR)
            handlersManager.handlers[3].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)
            handlersManager.handlers[4].messageHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)

            for handler in handlersManager.handlers[5:]:
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

            await handlersManager.handle_message(update, mockContext)

            # Verify first 5 handlers were called
            for i in range(5):
                handlersManager.handlers[i].messageHandler.assert_called_once()

            # Verify remaining handlers were not called (FINAL stopped chain)
            for handler in handlersManager.handlers[5:]:
                handler.messageHandler.assert_not_called()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testPossibleFinalResultsValidation(
        self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage
    ):
        """Test validation that at least one handler returns FINAL or NEXT, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock all handlers to return only SKIPPED and ERROR (no FINAL or NEXT)
        for i, handler in enumerate(handlersManager.handlers):
            if i % 2 == 0:
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.SKIPPED)
            else:
                handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.ERROR)

        # This should trigger the validation error log
        await handlersManager.handle_message(update, mockContext)

        # All handlers should have been called
        for handler in handlersManager.handlers:
            handler.messageHandler.assert_called_once()

    @pytest.mark.asyncio
    async def testButtonHandlerStatusProcessing(self, handlersManager, mockContext):
        """Test button handler status processing, dood!"""
        query = createMockCallbackQuery(data='{"action": "test"}')
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Mock handlers with different statuses
        handlersManager.handlers[0].buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.SKIPPED)
        handlersManager.handlers[1].buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)
        handlersManager.handlers[2].buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.FINAL)

        for handler in handlersManager.handlers[3:]:
            handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_button(update, mockContext)

        # Verify first 3 handlers were called
        for i in range(3):
            handlersManager.handlers[i].buttonHandler.assert_called_once()

        # Verify remaining handlers were not called (FINAL stopped chain)
        for handler in handlersManager.handlers[3:]:
            handler.buttonHandler.assert_not_called()

    @pytest.mark.asyncio
    async def testButtonHandlerErrorStatus(self, handlersManager, mockContext):
        """Test ERROR status in button handler chain, dood!"""
        query = createMockCallbackQuery(data='{"action": "test"}')
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Mock first handler to return ERROR, rest return NEXT
        handlersManager.handlers[0].buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.ERROR)

        for handler in handlersManager.handlers[1:]:
            handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_button(update, mockContext)

        # Verify all handlers were called (ERROR doesn't stop chain)
        for handler in handlersManager.handlers:
            handler.buttonHandler.assert_called_once()

    @pytest.mark.asyncio
    async def testButtonHandlerFatalStatus(self, handlersManager, mockContext):
        """Test FATAL status in button handler chain, dood!"""
        query = createMockCallbackQuery(data='{"action": "test"}')
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Mock first handler to return FATAL
        handlersManager.handlers[0].buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.FATAL)

        for handler in handlersManager.handlers[1:]:
            handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_button(update, mockContext)

        # Verify only first handler was called
        handlersManager.handlers[0].buttonHandler.assert_called_once()

        for handler in handlersManager.handlers[1:]:
            handler.buttonHandler.assert_not_called()

    @pytest.mark.asyncio
    async def testButtonHandlerPossibleFinalResultsValidation(self, handlersManager, mockContext):
        """Test button handler validation for FINAL or NEXT status, dood!"""
        query = createMockCallbackQuery(data='{"action": "test"}')
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Mock all handlers to return only SKIPPED and ERROR
        for i, handler in enumerate(handlersManager.handlers):
            if i % 2 == 0:
                handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.SKIPPED)
            else:
                handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.ERROR)

        # This should trigger the validation error log
        await handlersManager.handle_button(update, mockContext)

        # All handlers should have been called
        for handler in handlersManager.handlers:
            handler.buttonHandler.assert_called_once()


# ============================================================================
# Button Data Processing Tests
# ============================================================================


class TestButtonDataProcessing:
    """Test button callback data processing, dood!"""

    @pytest.mark.asyncio
    async def testButtonDataUnpacking(self, handlersManager, mockContext):
        """Test that button data is unpacked correctly using packed format, dood!"""
        # Use packed format: key:value,key2:value2
        from typing import Dict, Union

        from lib.utils import packDict

        testData: Dict[Union[str, int], Union[str, int, float, bool, None]] = {
            "action": "test_action",
            "value": 123,
            "flag": True,
        }
        packedData = packDict(testData)

        query = createMockCallbackQuery(data=packedData)
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Mock handlers to capture the data parameter
        capturedData = []

        async def captureData(update, context, data):
            capturedData.append(data)
            return HandlerResultStatus.FINAL

        handlersManager.handlers[0].buttonHandler = createAsyncMock(sideEffect=captureData)

        await handlersManager.handle_button(update, mockContext)

        # Verify data was unpacked correctly
        assert len(capturedData) == 1
        assert capturedData[0] == testData

    @pytest.mark.asyncio
    async def testButtonDataWithStrings(self, handlersManager, mockContext):
        """Test button data with string values, dood!"""
        from typing import Dict, Union

        from lib.utils import packDict

        testData: Dict[Union[str, int], Union[str, int, float, bool, None]] = {
            "action": "click",
            "target": "button1",
            "user": "test_user",
        }
        packedData = packDict(testData)

        query = createMockCallbackQuery(data=packedData)
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        capturedData = []

        async def captureData(update, context, data):
            capturedData.append(data)
            return HandlerResultStatus.FINAL

        handlersManager.handlers[0].buttonHandler = createAsyncMock(sideEffect=captureData)

        await handlersManager.handle_button(update, mockContext)

        # Verify data was unpacked correctly with strings
        assert len(capturedData) == 1
        assert capturedData[0] == testData

    @pytest.mark.asyncio
    async def testButtonDataEmpty(self, handlersManager, mockContext):
        """Test button data with empty string, dood!"""
        query = createMockCallbackQuery(data="")
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        capturedData = []

        async def captureData(update, context, data):
            capturedData.append(data)
            return HandlerResultStatus.FINAL

        handlersManager.handlers[0].buttonHandler = createAsyncMock(sideEffect=captureData)

        await handlersManager.handle_button(update, mockContext)

        # Verify empty data was unpacked to empty dict
        assert len(capturedData) == 1
        assert capturedData[0] == {}

    @pytest.mark.asyncio
    async def testButtonDataWithNumbers(self, handlersManager, mockContext):
        """Test button data with various number types, dood!"""
        from typing import Dict, Union

        from lib.utils import packDict

        testData: Dict[Union[str, int], Union[str, int, float, bool, None]] = {
            "int_val": 42,
            "float_val": 3.14,
            "zero": 0,
        }
        packedData = packDict(testData)

        query = createMockCallbackQuery(data=packedData)
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        capturedData = []

        async def captureData(update, context, data):
            capturedData.append(data)
            return HandlerResultStatus.FINAL

        handlersManager.handlers[0].buttonHandler = createAsyncMock(sideEffect=captureData)

        await handlersManager.handle_button(update, mockContext)

        # Verify number data was unpacked correctly
        assert len(capturedData) == 1
        assert capturedData[0] == testData

    @pytest.mark.asyncio
    async def testButtonDataWithBooleans(self, handlersManager, mockContext):
        """Test button data with boolean values, dood!"""
        from typing import Dict, Union

        from lib.utils import packDict

        testData: Dict[Union[str, int], Union[str, int, float, bool, None]] = {
            "enabled": True,
            "visible": False,
            "active": True,
        }
        packedData = packDict(testData)

        query = createMockCallbackQuery(data=packedData)
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        capturedData = []

        async def captureData(update, context, data):
            capturedData.append(data)
            return HandlerResultStatus.FINAL

        handlersManager.handlers[0].buttonHandler = createAsyncMock(sideEffect=captureData)

        await handlersManager.handle_button(update, mockContext)

        # Verify boolean data was unpacked correctly
        assert len(capturedData) == 1
        assert capturedData[0] == testData

    @pytest.mark.asyncio
    async def testButtonDataWithNullValues(self, handlersManager, mockContext):
        """Test button data with None/null values, dood!"""
        from typing import Dict, Union

        from lib.utils import packDict

        testData: Dict[Union[str, int], Union[str, int, float, bool, None]] = {
            "key1": "value1",
            "key2": None,
            "key3": "value3",
        }
        packedData = packDict(testData)

        query = createMockCallbackQuery(data=packedData)
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        capturedData = []

        async def captureData(update, context, data):
            capturedData.append(data)
            return HandlerResultStatus.FINAL

        handlersManager.handlers[0].buttonHandler = createAsyncMock(sideEffect=captureData)

        await handlersManager.handle_button(update, mockContext)

        # Verify null values were unpacked correctly
        assert len(capturedData) == 1
        assert capturedData[0] == testData


# ============================================================================
# Additional Edge Cases
# ============================================================================


class TestAdditionalEdgeCases:
    """Test additional edge cases for complete coverage, dood!"""

    @pytest.mark.asyncio
    async def testButtonHandlerWithNonMessageCallbackQuery(self, handlersManager, mockContext):
        """Test button handler when callback query message is not a Message type, dood!"""
        query = createMockCallbackQuery(data='{"action": "test"}')
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Make query.message something other than Message
        from telegram import InaccessibleMessage

        query.message = Mock(spec=InaccessibleMessage)

        # Mock handlers
        for handler in handlersManager.handlers:
            handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        # Should handle gracefully and not call handlers
        await handlersManager.handle_button(update, mockContext)

        # Verify handlers were not called (invalid message type)
        for handler in handlersManager.handlers:
            handler.buttonHandler.assert_not_called()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testMessageHandlerWithVeryLongChain(
        self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage
    ):
        """Test message handling with all handlers returning NEXT, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        callCount = 0

        async def countCalls(*args, **kwargs):
            nonlocal callCount
            callCount += 1
            return HandlerResultStatus.NEXT

        # Mock all handlers to return NEXT and count calls
        for handler in handlersManager.handlers:
            handler.messageHandler = createAsyncMock(sideEffect=countCalls)

        await handlersManager.handle_message(update, mockContext)

        # Verify all handlers were called exactly once
        assert callCount == len(handlersManager.handlers)

    @pytest.mark.asyncio
    async def testButtonHandlerWithAllSkipped(self, handlersManager, mockContext):
        """Test button handler when all handlers return SKIPPED, dood!"""
        query = createMockCallbackQuery(data='{"action": "test"}')
        update = createMockUpdate()
        update.callback_query = query
        update.message = None

        # Mock all handlers to return SKIPPED
        for handler in handlersManager.handlers:
            handler.buttonHandler = createAsyncMock(returnValue=HandlerResultStatus.SKIPPED)

        await handlersManager.handle_button(update, mockContext)

        # All handlers should have been called
        for handler in handlersManager.handlers:
            handler.buttonHandler.assert_called_once()

    @pytest.mark.asyncio
    @patch("internal.bot.models.ensured_message.EnsuredMessage.fromMessage")
    async def testMessageHandlerResultSetTracking(
        self, mockFromMessage, handlersManager, mockContext, mockEnsuredMessage
    ):
        """Test that result set is properly tracked across handlers, dood!"""
        mockFromMessage.return_value = mockEnsuredMessage
        update = createMockUpdate(text="test")

        # Mock handlers with various statuses
        statuses = [
            HandlerResultStatus.SKIPPED,
            HandlerResultStatus.NEXT,
            HandlerResultStatus.ERROR,
            HandlerResultStatus.NEXT,
            HandlerResultStatus.FINAL,
        ]

        for i, handler in enumerate(handlersManager.handlers[: len(statuses)]):
            handler.messageHandler = createAsyncMock(returnValue=statuses[i])

        for handler in handlersManager.handlers[len(statuses) :]:
            handler.messageHandler = createAsyncMock(returnValue=HandlerResultStatus.NEXT)

        await handlersManager.handle_message(update, mockContext)

        # Verify handlers up to FINAL were called
        for i in range(len(statuses)):
            handlersManager.handlers[i].messageHandler.assert_called_once()
