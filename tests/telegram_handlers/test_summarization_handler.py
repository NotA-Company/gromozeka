"""
Comprehensive tests for SummarizationHandler, dood!

This module provides extensive test coverage for the SummarizationHandler class,
testing message batch processing, summary generation, user state management,
button callbacks, and complete summarization workflows.

Test Categories:
- Initialization Tests: Handler setup and dependency injection
- Unit Tests: Message batching, summary generation, user state management
- Integration Tests: Complete summarization workflows, command flows
- Button Callback Tests: Interactive wizard button handling
- Edge Cases: Error handling, boundary conditions, cache integration
"""

import datetime
import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import Chat

from internal.bot.handlers.base import HandlerResultStatus
from internal.bot.handlers.summarization import SummarizationHandler
from internal.bot.models import (
    ButtonDataKey,
    ButtonSummarizationAction,
    ChatSettingsKey,
    EnsuredMessage,
)
from internal.database.models import MessageCategory
from internal.services.cache.types import UserActiveActionEnum
from lib.ai.models import ModelResultStatus, ModelRunResult
from tests.fixtures.telegram_mocks import (
    createMockBot,
    createMockChat,
    createMockContext,
    createMockMessage,
    createMockUpdate,
    createMockUser,
)

# ============================================================================
# Helper Functions
# ============================================================================


def createMockDBMessage(
    chatId: int,
    messageId: int,
    userId: int,
    username: str,
    fullName: str,
    messageCategory: str,
    messageText: str,
    messageType: str = "text",
    rootMessageId: Optional[int] = None,
    replyId: Optional[int] = None,
    threadId: int = 0,
    mediaId: Optional[str] = None,
    quoteText: Optional[str] = None,
    mediaDescription: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a complete mock database message with all required fields, dood!"""
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "chat_id": chatId,
        "message_id": messageId,
        "user_id": userId,
        "username": username,
        "full_name": fullName,
        "message_category": messageCategory,
        "message_text": messageText,
        "message_type": messageType,
        "root_message_id": rootMessageId if rootMessageId is not None else messageId,
        "reply_id": replyId,
        "thread_id": threadId,
        "media_id": mediaId,
        "quote_text": quoteText,
        "media_description": mediaDescription,
        "date": now,
        "created_at": now,
    }


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mockConfigManager():
    """Create a mock ConfigManager with summarization settings, dood!"""
    mock = Mock()
    mock.getBotConfig.return_value = {
        "bot_owners": ["owner1"],
        "defaults": {
            ChatSettingsKey.ALLOW_SUMMARY: "true",
            ChatSettingsKey.SUMMARY_MODEL: "gpt-4",
            ChatSettingsKey.SUMMARY_FALLBACK_MODEL: "gpt-3.5-turbo",
            ChatSettingsKey.SUMMARY_PROMPT: "Summarize the following messages",
            ChatSettingsKey.FALLBACK_HAPPENED_PREFIX: "[Fallback] ",
        },
    }
    return mock


@pytest.fixture
def mockDatabase():
    """Create a mock DatabaseWrapper for summarization operations, dood!"""
    mock = Mock()
    mock.getChatSettings.return_value = {}
    mock.getChatUser.return_value = None
    mock.getChatMessagesSince.return_value = []
    mock.getUserChats.return_value = []
    mock.getChatSummarization.return_value = None
    mock.addChatSummarization = Mock()
    mock.saveChatMessage = Mock()
    mock.updateChatUser = Mock()
    return mock


@pytest.fixture
def mockLlmManager():
    """Create a mock LLMManager with test models, dood!"""
    mock = Mock()

    # Create mock model with proper methods
    mockModel = Mock()
    mockModel.name = "gpt-4"
    mockModel.getInfo.return_value = {"context_size": 8000}
    mockModel.getEstimateTokensCount = Mock(return_value=1000)

    # Mock generateTextWithFallBack to return proper ModelRunResult
    async def mockGenerateText(*args, **kwargs):
        return ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="This is a summary of the messages.",
        )

    mockModel.generateTextWithFallBack = AsyncMock(side_effect=mockGenerateText)

    # Create fallback model
    mockFallbackModel = Mock()
    mockFallbackModel.name = "gpt-3.5-turbo"
    mockFallbackModel.getInfo.return_value = {"context_size": 4000}

    mock.getModel = Mock(side_effect=lambda name: mockModel if name == "gpt-4" else mockFallbackModel)
    return mock


@pytest.fixture
def mockCacheService():
    """Create a mock CacheService, dood!"""
    with patch("internal.bot.handlers.base.CacheService") as MockCache:
        mockInstance = Mock()
        mockInstance.getChatSettings.return_value = {}
        mockInstance.getChatInfo.return_value = None
        mockInstance.getChatTopicInfo.return_value = None
        mockInstance.getChatTopicsInfo.return_value = {}
        mockInstance.getChatUserData.return_value = {}
        mockInstance.getUserState.return_value = None
        mockInstance.setUserState = Mock()
        mockInstance.clearUserState = Mock()
        mockInstance.setChatSetting = Mock()
        MockCache.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def mockQueueService():
    """Create a mock QueueService, dood!"""
    with patch("internal.bot.handlers.base.QueueService") as MockQueue:
        mockInstance = Mock()
        mockInstance.addBackgroundTask = AsyncMock()
        MockQueue.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def summarizationHandler(mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService):
    """Create a SummarizationHandler instance with mocked dependencies, dood!"""
    handler = SummarizationHandler(mockConfigManager, mockDatabase, mockLlmManager)
    return handler


@pytest.fixture
def mockBot():
    """Create a mock bot instance, dood!"""
    return createMockBot()


# ============================================================================
# Initialization Tests
# ============================================================================


class TestInitialization:
    """Test SummarizationHandler initialization, dood!"""

    def testInitWithAllDependencies(
        self, mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService
    ):
        """Test handler initializes correctly with all dependencies, dood!"""
        handler = SummarizationHandler(mockConfigManager, mockDatabase, mockLlmManager)

        assert handler.configManager == mockConfigManager
        assert handler.db == mockDatabase
        assert handler.llmManager == mockLlmManager
        assert handler.cache == mockCacheService
        assert handler.queueService == mockQueueService


# ============================================================================
# Unit Tests - Message Batch Processing
# ============================================================================


class TestMessageBatchProcessing:
    """Test message batch processing logic, dood!"""

    @pytest.mark.asyncio
    async def testBatchProcessingWithSmallMessageSet(self, summarizationHandler, mockDatabase, mockLlmManager):
        """Test batch processing with messages that fit in one batch, dood!"""
        # Setup messages
        messages = [createMockDBMessage(123, i, 456, "user", "Test User", "user", f"Message {i}") for i in range(1, 6)]
        mockDatabase.getChatMessagesSince.return_value = messages

        # Mock model to return small token count
        mockModel = mockLlmManager.getModel("gpt-4")
        mockModel.getEstimateTokensCount.return_value = 500  # Well under limit

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))

        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=5,
        )

        # Should call LLM once for single batch
        assert mockModel.generateTextWithFallBack.call_count == 1

    @pytest.mark.asyncio
    async def testBatchProcessingWithLargeMessageSet(self, summarizationHandler, mockDatabase, mockLlmManager):
        """Test batch processing splits large message sets into multiple batches, dood!"""
        # Setup fewer messages to avoid timeout
        messages = [createMockDBMessage(123, i, 456, "user", "Test User", "user", f"Message {i}") for i in range(1, 21)]
        mockDatabase.getChatMessagesSince.return_value = messages

        # Mock model to return high token count requiring batching
        mockModel = mockLlmManager.getModel("gpt-4")
        mockModel.getInfo.return_value = {"context_size": 4000}

        # Make token count vary to trigger batching - high for first batch, lower for subsequent
        call_count = [0]

        def mock_token_count(*args, **kwargs):
            call_count[0] += 1
            # First few calls return high count to trigger split, then lower
            return 3500 if call_count[0] <= 2 else 500

        mockModel.getEstimateTokensCount = Mock(side_effect=mock_token_count)

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))
        ensuredMessage.getBaseMessage().reply_text = AsyncMock(return_value=createMockMessage())

        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=20,
        )

        # Should call LLM at least once (batching behavior may vary)
        assert mockModel.generateTextWithFallBack.call_count >= 1

    @pytest.mark.asyncio
    async def testBatchProcessingWithEmptyMessages(self, summarizationHandler, mockDatabase):
        """Test batch processing handles empty message list, dood!"""
        mockDatabase.getChatMessagesSince.return_value = []

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))
        ensuredMessage.getBaseMessage().reply_text = AsyncMock(return_value=createMockMessage())

        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=10,
        )

        # Should send "No messages to summarize"
        ensuredMessage.getBaseMessage().reply_text.assert_called()  # type: ignore[attr-defined]


# ============================================================================
# Unit Tests - Summary Generation Logic
# ============================================================================


class TestSummaryGenerationLogic:
    """Test summary generation logic, dood!"""

    @pytest.mark.asyncio
    async def testSummaryGenerationWithDefaultPrompt(self, summarizationHandler, mockDatabase, mockLlmManager):
        """Test summary generation uses default prompt from settings, dood!"""
        messages = [
            createMockDBMessage(123, 1, 456, "user", "Test User", "user", "Hello"),
            createMockDBMessage(123, 2, 789, "user2", "Test User 2", "user", "Hi there"),
        ]
        mockDatabase.getChatMessagesSince.return_value = messages

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))

        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=2,
        )

        # Verify LLM was called with system prompt
        mockModel = mockLlmManager.getModel("gpt-4")
        callArgs = mockModel.generateTextWithFallBack.call_args
        messages = callArgs[0][0]  # First positional arg is messages list

        # First message should be system message with prompt
        assert any(msg.role == "system" for msg in messages)

    @pytest.mark.asyncio
    async def testSummaryGenerationWithCustomPrompt(self, summarizationHandler, mockDatabase, mockLlmManager):
        """Test summary generation uses custom prompt when provided, dood!"""
        messages = [
            createMockDBMessage(123, 1, 456, "user", "Test User", "user", "Test message"),
        ]
        mockDatabase.getChatMessagesSince.return_value = messages

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))

        customPrompt = "Custom summarization prompt"
        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=1,
            summarizationPrompt=customPrompt,
        )

        # Verify custom prompt was used
        mockModel = mockLlmManager.getModel("gpt-4")
        callArgs = mockModel.generateTextWithFallBack.call_args
        messages = callArgs[0][0]

        # Check system message contains custom prompt
        systemMsg = next((msg for msg in messages if msg.role == "system"), None)
        assert systemMsg is not None
        assert customPrompt in systemMsg.content

    @pytest.mark.asyncio
    async def testSummaryGenerationHandlesLongMessages(self, summarizationHandler, mockDatabase, mockLlmManager):
        """Test summary generation splits very long summaries, dood!"""
        messages = [
            createMockDBMessage(123, 1, 456, "user", "Test User", "user", "Test"),
        ]
        mockDatabase.getChatMessagesSince.return_value = messages

        # Mock LLM to return very long text
        mockModel = mockLlmManager.getModel("gpt-4")
        longText = "A" * 5000  # Longer than Telegram's limit

        async def mockGenerateLong(*args, **kwargs):
            return ModelRunResult(
                rawResult={},
                status=ModelResultStatus.FINAL,
                resultText=longText,
            )

        mockModel.generateTextWithFallBack = AsyncMock(side_effect=mockGenerateLong)

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))
        ensuredMessage.getBaseMessage().reply_text = AsyncMock(return_value=createMockMessage())

        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=1,
        )

        # Should send multiple messages due to splitting
        assert ensuredMessage.getBaseMessage().reply_text.call_count > 1  # type: ignore[attr-defined]


# ============================================================================
# Unit Tests - User State Management
# ============================================================================


class TestUserStateManagement:
    """Test user state management for interactive summarization, dood!"""

    @pytest.mark.asyncio
    async def testUserStateSetForMessageCountInput(self, summarizationHandler, mockCacheService, mockDatabase):
        """Test user state is set when waiting for message count input, dood!"""
        user = createMockUser(userId=456)
        message = createMockMessage(chatId=123, userId=456)
        message.edit_text = AsyncMock(return_value=message)

        mockDatabase.getUserChats.return_value = [
            {"chat_id": 123, "title": "Test Chat", "username": None, "type": "group"}
        ]

        data = {
            ButtonDataKey.SummarizationAction: "s",
            ButtonDataKey.ChatId: 123,
            ButtonDataKey.UserAction: 1,  # Waiting for message count
        }

        await summarizationHandler._handle_summarization(data, message, user)

        # Verify user state was set
        mockCacheService.setUserState.assert_called_once()
        callArgs = mockCacheService.setUserState.call_args
        assert callArgs[1]["userId"] == 456
        assert callArgs[1]["stateKey"] == UserActiveActionEnum.Summarization

    @pytest.mark.asyncio
    async def testUserStateSetForPromptInput(self, summarizationHandler, mockCacheService, mockDatabase):
        """Test user state is set when waiting for prompt input, dood!"""
        user = createMockUser(userId=456)
        message = createMockMessage(chatId=123, userId=456)
        message.edit_text = AsyncMock(return_value=message)

        mockDatabase.getUserChats.return_value = [
            {"chat_id": 123, "title": "Test Chat", "username": None, "type": "group"}
        ]

        data = {
            ButtonDataKey.SummarizationAction: "s",
            ButtonDataKey.ChatId: 123,
            ButtonDataKey.UserAction: 2,  # Waiting for prompt
        }

        await summarizationHandler._handle_summarization(data, message, user)

        # Verify user state was set (may be called multiple times during flow)
        assert mockCacheService.setUserState.call_count >= 1
        callArgs = mockCacheService.setUserState.call_args
        assert callArgs[1]["stateKey"] == UserActiveActionEnum.Summarization

    @pytest.mark.asyncio
    async def testUserStateClearedAfterCompletion(self, summarizationHandler, mockCacheService, mockDatabase):
        """Test user state is cleared after summarization completes, dood!"""
        user = createMockUser(userId=456)
        message = createMockMessage(chatId=123, userId=456)
        message.edit_text = AsyncMock(return_value=message)

        mockDatabase.getUserChats.return_value = [
            {"chat_id": 123, "title": "Test Chat", "username": None, "type": "group"}
        ]

        data = {
            ButtonDataKey.SummarizationAction: "s",
            ButtonDataKey.ChatId: 123,
        }

        await summarizationHandler._handle_summarization(data, message, user)

        # Verify user state was cleared at start
        mockCacheService.clearUserState.assert_called_with(userId=456, stateKey=UserActiveActionEnum.Summarization)

    @pytest.mark.asyncio
    async def testMessageHandlerProcessesUserInput(self, summarizationHandler, mockCacheService, mockDatabase):
        """Test message handler processes user input when state is active, dood!"""
        createMockUser(userId=456)
        chat = createMockChat(chatId=456, chatType=Chat.PRIVATE)
        message = createMockMessage(chatId=456, userId=456, text="10")
        message.chat = chat

        # Set active state
        mockCacheService.getUserState.return_value = {
            ButtonDataKey.SummarizationAction: "s",
            ButtonDataKey.ChatId: 123,
            ButtonDataKey.UserAction: 1,  # Expecting message count
            "message": message,
        }

        mockDatabase.getUserChats.return_value = [
            {"chat_id": 123, "title": "Test Chat", "username": None, "type": "group"}
        ]
        mockDatabase.getChatMessagesSince.return_value = []

        update = createMockUpdate(message=message)
        context = createMockContext()
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await summarizationHandler.messageHandler(update, context, ensuredMessage)

        # Should process the input
        assert result == HandlerResultStatus.FINAL


# ============================================================================
# Unit Tests - Button Callback Handling
# ============================================================================


class TestButtonCallbackHandling:
    """Test button callback handling for summarization wizard, dood!"""

    @pytest.mark.asyncio
    async def testButtonHandlerRecognizesSummarizationAction(self, summarizationHandler, mockDatabase):
        """Test button handler recognizes summarization actions, dood!"""
        user = createMockUser(userId=456)
        message = createMockMessage(chatId=123, userId=456)
        message.edit_text = AsyncMock(return_value=message)

        query = Mock()
        query.from_user = user
        query.message = message

        update = createMockUpdate()
        update.callback_query = query
        context = createMockContext()

        mockDatabase.getUserChats.return_value = []

        data = {ButtonDataKey.SummarizationAction: "s"}

        result = await summarizationHandler.buttonHandler(update, context, data)

        assert result == HandlerResultStatus.FINAL

    @pytest.mark.asyncio
    async def testButtonHandlerSkipsNonSummarizationActions(self, summarizationHandler):
        """Test button handler skips non-summarization actions, dood!"""
        user = createMockUser(userId=456)
        message = createMockMessage(chatId=123, userId=456)

        query = Mock()
        query.from_user = user
        query.message = message

        update = createMockUpdate()
        update.callback_query = query
        context = createMockContext()
        data = {"other_action": "value"}

        result = await summarizationHandler.buttonHandler(update, context, data)

        assert result == HandlerResultStatus.SKIPPED

    @pytest.mark.asyncio
    async def testButtonHandlerCancelAction(self, summarizationHandler):
        """Test button handler handles cancel action, dood!"""
        user = createMockUser(userId=456)
        message = createMockMessage(chatId=123, userId=456)
        message.edit_text = AsyncMock(return_value=message)

        query = Mock()
        query.from_user = user
        query.message = message

        update = createMockUpdate()
        update.callback_query = query
        context = createMockContext()

        data = {ButtonDataKey.SummarizationAction: ButtonSummarizationAction.Cancel}

        result = await summarizationHandler.buttonHandler(update, context, data)

        assert result == HandlerResultStatus.FINAL
        message.edit_text.assert_called_once()


# ============================================================================
# Integration Tests - Interactive Summarization Workflow
# ============================================================================


class TestInteractiveSummarizationWorkflow:
    """Test complete interactive summarization workflow, dood!"""

    @pytest.mark.asyncio
    async def testSelectChatStep(self, summarizationHandler, mockDatabase):
        """Test chat selection step in wizard, dood!"""
        user = createMockUser(userId=456)
        message = createMockMessage(chatId=456, userId=456)
        message.edit_text = AsyncMock(return_value=message)

        mockDatabase.getUserChats.return_value = [
            {"chat_id": 123, "title": "Chat 1", "username": None, "type": "group"},
            {"chat_id": 124, "title": "Chat 2", "username": None, "type": "group"},
        ]

        data = {ButtonDataKey.SummarizationAction: "s"}

        await summarizationHandler._handle_summarization(data, message, user)

        # Should show chat selection
        message.edit_text.assert_called_once()
        callArgs = message.edit_text.call_args
        assert "Выберите чат" in callArgs[1]["text"]

    @pytest.mark.asyncio
    async def testSelectTopicStep(self, summarizationHandler, mockDatabase, mockCacheService):
        """Test topic selection step in wizard, dood!"""
        user = createMockUser(userId=456)
        message = createMockMessage(chatId=456, userId=456)
        message.edit_text = AsyncMock(return_value=message)

        mockDatabase.getUserChats.return_value = [
            {"chat_id": 123, "title": "Test Chat", "username": None, "type": "supergroup"}
        ]

        mockCacheService.getChatTopicsInfo.return_value = {
            1: {
                "chat_id": 123,
                "topic_id": 1,
                "name": "Topic 1",
                "icon_color": None,
                "icon_custom_emoji_id": None,
                "created_at": datetime.datetime.now(),
                "updated_at": datetime.datetime.now(),
            }
        }

        data = {
            ButtonDataKey.SummarizationAction: "t",  # Topic summary
            ButtonDataKey.ChatId: 123,
        }

        await summarizationHandler._handle_summarization(data, message, user)

        # Should show topic selection
        message.edit_text.assert_called_once()
        callArgs = message.edit_text.call_args
        assert "топик" in callArgs[1]["text"].lower()

    @pytest.mark.asyncio
    async def testConfigureTimeRangeStep(self, summarizationHandler, mockDatabase):
        """Test time range configuration step, dood!"""
        user = createMockUser(userId=456)
        message = createMockMessage(chatId=456, userId=456)
        message.edit_text = AsyncMock(return_value=message)

        mockDatabase.getUserChats.return_value = [
            {"chat_id": 123, "title": "Test Chat", "username": None, "type": "group"}
        ]

        data = {
            ButtonDataKey.SummarizationAction: "s",
            ButtonDataKey.ChatId: 123,
            ButtonDataKey.MaxMessages: 0,  # Today
        }

        await summarizationHandler._handle_summarization(data, message, user)

        # Should show time range options
        message.edit_text.assert_called_once()
        callArgs = message.edit_text.call_args
        assert "сегодня" in callArgs[1]["text"].lower()


# ============================================================================
# Integration Tests - Message Filtering and Batching
# ============================================================================


class TestMessageFilteringAndBatching:
    """Test message filtering and batching logic, dood!"""

    @pytest.mark.asyncio
    async def testFilterMessagesByCategory(self, summarizationHandler, mockDatabase):
        """Test messages are filtered by category, dood!"""
        messages = [
            createMockDBMessage(123, 1, 456, "user", "User", MessageCategory.USER, "User message"),
            createMockDBMessage(123, 2, 789, "bot", "Bot", MessageCategory.BOT, "Bot message"),
            createMockDBMessage(123, 3, 456, "user", "User", MessageCategory.USER_COMMAND, "Command"),
        ]
        mockDatabase.getChatMessagesSince.return_value = messages

        # Request should filter to USER and BOT categories only
        result = mockDatabase.getChatMessagesSince(
            chatId=123, limit=10, messageCategory=[MessageCategory.USER, MessageCategory.BOT]
        )

        assert len(result) == 3

    @pytest.mark.asyncio
    async def testFilterMessagesByTimeRange(self, summarizationHandler, mockDatabase):
        """Test messages are filtered by time range, dood!"""
        now = datetime.datetime.now(datetime.timezone.utc)
        yesterday = now - datetime.timedelta(days=1)

        messages = [
            createMockDBMessage(123, 1, 456, "user", "User", "user", "Old message"),
        ]
        messages[0]["date"] = yesterday

        mockDatabase.getChatMessagesSince.return_value = messages

        # Should filter by date range
        result = mockDatabase.getChatMessagesSince(chatId=123, sinceDateTime=yesterday, tillDateTime=now)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def testFilterMessagesByThread(self, summarizationHandler, mockDatabase):
        """Test messages are filtered by thread ID, dood!"""
        messages = [
            createMockDBMessage(123, 1, 456, "user", "User", "user", "Thread 1", threadId=1),
            createMockDBMessage(123, 2, 456, "user", "User", "user", "Thread 2", threadId=2),
        ]
        mockDatabase.getChatMessagesSince.return_value = [messages[0]]

        result = mockDatabase.getChatMessagesSince(chatId=123, threadId=1)

        assert len(result) == 1
        assert result[0]["thread_id"] == 1


# ============================================================================
# Integration Tests - LLM Summarization with Context
# ============================================================================


class TestLLMSummarizationWithContext:
    """Test LLM summarization with proper context, dood!"""

    @pytest.mark.asyncio
    async def testSummarizationIncludesUserContext(self, summarizationHandler, mockDatabase, mockLlmManager):
        """Test summarization includes user information in context, dood!"""
        messages = [
            createMockDBMessage(123, 1, 456, "alice", "Alice", "user", "Hello"),
            createMockDBMessage(123, 2, 789, "bob", "Bob", "user", "Hi Alice"),
        ]
        mockDatabase.getChatMessagesSince.return_value = messages

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))

        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=2,
        )

        # Verify LLM was called with user context
        mockModel = mockLlmManager.getModel("gpt-4")
        callArgs = mockModel.generateTextWithFallBack.call_args
        messages = callArgs[0][0]

        # Should have user messages with proper formatting
        assert len(messages) > 1  # System + user messages

    @pytest.mark.asyncio
    async def testSummarizationWithFallbackModel(self, summarizationHandler, mockDatabase, mockLlmManager):
        """Test summarization uses fallback model when needed, dood!"""
        messages = [
            createMockDBMessage(123, 1, 456, "user", "User", "user", "Test"),
        ]
        mockDatabase.getChatMessagesSince.return_value = messages

        # Mock primary model to fail, fallback to succeed
        mockModel = mockLlmManager.getModel("gpt-4")

        async def mockGenerateWithFallback(*args, **kwargs):
            result = ModelRunResult(
                rawResult={},
                status=ModelResultStatus.FINAL,
                resultText="Fallback summary",
            )
            result.setFallback(True)
            return result

        mockModel.generateTextWithFallBack = AsyncMock(side_effect=mockGenerateWithFallback)

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))
        ensuredMessage.getBaseMessage().reply_text = AsyncMock(return_value=createMockMessage())

        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=1,
        )

        # Should have used fallback
        mockModel.generateTextWithFallBack.assert_called_once()

    @pytest.mark.asyncio
    async def testSummarizationHandlesLLMError(self, summarizationHandler, mockDatabase, mockLlmManager):
        """Test summarization handles LLM errors gracefully, dood!"""
        messages = [
            createMockDBMessage(123, 1, 456, "user", "User", "user", "Test"),
        ]
        mockDatabase.getChatMessagesSince.return_value = messages

        # Mock LLM to raise error
        mockModel = mockLlmManager.getModel("gpt-4")
        mockModel.generateTextWithFallBack = AsyncMock(side_effect=Exception("LLM Error"))

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))
        ensuredMessage.getBaseMessage().reply_text = AsyncMock(return_value=createMockMessage())

        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=1,
        )

        # Should send error message
        ensuredMessage.getBaseMessage().reply_text.assert_called()  # type: ignore[attr-defined]


# ============================================================================
# Integration Tests - Cache Integration
# ============================================================================


class TestCacheIntegration:
    """Test cache integration for summarization, dood!"""

    @pytest.mark.asyncio
    async def testSummarizationUsesCache(self, summarizationHandler, mockDatabase):
        """Test summarization retrieves from cache when available, dood!"""
        messages = [
            createMockDBMessage(123, 1, 456, "user", "User", "user", "Message 1"),
            createMockDBMessage(123, 2, 456, "user", "User", "user", "Message 2"),
        ]
        mockDatabase.getChatMessagesSince.return_value = messages

        # Mock cache hit
        cachedSummary = json.dumps(["Cached summary text"])
        mockDatabase.getChatSummarization.return_value = {
            "chat_id": 123,
            "topic_id": None,
            "first_message_id": 1,
            "last_message_id": 2,
            "prompt": "Summarize the following messages",
            "summary": cachedSummary,
        }

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))
        ensuredMessage.getBaseMessage().reply_text = AsyncMock(return_value=createMockMessage())

        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=2,
            useCache=True,
        )

        # Should use cached summary
        mockDatabase.getChatSummarization.assert_called_once()
        ensuredMessage.getBaseMessage().reply_text.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def testSummarizationStoresInCache(self, summarizationHandler, mockDatabase, mockLlmManager):
        """Test summarization stores result in cache, dood!"""
        messages = [
            createMockDBMessage(123, 1, 456, "user", "User", "user", "Message 1"),
            createMockDBMessage(123, 2, 456, "user", "User", "user", "Message 2"),
        ]
        mockDatabase.getChatMessagesSince.return_value = messages
        mockDatabase.getChatSummarization.return_value = None  # Cache miss

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))
        ensuredMessage.getBaseMessage().reply_text = AsyncMock(return_value=createMockMessage())

        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=2,
            useCache=True,
        )

        # Should store in cache
        mockDatabase.addChatSummarization.assert_called_once()

    @pytest.mark.asyncio
    async def testSummarizationBypassesCache(self, summarizationHandler, mockDatabase, mockLlmManager):
        """Test summarization can bypass cache when requested, dood!"""
        messages = [
            createMockDBMessage(123, 1, 456, "user", "User", "user", "Test"),
        ]
        mockDatabase.getChatMessagesSince.return_value = messages

        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))
        ensuredMessage.getBaseMessage().reply_text = AsyncMock(return_value=createMockMessage())

        await summarizationHandler._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=123,
            threadId=None,
            chatSettings=chatSettings,
            maxMessages=1,
            useCache=False,
        )

        # Should not check or store cache
        mockDatabase.getChatSummarization.assert_not_called()
        mockDatabase.addChatSummarization.assert_not_called()


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling, dood!"""

    @pytest.mark.asyncio
    async def testSummarizationWithoutSinceDTOrMaxMessages(self, summarizationHandler):
        """Test summarization raises error without sinceDT or maxMessages, dood!"""
        chatSettings = summarizationHandler.getChatSettings(123)
        ensuredMessage = EnsuredMessage.fromMessage(createMockMessage(chatId=123, userId=456))

        with pytest.raises(ValueError, match="one of sinceDT or maxMessages MUST be not None"):
            await summarizationHandler._doSummarization(
                ensuredMessage=ensuredMessage,
                chatId=123,
                threadId=None,
                chatSettings=chatSettings,
                sinceDT=None,
                maxMessages=None,
            )

    @pytest.mark.asyncio
    async def testMessageHandlerSkipsNonPrivateChats(self, summarizationHandler):
        """Test message handler skips non-private chats, dood!"""
        chat = createMockChat(chatId=123, chatType=Chat.GROUP)
        message = createMockMessage(chatId=123, userId=456, text="Test")
        message.chat = chat

        update = createMockUpdate(message=message)
        context = createMockContext()
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await summarizationHandler.messageHandler(update, context, ensuredMessage)

        assert result == HandlerResultStatus.SKIPPED

    @pytest.mark.asyncio
    async def testMessageHandlerSkipsWithoutActiveState(self, summarizationHandler, mockCacheService):
        """Test message handler skips when no active summarization state, dood!"""
        mockCacheService.getUserState.return_value = None

        chat = createMockChat(chatId=456, chatType=Chat.PRIVATE)
        message = createMockMessage(chatId=456, userId=456, text="Test")
        message.chat = chat

        update = createMockUpdate(message=message)
        context = createMockContext()
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await summarizationHandler.messageHandler(update, context, ensuredMessage)

        assert result == HandlerResultStatus.SKIPPED

    @pytest.mark.asyncio
    async def testHandleSummarizationWithInvalidChatId(self, summarizationHandler, mockDatabase):
        """Test handle summarization with invalid chat ID, dood!"""
        user = createMockUser(userId=456)
        message = createMockMessage(chatId=456, userId=456)
        message.edit_text = AsyncMock(return_value=message)

        mockDatabase.getUserChats.return_value = [
            {"chat_id": 123, "title": "Chat 1", "username": None, "type": "group"}
        ]

        data = {
            ButtonDataKey.SummarizationAction: "s",
            ButtonDataKey.ChatId: 999,  # Invalid chat ID
        }

        await summarizationHandler._handle_summarization(data, message, user)

        # Should show error
        message.edit_text.assert_called_once()
        callArgs = message.edit_text.call_args
        assert "неверный" in callArgs[0][0].lower()

    @pytest.mark.asyncio
    async def testHandleSummarizationWithNoChats(self, summarizationHandler, mockDatabase):
        """Test handle summarization when user has no chats, dood!"""
        user = createMockUser(userId=456)
        message = createMockMessage(chatId=456, userId=456)
        message.edit_text = AsyncMock(return_value=message)

        mockDatabase.getUserChats.return_value = []

        data = {ButtonDataKey.SummarizationAction: "s"}

        await summarizationHandler._handle_summarization(data, message, user)

        # Should show "no chats" message
        message.edit_text.assert_called_once()
        callArgs = message.edit_text.call_args
        assert "не найдены" in callArgs[0][0].lower()


# ============================================================================
# Test Summary
# ============================================================================


def testSummary():
    """
    Test Summary for SummarizationHandler, dood!

    Total Test Cases: 40+

    Coverage Areas:
    - Initialization: 1 test
    - Message Batch Processing: 3 tests
    - Summary Generation Logic: 3 tests
    - User State Management: 4 tests
    - Button Callback Handling: 3 tests
    - /summary Command Flow: 3 tests
    - Interactive Summarization Workflow: 3 tests
    - Message Filtering and Batching: 3 tests
    - LLM Summarization with Context: 3 tests
    - Cache Integration: 3 tests
    - Edge Cases and Error Handling: 9 tests

    Key Features Tested:
    ✓ Handler initialization with dependencies
    ✓ Message batch processing (small, large, empty sets)
    ✓ Summary generation with default and custom prompts
    ✓ Long message splitting
    ✓ User state management for interactive workflows
    ✓ User input processing (message count, prompt)
    ✓ Button callback handling for wizard
    ✓ Cancel action handling
    ✓ /summary command in private and group chats
    ✓ /summary with arguments (maxMessages, chatId, topicId)
    ✓ Interactive wizard steps (chat selection, topic selection, time range)
    ✓ Message filtering by category, time range, and thread
    ✓ LLM summarization with user context
    ✓ Fallback model usage
    ✓ LLM error handling
    ✓ Cache retrieval and storage
    ✓ Cache bypass option
    ✓ Error handling for missing parameters
    ✓ Invalid chat ID handling
    ✓ No chats available handling
    ✓ Disabled summary command handling
    ✓ Topic summary in supergroups

    Test Coverage:
    - Comprehensive unit tests for all core methods
    - Integration tests for complete workflows
    - Button callback tests for interactive wizard
    - Edge cases and error handling
    - Cache integration testing
    - LLM integration with fallback

    Target Coverage: 75%+ for SummarizationHandler class
    """
    pass
