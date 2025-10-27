"""
Pytest configuration and common fixtures for gromozeka bot tests.

This module provides shared fixtures for testing bot handlers, services,
and database operations. All fixtures follow camelCase naming convention.
"""

import asyncio
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, Mock

import pytest

# Import test utilities
from tests.utils import (
    createAsyncMock,
    createMockChat,
    createMockMessage,
    createMockUpdate,
    createMockUser,
)

# ============================================================================
# Pytest Configuration
# ============================================================================


@pytest.fixture(scope="session")
def eventLoop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """
    Create an event loop for the test session.

    This fixture ensures all async tests share the same event loop,
    preventing issues with multiple event loops.

    Yields:
        asyncio.AbstractEventLoop: The event loop for async tests
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
def inMemoryDbPath() -> str:
    """
    Provide path for in-memory SQLite database.

    Returns:
        str: SQLite in-memory database path
    """
    return ":memory:"


@pytest.fixture
def mockDatabaseWrapper():
    """
    Create a mock DatabaseWrapper for testing.

    This fixture provides a fully mocked database wrapper with common
    methods pre-configured. Use this when you don't need actual database
    operations.

    Returns:
        Mock: Mocked DatabaseWrapper instance

    Example:
        def testHandler(mockDatabaseWrapper):
            mockDatabaseWrapper.getChatSettings.return_value = {"model": "gpt-4"}
            # Test code here
    """
    from internal.database.wrapper import DatabaseWrapper

    mock = Mock(spec=DatabaseWrapper)

    # Configure common return values
    mock.getChatSettings.return_value = {}
    mock.getUserData.return_value = {}
    mock.getChatMessages.return_value = []
    mock.getDelayedTasks.return_value = []

    # Configure async methods
    mock.saveChatMessage = AsyncMock(return_value=None)
    mock.updateChatUser = AsyncMock(return_value=None)

    return mock


@pytest.fixture
async def testDatabase(inMemoryDbPath) -> AsyncGenerator:
    """
    Create a real in-memory database for integration tests.

    This fixture creates an actual DatabaseWrapper instance with an
    in-memory SQLite database. Use this for integration tests that
    need real database operations.

    Yields:
        DatabaseWrapper: Real database instance with in-memory storage

    Example:
        async def testDatabaseOperations(testDatabase):
            await testDatabase.saveChatMessage(...)
            messages = testDatabase.getChatMessages(...)
            assert len(messages) == 1
    """
    from internal.database.wrapper import DatabaseWrapper

    db = DatabaseWrapper(inMemoryDbPath)
    yield db
    db.close()


# ============================================================================
# Telegram Mock Fixtures
# ============================================================================


@pytest.fixture
def mockBot():
    """
    Create a mock Telegram Bot instance.

    Returns:
        AsyncMock: Mocked ExtBot instance with common methods

    Example:
        async def testBotMessage(mockBot):
            await mockBot.sendMessage(chat_id=123, text="test")
            mockBot.sendMessage.assert_called_once()
    """
    from telegram.ext import ExtBot

    bot = AsyncMock(spec=ExtBot)
    bot.username = "test_bot"
    bot.id = 123456789
    bot.first_name = "Test Bot"

    # Configure common async methods
    bot.sendMessage = AsyncMock(return_value=createMockMessage())
    bot.sendPhoto = AsyncMock(return_value=createMockMessage())
    bot.deleteMessage = AsyncMock(return_value=True)
    bot.getChatAdministrators = AsyncMock(return_value=[])
    bot.banChatMember = AsyncMock(return_value=True)
    bot.unbanChatMember = AsyncMock(return_value=True)

    return bot


@pytest.fixture
def mockUpdate():
    """
    Create a mock Telegram Update with a text message.

    Returns:
        Mock: Mocked Update instance

    Example:
        def testMessageHandler(mockUpdate):
            assert mockUpdate.message.text == "test message"
    """
    return createMockUpdate(text="test message")


@pytest.fixture
def mockMessage():
    """
    Create a mock Telegram Message.

    Returns:
        Mock: Mocked Message instance

    Example:
        def testMessageProcessing(mockMessage):
            assert mockMessage.text == "test message"
            assert mockMessage.chat.id == 123
    """
    return createMockMessage()


@pytest.fixture
def mockUser():
    """
    Create a mock Telegram User.

    Returns:
        Mock: Mocked User instance

    Example:
        def testUserData(mockUser):
            assert mockUser.id == 456
            assert mockUser.username == "testuser"
    """
    return createMockUser()


@pytest.fixture
def mockChat():
    """
    Create a mock Telegram Chat.

    Returns:
        Mock: Mocked Chat instance

    Example:
        def testChatSettings(mockChat):
            assert mockChat.id == 123
            assert mockChat.type == "private"
    """
    return createMockChat()


@pytest.fixture
def mockCallbackQuery():
    """
    Create a mock Telegram CallbackQuery.

    Returns:
        Mock: Mocked CallbackQuery instance

    Example:
        async def testButtonCallback(mockCallbackQuery):
            assert mockCallbackQuery.data == "test_callback"
    """
    from telegram import CallbackQuery

    query = Mock(spec=CallbackQuery)
    query.id = "callback_123"
    query.data = "test_callback"
    query.message = createMockMessage()
    query.from_user = createMockUser()
    query.answer = AsyncMock(return_value=True)

    return query


# ============================================================================
# Service Mock Fixtures
# ============================================================================


@pytest.fixture
def mockConfigManager():
    """
    Create a mock ConfigManager.

    Returns:
        Mock: Mocked ConfigManager instance

    Example:
        def testConfig(mockConfigManager):
            mockConfigManager.getBotConfig.return_value = {"token": "test"}
    """
    from internal.config.manager import ConfigManager

    mock = Mock(spec=ConfigManager)
    mock.getBotConfig.return_value = {
        "token": "test_token",
        "owners": [123456],
    }
    mock.getProviderConfig.return_value = {}
    mock.getModelConfig.return_value = {}

    return mock


@pytest.fixture
def mockQueueService():
    """
    Create a mock QueueService.

    Returns:
        Mock: Mocked QueueService instance

    Example:
        async def testQueue(mockQueueService):
            await mockQueueService.addBackgroundTask(task)
            mockQueueService.addBackgroundTask.assert_called_once()
    """
    from internal.services.queue.service import QueueService

    mock = Mock(spec=QueueService)
    mock.addBackgroundTask = AsyncMock(return_value=None)
    mock.addDelayedTask = AsyncMock(return_value=None)
    mock.registerHandler = Mock(return_value=None)
    mock.start = AsyncMock(return_value=None)
    mock.stop = AsyncMock(return_value=None)

    return mock


@pytest.fixture
def mockLlmService():
    """
    Create a mock LLMService.

    Returns:
        Mock: Mocked LLMService instance

    Example:
        async def testLlm(mockLlmService):
            mockLlmService.generateText.return_value = "AI response"
            response = await mockLlmService.generateText(...)
            assert response == "AI response"
    """
    from internal.services.llm.service import LLMService

    mock = Mock(spec=LLMService)
    mock.generateText = AsyncMock(return_value="Test AI response")
    mock.registerTool = Mock(return_value=None)
    mock.getTool = Mock(return_value=None)

    return mock


@pytest.fixture
def mockCacheService():
    """
    Create a mock CacheService.

    Returns:
        Mock: Mocked CacheService instance

    Example:
        def testCache(mockCacheService):
            mockCacheService.get.return_value = "cached_value"
            value = mockCacheService.get("key")
            assert value == "cached_value"
    """
    from internal.services.cache.service import CacheService

    mock = Mock(spec=CacheService)
    mock.get = Mock(return_value=None)
    mock.set = Mock(return_value=None)
    mock.unset = Mock(return_value=None)
    mock.clear = Mock(return_value=None)

    return mock


@pytest.fixture
def mockLlmManager():
    """
    Create a mock LLMManager.

    Returns:
        Mock: Mocked LLMManager instance

    Example:
        def testLlmManager(mockLlmManager):
            mockLlmManager.getModel.return_value = mockModel
    """
    from lib.ai.manager import LLMManager

    mock = Mock(spec=LLMManager)
    mock.getModel = Mock(return_value=None)
    mock.listModels = Mock(return_value=[])

    return mock


# ============================================================================
# Handler Fixtures
# ============================================================================


@pytest.fixture
def mockBaseHandler(mockBot, mockDatabaseWrapper, mockConfigManager, mockLlmManager):
    """
    Create a mock BaseHandler with dependencies.

    Args:
        mockBot: Mocked bot instance
        mockDatabaseWrapper: Mocked database
        mockConfigManager: Mocked config manager
        mockLlmManager: Mocked LLM manager

    Returns:
        Mock: Mocked BaseHandler instance

    Example:
        async def testHandler(mockBaseHandler):
            await mockBaseHandler.sendMessage(chat_id=123, text="test")
    """
    from internal.bot.handlers.base import BaseBotHandler

    handler = BaseBotHandler(
        configManager=mockConfigManager,
        database=mockDatabaseWrapper,
        llmManager=mockLlmManager,
    )
    handler.injectBot(mockBot)

    return handler


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sampleChatSettings() -> dict:
    """
    Provide sample chat settings for testing.

    Returns:
        dict: Sample chat settings
    """
    return {
        "model": "gpt-4",
        "temperature": 0.7,
        "max_tokens": 1000,
        "system_prompt": "You are a helpful assistant",
    }


@pytest.fixture
def sampleUserData() -> dict:
    """
    Provide sample user data for testing.

    Returns:
        dict: Sample user data
    """
    return {
        "preferences": {"language": "en"},
        "history": [],
    }


@pytest.fixture
def sampleMessages() -> list:
    """
    Provide sample message list for testing.

    Returns:
        list: List of sample messages
    """
    return [
        {
            "message_id": 1,
            "chat_id": 123,
            "user_id": 456,
            "text": "Hello",
            "timestamp": 1234567890,
        },
        {
            "message_id": 2,
            "chat_id": 123,
            "user_id": 789,
            "text": "Hi there",
            "timestamp": 1234567891,
        },
    ]


# ============================================================================
# Async Test Utilities
# ============================================================================


@pytest.fixture
def asyncMockFactory():
    """
    Factory fixture for creating async mocks.

    Returns:
        callable: Function to create async mocks

    Example:
        def testAsync(asyncMockFactory):
            mockFunc = asyncMockFactory(return_value="result")
            result = await mockFunc()
            assert result == "result"
    """
    return createAsyncMock
