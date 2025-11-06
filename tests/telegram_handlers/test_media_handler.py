"""
Comprehensive tests for MediaHandler, dood!

This module provides extensive test coverage for the MediaHandler class,
testing image generation, media analysis, and media content retrieval.

Test Categories:
- Initialization Tests: Handler setup and LLM tool registration
- Unit Tests: LLM tool handlers, message handlers
- Integration Tests: Complete command workflows (/analyze, /draw)
- Edge Cases: Error handling, permission checks, validation
"""

from unittest.mock import Mock, patch

import pytest
from telegram import Chat

from internal.bot.handlers.media import MediaHandler
from internal.bot.models import ChatSettingsKey, ChatSettingsValue, EnsuredMessage
from lib.ai.models import ModelResultStatus
from tests.fixtures.service_mocks import createMockDatabaseWrapper, createMockLlmManager
from tests.fixtures.telegram_mocks import (
    createMockBot,
    createMockContext,
    createMockMessage,
    createMockPhoto,
    createMockUpdate,
)
from tests.utils import createAsyncMock

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mockConfigManager():
    """Create a mock ConfigManager with media handler settings, dood!"""
    mock = Mock()
    mock.getBotConfig.return_value = {
        "token": "test_token",
        "bot_owners": ["owner1"],
        "defaults": {
            ChatSettingsKey.IMAGE_GENERATION_MODEL: "dall-e-3",
            ChatSettingsKey.IMAGE_GENERATION_FALLBACK_MODEL: "dall-e-2",
            ChatSettingsKey.IMAGE_PARSING_MODEL: "gpt-4-vision",
            ChatSettingsKey.ALLOW_MENTION: "true",
            ChatSettingsKey.FALLBACK_HAPPENED_PREFIX: "[Fallback] ",
        },
    }
    return mock


@pytest.fixture
def mockDatabase():
    """Create a mock DatabaseWrapper for media operations, dood!"""
    mock = createMockDatabaseWrapper()
    mock.getChatSettings.return_value = {}
    mock.getChatUser.return_value = None
    mock.getChatMessageByMessageId.return_value = None
    mock.getMediaAttachment.return_value = None
    mock.saveChatMessage = Mock()
    mock.updateChatUser = Mock()
    return mock


@pytest.fixture
def mockLlmManager():
    """Create a mock LLMManager with image models, dood!"""
    mock = createMockLlmManager()

    # Create mock image generation model
    mockImageModel = Mock()
    mockImageModel.generateImageWithFallBack = createAsyncMock(
        returnValue=Mock(
            status=ModelResultStatus.FINAL,
            mediaData=b"fake_image_data",
            resultText="Image generated",
            isFallback=False,
        )
    )

    # Create mock vision model
    mockVisionModel = Mock()
    mockVisionModel.generateText = createAsyncMock(
        returnValue=Mock(
            status=ModelResultStatus.FINAL,
            resultText="Image analysis result",
            error=None,
        )
    )

    mock._models = {
        "dall-e-3": mockImageModel,
        "dall-e-2": mockImageModel,
        "gpt-4-vision": mockVisionModel,
    }

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
        MockCache.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def mockQueueService():
    """Create a mock QueueService, dood!"""
    with patch("internal.bot.handlers.base.QueueService") as MockQueue:
        mockInstance = Mock()
        mockInstance.addBackgroundTask = createAsyncMock()
        MockQueue.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def mockLlmService():
    """Create a mock LLMService, dood!"""
    with patch("internal.bot.handlers.media.LLMService") as MockLLM:
        mockInstance = Mock()
        mockInstance.registerTool = Mock()
        mockInstance._tools = {}
        MockLLM.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def mediaHandler(mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockLlmService):
    """Create a MediaHandler instance with mocked dependencies, dood!"""
    handler = MediaHandler(mockConfigManager, mockDatabase, mockLlmManager)
    return handler


@pytest.fixture
def mockBot():
    """Create a mock bot instance, dood!"""
    bot = createMockBot()
    bot.get_file = createAsyncMock(
        returnValue=Mock(download_as_bytearray=createAsyncMock(returnValue=bytearray(b"fake_image_data")))
    )
    return bot


# ============================================================================
# Initialization Tests
# ============================================================================


class TestInitialization:
    """Test MediaHandler initialization, dood!"""

    def testInitWithAllDependencies(
        self, mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockLlmService
    ):
        """Test handler initializes correctly with all dependencies, dood!"""
        handler = MediaHandler(mockConfigManager, mockDatabase, mockLlmManager)

        assert handler.configManager == mockConfigManager
        assert handler.db == mockDatabase
        assert handler.llmManager == mockLlmManager
        assert handler.llmService is not None

    def testInitRegistersImageGenerationTool(
        self, mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockLlmService
    ):
        """Test image generation tool is registered during initialization, dood!"""
        MediaHandler(mockConfigManager, mockDatabase, mockLlmManager)

        # Verify tool was registered
        mockLlmService.registerTool.assert_called_once()
        call_args = mockLlmService.registerTool.call_args
        assert call_args[1]["name"] == "generate_and_send_image"
        # Check that parameters list contains image_prompt parameter
        params = call_args[1]["parameters"]
        param_names = [p.name for p in params]
        assert "image_prompt" in param_names


# ============================================================================
# Unit Tests - LLM Tool Handler
# ============================================================================


class TestLlmToolGenerateAndSendImage:
    """Test LLM tool for image generation, dood!"""

    def testGenerateAndSendImageMissingExtraData(self, mediaHandler):
        """Test error when extraData is missing, dood!"""
        with pytest.raises(RuntimeError, match="extraData should be provided"):
            import asyncio

            asyncio.run(mediaHandler._llmToolGenerateAndSendImage(extraData=None, image_prompt="Test"))

    def testGenerateAndSendImageMissingEnsuredMessage(self, mediaHandler):
        """Test error when ensuredMessage is missing, dood!"""
        with pytest.raises(RuntimeError, match="ensuredMessage should be provided"):
            import asyncio

            asyncio.run(mediaHandler._llmToolGenerateAndSendImage(extraData={}, image_prompt="Test"))


# ============================================================================
# Unit Tests - Message Handler ("что там")
# ============================================================================


class TestMessageHandler:
    """Test message handler for media content retrieval, dood!"""

    @pytest.mark.asyncio
    async def testMessageHandlerWhatThereWithMediaReply(self, mediaHandler, mockBot, mockDatabase, mockCacheService):
        """Test 'что там' retrieves media content from replied message, dood!"""
        mediaHandler.injectBot(mockBot)

        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.ALLOW_MENTION: ChatSettingsValue("true"),
            ChatSettingsKey.BOT_NICKNAMES: ChatSettingsValue("bot"),
        }

        # Create reply message with media
        replyMessage = createMockMessage(messageId=100, chatId=123, userId=456, text="")
        replyMessage.photo = [createMockPhoto()]

        # Create main message mentioning bot
        message = createMockMessage(messageId=101, chatId=123, userId=456, text="@test_bot что там")
        message.reply_to_message = replyMessage
        message.reply_text = createAsyncMock(returnValue=message)
        message.chat.type = Chat.PRIVATE

        # Mock database to return stored media content
        mockDatabase.getChatMessageByMessageId.return_value = {
            "message_id": 100,
            "chat_id": 123,
            "user_id": 456,
            "username": "testuser",
            "full_name": "Test User",
            "message_text": "",
            "message_type": "image",
            "message_category": "user",
            "date": "2024-01-01 00:00:00",
            "reply_id": None,
            "root_message_id": None,
            "thread_id": None,
            "quote_text": None,
            "media_id": "unique_photo_123",
            "media_content": "A beautiful landscape photo",
            "media_description": None,
            "media_prompt": None,
        }

        update = createMockUpdate(message=message)
        context = createMockContext()
        ensuredMessage = EnsuredMessage.fromMessage(message)

        from internal.bot.handlers.base import HandlerResultStatus

        result = await mediaHandler.messageHandler(update, context, ensuredMessage)

        assert result == HandlerResultStatus.FINAL
        message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def testMessageHandlerWhatThereWithTextReply(self, mediaHandler, mockBot, mockCacheService):
        """Test 'что там' with text reply delegates to next handler, dood!"""
        mediaHandler.injectBot(mockBot)

        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.ALLOW_MENTION: ChatSettingsValue("true"),
            ChatSettingsKey.BOT_NICKNAMES: ChatSettingsValue("bot"),
        }

        # Create text reply message
        replyMessage = createMockMessage(messageId=100, chatId=123, userId=456, text="Some text")

        message = createMockMessage(messageId=101, chatId=123, userId=456, text="@test_bot что там")
        message.reply_to_message = replyMessage
        message.reply_text = createAsyncMock(returnValue=message)
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        ensuredMessage = EnsuredMessage.fromMessage(message)

        from internal.bot.handlers.base import HandlerResultStatus

        result = await mediaHandler.messageHandler(update, context, ensuredMessage)

        assert result == HandlerResultStatus.NEXT

    @pytest.mark.asyncio
    async def testMessageHandlerWhatThereNonReply(self, mediaHandler, mockBot, mockCacheService):
        """Test 'что там' without reply returns error, dood!"""
        mediaHandler.injectBot(mockBot)

        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.ALLOW_MENTION: ChatSettingsValue("true"),
            ChatSettingsKey.BOT_NICKNAMES: ChatSettingsValue("bot"),
        }

        message = createMockMessage(messageId=101, chatId=123, userId=456, text="@test_bot что там")
        message.reply_to_message = None
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        ensuredMessage = EnsuredMessage.fromMessage(message)

        from internal.bot.handlers.base import HandlerResultStatus

        result = await mediaHandler.messageHandler(update, context, ensuredMessage)

        assert result == HandlerResultStatus.ERROR

    @pytest.mark.asyncio
    async def testMessageHandlerSkipsWithoutMention(self, mediaHandler, mockCacheService):
        """Test handler skips messages without bot mention, dood!"""
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.ALLOW_MENTION: ChatSettingsValue("true"),
        }

        message = createMockMessage(messageId=101, chatId=123, userId=456, text="что там")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        ensuredMessage = EnsuredMessage.fromMessage(message)

        from internal.bot.handlers.base import HandlerResultStatus

        result = await mediaHandler.messageHandler(update, context, ensuredMessage)

        assert result == HandlerResultStatus.SKIPPED

    @pytest.mark.asyncio
    async def testMessageHandlerSkipsWhenMentionDisabled(self, mediaHandler, mockCacheService):
        """Test handler skips when ALLOW_MENTION is disabled, dood!"""
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.ALLOW_MENTION: ChatSettingsValue("false"),
        }

        message = createMockMessage(messageId=101, chatId=123, userId=456, text="@test_bot что там")
        message.chat.type = Chat.PRIVATE

        update = createMockUpdate(message=message)
        context = createMockContext()
        ensuredMessage = EnsuredMessage.fromMessage(message)

        from internal.bot.handlers.base import HandlerResultStatus

        result = await mediaHandler.messageHandler(update, context, ensuredMessage)

        assert result == HandlerResultStatus.SKIPPED


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling, dood!"""

    @pytest.mark.asyncio
    async def testAnalyzeCommandWithoutMessage(self, mediaHandler, mockBot):
        """Test /analyze command handles missing message gracefully, dood!"""
        mediaHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await mediaHandler.analyze_command(update, context)

    @pytest.mark.asyncio
    async def testDrawCommandWithoutMessage(self, mediaHandler, mockBot):
        """Test /draw command handles missing message gracefully, dood!"""
        mediaHandler.injectBot(mockBot)

        update = createMockUpdate()
        update.message = None
        context = createMockContext()

        # Should not raise exception
        await mediaHandler.draw_command(update, context)

    @pytest.mark.asyncio
    async def testAnalyzeCommandEnsuredMessageError(self, mediaHandler, mockBot):
        """Test /analyze command handles EnsuredMessage creation error, dood!"""
        mediaHandler.injectBot(mockBot)

        message = createMockMessage(text="/analyze Test")
        message.chat = None  # This will cause EnsuredMessage.fromMessage to fail

        update = createMockUpdate(message=message)
        context = createMockContext()

        # Should not raise exception
        await mediaHandler.analyze_command(update, context)

    @pytest.mark.asyncio
    async def testDrawCommandEnsuredMessageError(self, mediaHandler, mockBot):
        """Test /draw command handles EnsuredMessage creation error, dood!"""
        mediaHandler.injectBot(mockBot)

        message = createMockMessage(text="/draw Test")
        message.chat = None  # This will cause EnsuredMessage.fromMessage to fail

        update = createMockUpdate(message=message)
        context = createMockContext()

        # Should not raise exception
        await mediaHandler.draw_command(update, context)

    @pytest.mark.asyncio
    async def testMessageHandlerNoneEnsuredMessage(self, mediaHandler):
        """Test message handler handles None ensuredMessage, dood!"""
        update = createMockUpdate()
        context = createMockContext()

        from internal.bot.handlers.base import HandlerResultStatus

        result = await mediaHandler.messageHandler(update, context, None)

        assert result == HandlerResultStatus.SKIPPED

    @pytest.mark.asyncio
    async def testMessageHandlerChannelChat(self, mediaHandler, mockCacheService):
        """Test message handler skips channel chats, dood!"""
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.ALLOW_MENTION: ChatSettingsValue("true"),
        }

        message = createMockMessage(messageId=101, chatId=123, userId=456, text="@test_bot что там")
        message.chat.type = Chat.CHANNEL

        update = createMockUpdate(message=message)
        context = createMockContext()
        ensuredMessage = EnsuredMessage.fromMessage(message)

        from internal.bot.handlers.base import HandlerResultStatus

        result = await mediaHandler.messageHandler(update, context, ensuredMessage)

        assert result == HandlerResultStatus.SKIPPED
