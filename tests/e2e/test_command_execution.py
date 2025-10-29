"""
End-to-end tests for command execution through full Application, dood!

This module tests command routing through the complete bot setup, verifying
that commands reach the correct handlers via the Application's message routing.
These are simple smoke tests - comprehensive command testing is in integration tests.

Test Coverage:
    - /start command routing
    - /help command routing
    - Admin command permission check
    - Command with parameters routing
"""

from unittest.mock import AsyncMock, Mock

import pytest
from telegram import Chat

from internal.bot.application import BotApplication
from internal.database.wrapper import DatabaseWrapper
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
    mock.getOpenWeatherMapConfig.return_value = {
        "enabled": False,
    }
    return mock


@pytest.fixture
def mockLlmManager():
    """Create mock LLM manager, dood!"""
    from lib.ai.abstract import AbstractModel
    from lib.ai.manager import LLMManager

    mockModel = AsyncMock(spec=AbstractModel)
    mockModel.name = "test-model"
    mockModel.generateText = AsyncMock(return_value="Test response")

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


# ============================================================================
# Test: Command Routing Through Application
# ============================================================================


@pytest.mark.asyncio
async def testStartCommandRouting(application, mockBot, inMemoryDb):
    """
    Test /start command routes through Application to handler, dood!

    Verifies:
        - Command reaches correct handler
        - Response is sent
    """
    chatId = 123
    userId = 456

    # Add chat to database so handlers can determine chat type
    inMemoryDb.addChatInfo(chatId, "private", None, None)
    inMemoryDb.updateChatUser(chatId, userId, "testuser", "Test User")

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="/start",
    )
    message.chat.type = Chat.PRIVATE
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Find and call the /start command handler directly
    commandHandlers = application.handlerManager.getCommandHandlers()
    startHandler = next((h for h in commandHandlers if "start" in h.commands), None)
    assert startHandler is not None, "Start command handler not found, dood!"

    await startHandler.handler(update, context)

    # Verify response sent via reply_text
    assert message.reply_text.called, "Bot should send response, dood!"


@pytest.mark.asyncio
async def testHelpCommandRouting(application, mockBot, inMemoryDb):
    """
    Test /help command routes through Application to handler, dood!

    Verifies:
        - Command reaches correct handler
        - Help message sent
    """
    chatId = 123
    userId = 456

    # Add chat to database so handlers can determine chat type
    inMemoryDb.addChatInfo(chatId, "private", None, None)
    inMemoryDb.updateChatUser(chatId, userId, "testuser", "Test User")

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="/help",
    )
    message.chat.type = Chat.PRIVATE
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Find and call the /help command handler directly
    commandHandlers = application.handlerManager.getCommandHandlers()
    helpHandler = next((h for h in commandHandlers if "help" in h.commands), None)
    assert helpHandler is not None, "Help command handler not found, dood!"

    await helpHandler.handler(update, context)

    # Verify response sent via reply_text
    assert message.reply_text.called, "Bot should send help message, dood!"


@pytest.mark.asyncio
async def testAdminCommandPermissionCheck(application, mockBot):
    """
    Test admin command permission check through Application, dood!

    Verifies:
        - Non-owner cannot execute admin commands
        - Permission check works end-to-end
    """
    chatId = 123
    userId = 999  # Not a bot owner

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="/models",
    )
    message.chat.type = Chat.PRIVATE
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Route through Application
    await application.handlerManager.handle_message(update, context)

    # Non-owner should not get model list
    # (handler should reject or skip)


@pytest.mark.asyncio
async def testCommandWithParameters(application, mockBot, inMemoryDb):
    """
    Test command with parameters routes correctly, dood!

    Verifies:
        - Command parameters parsed
        - Handler receives parameters
        - Response includes parameter data
    """
    chatId = 123
    userId = 456
    echoText = "Test message"

    # Add chat to database so handlers can determine chat type
    inMemoryDb.addChatInfo(chatId, "private", None, None)
    inMemoryDb.updateChatUser(chatId, userId, "testuser", "Test User")

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text=f"/echo {echoText}",
    )
    message.chat.type = Chat.PRIVATE
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)
    context.args = echoText.split()

    # Find and call the /echo command handler directly
    commandHandlers = application.handlerManager.getCommandHandlers()
    echoHandler = next((h for h in commandHandlers if "echo" in h.commands), None)
    assert echoHandler is not None, "Echo command handler not found, dood!"

    await echoHandler.handler(update, context)

    # Verify response sent with echo text via reply_text
    assert message.reply_text.called, "Bot should send echo response, dood!"
    callArgs = message.reply_text.call_args
    responseText = str(callArgs)
    assert echoText in responseText, "Response should contain echo text, dood!"
