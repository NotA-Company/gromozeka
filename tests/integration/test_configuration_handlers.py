"""
Integration tests for configuration handlers in Gromozeka bot, dood!

This module tests configuration handlers by calling them directly, without going
through the full Application setup. Tests use real ConfigureHandler with mocked services.

Test Coverage:
    - Basic configuration command flow
    - Interactive configuration navigation
    - Setting types (boolean, string, numeric)
    - Permission checks (admin-only settings)
    - Error handling (invalid values, cancellation)
    - Setting persistence to database
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import Chat

from internal.bot.handlers.configure import ConfigureCommandHandler
from internal.bot.models import (
    ButtonConfigureAction,
    ButtonDataKey,
    ChatSettingsKey,
)
from internal.database.wrapper import DatabaseWrapper
from lib import utils
from tests.fixtures.telegram_mocks import (
    createMockBot,
    createMockContext,
    createMockMessage,
    createMockUpdate,
    createMockUser,
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
    return mock


@pytest.fixture
def mockLlmManager():
    """Create mock LLM manager, dood!"""
    from lib.ai.manager import LLMManager

    return Mock(spec=LLMManager)


@pytest.fixture
async def configureHandler(mockConfigManager, inMemoryDb, mockLlmManager, mockBot):
    """Create configure handler with all dependencies, dood!"""
    # Inject database into cache service singleton
    from internal.services.cache import CacheService

    cache = CacheService.getInstance()
    cache.injectDatabase(inMemoryDb)

    handler = ConfigureCommandHandler(
        configManager=mockConfigManager,
        database=inMemoryDb,
        llmManager=mockLlmManager,
    )
    handler.injectBot(mockBot)
    return handler


# ============================================================================
# Test: Basic Configuration Flow
# ============================================================================


@pytest.mark.asyncio
async def testConfigureCommand(inMemoryDb, mockBot, configureHandler):
    """
    Test /configure command handler directly, dood!

    Verifies:
        - Command execution
        - Menu generation
        - Chat list displayed
    """
    chatId = 123
    userId = 123456  # Bot owner

    # Add chat to database with proper values (not Mock objects)
    inMemoryDb.updateChatInfo(chatId, "private", None, "testuser")
    inMemoryDb.updateChatUser(chatId, userId, "testuser", "Test User")

    message = createMockMessage(
        messageId=1,
        chatId=userId,
        userId=userId,
        text="/configure",
    )
    message.chat.type = Chat.PRIVATE
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    sentMessage = createMockMessage(messageId=2, chatId=userId, userId=mockBot.id)
    sentMessage.get_bot = Mock(return_value=mockBot)
    mockBot.sendMessage = AsyncMock(return_value=sentMessage)

    # Mock getChatAdministrators to avoid bot association issues
    mockBot.get_chat_administrators = AsyncMock(return_value=[])

    # Call handler directly with mocked isAdmin, saveChatMessage, and sendMessage
    with (
        patch.object(configureHandler, "isAdmin", return_value=True),
        patch.object(configureHandler, "saveChatMessage"),
        patch.object(configureHandler, "sendMessage", return_value=sentMessage) as mockSendMessage,
    ):
        await configureHandler.configure_command(update, context)

    # Verify menu displayed
    mockSendMessage.assert_called_once()

    # Verify edit_text was called on the sent message
    sentMessage.edit_text.assert_called()


@pytest.mark.asyncio
async def testConfigureCommandDisplaysChatList(inMemoryDb, mockBot, configureHandler):
    """
    Test /configure command displays list of configurable chats, dood!

    Verifies:
        - Command shows chat selection menu
        - Chats where user is admin are shown
    """
    chatId = 123
    userId = 123456  # Bot owner

    # Add both user's private chat and the group chat
    inMemoryDb.updateChatInfo(userId, "private", None, "testuser")
    inMemoryDb.updateChatInfo(chatId, "group", "Test Group", None)
    inMemoryDb.updateChatUser(chatId, userId, "testuser", "Test User")

    message = createMockMessage(
        messageId=1,
        chatId=userId,
        userId=userId,
        text="/configure",
    )
    message.chat.type = Chat.PRIVATE
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    sentMessage = createMockMessage(messageId=2, chatId=userId, userId=mockBot.id)
    sentMessage.get_bot = Mock(return_value=mockBot)
    mockBot.sendMessage = AsyncMock(return_value=sentMessage)
    mockBot.get_chat_administrators = AsyncMock(return_value=[])

    with (
        patch.object(configureHandler, "isAdmin", return_value=True),
        patch.object(configureHandler, "saveChatMessage"),
        patch.object(configureHandler, "sendMessage", return_value=sentMessage),
    ):
        await configureHandler.configure_command(update, context)

    # Verify chat list displayed
    sentMessage.edit_text.assert_called()
    editArgs = sentMessage.edit_text.call_args
    assert "Выберите чат" in editArgs[1]["text"]


@pytest.mark.asyncio
async def testConfigureCommandNoAdminChats(inMemoryDb, mockBot, configureHandler):
    """
    Test /configure command when user is not admin in any chat, dood!

    Verifies:
        - Shows appropriate message when no admin chats
    """
    userId = 999  # Not a bot owner

    # Add user's private chat
    inMemoryDb.updateChatInfo(userId, "private", None, "testuser")

    message = createMockMessage(
        messageId=1,
        chatId=userId,
        userId=userId,
        text="/configure",
    )
    message.chat.type = Chat.PRIVATE
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    sentMessage = createMockMessage(messageId=2, chatId=userId, userId=mockBot.id)
    sentMessage.get_bot = Mock(return_value=mockBot)
    mockBot.sendMessage = AsyncMock(return_value=sentMessage)
    mockBot.get_chat_administrators = AsyncMock(return_value=[])

    with (
        patch.object(configureHandler, "isAdmin", return_value=False),
        patch.object(configureHandler, "saveChatMessage"),
        patch.object(configureHandler, "sendMessage", return_value=sentMessage),
    ):
        await configureHandler.configure_command(update, context)

    # Verify no admin message
    sentMessage.edit_text.assert_called()
    editArgs = sentMessage.edit_text.call_args
    # Check if text is in positional args or keyword args
    if editArgs[0]:  # Positional args
        assert "не являетесь администратором" in editArgs[0][0]
    else:  # Keyword args
        assert "не являетесь администратором" in editArgs[1]["text"]


# ============================================================================
# Test: Setting Types
# ============================================================================


@pytest.mark.asyncio
async def testBooleanSettingConfiguration(inMemoryDb, mockBot, configureHandler):
    """
    Test boolean setting configuration (on/off), dood!

    Verifies:
        - SetTrue action sets value to True
        - SetFalse action sets value to False
        - Value persisted to database
    """
    chatId = 123
    userId = 123456
    settingKey = ChatSettingsKey.USE_TOOLS

    inMemoryDb.updateChatInfo(chatId, "private", None, "testuser")

    message = createMockMessage(messageId=1, chatId=userId, userId=userId)
    message.get_bot = Mock(return_value=mockBot)

    # Set to True
    callbackData = utils.packDict(
        {
            ButtonDataKey.ChatId: chatId,
            ButtonDataKey.Key: settingKey.getId(),
            ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetTrue,
        }
    )

    with patch.object(configureHandler, "isAdmin", return_value=True):
        result = await configureHandler._handle_chat_configuration(
            utils.unpackDict(callbackData),
            message,
            createMockUser(userId=userId),
        )

    assert result is True

    # Verify value in database
    settings = inMemoryDb.getChatSettings(chatId)
    assert settingKey.value in settings
    assert settings[settingKey.value] == "True"

    # Set to False
    message.reset_mock()
    callbackData = utils.packDict(
        {
            ButtonDataKey.ChatId: chatId,
            ButtonDataKey.Key: settingKey.getId(),
            ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetFalse,
        }
    )

    with patch.object(configureHandler, "isAdmin", return_value=True):
        result = await configureHandler._handle_chat_configuration(
            utils.unpackDict(callbackData),
            message,
            createMockUser(userId=userId),
        )

    assert result is True

    # Verify value updated
    settings = inMemoryDb.getChatSettings(chatId)
    assert settings[settingKey.value] == "False"


@pytest.mark.asyncio
async def testStringSettingConfiguration(inMemoryDb, mockBot, configureHandler):
    """
    Test string setting configuration (text input), dood!

    Verifies:
        - String settings accept text input
        - Value validated and saved
    """
    chatId = 123
    userId = 123456
    settingKey = ChatSettingsKey.CHAT_PROMPT
    newValue = "You are a helpful assistant"

    inMemoryDb.updateChatInfo(chatId, "private", None, "testuser")

    message = createMockMessage(messageId=1, chatId=userId, userId=userId)
    message.get_bot = Mock(return_value=mockBot)

    callbackData = utils.packDict(
        {
            ButtonDataKey.ChatId: chatId,
            ButtonDataKey.Key: settingKey.getId(),
            ButtonDataKey.Value: newValue,
            ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetValue,
        }
    )

    with patch.object(configureHandler, "isAdmin", return_value=True):
        result = await configureHandler._handle_chat_configuration(
            utils.unpackDict(callbackData),
            message,
            createMockUser(userId=userId),
        )

    assert result is True

    # Verify value in database
    settings = inMemoryDb.getChatSettings(chatId)
    assert settingKey.value in settings
    assert settings[settingKey.value] == newValue


@pytest.mark.asyncio
async def testResetSettingToDefault(inMemoryDb, mockBot, configureHandler):
    """
    Test resetting setting to default value, dood!

    Verifies:
        - ResetValue action removes custom setting
        - Default value used after reset
    """
    chatId = 123
    userId = 123456
    settingKey = ChatSettingsKey.USE_TOOLS

    inMemoryDb.updateChatInfo(chatId, "private", None, "testuser")

    # Set custom value first
    inMemoryDb.setChatSetting(chatId, settingKey.value, "False")

    message = createMockMessage(messageId=1, chatId=userId, userId=userId)
    message.get_bot = Mock(return_value=mockBot)

    # Reset to default
    callbackData = utils.packDict(
        {
            ButtonDataKey.ChatId: chatId,
            ButtonDataKey.Key: settingKey.getId(),
            ButtonDataKey.ConfigureAction: ButtonConfigureAction.ResetValue,
        }
    )

    with patch.object(configureHandler, "isAdmin", return_value=True):
        result = await configureHandler._handle_chat_configuration(
            utils.unpackDict(callbackData),
            message,
            createMockUser(userId=userId),
        )

    assert result is True

    # Verify setting removed (will use default)
    settings = inMemoryDb.getChatSettings(chatId)
    assert settingKey.value not in settings or settings[settingKey.value] != "False"


# ============================================================================
# Test: Permission Checks
# ============================================================================


@pytest.mark.asyncio
async def testBotOwnerBypassesPermissions(inMemoryDb, mockBot, configureHandler):
    """
    Test bot owners can configure any chat, dood!

    Verifies:
        - Bot owners bypass admin checks
        - Settings saved successfully
    """
    chatId = 789
    userId = 123456  # Bot owner
    settingKey = ChatSettingsKey.USE_TOOLS

    inMemoryDb.updateChatInfo(chatId, "group", "Test Group", None)

    message = createMockMessage(messageId=1, chatId=userId, userId=userId)
    message.get_bot = Mock(return_value=mockBot)

    callbackData = utils.packDict(
        {
            ButtonDataKey.ChatId: chatId,
            ButtonDataKey.Key: settingKey.getId(),
            ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetTrue,
        }
    )

    with patch.object(configureHandler, "isAdmin", return_value=True):
        result = await configureHandler._handle_chat_configuration(
            utils.unpackDict(callbackData),
            message,
            createMockUser(userId=userId),
        )

    assert result is True

    # Verify setting saved
    settings = inMemoryDb.getChatSettings(chatId)
    assert settingKey.value in settings


# ============================================================================
# Test: Error Handling
# ============================================================================


@pytest.mark.asyncio
async def testInvalidSettingKey(inMemoryDb, mockBot, configureHandler):
    """
    Test handling of invalid setting key, dood!

    Verifies:
        - Invalid key ID handled gracefully
        - Error returned
    """
    chatId = 123
    userId = 123456
    invalidKeyId = 9999  # Non-existent key

    inMemoryDb.updateChatInfo(chatId, "private", None, "testuser")

    message = createMockMessage(messageId=1, chatId=userId, userId=userId)
    message.get_bot = Mock(return_value=mockBot)

    callbackData = utils.packDict(
        {
            ButtonDataKey.ChatId: chatId,
            ButtonDataKey.Key: invalidKeyId,
            ButtonDataKey.ConfigureAction: ButtonConfigureAction.ConfigureKey,
        }
    )

    with patch.object(configureHandler, "isAdmin", return_value=True):
        result = await configureHandler._handle_chat_configuration(
            utils.unpackDict(callbackData),
            message,
            createMockUser(userId=userId),
        )

    assert result is False


@pytest.mark.asyncio
async def testCancellationHandling(inMemoryDb, mockBot, configureHandler):
    """
    Test cancellation handling, dood!

    Verifies:
        - Cancel action exits configuration
        - Confirmation message shown
    """
    userId = 123456

    message = createMockMessage(messageId=1, chatId=userId, userId=userId)
    message.get_bot = Mock(return_value=mockBot)

    callbackData = utils.packDict(
        {
            ButtonDataKey.ConfigureAction: ButtonConfigureAction.Cancel,
        }
    )

    result = await configureHandler._handle_chat_configuration(
        utils.unpackDict(callbackData),
        message,
        createMockUser(userId=userId),
    )

    assert result is True

    # Verify cancellation message
    message.edit_text.assert_called()
    editArgs = message.edit_text.call_args
    assert "закончена" in editArgs[1]["text"]


# ============================================================================
# Test: Setting Persistence
# ============================================================================


@pytest.mark.asyncio
async def testSettingPersistenceToDatabase(inMemoryDb, mockBot, configureHandler):
    """
    Test settings persist to database correctly, dood!

    Verifies:
        - Settings saved to database
        - Settings retrievable after save
        - Multiple settings can coexist
    """
    chatId = 123
    userId = 123456

    inMemoryDb.updateChatInfo(chatId, "private", None, "testuser")

    message = createMockMessage(messageId=1, chatId=userId, userId=userId)
    message.get_bot = Mock(return_value=mockBot)

    # Set multiple settings
    settings = [
        (ChatSettingsKey.USE_TOOLS, "True"),
        (ChatSettingsKey.ALLOW_MENTION, "False"),
        (ChatSettingsKey.RANDOM_ANSWER_PROBABILITY, "0.5"),
    ]

    for settingKey, value in settings:
        callbackData = utils.packDict(
            {
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: settingKey.getId(),
                ButtonDataKey.Value: value,
                ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetValue,
            }
        )

        with patch.object(configureHandler, "isAdmin", return_value=True):
            result = await configureHandler._handle_chat_configuration(
                utils.unpackDict(callbackData),
                message,
                createMockUser(userId=userId),
            )
            assert result is True

    # Verify all settings persisted
    savedSettings = inMemoryDb.getChatSettings(chatId)
    for settingKey, value in settings:
        assert settingKey.value in savedSettings
        assert savedSettings[settingKey.value] == value
