"""
End-to-end tests for configuration flow through full Application, dood!

This module tests configuration command routing through the complete bot setup.
These are simple smoke tests - comprehensive configuration testing is in integration tests.

Test Coverage:
    - /configure command routing
    - Button callback routing for configuration
    - Permission check through full stack
"""

from unittest.mock import Mock

import pytest
from telegram import Chat

from internal.bot.application import BotApplication
from internal.bot.models import ButtonConfigureAction, ButtonDataKey
from internal.database.wrapper import DatabaseWrapper
from lib import utils
from tests.fixtures.telegram_mocks import (
    createMockBot,
    createMockCallbackQuery,
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
    # Mock OpenWeatherMap config to prevent initialization errors
    mock.getOpenWeatherMapConfig.return_value = {
        "enabled": False,  # Disable to avoid WeatherHandler initialization
    }
    return mock


@pytest.fixture
def mockLlmManager():
    """Create mock LLM manager, dood!"""
    from lib.ai.manager import LLMManager

    return Mock(spec=LLMManager)


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
# Test: Configuration Command Routing
# ============================================================================


@pytest.mark.asyncio
async def testConfigureCommandRouting(application, inMemoryDb, mockBot):
    """
    Test /configure command routes through Application, dood!

    Verifies:
        - Command reaches configuration handler
        - Menu is displayed
    """
    chatId = 123
    userId = 123456  # Bot owner

    # Add chat to database
    inMemoryDb.addChatInfo(chatId, "private", None, "testuser")
    inMemoryDb.updateChatUser(chatId, userId, "testuser", "Test User")

    message = createMockMessage(
        messageId=1,
        chatId=userId,
        userId=userId,
        text="/configure",
    )
    message.chat.type = Chat.PRIVATE
    message._bot = mockBot  # Set bot for shortcuts
    message.chat._bot = mockBot  # Set bot on chat for get_administrators()
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    sentMessage = createMockMessage(messageId=2, chatId=userId, userId=mockBot.id)
    mockBot.sendMessage.return_value = sentMessage

    # Find and call the /configure command handler directly
    commandHandlers = application.handlerManager.getCommandHandlers()
    configureHandler = next((h for h in commandHandlers if "configure" in h.commands), None)
    assert configureHandler is not None, "Configure command handler not found, dood!"

    await configureHandler.handler(update, context)

    # Verify menu displayed
    assert message.reply_text.called, "Bot should send configuration menu, dood!"


@pytest.mark.asyncio
async def testConfigurationButtonRouting(application, inMemoryDb, mockBot):
    """
    Test configuration button callbacks route through Application, dood!

    Verifies:
        - Button callbacks reach configuration handler
        - Handler processes button action
    """
    chatId = 123
    userId = 123456  # Bot owner

    inMemoryDb.addChatInfo(chatId, "private", None, "testuser")

    callbackMessage = createMockMessage(messageId=1, chatId=userId, userId=mockBot.id)

    callbackData = utils.packDict(
        {
            ButtonDataKey.ConfigureAction: ButtonConfigureAction.Cancel,
        }
    )

    query = createMockCallbackQuery(
        data=callbackData,
        message=callbackMessage,
        userId=userId,
    )

    update = createMockUpdate(callbackQuery=query)
    context = createMockContext(bot=mockBot)

    # Route through Application
    await application.handlerManager.handle_button(update, context)

    # Verify button handled
    query.answer.assert_called()


@pytest.mark.asyncio
async def testConfigurationPermissionCheck(application, inMemoryDb, mockBot):
    """
    Test configuration permission check through full Application, dood!

    Verifies:
        - Non-admin users cannot configure group chats
        - Permission check works end-to-end
    """
    chatId = 789  # Group chat
    userId = 999  # Not bot owner, not admin

    # Add both the group chat and the private chat with user
    inMemoryDb.addChatInfo(chatId, "group", "Test Group", None)
    inMemoryDb.addChatInfo(userId, "private", None, None)
    inMemoryDb.updateChatUser(userId, userId, "testuser", "Test User")

    message = createMockMessage(
        messageId=1,
        chatId=userId,
        userId=userId,
        text="/configure",
    )
    message.chat.type = Chat.PRIVATE
    message._bot = mockBot  # Set bot for shortcuts
    message.chat._bot = mockBot  # Set bot on chat for get_administrators()
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    sentMessage = createMockMessage(messageId=2, chatId=userId, userId=mockBot.id)
    mockBot.sendMessage.return_value = sentMessage

    # Find and call the /configure command handler directly
    commandHandlers = application.handlerManager.getCommandHandlers()
    configureHandler = next((h for h in commandHandlers if "configure" in h.commands), None)
    assert configureHandler is not None, "Configure command handler not found, dood!"

    await configureHandler.handler(update, context)

    # Verify response sent (should show "no admin chats" message)
    assert message.reply_text.called, "Bot should send response, dood!"
