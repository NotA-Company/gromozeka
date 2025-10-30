"""
Integration tests for bot workflows, dood!

This module tests complete workflows from message receipt to response,
including handler chain execution, database persistence, and error handling.

Test Coverage:
- Handler chain execution
- Interactive workflow (buttons/callbacks)
- Error handling workflow
- Database persistence
- Concurrent operations
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from telegram import Chat

from internal.bot.handlers.base import HandlerResultStatus
from internal.bot.handlers.manager import HandlersManager
from internal.bot.models import ChatSettingsKey, ChatSettingsValue
from internal.config.manager import ConfigManager
from internal.database.wrapper import DatabaseWrapper
from lib.ai.manager import LLMManager
from lib.ai.models import ModelResultStatus, ModelRunResult
from tests.fixtures.telegram_mocks import (
    createMockBot,
    createMockCallbackQuery,
    createMockContext,
    createMockMessage,
    createMockUpdate,
)


@pytest.fixture
def inMemoryDb():
    """Create in-memory database for testing, dood!"""
    db = DatabaseWrapper(":memory:")
    yield db
    db.close()


@pytest.fixture
def mockConfigManager():
    """Create mock config manager, dood!"""
    config = Mock(spec=ConfigManager)
    config.getBotConfig.return_value = {
        "bot_owners": ["testowner"],
        "defaults": {
            "chat-model": "gpt-4",
            "parse-images": "false",
            "save-images": "false",
        },
    }
    config.getOpenWeatherMapConfig.return_value = {"enabled": False}
    return config


@pytest.fixture
def mockLlmManager():
    """Create mock LLM manager, dood!"""
    manager = Mock(spec=LLMManager)
    mockModel = Mock()
    mockModel.generateText = AsyncMock(
        return_value=ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Test LLM response",
            toolCalls=[],
        )
    )
    manager.getModel.return_value = mockModel
    return manager


@pytest.fixture
def mockBot():
    """Create mock bot instance, dood!"""
    return createMockBot(username="test_bot")


@pytest.fixture
async def handlersManager(mockConfigManager, inMemoryDb, mockLlmManager, mockBot):
    """Create handlers manager with real components, dood!"""
    manager = HandlersManager(mockConfigManager, inMemoryDb, mockLlmManager)
    manager.injectBot(mockBot)
    return manager


@pytest.mark.asyncio
class TestInteractiveWorkflow:
    """Test interactive workflow with buttons and callbacks, dood!"""

    async def testButtonCallbackHandling(self, handlersManager, inMemoryDb, mockBot):
        """Test button callback handling workflow, dood!"""
        callbackQuery = createMockCallbackQuery(
            queryId="callback_123",
            data='{"action":"test","value":"123"}',
            userId=456,
        )
        update = createMockUpdate(callbackQuery=callbackQuery)
        context = createMockContext(bot=mockBot)

        await handlersManager.handle_button(update, context)

        callbackQuery.answer.assert_called_once()

    async def testMultiStepInteraction(self, handlersManager, inMemoryDb, mockBot):
        """Test multi-step interaction workflow, dood!"""
        chatId = 123
        userId = 456

        message1 = createMockMessage(
            messageId=1,
            chatId=chatId,
            userId=userId,
            text="/configure",
        )
        update1 = createMockUpdate(message=message1)
        context = createMockContext(bot=mockBot)

        await handlersManager.handle_message(update1, context)

        callbackQuery = createMockCallbackQuery(
            queryId="callback_123",
            data='{"action":"configure","setting":"chat-model"}',
            userId=userId,
        )
        update2 = createMockUpdate(callbackQuery=callbackQuery)

        await handlersManager.handle_button(update2, context)

        callbackQuery.answer.assert_called()

    async def testStateManagement(self, handlersManager, inMemoryDb, mockBot):
        """Test state management during interactive workflow, dood!"""
        chatId = 123
        userId = 456

        handlersManager.handlers[0].setUserData(chatId, userId, "config_state", "selecting_model")

        userData = handlersManager.handlers[0].getUserData(chatId, userId)
        assert "config_state" in userData
        assert userData["config_state"] == "selecting_model"

        handlersManager.handlers[0].unsetUserData(chatId, userId, "config_state")

        userData = handlersManager.handlers[0].getUserData(chatId, userId)
        assert "config_state" not in userData


@pytest.mark.asyncio
class TestErrorHandlingWorkflow:
    """Test error handling workflow, dood!"""

    async def testHandlerErrorRecovery(self, handlersManager, inMemoryDb, mockBot):
        """Test handler error recovery, dood!"""
        message = createMockMessage(
            messageId=1,
            chatId=123,
            userId=456,
            text="Test message",
        )
        update = createMockUpdate(message=message)
        context = createMockContext(bot=mockBot)

        originalHandler = handlersManager.handlers[0].messageHandler

        async def errorHandler(update, context, ensuredMessage):
            return HandlerResultStatus.ERROR

        handlersManager.handlers[0].messageHandler = errorHandler

        try:
            await handlersManager.handle_message(update, context)
        finally:
            handlersManager.handlers[0].messageHandler = originalHandler

    async def testDatabaseErrorHandling(self, handlersManager, inMemoryDb, mockBot):
        """Test database error handling, dood!"""
        message = createMockMessage(
            messageId=1,
            chatId=123,
            userId=456,
            text="Test message",
        )
        update = createMockUpdate(message=message)
        context = createMockContext(bot=mockBot)

        originalSave = inMemoryDb.saveChatMessage
        inMemoryDb.saveChatMessage = Mock(return_value=False)

        try:
            await handlersManager.handle_message(update, context)
        except Exception:
            pass
        finally:
            inMemoryDb.saveChatMessage = originalSave

    async def testApiErrorHandling(self, handlersManager, inMemoryDb, mockBot):
        """Test API error handling, dood!"""
        mockBot.sendMessage = AsyncMock(side_effect=Exception("API error"))

        message = createMockMessage(
            messageId=1,
            chatId=123,
            userId=456,
            text="/echo test",
        )
        message.from_user.username = "testowner"
        update = createMockUpdate(message=message)
        context = createMockContext(bot=mockBot)

        try:
            await handlersManager.handle_message(update, context)
        except Exception:
            pass


@pytest.mark.asyncio
class TestHandlerChainExecution:
    """Test handler chain execution, dood!"""

    async def testHandlerChainOrder(self, handlersManager, inMemoryDb, mockBot):
        """Test handlers execute in correct order, dood!"""
        executionOrder = []

        async def trackingHandler(name):
            async def handler(update, context, ensuredMessage):
                executionOrder.append(name)
                return HandlerResultStatus.NEXT

            return handler

        originalHandlers = []
        for i, handler in enumerate(handlersManager.handlers):
            originalHandlers.append(handler.messageHandler)
            handler.messageHandler = await trackingHandler(f"handler_{i:02d}")

        message = createMockMessage(messageId=1, chatId=123, userId=456, text="test")
        update = createMockUpdate(message=message)
        context = createMockContext(bot=mockBot)

        await handlersManager.handle_message(update, context)

        assert len(executionOrder) > 0
        for i in range(len(executionOrder) - 1):
            assert executionOrder[i] < executionOrder[i + 1]

        for i, handler in enumerate(handlersManager.handlers):
            handler.messageHandler = originalHandlers[i]

    async def testHandlerChainStopsOnFinal(self, handlersManager, inMemoryDb, mockBot):
        """Test handler chain stops when FINAL returned, dood!"""
        executionCount = {"count": 0}

        async def countingHandler(update, context, ensuredMessage):
            executionCount["count"] += 1
            if executionCount["count"] == 2:
                return HandlerResultStatus.FINAL
            return HandlerResultStatus.NEXT

        originalHandlers = []
        for i in range(min(3, len(handlersManager.handlers))):
            originalHandlers.append(handlersManager.handlers[i].messageHandler)
            handlersManager.handlers[i].messageHandler = countingHandler

        message = createMockMessage(messageId=1, chatId=123, userId=456, text="test")
        update = createMockUpdate(message=message)
        context = createMockContext(bot=mockBot)

        await handlersManager.handle_message(update, context)

        assert executionCount["count"] == 2

        for i in range(len(originalHandlers)):
            handlersManager.handlers[i].messageHandler = originalHandlers[i]

    async def testHandlerChainContinuesOnSkipped(self, handlersManager, inMemoryDb, mockBot):
        """Test handler chain continues when SKIPPED returned, dood!"""
        executionCount = {"count": 0}

        async def skippingHandler(update, context, ensuredMessage):
            executionCount["count"] += 1
            return HandlerResultStatus.SKIPPED

        originalHandlers = []
        for handler in handlersManager.handlers:
            originalHandlers.append(handler.messageHandler)
            handler.messageHandler = skippingHandler

        message = createMockMessage(messageId=1, chatId=123, userId=456, text="test")
        update = createMockUpdate(message=message)
        context = createMockContext(bot=mockBot)

        await handlersManager.handle_message(update, context)

        assert executionCount["count"] == len(handlersManager.handlers)

        for i, handler in enumerate(handlersManager.handlers):
            handler.messageHandler = originalHandlers[i]


@pytest.mark.asyncio
class TestDatabasePersistence:
    """Test database state changes during workflows, dood!"""

    async def testUserDataPersistence(self, handlersManager, inMemoryDb, mockBot):
        """Test user data persists across workflow, dood!"""
        chatId = 123
        userId = 456

        handler = handlersManager.handlers[0]
        handler.setUserData(chatId, userId, "preference", "dark_mode")
        handler.setUserData(chatId, userId, "language", "en")

        userData = handler.getUserData(chatId, userId)
        assert userData["preference"] == "dark_mode"
        assert userData["language"] == "en"

        newHandler = type(handler)(handlersManager.configManager, inMemoryDb, handlersManager.llmManager)
        newUserData = newHandler.getUserData(chatId, userId)
        assert newUserData["preference"] == "dark_mode"

    async def testChatSettingsPersistence(self, handlersManager, inMemoryDb, mockBot):
        """Test chat settings persistence, dood!"""
        chatId = 123

        handlersManager.handlers[0].setChatSetting(
            chatId, ChatSettingsKey.CHAT_MODEL, ChatSettingsValue("gpt-3.5-turbo")
        )

        settings = inMemoryDb.getChatSettings(chatId)
        assert ChatSettingsKey.CHAT_MODEL in settings
        assert settings[ChatSettingsKey.CHAT_MODEL] == "gpt-3.5-turbo"

        retrievedSettings = handlersManager.handlers[0].getChatSettings(chatId)
        assert retrievedSettings[ChatSettingsKey.CHAT_MODEL].toStr() == "gpt-3.5-turbo"

    async def testChatInfoUpdates(self, handlersManager, inMemoryDb, mockBot):
        """Test chat info updates, dood!"""
        chatId = 123

        inMemoryDb.updateChatInfo(
            chatId=chatId,
            type=Chat.GROUP,
            title="Test Group",
            username="testgroup",
            isForum=False,
        )

        chatInfo = inMemoryDb.getChatInfo(chatId=chatId)
        assert chatInfo is not None
        assert chatInfo["title"] == "Test Group"
        assert chatInfo["username"] == "testgroup"
        assert chatInfo["type"] == Chat.GROUP


@pytest.mark.asyncio
class TestConcurrentOperations:
    """Test concurrent operations, dood!"""

    async def testConcurrentUserData(self, handlersManager, inMemoryDb, mockBot):
        """Test concurrent user data updates, dood!"""
        chatId = 123
        userId = 456

        async def updateUserData(key, value):
            handlersManager.handlers[0].setUserData(chatId, userId, key, value)

        tasks = [
            updateUserData("pref1", "value1"),
            updateUserData("pref2", "value2"),
            updateUserData("pref3", "value3"),
        ]

        await asyncio.gather(*tasks)

        userData = handlersManager.handlers[0].getUserData(chatId, userId)
        assert "pref1" in userData
        assert "pref2" in userData
        assert "pref3" in userData

    async def testConcurrentChatSettings(self, handlersManager, inMemoryDb, mockBot):
        """Test concurrent chat settings updates, dood!"""
        chatId = 123

        async def updateSetting(key, value):
            handlersManager.handlers[0].setChatSetting(chatId, key, ChatSettingsValue(value))

        tasks = [
            updateSetting(ChatSettingsKey.CHAT_MODEL, "gpt-4"),
            updateSetting(ChatSettingsKey.SUMMARY_MODEL, "gpt-3.5-turbo"),
            updateSetting(ChatSettingsKey.USE_TOOLS, "true"),
        ]

        await asyncio.gather(*tasks)

        settings = inMemoryDb.getChatSettings(chatId)
        assert ChatSettingsKey.CHAT_MODEL in settings
        assert ChatSettingsKey.SUMMARY_MODEL in settings
        assert ChatSettingsKey.USE_TOOLS in settings
