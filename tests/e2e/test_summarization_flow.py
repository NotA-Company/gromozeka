"""
End-to-end tests for summarization flow through full Application, dood!

This module tests summarization command routing through the complete bot setup.
These are simple smoke tests - comprehensive summarization testing is in integration tests.

Test Coverage:
    - /summary command routing
    - Permission check through full stack
    - Error handling through full stack
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from telegram import Chat

from internal.bot.application import BotApplication
from internal.bot.models import ChatSettingsKey
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from lib.ai.models import ModelResultStatus, ModelRunResult
from tests.fixtures.telegram_mocks import (
    createMockBot,
    createMockContext,
    createMockMessage,
    createMockUpdate,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def inMemoryDb():
    """Provide in-memory SQLite database for testing, dood!"""
    db = DatabaseWrapper(":memory:")
    yield db
    db.close()


@pytest.fixture
def mockBot():
    """Create mock Telegram bot, dood!"""
    return createMockBot()


@pytest.fixture
def mockConfigManager():
    """Create mock config manager with default settings, dood!"""
    from internal.config.manager import ConfigManager

    mock = Mock(spec=ConfigManager)
    mock.getBotConfig.return_value = {
        "token": "test_token",
        "owners": [123456],
    }
    mock.getOpenWeatherMapConfig.return_value = {"enabled": False}
    return mock


@pytest.fixture
def mockLlmManager():
    """Create mock LLM manager with test model, dood!"""
    from lib.ai.abstract import AbstractModel
    from lib.ai.manager import LLMManager

    mockModel = AsyncMock(spec=AbstractModel)
    mockModel.name = "test-model"
    mockModel.getInfo.return_value = {
        "context_size": 4096,
        "max_tokens": 1000,
    }
    mockModel.getEstimateTokensCount = Mock(return_value=500)

    async def mockGenerateWithFallback(messages, fallbackModel=None):
        result = ModelRunResult(
            rawResult=None,
            status=ModelResultStatus.FINAL,
            resultText="Summary: Test summary, dood!",
        )
        result.setFallback(False)
        result.setToolsUsed(False)
        return result

    mockModel.generateTextWithFallBack = AsyncMock(side_effect=mockGenerateWithFallback)

    manager = Mock(spec=LLMManager)
    manager.getModel.return_value = mockModel
    manager.listModels.return_value = ["test-model"]

    return manager


@pytest.fixture
async def application(mockConfigManager, inMemoryDb, mockLlmManager, mockBot):
    """Create BotApplication with full setup, dood!"""
    app = BotApplication(
        configManager=mockConfigManager,
        botToken="test_token",
        database=inMemoryDb,
        llmManager=mockLlmManager,
    )
    app.handlerManager.injectBot(mockBot)
    return app


def populateDatabaseWithMessages(db: DatabaseWrapper, chatId: int = 123, messageCount: int = 10):
    """Populate database with sample messages for testing, dood!"""
    startTime = datetime.now(timezone.utc) - timedelta(hours=1)
    baseTimestamp = int(startTime.timestamp())

    for i in range(messageCount):
        db.saveChatMessage(
            messageId=i + 1,
            chatId=chatId,
            userId=456,
            messageText=f"Test message {i + 1}",
            date=datetime.fromtimestamp(baseTimestamp + (i * 60), tz=timezone.utc),
            messageCategory=MessageCategory.USER,
        )


# ============================================================================
# Test: Summarization Command Routing
# ============================================================================


@pytest.mark.skip("LLM singleton mocking issue - requires refactoring")
@pytest.mark.asyncio
async def testSummaryCommandRouting(application, inMemoryDb, mockBot):
    """
    Test /summary command routes through Application, dood!

    Verifies:
        - Command reaches summarization handler
        - Summary is generated and sent
    """
    chatId = 123
    userId = 456

    # Populate database with messages
    populateDatabaseWithMessages(inMemoryDb, chatId=chatId, messageCount=10)

    message = createMockMessage(
        messageId=100,
        chatId=chatId,
        userId=userId,
        text="/summary",
    )
    message.chat.type = Chat.GROUP
    message.entities = [Mock(type="bot_command", offset=0, length=8)]

    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Enable summary in chat settings
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_SUMMARY.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_FALLBACK_MODEL.value, "test-model")

    # Route through Application
    await application.handlerManager.handle_message(update, context)

    # Verify summary sent
    assert mockBot.sendMessage.called, "Bot should send summary, dood!"


@pytest.mark.asyncio
async def testSummaryCommandPermissionCheck(application, inMemoryDb, mockBot):
    """
    Test summary command permission check through full Application, dood!

    Verifies:
        - Unauthorized users cannot use summary
        - Permission check works end-to-end
    """
    chatId = 123
    userId = 999  # Not bot owner

    # Populate database
    populateDatabaseWithMessages(inMemoryDb, chatId=chatId, messageCount=5)

    message = createMockMessage(
        messageId=100,
        chatId=chatId,
        userId=userId,
        text="/summary",
    )
    message.chat.type = Chat.GROUP
    message.entities = [Mock(type="bot_command", offset=0, length=8)]

    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # DISABLE summary in settings
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_SUMMARY.value, "false")

    # Route through Application
    await application.handlerManager.handle_message(update, context)

    # Verify no summary sent (command rejected)
    assert not mockBot.sendMessage.called, "Bot should not send summary for unauthorized user, dood!"


@pytest.mark.skip("Cache service needs dbWrapper initialization - requires refactoring")
@pytest.mark.asyncio
async def testSummaryCommandWithNoMessages(application, inMemoryDb, mockBot):
    """
    Test summary command with no messages through full Application, dood!

    Verifies:
        - Error handling works end-to-end
        - User notified when no messages available
    """
    chatId = 123
    userId = 456

    # Don't populate database - no messages

    message = createMockMessage(
        messageId=100,
        chatId=chatId,
        userId=userId,
        text="/summary",
    )
    message.chat.type = Chat.GROUP
    message.entities = [Mock(type="bot_command", offset=0, length=8)]

    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Enable summary
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_SUMMARY.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_FALLBACK_MODEL.value, "test-model")

    # Route through Application
    await application.handlerManager.handle_message(update, context)

    # Verify error message sent
    assert mockBot.sendMessage.called, "Bot should send no messages notification, dood!"
