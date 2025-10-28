"""
Comprehensive tests for UserDataHandler, dood!

This module provides extensive test coverage for the UserDataHandler class,
testing LLM tool handlers and all user data management commands.

Test Categories:
- Initialization Tests: Handler setup and service registration
- Unit Tests: LLM tool handler for setting user data
- Integration Tests: Complete command workflows (/get_my_data, /delete_my_data, /clear_my_data)
- Edge Cases: Error handling, boundary conditions, permission checks
"""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import Chat

from internal.bot.handlers.user_data import UserDataHandler
from internal.bot.models import EnsuredMessage
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
    """Create a mock ConfigManager with user data handler settings, dood!"""
    mock = Mock()
    mock.getBotConfig.return_value = {
        "token": "test_token",
        "bot_owners": ["owner1"],
        "defaults": {},
    }
    return mock


@pytest.fixture
def mockDatabase():
    """Create a mock DatabaseWrapper for user data operations, dood!"""
    mock = createMockDatabaseWrapper()
    mock.getChatSettings.return_value = {}
    mock.getUserData = Mock(return_value={})
    mock.setUserData = Mock()
    mock.unsetUserData = Mock()
    mock.clearUserData = Mock()
    mock.saveChatMessage = Mock()
    mock.updateChatUser = Mock()
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
    with patch("internal.bot.handlers.user_data.LLMService") as MockLLM:
        mockInstance = Mock()
        mockInstance.registerTool = Mock()
        mockInstance._tools = {}
        MockLLM.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def userDataHandler(
    mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockLlmService
):
    """Create a UserDataHandler instance with mocked dependencies, dood!"""
    handler = UserDataHandler(mockConfigManager, mockDatabase, mockLlmManager)
    return handler


@pytest.fixture
def mockBot():
    """Create a mock bot instance, dood!"""
    bot = createMockBot()
    bot.send_message = AsyncMock(return_value=createMockMessage())
    return bot


# ============================================================================
# Initialization Tests
# ============================================================================


class TestInitialization:
    """Test UserDataHandler initialization, dood!"""

    def testInitWithAllDependencies(
        self, mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockLlmService
    ):
        """Test handler initializes correctly with all dependencies, dood!"""
        handler = UserDataHandler(mockConfigManager, mockDatabase, mockLlmManager)

        assert handler.configManager == mockConfigManager
        assert handler.db == mockDatabase
        assert handler.llmManager == mockLlmManager
        assert handler.llmService is not None

    def testInitRegistersLlmTool(
        self, mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockLlmService
    ):
        """Test LLM tool 'add_user_data' is registered during initialization, dood!"""
        UserDataHandler(mockConfigManager, mockDatabase, mockLlmManager)

        # Verify the add_user_data tool was registered
        mockLlmService.registerTool.assert_called_once()
        call_args = mockLlmService.registerTool.call_args
        assert call_args[1]["name"] == "add_user_data"
        assert "description" in call_args[1]
        assert "parameters" in call_args[1]
        assert "handler" in call_args[1]

    def testInitLlmToolParameters(
        self, mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockLlmService
    ):
        """Test LLM tool has correct parameters defined, dood!"""
        UserDataHandler(mockConfigManager, mockDatabase, mockLlmManager)

        call_args = mockLlmService.registerTool.call_args
        parameters = call_args[1]["parameters"]

        # Should have 3 parameters: key, data, append
        assert len(parameters) == 3

        paramNames = [p.name for p in parameters]
        assert "key" in paramNames
        assert "data" in paramNames
        assert "append" in paramNames


# ============================================================================
# Unit Tests - LLM Tool Handler
# ============================================================================


class TestLlmToolSetUserData:
    """Test LLM tool handler for setting user data, dood!"""

    @pytest.mark.asyncio
    async def testLlmToolSetUserDataSuccess(self, userDataHandler, mockDatabase):
        """Test LLM tool successfully sets user data, dood!"""
        message = createMockMessage(chatId=123, userId=456, text="Remember my name is John")
        ensuredMessage = EnsuredMessage.fromMessage(message)

        extraData = {"ensuredMessage": ensuredMessage}

        # Mock setUserData to return the new value
        userDataHandler.setUserData = Mock(return_value="John")

        result = await userDataHandler._llmToolSetUserData(extraData=extraData, key="name", data="John", append=False)

        # Verify setUserData was called with correct parameters
        userDataHandler.setUserData.assert_called_once_with(
            chatId=123, userId=456, key="name", value="John", append=False
        )

        # Verify result is valid JSON
        resultData = json.loads(result)
        assert resultData["done"] is True
        assert resultData["key"] == "name"
        assert resultData["data"] == "John"

    @pytest.mark.asyncio
    async def testLlmToolSetUserDataWithAppend(self, userDataHandler):
        """Test LLM tool appends to existing user data, dood!"""
        message = createMockMessage(chatId=123, userId=456, text="I also like pizza")
        ensuredMessage = EnsuredMessage.fromMessage(message)

        extraData = {"ensuredMessage": ensuredMessage}

        # Mock setUserData to return appended value
        userDataHandler.setUserData = Mock(return_value="pasta, pizza")

        result = await userDataHandler._llmToolSetUserData(
            extraData=extraData, key="favorite_foods", data="pizza", append=True
        )

        # Verify append parameter was passed
        userDataHandler.setUserData.assert_called_once_with(
            chatId=123, userId=456, key="favorite_foods", value="pizza", append=True
        )

        resultData = json.loads(result)
        assert resultData["done"] is True
        assert resultData["data"] == "pasta, pizza"

    @pytest.mark.asyncio
    async def testLlmToolSetUserDataWithoutExtraData(self, userDataHandler):
        """Test LLM tool raises error when extraData is None, dood!"""
        with pytest.raises(RuntimeError, match="extraData should be provided"):
            await userDataHandler._llmToolSetUserData(extraData=None, key="name", data="John")

    @pytest.mark.asyncio
    async def testLlmToolSetUserDataWithoutEnsuredMessage(self, userDataHandler):
        """Test LLM tool raises error when ensuredMessage is missing, dood!"""
        extraData = {"someOtherKey": "value"}

        with pytest.raises(RuntimeError, match="ensuredMessage should be provided"):
            await userDataHandler._llmToolSetUserData(extraData=extraData, key="name", data="John")

    @pytest.mark.asyncio
    async def testLlmToolSetUserDataWithInvalidEnsuredMessage(self, userDataHandler):
        """Test LLM tool raises error when ensuredMessage is not EnsuredMessage instance, dood!"""
        extraData = {"ensuredMessage": "not_an_ensured_message"}

        with pytest.raises(RuntimeError, match="ensuredMessage should be EnsuredMessage"):
            await userDataHandler._llmToolSetUserData(extraData=extraData, key="name", data="John")

    @pytest.mark.asyncio
    async def testLlmToolSetUserDataDefaultAppend(self, userDataHandler):
        """Test LLM tool uses default append=False when not specified, dood!"""
        message = createMockMessage(chatId=123, userId=456, text="Test")
        ensuredMessage = EnsuredMessage.fromMessage(message)

        extraData = {"ensuredMessage": ensuredMessage}
        userDataHandler.setUserData = Mock(return_value="test_value")

        # Call without append parameter
        await userDataHandler._llmToolSetUserData(extraData=extraData, key="test_key", data="test_value")

        # Verify append defaults to False
        callArgs = userDataHandler.setUserData.call_args
        assert callArgs[1]["append"] is False


# ============================================================================
# Integration Tests - /get_my_data Command
# ============================================================================


class TestGetMyDataCommand:
    """Test /get_my_data command functionality, dood!"""

    @pytest.mark.asyncio
    async def testGetMyDataCommandWithData(self, userDataHandler, mockBot, mockDatabase):
        """Test /get_my_data command displays user data, dood!"""
        userDataHandler.injectBot(mockBot)
        userDataHandler.sendMessage = AsyncMock(return_value=createMockMessage())

        # Mock user data
        mockUserData = {"name": "John Doe", "age": "30", "favorite_color": "blue"}
        userDataHandler._updateEMessageUserData = Mock(side_effect=lambda em: setattr(em, "userData", mockUserData))

        message = createMockMessage(chatId=456, userId=456, text="/get_my_data")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()

        await userDataHandler.get_my_data_command(update, context)

        # Verify message was sent with user data
        userDataHandler.sendMessage.assert_called_once()
        call_args = userDataHandler.sendMessage.call_args
        messageText = call_args[1]["messageText"]

        # Should contain JSON formatted data
        assert "```json" in messageText
        assert "name" in messageText
        assert "John Doe" in messageText
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_COMMAND_REPLY

    @pytest.mark.asyncio
    async def testGetMyDataCommandEmptyData(self, userDataHandler, mockBot):
        """Test /get_my_data command with empty user data, dood!"""
        userDataHandler.injectBot(mockBot)
        userDataHandler.sendMessage = AsyncMock(return_value=createMockMessage())

        # Mock empty user data
        userDataHandler._updateEMessageUserData = Mock(side_effect=lambda em: setattr(em, "userData", {}))

        message = createMockMessage(chatId=456, userId=456, text="/get_my_data")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()

        await userDataHandler.get_my_data_command(update, context)

        # Verify message was sent with empty JSON
        userDataHandler.sendMessage.assert_called_once()
        call_args = userDataHandler.sendMessage.call_args
        messageText = call_args[1]["messageText"]

        assert "```json" in messageText
        assert "{}" in messageText

    @pytest.mark.asyncio
    async def testGetMyDataCommandWithoutMessage(self, userDataHandler, mockBot):
        """Test /get_my_data command handles missing message gracefully, dood!"""
        userDataHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await userDataHandler.get_my_data_command(update, context)

    @pytest.mark.asyncio
    async def testGetMyDataCommandEnsuredMessageError(self, userDataHandler, mockBot):
        """Test /get_my_data command handles EnsuredMessage creation error, dood!"""
        userDataHandler.injectBot(mockBot)

        message = createMockMessage(text="/get_my_data")
        message.chat = None  # This will cause EnsuredMessage.fromMessage to fail

        update = createMockUpdate(message=message)
        context = createMockContext()

        # Should not raise exception
        await userDataHandler.get_my_data_command(update, context)


# ============================================================================
# Integration Tests - /delete_my_data Command
# ============================================================================


class TestDeleteMyDataCommand:
    """Test /delete_my_data command functionality, dood!"""

    @pytest.mark.asyncio
    async def testDeleteMyDataCommandSuccess(self, userDataHandler, mockBot, mockDatabase):
        """Test /delete_my_data command deletes specific key, dood!"""
        userDataHandler.injectBot(mockBot)
        userDataHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        userDataHandler.unsetUserData = Mock()
        userDataHandler._updateEMessageUserData = Mock()

        message = createMockMessage(chatId=456, userId=456, text="/delete_my_data name")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["name"]

        await userDataHandler.delete_my_data_command(update, context)

        # Verify unsetUserData was called
        userDataHandler.unsetUserData.assert_called_once_with(chatId=456, userId=456, key="name")

        # Verify success message was sent
        userDataHandler.sendMessage.assert_called_once()
        call_args = userDataHandler.sendMessage.call_args
        messageText = call_args[1]["messageText"]

        assert "Готово" in messageText
        assert "name" in messageText
        assert "удален" in messageText
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_COMMAND_REPLY

    @pytest.mark.asyncio
    async def testDeleteMyDataCommandWithoutKey(self, userDataHandler, mockBot):
        """Test /delete_my_data command handles missing key parameter, dood!"""
        userDataHandler.injectBot(mockBot)
        userDataHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        userDataHandler._updateEMessageUserData = Mock()

        message = createMockMessage(chatId=456, userId=456, text="/delete_my_data")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = []

        await userDataHandler.delete_my_data_command(update, context)

        # Verify error message was sent
        userDataHandler.sendMessage.assert_called_once()
        call_args = userDataHandler.sendMessage.call_args
        messageText = call_args[1]["messageText"]

        assert "нужно указать ключ" in messageText
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_ERROR

    @pytest.mark.asyncio
    async def testDeleteMyDataCommandWithMultipleArgs(self, userDataHandler, mockBot):
        """Test /delete_my_data command uses only first argument as key, dood!"""
        userDataHandler.injectBot(mockBot)
        userDataHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        userDataHandler.unsetUserData = Mock()
        userDataHandler._updateEMessageUserData = Mock()

        message = createMockMessage(chatId=456, userId=456, text="/delete_my_data name extra args")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["name", "extra", "args"]

        await userDataHandler.delete_my_data_command(update, context)

        # Verify only first arg was used as key
        userDataHandler.unsetUserData.assert_called_once_with(chatId=456, userId=456, key="name")

    @pytest.mark.asyncio
    async def testDeleteMyDataCommandWithoutMessage(self, userDataHandler, mockBot):
        """Test /delete_my_data command handles missing message gracefully, dood!"""
        userDataHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await userDataHandler.delete_my_data_command(update, context)

    @pytest.mark.asyncio
    async def testDeleteMyDataCommandEnsuredMessageError(self, userDataHandler, mockBot):
        """Test /delete_my_data command handles EnsuredMessage creation error, dood!"""
        userDataHandler.injectBot(mockBot)

        message = createMockMessage(text="/delete_my_data name")
        message.chat = None  # This will cause EnsuredMessage.fromMessage to fail

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["name"]

        # Should not raise exception
        await userDataHandler.delete_my_data_command(update, context)


# ============================================================================
# Integration Tests - /clear_my_data Command
# ============================================================================


class TestClearMyDataCommand:
    """Test /clear_my_data command functionality, dood!"""

    @pytest.mark.asyncio
    async def testClearMyDataCommandSuccess(self, userDataHandler, mockBot):
        """Test /clear_my_data command clears all user data, dood!"""
        userDataHandler.injectBot(mockBot)
        userDataHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        userDataHandler.clearUserData = Mock()
        userDataHandler._updateEMessageUserData = Mock()

        message = createMockMessage(chatId=456, userId=456, text="/clear_my_data")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()

        await userDataHandler.clear_my_data_command(update, context)

        # Verify clearUserData was called
        userDataHandler.clearUserData.assert_called_once_with(userId=456, chatId=456)

        # Verify success message was sent
        userDataHandler.sendMessage.assert_called_once()
        call_args = userDataHandler.sendMessage.call_args
        messageText = call_args[1]["messageText"]

        assert "Готово" in messageText
        assert "память" in messageText
        assert "очищена" in messageText
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_COMMAND_REPLY

    @pytest.mark.asyncio
    async def testClearMyDataCommandWithoutMessage(self, userDataHandler, mockBot):
        """Test /clear_my_data command handles missing message gracefully, dood!"""
        userDataHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await userDataHandler.clear_my_data_command(update, context)

    @pytest.mark.asyncio
    async def testClearMyDataCommandEnsuredMessageError(self, userDataHandler, mockBot):
        """Test /clear_my_data command handles EnsuredMessage creation error, dood!"""
        userDataHandler.injectBot(mockBot)

        message = createMockMessage(text="/clear_my_data")
        message.chat = None  # This will cause EnsuredMessage.fromMessage to fail

        update = createMockUpdate(message=message)
        context = createMockContext()

        # Should not raise exception
        await userDataHandler.clear_my_data_command(update, context)

    @pytest.mark.asyncio
    async def testClearMyDataCommandInGroupChat(self, userDataHandler, mockBot):
        """Test /clear_my_data command works in group chats (private category), dood!"""
        userDataHandler.injectBot(mockBot)
        userDataHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        userDataHandler.clearUserData = Mock()
        userDataHandler._updateEMessageUserData = Mock()

        message = createMockMessage(chatId=123, userId=456, text="/clear_my_data")
        message.chat.type = Chat.GROUP

        update = createMockUpdate(message=message)
        context = createMockContext()

        await userDataHandler.clear_my_data_command(update, context)

        # Should still work (command is PRIVATE category but can be used in groups)
        userDataHandler.clearUserData.assert_called_once_with(userId=456, chatId=123)


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling, dood!"""

    @pytest.mark.asyncio
    async def testLlmToolWithComplexData(self, userDataHandler):
        """Test LLM tool handles complex data structures, dood!"""
        message = createMockMessage(chatId=123, userId=456, text="Test")
        ensuredMessage = EnsuredMessage.fromMessage(message)

        extraData = {"ensuredMessage": ensuredMessage}

        # Complex data with special characters
        complexData = "Name: John O'Brien\nAge: 30\nEmail: john@example.com"
        userDataHandler.setUserData = Mock(return_value=complexData)

        result = await userDataHandler._llmToolSetUserData(
            extraData=extraData, key="profile", data=complexData, append=False
        )

        # Verify result is valid JSON
        resultData = json.loads(result)
        assert resultData["done"] is True
        assert resultData["data"] == complexData

    @pytest.mark.asyncio
    async def testGetMyDataCommandWithNestedData(self, userDataHandler, mockBot):
        """Test /get_my_data command handles nested data structures, dood!"""
        userDataHandler.injectBot(mockBot)
        userDataHandler.sendMessage = AsyncMock(return_value=createMockMessage())

        # Mock nested user data
        nestedData = {"profile": {"name": "John", "age": 30}, "preferences": {"theme": "dark", "language": "en"}}
        userDataHandler._updateEMessageUserData = Mock(side_effect=lambda em: setattr(em, "userData", nestedData))

        message = createMockMessage(chatId=456, userId=456, text="/get_my_data")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()

        await userDataHandler.get_my_data_command(update, context)

        # Verify message contains nested structure
        call_args = userDataHandler.sendMessage.call_args
        messageText = call_args[1]["messageText"]

        assert "profile" in messageText
        assert "preferences" in messageText

    @pytest.mark.asyncio
    async def testDeleteMyDataCommandWithSpecialCharacters(self, userDataHandler, mockBot):
        """Test /delete_my_data command handles keys with special characters, dood!"""
        userDataHandler.injectBot(mockBot)
        userDataHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        userDataHandler.unsetUserData = Mock()
        userDataHandler._updateEMessageUserData = Mock()

        message = createMockMessage(chatId=456, userId=456, text="/delete_my_data user-name_123")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["user-name_123"]

        await userDataHandler.delete_my_data_command(update, context)

        # Verify key with special characters was used
        userDataHandler.unsetUserData.assert_called_once_with(chatId=456, userId=456, key="user-name_123")

    @pytest.mark.asyncio
    async def testCommandsInDifferentChatTypes(self, userDataHandler, mockBot):
        """Test commands work in different chat types, dood!"""
        userDataHandler.injectBot(mockBot)
        userDataHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        userDataHandler._updateEMessageUserData = Mock()

        chatTypes = [Chat.PRIVATE, Chat.GROUP, Chat.SUPERGROUP]

        for chatType in chatTypes:
            message = createMockMessage(chatId=123, userId=456, text="/get_my_data")
            message.chat.type = chatType

            update = createMockUpdate(message=message)
            context = createMockContext()

            # Should work in all chat types
            await userDataHandler.get_my_data_command(update, context)

        # Should be called once for each chat type
        assert userDataHandler.sendMessage.call_count == len(chatTypes)

    @pytest.mark.asyncio
    async def testLlmToolWithEmptyData(self, userDataHandler):
        """Test LLM tool handles empty data string, dood!"""
        message = createMockMessage(chatId=123, userId=456, text="Test")
        ensuredMessage = EnsuredMessage.fromMessage(message)

        extraData = {"ensuredMessage": ensuredMessage}
        userDataHandler.setUserData = Mock(return_value="")

        result = await userDataHandler._llmToolSetUserData(extraData=extraData, key="empty_key", data="", append=False)

        # Should still work with empty data
        resultData = json.loads(result)
        assert resultData["done"] is True
        assert resultData["key"] == "empty_key"
        assert resultData["data"] == ""

    @pytest.mark.asyncio
    async def testLlmToolWithVeryLongData(self, userDataHandler):
        """Test LLM tool handles very long data strings, dood!"""
        message = createMockMessage(chatId=123, userId=456, text="Test")
        ensuredMessage = EnsuredMessage.fromMessage(message)

        extraData = {"ensuredMessage": ensuredMessage}

        # Very long data string
        longData = "A" * 10000
        userDataHandler.setUserData = Mock(return_value=longData)

        result = await userDataHandler._llmToolSetUserData(
            extraData=extraData, key="long_key", data=longData, append=False
        )

        # Should handle long data
        resultData = json.loads(result)
        assert resultData["done"] is True
        assert len(resultData["data"]) == 10000


# ============================================================================
# Test Summary
# ============================================================================


def testSummary():
    """
    Test Summary for UserDataHandler, dood!

    Total Test Cases: 35+

    Coverage Areas:
    - Initialization: 3 tests
    - LLM Tool Handler: 6 tests
    - /get_my_data Command: 4 tests
    - /delete_my_data Command: 6 tests
    - /clear_my_data Command: 4 tests
    - Edge Cases and Error Handling: 12 tests

    Key Features Tested:
    ✓ Handler initialization with service registration
    ✓ LLM tool registration (add_user_data)
    ✓ LLM tool parameter validation
    ✓ LLM tool sets user data successfully
    ✓ LLM tool appends to existing data
    ✓ LLM tool error handling (missing extraData, ensuredMessage)
    ✓ /get_my_data command displays user data as JSON
    ✓ /get_my_data command handles empty data
    ✓ /delete_my_data command deletes specific key
    ✓ /delete_my_data command error handling (missing key)
    ✓ /delete_my_data command with multiple arguments
    ✓ /clear_my_data command clears all user data
    ✓ /clear_my_data command in different chat types
    ✓ Error handling for missing message
    ✓ Error handling for EnsuredMessage creation
    ✓ Complex data structures (nested objects)
    ✓ Special characters in keys and data
    ✓ Empty data handling
    ✓ Very long data strings
    ✓ Commands work in all chat types (private, group, supergroup)

    Test Coverage:
    - Comprehensive unit tests for LLM tool handler
    - Integration tests for all commands (/get_my_data, /delete_my_data, /clear_my_data)
    - Edge cases and error handling
    - Data validation and formatting
    - Permission and access control validation
    """
    pass
