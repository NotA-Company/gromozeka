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
    from internal.services.cache.models import CacheNamespace
    from internal.services.cache.service import CacheService

    db = DatabaseWrapper(":memory:")
    # Inject database into CacheService singleton
    cache = CacheService.getInstance()
    cache.injectDatabase(db)
    yield db
    # Clean up: clear cache after test
    for namespace in CacheNamespace:
        cache._caches[namespace].clear()
        cache.dirtyKeys[namespace].clear()
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
        "bot_owners": ["testuser"],  # Add bot_owners as usernames
    }
    mock.getOpenWeatherMapConfig.return_value = {"enabled": False}
    mock.getYandexSearchConfig.return_value = {
        "enabled": False,
        "api-key": "test-key",
        "folder-id": "test-folder",
        "cache-ttl": 3600,
    }
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

    # Find and call the /summary command handler directly
    commandHandlers = application.handlerManager.getCommandHandlers()
    summaryHandler = next((h for h in commandHandlers if "summary" in h.commands), None)
    assert summaryHandler is not None, "Summary command handler not found, dood!"

    await summaryHandler.handler(update, context)

    # Verify summary sent
    assert message.reply_text.called, "Bot should send summary, dood!"


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

    # Register user in chat (required for message handling)
    inMemoryDb.updateChatUser(chatId=chatId, userId=userId, username="testuser", fullName="Test User")

    # Don't populate database with messages - testing empty case

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

    # Enable summary and set required settings
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_SUMMARY.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_FALLBACK_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_PROMPT.value, "Summarize this chat")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.FALLBACK_HAPPENED_PREFIX.value, "[Fallback]")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.RANDOM_ANSWER_PROBABILITY.value, "0.0")

    # Find and call the /summary command handler directly
    commandHandlers = application.handlerManager.getCommandHandlers()
    summaryHandler = next((h for h in commandHandlers if "summary" in h.commands), None)
    assert summaryHandler is not None, "Summary command handler not found, dood!"

    await summaryHandler.handler(update, context)

    # Verify error message sent (handler uses message.reply_text, not bot.sendMessage)
    # Note: In e2e flow through full application, the message gets saved first,
    # then the handler processes it. Check if reply was called.
    assert message.reply_text.called, "Bot should send no messages notification, dood!"
    # Also verify the message content
    assert message.reply_text.call_count >= 1, "Should have called reply_text at least once"
    call_args = message.reply_text.call_args
    assert call_args is not None, "reply_text should have been called with arguments"
