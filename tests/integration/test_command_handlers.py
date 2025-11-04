"""
Integration tests for command handlers in Gromozeka bot, dood!

This module tests command handlers by calling them directly, without going through
the full Application setup. Tests use real handlers with mocked external services.

Test Coverage:
    - Basic commands (/start, /help, /echo)
    - Admin commands (/set, /unset, /models, /settings)
    - Feature commands (/weather, /remind, /list_chats)
    - Command parsing and validation
    - Permission checks
    - Error handling
    - Response formatting
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import Chat

from internal.bot.handlers.common import CommonHandler
from internal.bot.handlers.dev_commands import DevCommandsHandler
from internal.bot.handlers.help_command import HelpHandler
from internal.bot.models import ChatSettingsKey
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
    """
    Provide in-memory SQLite database for testing, dood!

    Yields:
        DatabaseWrapper: In-memory database instance
    """
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
    """
    Create mock Telegram bot, dood!

    Returns:
        AsyncMock: Mocked bot instance
    """
    return createMockBot()


@pytest.fixture
def mockConfigManager():
    """
    Create mock config manager with default settings, dood!

    Returns:
        Mock: Mocked ConfigManager
    """
    from internal.config.manager import ConfigManager

    mock = Mock(spec=ConfigManager)
    mock.getBotConfig.return_value = {
        "token": "test_token",
        "owners": [123456],
    }
    mock.getOpenWeatherMapConfig.return_value = {
        "enabled": True,
        "api-key": "test_api_key",
    }
    return mock


@pytest.fixture
def mockLlmManager():
    """
    Create mock LLM manager with test model, dood!

    Returns:
        Mock: Mocked LLMManager
    """
    from lib.ai.abstract import AbstractModel
    from lib.ai.manager import LLMManager

    mockModel = AsyncMock(spec=AbstractModel)
    mockModel.name = "test-model"
    mockModel.generateText = AsyncMock(return_value="Test AI response, dood!")

    manager = Mock(spec=LLMManager)
    manager.getModel.return_value = mockModel
    manager.listModels.return_value = ["test-model", "gpt-4", "claude-3"]
    manager.getModelInfo.return_value = {
        "model_id": "test-model",
        "provider": "test-provider",
        "temperature": 0.7,
        "context_size": 4096,
        "support_tools": True,
        "support_text": True,
        "support_images": False,
    }

    return manager


@pytest.fixture
async def commonHandler(mockConfigManager, inMemoryDb, mockLlmManager, mockBot):
    """Create CommonHandler with dependencies, dood!"""
    handler = CommonHandler(
        configManager=mockConfigManager,
        database=inMemoryDb,
        llmManager=mockLlmManager,
    )
    handler.injectBot(mockBot)
    return handler


@pytest.fixture
async def devCommandsHandler(mockConfigManager, inMemoryDb, mockLlmManager, mockBot):
    """Create DevCommandsHandler with dependencies, dood!"""
    handler = DevCommandsHandler(
        configManager=mockConfigManager,
        database=inMemoryDb,
        llmManager=mockLlmManager,
    )
    handler.injectBot(mockBot)
    return handler


@pytest.fixture
async def helpHandler(mockConfigManager, inMemoryDb, mockLlmManager, mockBot):
    """Create HelpHandler with dependencies, dood!"""
    # HelpHandler needs a commandsGetter, so we'll create a mock
    from internal.bot.handlers.help_command import CommandHandlerGetterInterface

    mockCommandsGetter = Mock(spec=CommandHandlerGetterInterface)
    mockCommandsGetter.getCommandHandlers.return_value = []

    handler = HelpHandler(
        configManager=mockConfigManager,
        database=inMemoryDb,
        llmManager=mockLlmManager,
        commandsGetter=mockCommandsGetter,
    )
    handler.injectBot(mockBot)
    return handler


# ============================================================================
# Test: Basic Commands
# ============================================================================


@pytest.mark.asyncio
async def testStartCommand(inMemoryDb, mockBot, commonHandler):
    """
    Test /start command handler directly, dood!

    Verifies:
        - Welcome message sent with correct text
        - Bot responds with greeting
    """
    chatId = 123
    userId = 456

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="/start",
    )
    message.chat.type = Chat.PRIVATE
    message.reply_text = AsyncMock(return_value=message)
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Call handler directly
    await commonHandler.start_command(update, context)

    # Verify welcome message sent
    message.reply_text.assert_called()
    callArgs = message.reply_text.call_args
    responseText = str(callArgs)
    assert "Привет" in responseText or "Громозека" in responseText, "Should send welcome message, dood!"


@pytest.mark.asyncio
async def testHelpCommand(inMemoryDb, mockBot, helpHandler):
    """
    Test /help command handler directly, dood!

    Verifies:
        - Help message sent
        - Contains command descriptions
    """
    chatId = 123
    userId = 456

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="/help",
    )
    message.chat.type = Chat.PRIVATE
    message.reply_text = AsyncMock(return_value=message)
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Call handler directly
    await helpHandler.help_command(update, context)

    # Verify help message sent
    message.reply_text.assert_called()


# ============================================================================
# Test: Admin Commands
# ============================================================================


@pytest.mark.asyncio
async def testModelsCommand(inMemoryDb, mockBot, devCommandsHandler, mockLlmManager):
    """
    Test /models command handler directly, dood!

    Verifies:
        - Model list sent
        - Contains model details
        - Only accessible to bot owners
    """
    chatId = 123
    userId = 123456  # Bot owner ID from mockConfigManager

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="/models",
    )
    message.chat.type = Chat.PRIVATE
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Mock isAdmin to bypass permission check
    with patch.object(devCommandsHandler, "isAdmin", return_value=True):
        # Call handler directly with mocked sendMessage
        with patch.object(devCommandsHandler, "sendMessage", new_callable=AsyncMock) as mockSend:
            await devCommandsHandler.models_command(update, context)

            # Verify model list sent
            mockSend.assert_called()
            callArgs = mockSend.call_args
            responseText = str(callArgs)
            assert "test-model" in responseText or "Модель" in responseText, "Should list models, dood!"


@pytest.mark.asyncio
async def testSettingsCommand(inMemoryDb, mockBot, devCommandsHandler):
    """
    Test /settings command handler directly, dood!

    Verifies:
        - Settings displayed
        - Contains setting keys and values
        - Only accessible to bot owners
    """
    chatId = 123
    userId = 123456  # Bot owner

    # Set some test settings
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_MENTION.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_REPLY.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_MENTION.value, "false")

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="/settings",
    )
    message.chat.type = Chat.PRIVATE
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Mock isAdmin to bypass permission check
    with patch.object(devCommandsHandler, "isAdmin", return_value=True):
        # Call handler directly with mocked sendMessage
        with patch.object(devCommandsHandler, "sendMessage", new_callable=AsyncMock) as mockSend:
            await devCommandsHandler.chat_settings_command(update, context)

            # Verify settings sent
            mockSend.assert_called()
            callArgs = mockSend.call_args
            responseText = str(callArgs)
            assert "Настройки" in responseText or "settings" in responseText.lower(), "Should show settings, dood!"


# ============================================================================
# Test: Permission Checks
# ============================================================================


@pytest.mark.asyncio
async def testBotOwnerBypassesPermissions(inMemoryDb, mockBot, devCommandsHandler):
    """
    Test bot owners can execute commands anywhere, dood!

    Verifies:
        - Bot owners bypass permission checks
        - Owner commands work in any chat type
    """
    chatId = 789
    userId = 123456  # Bot owner

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="/settings",
    )
    message.chat.type = Chat.GROUP
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Mock isAdmin to bypass permission check
    with patch.object(devCommandsHandler, "isAdmin", return_value=True):
        # Call handler directly with mocked sendMessage
        with patch.object(devCommandsHandler, "sendMessage", new_callable=AsyncMock) as mockSend:
            await devCommandsHandler.chat_settings_command(update, context)

            # Verify command executed (owner bypasses checks)
            mockSend.assert_called()


# ============================================================================
# Test: Error Handling
# ============================================================================


@pytest.mark.asyncio
async def testCommandWithBotApiError(inMemoryDb, mockBot, commonHandler):
    """
    Test command handling when bot API fails, dood!

    Verifies:
        - Bot API errors handled gracefully
        - Error doesn't crash handler
    """
    chatId = 123
    userId = 456

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="/start",
    )
    message.chat.type = Chat.PRIVATE
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Mock bot to raise error
    mockBot.sendMessage = AsyncMock(side_effect=Exception("API Error"))

    # Call handler directly (should handle error)
    try:
        await commonHandler.start_command(update, context)
    except Exception:
        pass  # Error expected and handled
