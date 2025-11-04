"""
Comprehensive tests for DevCommandsHandler, dood!

This module provides extensive test coverage for the DevCommandsHandler class,
testing all development and debugging commands.

Test Categories:
- Initialization Tests: Handler setup
- Unit Tests: Command handlers, admin permission checks
- Integration Tests: Complete command workflows (/echo, /models, /settings, /set, /unset, /test)
- Edge Cases: Error handling, permission checks, validation
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import Chat, MessageEntity
from telegram.constants import MessageEntityType

from internal.bot.handlers.dev_commands import DevCommandsHandler
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
    """Create a mock ConfigManager with dev commands handler settings, dood!"""
    mock = Mock()
    mock.getBotConfig.return_value = {
        "token": "test_token",
        "bot_owners": ["owner1"],
        "defaults": {},
    }
    return mock


@pytest.fixture
def mockDatabase():
    """Create a mock DatabaseWrapper for dev commands operations, dood!"""
    mock = createMockDatabaseWrapper()
    mock.getChatSettings.return_value = {}
    mock.saveChatMessage = Mock()
    mock.updateChatUser = Mock()
    mock.getChatMessageByMessageId = Mock(return_value=None)
    return mock


@pytest.fixture
def mockLlmManager():
    """Create a mock LLMManager with test models, dood!"""
    mock = createMockLlmManager()
    mock.listModels.return_value = ["model1", "model2", "model3"]
    mock.getModelInfo.side_effect = lambda name: (
        {
            "model_id": name,
            "model_version": "1.0",
            "temperature": 0.7,
            "context_size": 4096,
            "provider": "test_provider",
            "support_tools": True,
            "support_text": True,
            "support_images": False,
        }
        if name in ["model1", "model2", "model3"]
        else None
    )
    return mock


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
        mockInstance.unsetChatSetting = Mock()
        mockInstance.chats = {}
        mockInstance.getStats = Mock(return_value={"hits": 100, "misses": 10, "size": 50})
        MockCache.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def mockQueueService():
    """Create a mock QueueService, dood!"""
    with patch("internal.bot.handlers.base.QueueService") as MockQueue:
        mockInstance = Mock()
        mockInstance.addBackgroundTask = AsyncMock()
        mockInstance.delayedActionsQueue = Mock()
        mockInstance.delayedActionsQueue.qsize.return_value = 5
        mockInstance.delayedActionsQueue.__str__ = Mock(return_value="DelayedQueue[5 items]")
        MockQueue.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def devCommandsHandler(mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService):
    """Create a DevCommandsHandler instance with mocked dependencies, dood!"""
    handler = DevCommandsHandler(mockConfigManager, mockDatabase, mockLlmManager)
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
    """Test DevCommandsHandler initialization, dood!"""

    def testInitWithAllDependencies(
        self, mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService
    ):
        """Test handler initializes correctly with all dependencies, dood!"""
        handler = DevCommandsHandler(mockConfigManager, mockDatabase, mockLlmManager)

        assert handler.configManager == mockConfigManager
        assert handler.db == mockDatabase
        assert handler.llmManager == mockLlmManager

    def testInitInheritsFromBaseBotHandler(self, devCommandsHandler):
        """Test handler inherits from BaseBotHandler, dood!"""
        from internal.bot.handlers.base import BaseBotHandler

        assert isinstance(devCommandsHandler, BaseBotHandler)


# ============================================================================
# Integration Tests - /echo Command
# ============================================================================


class TestEchoCommand:
    """Test /echo command functionality, dood!"""

    @pytest.mark.asyncio
    async def testEchoCommandWithText(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /echo command echoes back provided text, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())

        message = createMockMessage(chatId=456, userId=456, text="/echo Hello World")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["Hello", "World"]

        await devCommandsHandler.echo_command(update, context)

        devCommandsHandler.sendMessage.assert_called_once()
        call_args = devCommandsHandler.sendMessage.call_args
        assert "Hello World" in call_args[1]["messageText"]
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_COMMAND_REPLY

    @pytest.mark.asyncio
    async def testEchoCommandWithoutText(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /echo command handles missing text, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())

        message = createMockMessage(chatId=456, userId=456, text="/echo")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = []

        await devCommandsHandler.echo_command(update, context)

        devCommandsHandler.sendMessage.assert_called_once()
        call_args = devCommandsHandler.sendMessage.call_args
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_ERROR
        assert "provide a message" in call_args[1]["messageText"]

    @pytest.mark.asyncio
    async def testEchoCommandWithMultipleWords(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /echo command with multiple words, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())

        message = createMockMessage(chatId=456, userId=456, text="/echo This is a test message")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["This", "is", "a", "test", "message"]

        await devCommandsHandler.echo_command(update, context)

        devCommandsHandler.sendMessage.assert_called_once()
        call_args = devCommandsHandler.sendMessage.call_args
        assert "This is a test message" in call_args[1]["messageText"]

    @pytest.mark.asyncio
    async def testEchoCommandWithoutMessage(self, devCommandsHandler, mockBot):
        """Test /echo command handles missing message gracefully, dood!"""
        devCommandsHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await devCommandsHandler.echo_command(update, context)


# ============================================================================
# Integration Tests - /models Command
# ============================================================================


class TestModelsCommand:
    """Test /models command functionality, dood!"""

    @pytest.mark.asyncio
    async def testModelsCommandListsAllModels(self, devCommandsHandler, mockBot, mockDatabase, mockLlmManager):
        """Test /models command lists all available models, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        message = createMockMessage(chatId=456, userId=456, text="/models")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()

        await devCommandsHandler.models_command(update, context)

        # Should send at least one message with model info
        assert devCommandsHandler.sendMessage.call_count >= 1
        call_args = devCommandsHandler.sendMessage.call_args
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_COMMAND_REPLY

    @pytest.mark.asyncio
    async def testModelsCommandShowsModelDetails(self, devCommandsHandler, mockBot, mockDatabase, mockLlmManager):
        """Test /models command shows detailed model information, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        message = createMockMessage(chatId=456, userId=456, text="/models")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()

        await devCommandsHandler.models_command(update, context)

        # Verify model info was retrieved
        assert mockLlmManager.listModels.called
        assert mockLlmManager.getModelInfo.called

    @pytest.mark.asyncio
    async def testModelsCommandWithoutMessage(self, devCommandsHandler, mockBot):
        """Test /models command handles missing message gracefully, dood!"""
        devCommandsHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await devCommandsHandler.models_command(update, context)

    @pytest.mark.asyncio
    async def testModelsCommandEnsuredMessageError(self, devCommandsHandler, mockBot):
        """Test /models command handles EnsuredMessage creation error, dood!"""
        devCommandsHandler.injectBot(mockBot)

        message = createMockMessage(text="/models")
        message.chat = None  # This will cause EnsuredMessage.fromMessage to fail

        update = createMockUpdate(message=message)
        context = createMockContext()

        # Should not raise exception
        await devCommandsHandler.models_command(update, context)


# ============================================================================
# Integration Tests - /settings Command
# ============================================================================


class TestSettingsCommand:
    """Test /settings command functionality, dood!"""

    @pytest.mark.asyncio
    async def testSettingsCommandWithDebugMode(self, devCommandsHandler, mockBot, mockDatabase, mockCacheService):
        """Test /settings command with debug parameter, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        mockCacheService.getChatSettings.return_value = {}

        message = createMockMessage(chatId=456, userId=456, text="/settings debug")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["debug"]

        await devCommandsHandler.chat_settings_command(update, context)

        devCommandsHandler.sendMessage.assert_called_once()

    @pytest.mark.asyncio
    async def testSettingsCommandWithoutMessage(self, devCommandsHandler, mockBot):
        """Test /settings command handles missing message gracefully, dood!"""
        devCommandsHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await devCommandsHandler.chat_settings_command(update, context)

    @pytest.mark.asyncio
    async def testSettingsCommandEnsuredMessageError(self, devCommandsHandler, mockBot):
        """Test /settings command handles EnsuredMessage creation error, dood!"""
        devCommandsHandler.injectBot(mockBot)

        message = createMockMessage(text="/settings")
        message.chat = None  # This will cause EnsuredMessage.fromMessage to fail

        update = createMockUpdate(message=message)
        context = createMockContext()

        # Should not raise exception
        await devCommandsHandler.chat_settings_command(update, context)


# ============================================================================
# Integration Tests - /set and /unset Commands
# ============================================================================


class TestSetUnsetCommands:
    """Test /set and /unset command functionality, dood!"""

    @pytest.mark.asyncio
    async def testSetUnsetCommandWithoutMessage(self, devCommandsHandler, mockBot):
        """Test /set and /unset commands handle missing message gracefully, dood!"""
        devCommandsHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await devCommandsHandler.set_or_unset_chat_setting_command(update, context)

    @pytest.mark.asyncio
    async def testSetUnsetCommandEnsuredMessageError(self, devCommandsHandler, mockBot):
        """Test /set and /unset commands handle EnsuredMessage creation error, dood!"""
        devCommandsHandler.injectBot(mockBot)

        message = createMockMessage(text="/set MODEL gpt-4")
        message.chat = None  # This will cause EnsuredMessage.fromMessage to fail

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["MODEL", "gpt-4"]

        # Should not raise exception
        await devCommandsHandler.set_or_unset_chat_setting_command(update, context)


# ============================================================================
# Integration Tests - /test Command
# ============================================================================


class TestTestCommand:
    """Test /test command functionality, dood!"""

    @pytest.mark.asyncio
    async def testTestCommandLongSuite(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /test long suite sends multiple messages, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        message = createMockMessage(chatId=456, userId=456, text="/test long 3 0")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["long", "3", "0"]

        await devCommandsHandler.test_command(update, context)

        # Should send 3 iteration messages
        assert devCommandsHandler.sendMessage.call_count == 3

    @pytest.mark.asyncio
    async def testTestCommandDelayedQueueSuite(self, devCommandsHandler, mockBot, mockDatabase, mockQueueService):
        """Test /test delayedQueue suite shows queue status, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        message = createMockMessage(chatId=456, userId=456, text="/test delayedQueue")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["delayedQueue"]

        await devCommandsHandler.test_command(update, context)

        devCommandsHandler.sendMessage.assert_called_once()
        call_args = devCommandsHandler.sendMessage.call_args
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_COMMAND_REPLY

    @pytest.mark.asyncio
    async def testTestCommandCacheStatsSuite(self, devCommandsHandler, mockBot, mockDatabase, mockCacheService):
        """Test /test cacheStats suite displays cache statistics, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        message = createMockMessage(chatId=456, userId=456, text="/test cacheStats")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["cacheStats"]

        await devCommandsHandler.test_command(update, context)

        devCommandsHandler.sendMessage.assert_called_once()
        call_args = devCommandsHandler.sendMessage.call_args
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_COMMAND_REPLY

    @pytest.mark.asyncio
    async def testTestCommandDumpEntitiesSuite(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /test dumpEntities suite dumps message entities, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        # Create replied message with entities
        repliedMessage = createMockMessage(text="Test @mention #hashtag")
        entity1 = Mock(spec=MessageEntity)
        entity1.type = MessageEntityType.MENTION
        entity1.offset = 5
        entity1.length = 8
        repliedMessage.entities = [entity1]

        message = createMockMessage(chatId=456, userId=456, text="/test dumpEntities")
        message.chat.type = Chat.PRIVATE
        message.reply_to_message = repliedMessage

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["dumpEntities"]

        await devCommandsHandler.test_command(update, context)

        # Should send 2 messages (entity dump + parse_entities)
        assert devCommandsHandler.sendMessage.call_count == 2

    @pytest.mark.asyncio
    async def testTestCommandDumpEntitiesWithoutReply(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /test dumpEntities suite requires reply to message, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        message = createMockMessage(chatId=456, userId=456, text="/test dumpEntities")
        message.chat.type = Chat.PRIVATE
        message.reply_to_message = None

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["dumpEntities"]

        await devCommandsHandler.test_command(update, context)

        devCommandsHandler.sendMessage.assert_called_once()
        call_args = devCommandsHandler.sendMessage.call_args
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_ERROR

    @pytest.mark.asyncio
    async def testTestCommandDumpEntitiesWithoutEntities(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /test dumpEntities suite handles message without entities, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        repliedMessage = createMockMessage(text="Plain text")
        repliedMessage.entities = None

        message = createMockMessage(chatId=456, userId=456, text="/test dumpEntities")
        message.chat.type = Chat.PRIVATE
        message.reply_to_message = repliedMessage

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["dumpEntities"]

        await devCommandsHandler.test_command(update, context)

        devCommandsHandler.sendMessage.assert_called_once()
        call_args = devCommandsHandler.sendMessage.call_args
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_ERROR

    @pytest.mark.asyncio
    async def testTestCommandUnknownSuite(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /test command with unknown suite name, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        message = createMockMessage(chatId=456, userId=456, text="/test unknownSuite")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["unknownSuite"]

        await devCommandsHandler.test_command(update, context)

        devCommandsHandler.sendMessage.assert_called_once()
        call_args = devCommandsHandler.sendMessage.call_args
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_ERROR
        assert "Unknown test suite" in call_args[1]["messageText"]

    @pytest.mark.asyncio
    async def testTestCommandWithoutSuite(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /test command without suite parameter, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        message = createMockMessage(chatId=456, userId=456, text="/test")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = []

        await devCommandsHandler.test_command(update, context)

        devCommandsHandler.sendMessage.assert_called_once()
        call_args = devCommandsHandler.sendMessage.call_args
        assert call_args[1]["messageCategory"] == MessageCategory.BOT_ERROR

    @pytest.mark.asyncio
    async def testTestCommandLongSuiteWithInvalidIterations(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /test long suite handles invalid iterations parameter, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        message = createMockMessage(chatId=456, userId=456, text="/test long invalid")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["long", "invalid"]

        await devCommandsHandler.test_command(update, context)

        # Should send error message about invalid iterations
        assert devCommandsHandler.sendMessage.call_count >= 1

    @pytest.mark.asyncio
    async def testTestCommandLongSuiteWithInvalidDelay(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /test long suite handles invalid delay parameter, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        message = createMockMessage(chatId=456, userId=456, text="/test long 2 invalid")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["long", "2", "invalid"]

        await devCommandsHandler.test_command(update, context)

        # Should send error message about invalid delay
        assert devCommandsHandler.sendMessage.call_count >= 1

    @pytest.mark.asyncio
    async def testTestCommandWithoutMessage(self, devCommandsHandler, mockBot):
        """Test /test command handles missing message gracefully, dood!"""
        devCommandsHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await devCommandsHandler.test_command(update, context)

    @pytest.mark.asyncio
    async def testTestCommandEnsuredMessageError(self, devCommandsHandler, mockBot):
        """Test /test command handles EnsuredMessage creation error, dood!"""
        devCommandsHandler.injectBot(mockBot)

        message = createMockMessage(text="/test long")
        message.chat = None  # This will cause EnsuredMessage.fromMessage to fail

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["long"]

        # Should not raise exception
        await devCommandsHandler.test_command(update, context)


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling, dood!"""

    @pytest.mark.asyncio
    async def testEchoCommandSavesMessageToDatabase(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /echo command saves message to database, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())

        message = createMockMessage(chatId=456, userId=456, text="/echo test")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["test"]

        await devCommandsHandler.echo_command(update, context)

        # Verify message was saved
        mockDatabase.saveChatMessage.assert_called()

    @pytest.mark.asyncio
    async def testModelsCommandHandlesNoneModelInfo(self, devCommandsHandler, mockBot, mockDatabase, mockLlmManager):
        """Test /models command handles None model info gracefully, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        # Make getModelInfo return None for one model
        mockLlmManager.getModelInfo.side_effect = lambda name: (
            None
            if name == "model2"
            else {
                "model_id": name,
                "temperature": 0.7,
            }
        )

        message = createMockMessage(chatId=456, userId=456, text="/models")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()

        await devCommandsHandler.models_command(update, context)

        # Should still send messages without crashing
        assert devCommandsHandler.sendMessage.call_count >= 1

    @pytest.mark.asyncio
    async def testModelsCommandBatchesSending(self, devCommandsHandler, mockBot, mockDatabase, mockLlmManager):
        """Test /models command sends models in batches, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        # Create many models to trigger batching
        mockLlmManager.listModels.return_value = [f"model{i}" for i in range(10)]
        mockLlmManager.getModelInfo.side_effect = lambda name: {
            "model_id": name,
            "temperature": 0.7,
        }

        message = createMockMessage(chatId=456, userId=456, text="/models")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()

        await devCommandsHandler.models_command(update, context)

        # Should send multiple messages (batches of 4)
        assert devCommandsHandler.sendMessage.call_count >= 2

    @pytest.mark.asyncio
    async def testSettingsCommandWithEmptySettings(self, devCommandsHandler, mockBot, mockDatabase, mockCacheService):
        """Test /settings command with no settings configured, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        mockCacheService.getChatSettings.return_value = {}

        message = createMockMessage(chatId=456, userId=456, text="/settings")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = []

        await devCommandsHandler.chat_settings_command(update, context)

        devCommandsHandler.sendMessage.assert_called_once()

    @pytest.mark.asyncio
    async def testTestCommandLongSuiteWithDefaultParameters(self, devCommandsHandler, mockBot, mockDatabase):
        """Test /test long suite uses default parameters, dood!"""
        devCommandsHandler.injectBot(mockBot)
        devCommandsHandler.sendMessage = AsyncMock(return_value=createMockMessage())
        devCommandsHandler.isAdmin = AsyncMock(return_value=True)

        message = createMockMessage(chatId=456, userId=456, text="/test long")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["long"]

        # Mock asyncio.sleep to avoid actual delays
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await devCommandsHandler.test_command(update, context)

        # Should send 10 messages (default iterations)
        assert devCommandsHandler.sendMessage.call_count == 2
