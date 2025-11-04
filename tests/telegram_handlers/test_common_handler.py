"""
Comprehensive tests for CommonHandler, dood!

This module provides extensive test coverage for the CommonHandler class,
testing delayed task handlers, LLM tool handlers, and all common commands.

Test Categories:
- Initialization Tests: Handler setup and service registration
- Unit Tests: Delayed task handlers, LLM tool handlers
- Integration Tests: Complete command workflows (/start, /remind, /list_chats)
- Edge Cases: Error handling, boundary conditions, permission checks
"""

import time
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import Chat

from internal.bot.handlers.common import CommonHandler
from internal.bot.models import DelayedTask, DelayedTaskFunction, EnsuredMessage
from internal.database.models import MessageCategory
from tests.fixtures.service_mocks import createMockDatabaseWrapper, createMockLlmManager
from tests.fixtures.telegram_mocks import (
    createMockBot,
    createMockContext,
    createMockMessage,
    createMockUpdate,
)

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mockConfigManager():
    """Create a mock ConfigManager with common handler settings, dood!"""
    mock = Mock()
    mock.getBotConfig.return_value = {
        "token": "test_token",
        "bot_owners": ["owner1"],
        "defaults": {},
    }
    return mock


@pytest.fixture
def mockDatabase():
    """Create a mock DatabaseWrapper for common handler operations, dood!"""
    mock = createMockDatabaseWrapper()
    mock.getChatSettings.return_value = {}
    mock.getUserChats = Mock(return_value=[])
    mock.getAllGroupChats = Mock(return_value=[])
    mock.saveChatMessage = Mock()
    mock.updateChatUser = Mock()
    mock.getChatMessageByMessageId = Mock(return_value=None)
    return mock


@pytest.fixture
def mockLlmManager():
    """Create a mock LLMManager, dood!"""
    return createMockLlmManager()


@pytest.fixture
def mockCacheService():
    """Create a mock CacheService, dood!"""
    with patch("internal.bot.handlers.base.CacheService") as MockCache:
        mockInstance = Mock()
        mockInstance.getChatSettings.return_value = {}
        mockInstance.getChatInfo.return_value = None
        mockInstance.getChatTopicInfo.return_value = None
        mockInstance.getChatUserData.return_value = {}
        mockInstance.setChatSetting = Mock()
        mockInstance.chats = {}
        MockCache.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def mockQueueService():
    """Create a mock QueueService, dood!"""
    with patch("internal.bot.handlers.base.QueueService") as MockQueue:
        mockInstance = Mock()
        mockInstance.addBackgroundTask = AsyncMock()
        mockInstance.addDelayedTask = AsyncMock()
        mockInstance.registerDelayedTaskHandler = Mock()
        mockInstance._delayedTaskHandlers = {}
        MockQueue.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def mockLlmService():
    """Create a mock LLMService, dood!"""
    with patch("internal.bot.handlers.common.LLMService") as MockLLM:
        mockInstance = Mock()
        mockInstance.registerTool = Mock()
        mockInstance._tools = {}
        MockLLM.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def commonHandler(mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockLlmService):
    """Create a CommonHandler instance with mocked dependencies, dood!"""
    handler = CommonHandler(mockConfigManager, mockDatabase, mockLlmManager)
    return handler


@pytest.fixture
def mockBot():
    """Create a mock bot instance, dood!"""
    bot = createMockBot()
    bot.delete_message = AsyncMock(return_value=True)
    bot.send_message = AsyncMock(return_value=createMockMessage())
    return bot


# ============================================================================
# Initialization Tests
# ============================================================================


class TestInitialization:
    """Test CommonHandler initialization, dood!"""

    def testInitWithAllDependencies(
        self, mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockLlmService
    ):
        """Test handler initializes correctly with all dependencies, dood!"""
        handler = CommonHandler(mockConfigManager, mockDatabase, mockLlmManager)

        assert handler.configManager == mockConfigManager
        assert handler.db == mockDatabase
        assert handler.llmManager == mockLlmManager
        assert handler.llmService is not None

    def testInitRegistersLlmTools(
        self, mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockLlmService
    ):
        """Test LLM tools are registered during initialization, dood!"""
        CommonHandler(mockConfigManager, mockDatabase, mockLlmManager)

        # Verify tools were registered (at least 1 calls)
        assert mockLlmService.registerTool.call_count >= 1

    def testInitRegistersDelayedTaskHandlers(
        self, mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockLlmService
    ):
        """Test delayed task handlers are registered during initialization, dood!"""
        CommonHandler(mockConfigManager, mockDatabase, mockLlmManager)

        # Verify delayed task handlers were registered
        assert mockQueueService.registerDelayedTaskHandler.call_count >= 2
        calls = [call[0][0] for call in mockQueueService.registerDelayedTaskHandler.call_args_list]
        assert DelayedTaskFunction.SEND_MESSAGE in calls
        assert DelayedTaskFunction.DELETE_MESSAGE in calls


# ============================================================================
# Unit Tests - Delayed Task Handlers
# ============================================================================


class TestDelayedTaskHandlers:
    """Test delayed task handlers, dood!"""

    @pytest.mark.asyncio
    async def testDqSendMessageHandler(self, commonHandler, mockBot, mockDatabase):
        """Test delayed message sending handler, dood!"""
        commonHandler.injectBot(mockBot)
        commonHandler.sendMessage = AsyncMock(return_value=createMockMessage())

        delayedTask = DelayedTask(
            taskId="test-1",
            delayedUntil=time.time(),
            function=DelayedTaskFunction.SEND_MESSAGE,
            kwargs={
                "messageId": 100,
                "chatId": 123,
                "chatType": "group",
                "userId": 456,
                "messageText": "Delayed message text",
                "threadId": None,
                "messageCategory": MessageCategory.BOT,
            },
        )

        await commonHandler._dqSendMessageHandler(delayedTask)

        commonHandler.sendMessage.assert_called_once()
        call_args = commonHandler.sendMessage.call_args
        assert call_args[1]["messageText"] == "Delayed message text"
        assert call_args[1]["messageCategory"] == MessageCategory.BOT

    @pytest.mark.asyncio
    async def testDqSendMessageHandlerWithThread(self, commonHandler, mockBot):
        """Test delayed message sending with thread ID, dood!"""
        commonHandler.injectBot(mockBot)
        commonHandler.sendMessage = AsyncMock(return_value=createMockMessage())

        delayedTask = DelayedTask(
            taskId="test-2",
            delayedUntil=time.time(),
            function=DelayedTaskFunction.SEND_MESSAGE,
            kwargs={
                "messageId": 100,
                "chatId": 123,
                "chatType": "supergroup",
                "userId": 456,
                "messageText": "Thread message",
                "threadId": 789,
                "messageCategory": MessageCategory.BOT_COMMAND_REPLY,
            },
        )

        await commonHandler._dqSendMessageHandler(delayedTask)

        commonHandler.sendMessage.assert_called_once()

    @pytest.mark.asyncio
    async def testDqDeleteMessageHandler(self, commonHandler, mockBot):
        """Test delayed message deletion handler, dood!"""
        commonHandler.injectBot(mockBot)

        delayedTask = DelayedTask(
            taskId="test-3",
            delayedUntil=time.time(),
            function=DelayedTaskFunction.DELETE_MESSAGE,
            kwargs={
                "chatId": 123,
                "messageId": 456,
            },
        )

        await commonHandler._dqDeleteMessageHandler(delayedTask)

        mockBot.delete_message.assert_called_once_with(chat_id=123, message_id=456)

    @pytest.mark.asyncio
    async def testDqDeleteMessageHandlerWithoutBot(self, commonHandler):
        """Test delete handler handles missing bot gracefully, dood!"""
        # Don't inject bot
        delayedTask = DelayedTask(
            taskId="test-4",
            delayedUntil=time.time(),
            function=DelayedTaskFunction.DELETE_MESSAGE,
            kwargs={
                "chatId": 123,
                "messageId": 456,
            },
        )

        # Should not raise exception
        await commonHandler._dqDeleteMessageHandler(delayedTask)


# ============================================================================
# Unit Tests - LLM Tool Handlers
# ============================================================================


class TestLlmToolHandlers:
    """Test LLM tool handlers, dood!"""

    @pytest.mark.asyncio
    async def testLlmToolGetCurrentDateTime(self, commonHandler):
        """Test current datetime retrieval tool, dood!"""
        result = await commonHandler._llmToolGetCurrentDateTime(None)

        # Result should be JSON with datetime, timestamp, and timezone
        assert "datetime" in result
        assert "timestamp" in result
        assert "timezone" in result
        assert "UTC" in result

    @pytest.mark.asyncio
    async def testLlmToolGetCurrentDateTimeFormat(self, commonHandler):
        """Test datetime tool returns proper ISO format, dood!"""
        import json

        result = await commonHandler._llmToolGetCurrentDateTime(None)
        data = json.loads(result)

        assert "datetime" in data
        assert "T" in data["datetime"]  # ISO 8601 format
        assert isinstance(data["timestamp"], (int, float))
        assert data["timezone"] == "UTC"


# ============================================================================
# Unit Tests - Message Helpers
# ============================================================================


class TestMessageHelpers:
    """Test message helper methods, dood!"""

    @pytest.mark.asyncio
    async def testSendDelayedMessage(self, commonHandler, mockQueueService):
        """Test scheduling delayed message, dood!"""
        message = createMockMessage(text="Original message")
        ensuredMessage = EnsuredMessage.fromMessage(message)
        delayedUntil = time.time() + 3600  # 1 hour from now
        messageText = "Delayed message"

        await commonHandler._sendDelayedMessage(
            ensuredMessage,
            delayedUntil=delayedUntil,
            messageText=messageText,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

        mockQueueService.addDelayedTask.assert_called_once()
        call_args = mockQueueService.addDelayedTask.call_args
        assert call_args[1]["delayedUntil"] == delayedUntil
        assert call_args[1]["function"] == DelayedTaskFunction.SEND_MESSAGE
        assert call_args[1]["kwargs"]["messageText"] == messageText
        assert call_args[1]["kwargs"]["messageCategory"] == MessageCategory.BOT_COMMAND_REPLY

    @pytest.mark.asyncio
    async def testSendDelayedMessageWithThread(self, commonHandler, mockQueueService):
        """Test scheduling delayed message with thread ID, dood!"""
        message = createMockMessage(text="Original message")
        message.message_thread_id = 789
        message.is_topic_message = True
        ensuredMessage = EnsuredMessage.fromMessage(message)
        delayedUntil = time.time() + 1800

        await commonHandler._sendDelayedMessage(
            ensuredMessage,
            delayedUntil=delayedUntil,
            messageText="Thread message",
        )

        mockQueueService.addDelayedTask.assert_called_once()
        call_args = mockQueueService.addDelayedTask.call_args
        # Verify the task was scheduled with correct parameters
        assert call_args[1]["delayedUntil"] == delayedUntil
        assert call_args[1]["function"] == DelayedTaskFunction.SEND_MESSAGE
        # threadId should be in the kwargs
        assert "threadId" in call_args[1]["kwargs"]


# ============================================================================
# Integration Tests - /start Command
# ============================================================================


class TestStartCommand:
    """Test /start command functionality, dood!"""

    @pytest.mark.asyncio
    async def testStartCommandWithoutUser(self, commonHandler, mockBot):
        """Test /start command handles missing user gracefully, dood!"""
        commonHandler.injectBot(mockBot)

        message = createMockMessage(text="/start")
        message.from_user = None

        update = createMockUpdate(message=message)
        update.effective_user = None
        context = createMockContext()

        # Should not raise exception
        await commonHandler.start_command(update, context)

    @pytest.mark.asyncio
    async def testStartCommandWithoutMessage(self, commonHandler, mockBot):
        """Test /start command handles missing message gracefully, dood!"""
        commonHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await commonHandler.start_command(update, context)


# ============================================================================
# Integration Tests - /remind Command
# ============================================================================


class TestRemindCommand:
    """Test /remind command functionality, dood!"""

    @pytest.mark.asyncio
    async def testRemindCommandWithoutMessage(self, commonHandler, mockBot):
        """Test /remind command handles missing message gracefully, dood!"""
        commonHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await commonHandler.remind_command(update, context)


# ============================================================================
# Integration Tests - /list_chats Command
# ============================================================================


class TestListChatsCommand:
    """Test /list_chats command functionality, dood!"""

    @pytest.mark.asyncio
    async def testListChatsCommandInPrivateChat(self, commonHandler, mockBot, mockDatabase):
        """Test /list_chats command lists user's chats, dood!"""
        commonHandler.injectBot(mockBot)
        commonHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        commonHandler.isAdmin = AsyncMock(return_value=False)

        mockDatabase.getUserChats.return_value = [
            {"chat_id": -100123, "title": "Test Group", "type": "supergroup", "username": None},
            {"chat_id": -100456, "title": None, "type": "group", "username": "testgroup"},
        ]

        message = createMockMessage(chatId=456, userId=456, text="/list_chats")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = []

        await commonHandler.list_chats_command(update, context)

        commonHandler.sendMessage.assert_called_once()
        call_args = commonHandler.sendMessage.call_args
        response = call_args[0][1]
        assert "Test Group" in response
        assert "testgroup" in response

    @pytest.mark.asyncio
    async def testListChatsCommandWithAllParameter(self, commonHandler, mockBot, mockDatabase):
        """Test /list_chats command with 'all' parameter for admins, dood!"""
        commonHandler.injectBot(mockBot)
        commonHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        commonHandler.isAdmin = AsyncMock(return_value=True)

        mockDatabase.getAllGroupChats.return_value = [
            {"chat_id": -100123, "title": "Group 1", "type": "supergroup", "username": None},
            {"chat_id": -100456, "title": "Group 2", "type": "group", "username": None},
        ]

        message = createMockMessage(chatId=456, userId=456, text="/list_chats all")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["all"]

        await commonHandler.list_chats_command(update, context)

        mockDatabase.getAllGroupChats.assert_called_once()
        commonHandler.sendMessage.assert_called_once()

    @pytest.mark.asyncio
    async def testListChatsCommandAllParameterNonAdmin(self, commonHandler, mockBot, mockDatabase):
        """Test /list_chats 'all' parameter ignored for non-admins, dood!"""
        commonHandler.injectBot(mockBot)
        commonHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        commonHandler.isAdmin = AsyncMock(return_value=False)

        mockDatabase.getUserChats.return_value = []

        message = createMockMessage(chatId=456, userId=456, text="/list_chats all")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["all"]

        await commonHandler.list_chats_command(update, context)

        # Should call getUserChats, not getAllGroupChats
        mockDatabase.getUserChats.assert_called_once()
        mockDatabase.getAllGroupChats.assert_not_called()

    @pytest.mark.asyncio
    async def testListChatsCommandWithoutMessage(self, commonHandler, mockBot):
        """Test /list_chats command handles missing message gracefully, dood!"""
        commonHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await commonHandler.list_chats_command(update, context)

    @pytest.mark.asyncio
    async def testListChatsCommandEmptyList(self, commonHandler, mockBot, mockDatabase):
        """Test /list_chats command with no chats, dood!"""
        commonHandler.injectBot(mockBot)
        commonHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        commonHandler.isAdmin = AsyncMock(return_value=False)

        mockDatabase.getUserChats.return_value = []

        message = createMockMessage(chatId=456, userId=456, text="/list_chats")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = []

        await commonHandler.list_chats_command(update, context)

        commonHandler.sendMessage.assert_called_once()
        call_args = commonHandler.sendMessage.call_args
        response = call_args[0][1]
        assert "Список доступных чатов" in response


# ============================================================================
# Integration Tests - Delayed Message Workflow
# ============================================================================


class TestDelayedMessageWorkflow:
    """Test complete delayed message workflow, dood!"""

    @pytest.mark.asyncio
    async def testDelayedMessageWithDeletion(self, commonHandler, mockBot, mockQueueService):
        """Test scheduling message deletion, dood!"""
        commonHandler.injectBot(mockBot)

        # Schedule a message deletion
        delayedUntil = time.time() + 60
        await mockQueueService.addDelayedTask(
            delayedUntil=delayedUntil,
            function=DelayedTaskFunction.DELETE_MESSAGE,
            kwargs={"chatId": 123, "messageId": 456},
        )

        mockQueueService.addDelayedTask.assert_called_once()

        # Simulate execution
        delayedTask = DelayedTask(
            taskId="test-6",
            delayedUntil=time.time(),
            function=DelayedTaskFunction.DELETE_MESSAGE,
            kwargs={"chatId": 123, "messageId": 456},
        )

        await commonHandler._dqDeleteMessageHandler(delayedTask)

        mockBot.delete_message.assert_called_once_with(chat_id=123, message_id=456)


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling, dood!"""

    @pytest.mark.asyncio
    async def testRemindCommandWithEnsuredMessageError(self, commonHandler, mockBot):
        """Test /remind command handles EnsuredMessage creation error, dood!"""
        commonHandler.injectBot(mockBot)

        message = createMockMessage(text="/remind 5m Test")
        message.chat = None  # This will cause EnsuredMessage.fromMessage to fail

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["5m", "Test"]

        # Should not raise exception
        await commonHandler.remind_command(update, context)

    @pytest.mark.asyncio
    async def testListChatsCommandWithEnsuredMessageError(self, commonHandler, mockBot):
        """Test /list_chats command handles EnsuredMessage creation error, dood!"""
        commonHandler.injectBot(mockBot)

        message = createMockMessage(text="/list_chats")
        message.chat = None  # This will cause EnsuredMessage.fromMessage to fail

        update = createMockUpdate(message=message)
        context = createMockContext()

        # Should not raise exception
        await commonHandler.list_chats_command(update, context)

    @pytest.mark.asyncio
    async def testDelayedTaskWithMissingKwargs(self, commonHandler, mockBot):
        """Test delayed task handlers handle missing kwargs gracefully, dood!"""
        commonHandler.injectBot(mockBot)
        commonHandler.sendMessage = AsyncMock(return_value=createMockMessage())

        # Task with minimal kwargs
        delayedTask = DelayedTask(
            taskId="test-7",
            delayedUntil=time.time(),
            function=DelayedTaskFunction.SEND_MESSAGE,
            kwargs={
                "messageId": 100,
                "chatId": 123,
                "chatType": "private",
                "userId": 456,
                "messageText": "Test",
                "threadId": None,
                "messageCategory": MessageCategory.BOT,
            },
        )

        # Should not raise exception
        await commonHandler._dqSendMessageHandler(delayedTask)

    @pytest.mark.asyncio
    async def testListChatsCommandWithChatIcons(self, commonHandler, mockBot, mockDatabase):
        """Test /list_chats command formats chat icons correctly, dood!"""
        commonHandler.injectBot(mockBot)
        commonHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        commonHandler.isAdmin = AsyncMock(return_value=False)

        mockDatabase.getUserChats.return_value = [
            {"chat_id": -100123, "title": "Public Group", "type": "supergroup", "username": None},
            {"chat_id": 456, "title": None, "type": "private", "username": "privateuser"},
        ]

        message = createMockMessage(chatId=456, userId=456, text="/list_chats")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = []

        await commonHandler.list_chats_command(update, context)

        commonHandler.sendMessage.assert_called_once()
        call_args = commonHandler.sendMessage.call_args
        response = call_args[0][1]
        # Should contain chat info
        assert "-100123" in response or "Public Group" in response
