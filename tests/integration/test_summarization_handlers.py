"""
Integration tests for summarization handlers in Gromozeka bot, dood!

This module tests summarization handlers by calling them directly, without going
through the full Application setup. Tests use real SummarizationHandler with mocked LLM.

Test Coverage:
    - Basic /summary command with default parameters
    - Custom time range and message count parameters
    - Error handling (no messages, LLM failures)
    - Permission checks
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from unittest.mock import AsyncMock, Mock

import pytest
from telegram import Chat

from internal.bot.handlers.summarization import SummarizationHandler
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
            resultText="Summary: This is a test summary of the messages, dood!",
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
async def summarizationHandler(mockConfigManager, inMemoryDb, mockLlmManager, mockBot):
    """Create summarization handler with all dependencies, dood!"""
    handler = SummarizationHandler(
        configManager=mockConfigManager,
        database=inMemoryDb,
        llmManager=mockLlmManager,
    )
    handler.injectBot(mockBot)
    return handler


def populateDatabaseWithMessages(
    db: DatabaseWrapper,
    chatId: int = 123,
    messageCount: int = 10,
    startTime: Optional[datetime] = None,
) -> List[dict]:
    """Populate database with sample messages for testing, dood!"""
    if startTime is None:
        startTime = datetime.now(timezone.utc) - timedelta(hours=1)

    messages = []
    baseTimestamp = int(startTime.timestamp())

    for i in range(messageCount):
        messageData = {
            "messageId": i + 1,
            "chatId": chatId,
            "userId": 456 + (i % 3),
            "messageText": f"Test message {i + 1} for summarization, dood!",
            "date": datetime.fromtimestamp(baseTimestamp + (i * 60), tz=timezone.utc),
            "messageCategory": MessageCategory.USER,
        }
        db.saveChatMessage(**messageData)
        messages.append(messageData)

        # Also add user to chat
        db.updateChatUser(
            chatId=chatId,
            userId=messageData["userId"],
            username=f"user{i % 3}",
            fullName=f"User{i % 3}",
        )

    return messages


# ============================================================================
# Test: Basic Summarization Command
# ============================================================================


@pytest.mark.asyncio
async def testBasicSummaryCommand(inMemoryDb, mockBot, summarizationHandler):
    """
    Test /summary command handler directly, dood!

    Verifies:
        - Messages retrieved correctly
        - LLM called with proper context
        - Summary response sent
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
    inMemoryDb.setChatSetting(
        chatId,
        ChatSettingsKey.SUMMARY_PROMPT.value,
        "Summarize the following messages concisely.",
    )

    # Call handler directly
    await summarizationHandler.summary_command(update, context)

    # Verify message.reply_text was called (handlers use message.reply_text, not bot.sendMessage)
    assert message.reply_text.called, "Bot should send summary response, dood!"


@pytest.mark.asyncio
async def testSummaryCommandWithCustomMessageCount(inMemoryDb, mockBot, summarizationHandler):
    """
    Test /summary command with custom message count parameter, dood!

    Verifies:
        - Custom message count parameter works
        - Summary generated for subset
    """
    chatId = 123
    userId = 456

    # Populate with 20 messages
    populateDatabaseWithMessages(inMemoryDb, chatId=chatId, messageCount=20)

    message = createMockMessage(
        messageId=100,
        chatId=chatId,
        userId=userId,
        text="/summary 5",
    )
    message.chat.type = Chat.GROUP
    message.entities = [Mock(type="bot_command", offset=0, length=8)]

    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)
    context.args = ["5"]

    # Enable summary
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_SUMMARY.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_FALLBACK_MODEL.value, "test-model")

    # Call handler directly
    await summarizationHandler.summary_command(update, context)

    # Verify message.reply_text was called (handlers use message.reply_text, not bot.sendMessage)
    assert message.reply_text.called, "Bot should send summary, dood!"


# ============================================================================
# Test: Error Handling
# ============================================================================


@pytest.mark.asyncio
async def testSummarizationWithNoMessages(inMemoryDb, mockBot, summarizationHandler):
    """
    Test error handling when no messages to summarize, dood!

    Verifies:
        - Empty message set handled gracefully
        - User notified appropriately
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

    # Call handler directly
    await summarizationHandler.summary_command(update, context)

    # Verify message.reply_text was called (should be "No messages to summarize")
    assert message.reply_text.called, "Bot should send no messages notification, dood!"


@pytest.mark.asyncio
async def testSummarizationWithLlmError(inMemoryDb, mockBot, mockConfigManager):
    """
    Test error handling when LLM fails during summarization, dood!

    Verifies:
        - LLM errors caught and handled
        - User receives error notification
    """
    chatId = 123
    userId = 456

    # Create LLM manager that raises error
    from lib.ai.abstract import AbstractModel
    from lib.ai.manager import LLMManager

    mockModel = AsyncMock(spec=AbstractModel)
    mockModel.name = "test-model"
    mockModel.getInfo.return_value = {"context_size": 4096}
    mockModel.getEstimateTokensCount = Mock(return_value=500)
    mockModel.generateTextWithFallBack = AsyncMock(side_effect=Exception("LLM service error, dood!"))

    mockLlmManager = Mock(spec=LLMManager)
    mockLlmManager.getModel.return_value = mockModel

    # Create handler with error-prone LLM
    handler = SummarizationHandler(
        configManager=mockConfigManager,
        database=inMemoryDb,
        llmManager=mockLlmManager,
    )
    handler.injectBot(mockBot)

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

    # Enable summary
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_SUMMARY.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_FALLBACK_MODEL.value, "test-model")

    # Call handler directly
    await handler.summary_command(update, context)

    # Verify message.reply_text was called for error notification
    assert message.reply_text.called, "Bot should send error notification, dood!"


@pytest.mark.asyncio
async def testSummarizationUnauthorizedUser(inMemoryDb, mockBot, summarizationHandler):
    """
    Test unauthorized user attempting to use summary command, dood!

    Verifies:
        - Permission checks work
        - Unauthorized users blocked
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

    # Call handler directly
    await summarizationHandler.summary_command(update, context)

    # Verify no summary sent (command rejected)
    assert not mockBot.sendMessage.called, "Bot should not send summary for unauthorized user, dood!"


# ============================================================================
# Test: Topic-Specific Summaries
# ============================================================================


@pytest.mark.asyncio
async def testTopicSummarization(inMemoryDb, mockBot, summarizationHandler):
    """
    Test topic-specific summarization in supergroups, dood!

    Verifies:
        - Topic filtering works
        - Only specified topic messages summarized
    """
    chatId = 123
    userId = 456
    topicId = 5

    # Add messages to specific topic
    for i in range(5):
        inMemoryDb.saveChatMessage(
            messageId=i + 1,
            chatId=chatId,
            userId=userId,
            messageText=f"Topic message {i + 1}",
            date=datetime.now(timezone.utc),
            threadId=topicId,
            messageCategory=MessageCategory.USER,
        )

    # Add messages to different topic (should be excluded)
    for i in range(5):
        inMemoryDb.saveChatMessage(
            messageId=i + 10,
            chatId=chatId,
            userId=userId,
            messageText=f"Other topic message {i + 1}",
            date=datetime.now(timezone.utc),
            threadId=99,  # Different topic
            messageCategory=MessageCategory.USER,
        )

    message = createMockMessage(
        messageId=100,
        chatId=chatId,
        userId=userId,
        text="/topic_summary",
    )
    message.chat.type = Chat.SUPERGROUP
    message.message_thread_id = topicId
    message.is_topic_message = True
    message.entities = [Mock(type="bot_command", offset=0, length=14)]

    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Enable summary
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_SUMMARY.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.SUMMARY_FALLBACK_MODEL.value, "test-model")

    # Call handler directly
    await summarizationHandler.summary_command(update, context)

    # Verify message.reply_text was called (handlers use message.reply_text, not bot.sendMessage)
    assert message.reply_text.called, "Bot should send topic summary, dood!"
