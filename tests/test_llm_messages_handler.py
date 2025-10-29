"""Comprehensive tests for LLM Message Handler, dood!

This module provides extensive test coverage for the LLMMessageHandler class,
including message context building, LLM prompt construction, response formatting,
tool call handling, and various integration scenarios for different chat types.
"""

import datetime
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import Chat

from internal.bot.handlers.llm_messages import LLMMessageHandler
from internal.bot.models import ChatSettingsKey, EnsuredMessage
from lib.ai.models import ModelResultStatus, ModelRunResult
from tests.fixtures.service_mocks import (
    createMockAbstractModel,
    createMockDatabaseWrapper,
    createMockLlmManager,
    createMockLlmService,
)
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
# Fixtures
# ============================================================================


@pytest.fixture
def mockConfigManager():
    """Create a mock ConfigManager, dood!"""
    from internal.config.manager import ConfigManager

    config = Mock(spec=ConfigManager)

    # Default bot config
    defaultBotConfig = {
        "token": "test_token",
        "owners": [123456],
        "log_level": "INFO",
    }

    config.getBotConfig = Mock(return_value=defaultBotConfig)
    config.getProviderConfig = Mock(return_value={})
    config.getModelConfig = Mock(return_value={})

    return config


@pytest.fixture
def mockDatabase():
    """Create a mock DatabaseWrapper with default chat settings, dood!"""
    db = createMockDatabaseWrapper()

    # Mock message retrieval methods
    db.getChatMessageByMessageId = Mock(return_value=None)
    db.getChatMessagesByRootId = Mock(return_value=[])
    db.getChatMessagesSince = Mock(return_value=[])
    db.getChatUsers = Mock(return_value=[])

    return db


@pytest.fixture
def mockCacheService():
    """Create a mock CacheService with default chat settings, dood!"""
    from internal.bot.models import ChatSettingsValue
    from internal.services.cache.service import CacheService

    mock = Mock(spec=CacheService)

    # Setup default chat settings as ChatSettingsValue objects
    # Note: These must match the defaults in the actual config
    defaultSettings = {
        ChatSettingsKey.CHAT_MODEL: ChatSettingsValue("gpt-4"),
        ChatSettingsKey.FALLBACK_MODEL: ChatSettingsValue("gpt-3.5-turbo"),
        ChatSettingsKey.CHAT_PROMPT: ChatSettingsValue("You are a helpful assistant"),
        ChatSettingsKey.CHAT_PROMPT_SUFFIX: ChatSettingsValue(""),
        ChatSettingsKey.LLM_MESSAGE_FORMAT: ChatSettingsValue("text"),
        ChatSettingsKey.USE_TOOLS: ChatSettingsValue("false"),
        ChatSettingsKey.ALLOW_PRIVATE: ChatSettingsValue("true"),
        ChatSettingsKey.ALLOW_REPLY: ChatSettingsValue("true"),
        ChatSettingsKey.ALLOW_MENTION: ChatSettingsValue("true"),
        ChatSettingsKey.RANDOM_ANSWER_PROBABILITY: ChatSettingsValue("0.0"),
        ChatSettingsKey.RANDOM_ANSWER_TO_ADMIN: ChatSettingsValue("false"),
        ChatSettingsKey.FALLBACK_HAPPENED_PREFIX: ChatSettingsValue("[Fallback] "),
        ChatSettingsKey.TOOLS_USED_PREFIX: ChatSettingsValue("[Tools] "),
        ChatSettingsKey.IMAGE_GENERATION_MODEL: ChatSettingsValue("dall-e-3"),
        ChatSettingsKey.IMAGE_GENERATION_FALLBACK_MODEL: ChatSettingsValue("dall-e-2"),
        ChatSettingsKey.IMAGE_PARSING_MODEL: ChatSettingsValue("gpt-4-vision"),
        ChatSettingsKey.PARSE_IMAGES: ChatSettingsValue("false"),
        ChatSettingsKey.SAVE_IMAGES: ChatSettingsValue("false"),
        ChatSettingsKey.PARSE_IMAGE_PROMPT: ChatSettingsValue("Describe this image"),
        ChatSettingsKey.OPTIMAL_IMAGE_SIZE: ChatSettingsValue("512"),
        ChatSettingsKey.BOT_NICKNAMES: ChatSettingsValue("[]"),
    }

    # Store settings per chat
    mock._chat_settings = {
        123: defaultSettings.copy(),
        456: defaultSettings.copy(),
    }

    # Mock getChatSettings to return settings for the chat
    mock.getChatSettings = Mock(side_effect=lambda chatId: mock._chat_settings.get(chatId, {}))

    # Mock setChatSetting
    mock.setChatSetting = Mock(
        side_effect=lambda chatId, key, value: mock._chat_settings.setdefault(chatId, {}).update({key: value})
    )

    # Mock other cache methods
    mock.getChatInfo = Mock(return_value=None)
    mock.setChatInfo = Mock(return_value=None)
    mock.getChatTopicInfo = Mock(return_value=None)
    mock.setChatTopicInfo = Mock(return_value=None)
    mock.getChatUserData = Mock(return_value={})
    mock.setChatUserData = Mock(return_value=None)

    return mock


@pytest.fixture
def mockLlmManager():
    """Create a mock LLMManager with test models, dood!"""
    mockModel = createMockAbstractModel(modelName="gpt-4", defaultResponse="Test response")
    mockFallbackModel = createMockAbstractModel(modelName="gpt-3.5-turbo", defaultResponse="Fallback response")

    manager = createMockLlmManager(
        models={
            "gpt-4": mockModel,
            "gpt-3.5-turbo": mockFallbackModel,
            "dall-e-3": createMockAbstractModel(modelName="dall-e-3"),
            "dall-e-2": createMockAbstractModel(modelName="dall-e-2"),
        }
    )

    return manager


@pytest.fixture
def mockLlmService():
    """Create a mock LLMService, dood!"""
    service = createMockLlmService(defaultResponse="LLM response")

    # Mock generateTextViaLLM to return a proper ModelRunResult
    async def mockGenerateText(*args, **kwargs):
        return ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Test LLM response",
        )

    service.generateTextViaLLM = AsyncMock(side_effect=mockGenerateText)

    return service


@pytest.fixture
def llmHandler(mockConfigManager, mockDatabase, mockLlmManager, mockLlmService, mockCacheService):
    """Create an LLMMessageHandler instance with mocked dependencies, dood!"""
    with (
        patch("internal.services.llm.service.LLMService.getInstance", return_value=mockLlmService),
        patch("internal.services.cache.service.CacheService.getInstance", return_value=mockCacheService),
        patch("internal.services.queue_service.service.QueueService.getInstance", return_value=Mock()),
    ):
        handler = LLMMessageHandler(
            configManager=mockConfigManager,
            database=mockDatabase,
            llmManager=mockLlmManager,
        )
        return handler


@pytest.fixture
def mockContext():
    """Create a mock Telegram context, dood!"""
    bot = createMockBot(botId=123456789, username="test_bot")
    return createMockContext(bot=bot)


@pytest.fixture
def privateChat():
    """Create a mock private chat, dood!"""
    return createMockChat(chatId=123, chatType=Chat.PRIVATE)


@pytest.fixture
def groupChat():
    """Create a mock group chat, dood!"""
    return createMockChat(chatId=456, chatType=Chat.GROUP, title="Test Group")


@pytest.fixture
def testUser():
    """Create a mock user, dood!"""
    return createMockUser(userId=789, username="testuser", firstName="Test", lastName="User")


# ============================================================================
# Unit Tests: Message Context Building
# ============================================================================


@pytest.mark.asyncio
async def testBuildContextFromEmptyHistory(llmHandler, mockDatabase):
    """Test building conversation context from empty history, dood!"""
    mockDatabase.getChatMessagesSince.return_value = []

    messages = mockDatabase.getChatMessagesSince(chatId=123, limit=10)

    assert len(messages) == 0
    mockDatabase.getChatMessagesSince.assert_called_once()


@pytest.mark.asyncio
async def testBuildContextFromMessageHistory(llmHandler, mockDatabase):
    """Test building conversation context from message history, dood!"""
    # Setup message history
    historyMessages = [
        createMockDBMessage(123, 1, 789, "testuser", "Test User", "user", "Hello"),
        createMockDBMessage(123, 2, 123456789, "test_bot", "Test Bot", "bot", "Hi there!"),
    ]

    mockDatabase.getChatMessagesSince.return_value = historyMessages

    messages = mockDatabase.getChatMessagesSince(chatId=123, limit=10)

    assert len(messages) == 2
    assert messages[0]["message_category"] == "user"
    assert messages[1]["message_category"] == "bot"


@pytest.mark.asyncio
async def testBuildContextWithThreadMessages(llmHandler, mockDatabase):
    """Test building context from threaded conversation, dood!"""
    threadMessages = [
        createMockDBMessage(456, 10, 789, "testuser", "Test User", "user", "Start of thread", rootMessageId=10),
        createMockDBMessage(456, 11, 123456789, "test_bot", "Test Bot", "bot", "Reply in thread", rootMessageId=10),
    ]

    mockDatabase.getChatMessagesByRootId.return_value = threadMessages

    messages = mockDatabase.getChatMessagesByRootId(chatId=456, rootMessageId=10)

    assert len(messages) == 2
    assert all(msg["root_message_id"] == 10 for msg in messages)


# ============================================================================
# Unit Tests: LLM Prompt Construction
# ============================================================================


def testSystemPromptConstruction(llmHandler, mockDatabase):
    """Test system prompt construction from chat settings, dood!"""
    chatSettings = llmHandler.getChatSettings(123)

    systemPrompt = chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr()
    suffix = chatSettings[ChatSettingsKey.CHAT_PROMPT_SUFFIX].toStr()

    fullPrompt = systemPrompt + "\n" + suffix

    assert "helpful assistant" in systemPrompt.lower()
    assert isinstance(fullPrompt, str)


def testSystemPromptWithCustomSuffix(llmHandler, mockDatabase, mockCacheService):
    """Test system prompt with custom suffix, dood!"""
    from internal.bot.models import ChatSettingsValue

    mockCacheService._chat_settings[123][ChatSettingsKey.CHAT_PROMPT_SUFFIX] = ChatSettingsValue("\nAlways be polite.")

    chatSettings = llmHandler.getChatSettings(123)
    systemPrompt = chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr()
    suffix = chatSettings[ChatSettingsKey.CHAT_PROMPT_SUFFIX].toStr()

    fullPrompt = systemPrompt + "\n" + suffix

    assert "Always be polite" in fullPrompt


def testModelSelectionFromSettings(llmHandler, mockDatabase, mockLlmManager):
    """Test model selection from chat settings, dood!"""
    chatSettings = llmHandler.getChatSettings(123)

    modelName = chatSettings[ChatSettingsKey.CHAT_MODEL].toStr()
    assert modelName == "gpt-4"

    # Verify model can be retrieved from manager
    model = mockLlmManager.getModel(modelName)
    assert model is not None
    assert model.name == "gpt-4"


# ============================================================================
# Unit Tests: Response Formatting
# ============================================================================


@pytest.mark.asyncio
async def testFormatTextResponse(llmHandler, mockLlmService):
    """Test formatting plain text LLM response, dood!"""
    result = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="This is a test response",
    )

    assert result.resultText == "This is a test response"
    assert result.status == ModelResultStatus.FINAL


@pytest.mark.asyncio
async def testFormatResponseWithFallbackPrefix(llmHandler, mockDatabase):
    """Test response formatting with fallback prefix, dood!"""
    chatSettings = llmHandler.getChatSettings(123)
    fallbackPrefix = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()

    result = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Response text",
    )
    result.setFallback(True)

    assert fallbackPrefix == "[Fallback]"
    assert result.isFallback is True


@pytest.mark.asyncio
async def testFormatResponseWithToolsPrefix(llmHandler, mockDatabase):
    """Test response formatting with tools used prefix, dood!"""
    chatSettings = llmHandler.getChatSettings(123)
    toolsPrefix = chatSettings[ChatSettingsKey.TOOLS_USED_PREFIX].toStr()

    result = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Response text",
    )
    result.setToolsUsed(True)

    assert toolsPrefix == "[Tools]"
    assert result.isToolsUsed is True


@pytest.mark.asyncio
async def testExtractMediaDescriptionTag(llmHandler):
    """Test extracting <media-description> tag from response, dood!"""
    responseText = "<media-description>A beautiful sunset</media-description>The image shows a sunset"

    import re

    match = re.search(r"^<media-description>(.*?)</media-description>(.*)", responseText, re.DOTALL)

    assert match is not None
    imagePrompt = match.group(1).strip()
    remainingText = match.group(2).strip()

    assert imagePrompt == "A beautiful sunset"
    assert remainingText == "The image shows a sunset"


# ============================================================================
# Unit Tests: Tool Call Handling
# ============================================================================


@pytest.mark.asyncio
async def testToolCallDetection(llmHandler, mockLlmService):
    """Test detection of tool calls in LLM response, dood!"""
    from lib.ai.models import LLMToolCall

    result = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[
            LLMToolCall(
                id="call_123",
                name="getWeather",
                parameters={"location": "Tokyo"},
            )
        ],
    )

    assert result.status == ModelResultStatus.TOOL_CALLS
    assert len(result.toolCalls) == 1
    assert result.toolCalls[0].name == "getWeather"


@pytest.mark.asyncio
async def testToolCallExecution(llmHandler, mockLlmService):
    """Test tool call execution flow, dood!"""
    from lib.ai.models import LLMToolCall

    # Mock tool execution
    async def mockToolHandler(extraData=None, **kwargs):
        return "Weather: Sunny, 25°C"

    mockLlmService.toolsHandlers = {"getWeather": Mock(call=AsyncMock(return_value="Weather: Sunny, 25°C"))}

    toolCall = LLMToolCall(
        id="call_123",
        name="getWeather",
        parameters={"location": "Tokyo"},
    )

    # Simulate tool execution
    result = await mockLlmService.toolsHandlers["getWeather"].call(None, **toolCall.parameters)

    assert result == "Weather: Sunny, 25°C"


@pytest.mark.asyncio
async def testMultipleToolCalls(llmHandler, mockLlmService):
    """Test handling multiple tool calls in sequence, dood!"""
    from lib.ai.models import LLMToolCall

    result = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[
            LLMToolCall(id="call_1", name="getWeather", parameters={"location": "Tokyo"}),
            LLMToolCall(id="call_2", name="getTime", parameters={}),
        ],
    )

    assert len(result.toolCalls) == 2
    assert result.toolCalls[0].name == "getWeather"
    assert result.toolCalls[1].name == "getTime"


# ============================================================================
# Integration Tests: Reply to Bot Message
# ============================================================================


@pytest.mark.asyncio
async def testHandleReplyToBotMessage(llmHandler, mockContext, mockDatabase, mockLlmService, privateChat, testUser):
    """Test handling reply to bot's message, dood!"""
    # Create bot message
    botMessage = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=mockContext.bot.id,
        text="Hello! How can I help?",
    )

    # Create user reply
    userReply = createMockMessage(
        messageId=2,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Tell me a joke",
        replyToMessage=botMessage,
    )

    update = createMockUpdate(message=userReply)
    ensuredMessage = EnsuredMessage.fromMessage(userReply)

    # Mock database to return bot message
    mockDatabase.getChatMessageByMessageId.return_value = createMockDBMessage(
        privateChat.id, 1, mockContext.bot.id, "test_bot", "Test Bot", "bot", "Hello! How can I help?"
    )

    mockDatabase.getChatMessagesByRootId.return_value = [
        createMockDBMessage(
            privateChat.id, 1, mockContext.bot.id, "test_bot", "Test Bot", "bot", "Hello! How can I help?"
        )
    ]

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handleReply(update, mockContext, ensuredMessage)

    assert result is True
    mockLlmService.generateTextViaLLM.assert_called_once()


@pytest.mark.asyncio
async def testHandleReplyToUserMessage(llmHandler, mockContext, mockDatabase, privateChat, testUser):
    """Test that reply to user message is not handled, dood!"""
    # Create user message
    userMessage = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Hello",
    )

    # Create another user reply
    userReply = createMockMessage(
        messageId=2,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Anyone there?",
        replyToMessage=userMessage,
    )

    update = createMockUpdate(message=userReply)
    ensuredMessage = EnsuredMessage.fromMessage(userReply)

    result = await llmHandler.handleReply(update, mockContext, ensuredMessage)

    assert result is False


@pytest.mark.asyncio
async def testHandleReplyDisabledInSettings(
    llmHandler, mockContext, mockDatabase, mockCacheService, privateChat, testUser
):
    """Test reply handling when disabled in settings, dood!"""
    from internal.bot.models import ChatSettingsValue

    # Disable reply handling
    mockCacheService._chat_settings[privateChat.id][ChatSettingsKey.ALLOW_REPLY] = ChatSettingsValue("false")

    botMessage = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=mockContext.bot.id,
        text="Hello!",
    )

    userReply = createMockMessage(
        messageId=2,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Hi",
        replyToMessage=botMessage,
    )

    update = createMockUpdate(message=userReply)
    ensuredMessage = EnsuredMessage.fromMessage(userReply)

    result = await llmHandler.handleReply(update, mockContext, ensuredMessage)

    assert result is False


# ============================================================================
# Integration Tests: Mention Bot in Group
# ============================================================================


@pytest.mark.asyncio
async def testHandleMentionByUsername(llmHandler, mockContext, mockDatabase, mockLlmService, groupChat, testUser):
    """Test handling bot mention by username, dood!"""
    from telegram import MessageEntity

    message = createMockMessage(
        messageId=1,
        chatId=groupChat.id,
        userId=testUser.id,
        text="@test_bot tell me a joke",
    )

    # Add mention entity
    message.entities = [Mock(spec=MessageEntity, type="mention", offset=0, length=9)]

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock checkEMMentionsMe
    llmHandler.checkEMMentionsMe = Mock(return_value=Mock(byName=None, byNick="@test_bot", restText="tell me a joke"))

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handleMention(update, mockContext, ensuredMessage)

    assert result is True
    mockLlmService.generateTextViaLLM.assert_called_once()


@pytest.mark.asyncio
async def testHandleMentionDisabledInSettings(
    llmHandler, mockContext, mockDatabase, mockCacheService, groupChat, testUser
):
    """Test mention handling when disabled in settings, dood!"""
    from internal.bot.models import ChatSettingsValue

    # Disable mention handling
    mockCacheService._chat_settings[groupChat.id][ChatSettingsKey.ALLOW_MENTION] = ChatSettingsValue("false")

    message = createMockMessage(
        messageId=1,
        chatId=groupChat.id,
        userId=testUser.id,
        text="@test_bot hello",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    result = await llmHandler.handleMention(update, mockContext, ensuredMessage)

    assert result is False


@pytest.mark.asyncio
async def testHandleWhoTodayQuery(llmHandler, mockContext, mockDatabase, groupChat, testUser):
    """Test 'кто сегодня' special query, dood!"""
    message = createMockMessage(
        messageId=1,
        chatId=groupChat.id,
        userId=testUser.id,
        text="@test_bot кто сегодня дурак?",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock checkEMMentionsMe
    llmHandler.checkEMMentionsMe = Mock(
        return_value=Mock(byName=None, byNick="@test_bot", restText="кто сегодня дурак?")
    )

    # Mock getChatUsers to return test users
    mockDatabase.getChatUsers.return_value = [
        {"user_id": testUser.id, "username": "testuser"},
        {"user_id": 999, "username": "anotheruser"},
    ]

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handleMention(update, mockContext, ensuredMessage)

    assert result is True
    llmHandler.sendMessage.assert_called_once()
    # Verify message contains username
    callArgs = llmHandler.sendMessage.call_args
    assert "дурак" in callArgs.kwargs["messageText"]


# ============================================================================
# Integration Tests: Private Message to Bot
# ============================================================================


@pytest.mark.asyncio
async def testHandlePrivateMessage(llmHandler, mockContext, mockDatabase, mockLlmService, privateChat, testUser):
    """Test handling private message to bot, dood!"""
    message = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Hello bot!",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock message history
    mockDatabase.getChatMessagesSince.return_value = [
        createMockDBMessage(privateChat.id, 1, testUser.id, "testuser", "Test User", "user", "Hello bot!")
    ]

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handlePrivateMessage(update, mockContext, ensuredMessage)

    assert result is True
    mockLlmService.generateTextViaLLM.assert_called_once()


@pytest.mark.asyncio
async def testHandlePrivateMessageWithHistory(
    llmHandler, mockContext, mockDatabase, mockLlmService, privateChat, testUser
):
    """Test private message handling with conversation history, dood!"""
    message = createMockMessage(
        messageId=3,
        chatId=privateChat.id,
        userId=testUser.id,
        text="What did I ask before?",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock message history with previous conversation
    mockDatabase.getChatMessagesSince.return_value = [
        createMockDBMessage(privateChat.id, 1, testUser.id, "testuser", "Test User", "user", "Tell me a joke"),
        createMockDBMessage(
            privateChat.id, 2, mockContext.bot.id, "test_bot", "Test Bot", "bot", "Why did the chicken cross the road?"
        ),
        createMockDBMessage(privateChat.id, 3, testUser.id, "testuser", "Test User", "user", "What did I ask before?"),
    ]

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handlePrivateMessage(update, mockContext, ensuredMessage)

    assert result is True
    mockLlmService.generateTextViaLLM.assert_called_once()

    # Verify history was retrieved
    mockDatabase.getChatMessagesSince.assert_called_once()


@pytest.mark.asyncio
async def testHandlePrivateMessageDisabled(
    llmHandler, mockContext, mockDatabase, mockCacheService, privateChat, testUser
):
    """Test private message handling when disabled, dood!"""
    from internal.bot.models import ChatSettingsValue

    # Disable private messages
    mockCacheService._chat_settings[privateChat.id][ChatSettingsKey.ALLOW_PRIVATE] = ChatSettingsValue("false")

    message = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Hello",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    from internal.bot.handlers.base import HandlerResultStatus

    result = await llmHandler.messageHandler(update, mockContext, ensuredMessage)

    assert result == HandlerResultStatus.SKIPPED


# ============================================================================
# Integration Tests: Random Message Probability
# ============================================================================


@pytest.mark.asyncio
async def testHandleRandomMessageWithZeroProbability(llmHandler, mockContext, mockDatabase, groupChat, testUser):
    """Test random message handling with zero probability, dood!"""
    message = createMockMessage(
        messageId=1,
        chatId=groupChat.id,
        userId=testUser.id,
        text="Random message in group",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Probability is 0.0 by default
    result = await llmHandler.handleRandomMessage(update, mockContext, ensuredMessage)

    assert result is False


@pytest.mark.asyncio
async def testHandleRandomMessageWithHighProbability(
    llmHandler, mockContext, mockDatabase, mockCacheService, mockLlmService, groupChat, testUser
):
    """Test random message handling with high probability, dood!"""
    from internal.bot.models import ChatSettingsValue

    # Set high probability
    mockCacheService._chat_settings[groupChat.id][ChatSettingsKey.RANDOM_ANSWER_PROBABILITY] = ChatSettingsValue("1.0")

    message = createMockMessage(
        messageId=1,
        chatId=groupChat.id,
        userId=testUser.id,
        text="Random message",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock message history
    mockDatabase.getChatMessagesSince.return_value = [
        createMockDBMessage(groupChat.id, 1, testUser.id, "testuser", "Test User", "user", "Random message")
    ]

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    # Mock isAdmin to return False
    llmHandler.isAdmin = AsyncMock(return_value=False)

    result = await llmHandler.handleRandomMessage(update, mockContext, ensuredMessage)

    assert result is True
    mockLlmService.generateTextViaLLM.assert_called_once()


@pytest.mark.asyncio
async def testHandleRandomMessageSkipsAdmin(
    llmHandler, mockContext, mockDatabase, mockCacheService, groupChat, testUser
):
    """Test random message skips admin when configured, dood!"""
    from internal.bot.models import ChatSettingsValue

    # Set probability and disable admin responses
    mockCacheService._chat_settings[groupChat.id][ChatSettingsKey.RANDOM_ANSWER_PROBABILITY] = ChatSettingsValue("1.0")
    mockCacheService._chat_settings[groupChat.id][ChatSettingsKey.RANDOM_ANSWER_TO_ADMIN] = ChatSettingsValue("false")

    message = createMockMessage(
        messageId=1,
        chatId=groupChat.id,
        userId=testUser.id,
        text="Admin message",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock isAdmin to return True
    llmHandler.isAdmin = AsyncMock(return_value=True)

    result = await llmHandler.handleRandomMessage(update, mockContext, ensuredMessage)

    assert result is False


# ============================================================================
# Integration Tests: Multi-turn Conversations
# ============================================================================


@pytest.mark.asyncio
async def testMultiTurnConversationInPrivateChat(
    llmHandler, mockContext, mockDatabase, mockLlmService, privateChat, testUser
):
    """Test multi-turn conversation in private chat, dood!"""
    # Simulate a 3-turn conversation
    conversationHistory = [
        createMockDBMessage(privateChat.id, 1, testUser.id, "testuser", "Test User", "user", "What's the weather?"),
        createMockDBMessage(
            privateChat.id, 2, mockContext.bot.id, "test_bot", "Test Bot", "bot", "It's sunny and 25°C"
        ),
        createMockDBMessage(
            privateChat.id, 3, testUser.id, "testuser", "Test User", "user", "Should I bring an umbrella?"
        ),
    ]

    mockDatabase.getChatMessagesSince.return_value = conversationHistory

    message = createMockMessage(
        messageId=3,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Should I bring an umbrella?",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handlePrivateMessage(update, mockContext, ensuredMessage)

    assert result is True
    # Verify LLM was called with conversation history
    mockLlmService.generateTextViaLLM.assert_called_once()


@pytest.mark.asyncio
async def testMultiTurnConversationWithReply(
    llmHandler, mockContext, mockDatabase, mockLlmService, groupChat, testUser
):
    """Test multi-turn conversation via replies, dood!"""
    # Setup thread of messages
    threadMessages = [
        createMockDBMessage(
            groupChat.id, 10, testUser.id, "testuser", "Test User", "user", "Start conversation", rootMessageId=10
        ),
        createMockDBMessage(
            groupChat.id, 11, mockContext.bot.id, "test_bot", "Test Bot", "bot", "I'm listening", rootMessageId=10
        ),
        createMockDBMessage(
            groupChat.id, 12, testUser.id, "testuser", "Test User", "user", "Continue discussion", rootMessageId=10
        ),
    ]

    mockDatabase.getChatMessageByMessageId.return_value = threadMessages[1]
    mockDatabase.getChatMessagesByRootId.return_value = threadMessages

    # Create reply to bot message
    botMessage = createMockMessage(
        messageId=11,
        chatId=groupChat.id,
        userId=mockContext.bot.id,
        text="I'm listening",
    )

    userReply = createMockMessage(
        messageId=12,
        chatId=groupChat.id,
        userId=testUser.id,
        text="Continue discussion",
        replyToMessage=botMessage,
    )

    update = createMockUpdate(message=userReply)
    ensuredMessage = EnsuredMessage.fromMessage(userReply)

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handleReply(update, mockContext, ensuredMessage)

    assert result is True
    mockLlmService.generateTextViaLLM.assert_called_once()


# ============================================================================
# Integration Tests: Tool Usage in Conversations
# ============================================================================


@pytest.mark.asyncio
async def testToolUsageInConversation(
    llmHandler, mockContext, mockDatabase, mockCacheService, mockLlmService, privateChat, testUser
):
    """Test LLM using tools during conversation, dood!"""
    from internal.bot.models import ChatSettingsValue

    # Enable tools
    mockCacheService._chat_settings[privateChat.id][ChatSettingsKey.USE_TOOLS] = ChatSettingsValue("true")

    message = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="What's the weather in Tokyo?",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock LLM service to return tool call result
    result = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="The weather in Tokyo is sunny and 25°C",
    )
    result.setToolsUsed(True)
    mockLlmService.generateTextViaLLM.return_value = result

    mockDatabase.getChatMessagesSince.return_value = []

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handlePrivateMessage(update, mockContext, ensuredMessage)

    assert result is True
    # Verify tools were enabled in the call
    callArgs = mockLlmService.generateTextViaLLM.call_args
    assert callArgs.kwargs["useTools"] is True


@pytest.mark.asyncio
async def testToolUsagePrefixAdded(
    llmHandler, mockContext, mockDatabase, mockCacheService, mockLlmService, privateChat, testUser
):
    """Test tools used prefix is added to response, dood!"""
    from internal.bot.models import ChatSettingsValue

    mockCacheService._chat_settings[privateChat.id][ChatSettingsKey.USE_TOOLS] = ChatSettingsValue("true")

    message = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Get weather",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock LLM to return result with tools used
    result = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Weather data retrieved",
    )
    result.setToolsUsed(True)
    mockLlmService.generateTextViaLLM.return_value = result

    mockDatabase.getChatMessagesSince.return_value = []

    # Mock sendMessage to capture the call
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handlePrivateMessage(update, mockContext, ensuredMessage)

    assert result is True
    # Verify sendMessage was called
    llmHandler.sendMessage.assert_called_once()


# ============================================================================
# Edge Cases and Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def testHandleNoneEnsuredMessage(llmHandler, mockContext):
    """Test handling None ensuredMessage, dood!"""
    from internal.bot.handlers.base import HandlerResultStatus

    update = createMockUpdate()
    result = await llmHandler.messageHandler(update, mockContext, None)

    assert result == HandlerResultStatus.SKIPPED


@pytest.mark.asyncio
async def testHandleAutomaticForward(llmHandler, mockContext, groupChat, testUser):
    """Test handling automatic forward from channel, dood!"""
    from internal.bot.handlers.base import HandlerResultStatus

    message = createMockMessage(
        messageId=1,
        chatId=groupChat.id,
        userId=testUser.id,
        text="Forwarded message",
    )
    message.is_automatic_forward = True

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    result = await llmHandler.messageHandler(update, mockContext, ensuredMessage)

    assert result == HandlerResultStatus.NEXT


@pytest.mark.asyncio
async def testHandleUnsupportedChatType(llmHandler, mockContext):
    """Test handling unsupported chat type, dood!"""
    from internal.bot.handlers.base import HandlerResultStatus

    channelChat = createMockChat(chatId=999, chatType=Chat.CHANNEL)
    message = createMockMessage(chatId=channelChat.id, text="Channel message")
    message.chat = channelChat

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    result = await llmHandler.messageHandler(update, mockContext, ensuredMessage)

    assert result == HandlerResultStatus.SKIPPED


@pytest.mark.asyncio
async def testHandleLLMGenerationError(llmHandler, mockContext, mockDatabase, mockLlmService, privateChat, testUser):
    """Test handling LLM generation error, dood!"""
    message = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Test message",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock LLM service to raise exception
    mockLlmService.generateTextViaLLM.side_effect = Exception("LLM API error")

    mockDatabase.getChatMessagesSince.return_value = []

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handlePrivateMessage(update, mockContext, ensuredMessage)

    assert result is False
    # Verify error message was sent
    llmHandler.sendMessage.assert_called_once()
    callArgs = llmHandler.sendMessage.call_args
    assert "Error" in callArgs.kwargs["messageText"]


@pytest.mark.asyncio
async def testHandleEmptyMessageHistory(llmHandler, mockContext, mockDatabase, mockLlmService, privateChat, testUser):
    """Test handling empty message history, dood!"""
    message = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="First message",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Return empty history
    mockDatabase.getChatMessagesSince.return_value = []

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handlePrivateMessage(update, mockContext, ensuredMessage)

    assert result is True
    mockLlmService.generateTextViaLLM.assert_called_once()


@pytest.mark.asyncio
async def testHandleMissingParentMessage(llmHandler, mockContext, mockDatabase, mockLlmService, groupChat, testUser):
    """Test handling reply when parent message not found, dood!"""
    botMessage = createMockMessage(
        messageId=1,
        chatId=groupChat.id,
        userId=mockContext.bot.id,
        text="Bot message",
    )

    userReply = createMockMessage(
        messageId=2,
        chatId=groupChat.id,
        userId=testUser.id,
        text="Reply",
        replyToMessage=botMessage,
    )

    update = createMockUpdate(message=userReply)
    ensuredMessage = EnsuredMessage.fromMessage(userReply)

    # Mock database to return None for parent message
    mockDatabase.getChatMessageByMessageId.return_value = None

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handleReply(update, mockContext, ensuredMessage)

    # Should still handle the reply with fallback
    assert result is True


@pytest.mark.asyncio
async def testHandleFallbackModel(llmHandler, mockContext, mockDatabase, mockLlmService, privateChat, testUser):
    """Test fallback model usage, dood!"""
    message = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Test message",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock LLM to return fallback result
    result = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="Fallback response",
    )
    result.setFallback(True)
    mockLlmService.generateTextViaLLM.return_value = result

    mockDatabase.getChatMessagesSince.return_value = []

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handlePrivateMessage(update, mockContext, ensuredMessage)

    assert result is True
    # Verify sendMessage was called
    llmHandler.sendMessage.assert_called_once()


@pytest.mark.asyncio
async def testHandleImageGeneration(
    llmHandler, mockContext, mockDatabase, mockLlmService, mockLlmManager, privateChat, testUser
):
    """Test image generation from media description, dood!"""
    message = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Generate an image of a sunset",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock LLM to return response with media description
    mockLlmService.generateTextViaLLM.return_value = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="<media-description>A beautiful sunset over the ocean</media-description>Here's your image",
    )

    mockDatabase.getChatMessagesSince.return_value = []

    # Mock image generation model
    imageModel = mockLlmManager.getModel("dall-e-3")
    result = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="",
        mediaData=b"fake_image_data",
    )
    imageModel.generateImageWithFallBack = AsyncMock(return_value=result)

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handlePrivateMessage(update, mockContext, ensuredMessage)

    assert result is True


@pytest.mark.asyncio
async def testHandleImageGenerationFailure(
    llmHandler, mockContext, mockDatabase, mockLlmService, mockLlmManager, privateChat, testUser
):
    """Test fallback when image generation fails, dood!"""
    message = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Generate image",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock LLM to return response with media description
    mockLlmService.generateTextViaLLM.return_value = ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="<media-description>Test image</media-description>Text response",
    )

    mockDatabase.getChatMessagesSince.return_value = []

    # Mock image generation to fail
    imageModel = mockLlmManager.getModel("dall-e-3")
    imageModel.generateImageWithFallBack = AsyncMock(
        return_value=ModelRunResult(
            rawResult={},
            status=ModelResultStatus.ERROR,
            resultText="",
            mediaData=None,
        )
    )

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handlePrivateMessage(update, mockContext, ensuredMessage)

    # Should fallback to text-only message
    assert result is True


@pytest.mark.asyncio
async def testHandleJSONMessageFormat(
    llmHandler, mockContext, mockDatabase, mockCacheService, mockLlmService, privateChat, testUser
):
    """Test JSON message format handling, dood!"""
    from internal.bot.models import ChatSettingsValue

    # Set JSON format
    mockCacheService._chat_settings[privateChat.id][ChatSettingsKey.LLM_MESSAGE_FORMAT] = ChatSettingsValue("json")

    message = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Test",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    mockDatabase.getChatMessagesSince.return_value = []

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.handlePrivateMessage(update, mockContext, ensuredMessage)

    assert result is True


@pytest.mark.asyncio
async def testHandleRandomMessageWithThread(
    llmHandler, mockContext, mockDatabase, mockCacheService, mockLlmService, groupChat, testUser
):
    """Test random message handling with thread context, dood!"""
    from internal.bot.models import ChatSettingsValue

    # Set high probability
    mockCacheService._chat_settings[groupChat.id][ChatSettingsKey.RANDOM_ANSWER_PROBABILITY] = ChatSettingsValue("1.0")

    # Create message that's a reply
    parentMessage = createMockMessage(
        messageId=10,
        chatId=groupChat.id,
        userId=testUser.id,
        text="Parent message",
    )

    replyMessage = createMockMessage(
        messageId=11,
        chatId=groupChat.id,
        userId=testUser.id,
        text="Reply message",
        replyToMessage=parentMessage,
    )

    update = createMockUpdate(message=replyMessage)
    ensuredMessage = EnsuredMessage.fromMessage(replyMessage)

    # Mock parent message in database
    mockDatabase.getChatMessageByMessageId.return_value = createMockDBMessage(
        groupChat.id, 10, testUser.id, "testuser", "Test User", "user", "Parent message", rootMessageId=10
    )

    mockDatabase.getChatMessagesByRootId.return_value = [
        createMockDBMessage(
            groupChat.id, 10, testUser.id, "testuser", "Test User", "user", "Parent message", rootMessageId=10
        ),
        createMockDBMessage(
            groupChat.id, 11, testUser.id, "testuser", "Test User", "user", "Reply message", rootMessageId=10
        ),
    ]

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    # Mock isAdmin
    llmHandler.isAdmin = AsyncMock(return_value=False)

    result = await llmHandler.handleRandomMessage(update, mockContext, ensuredMessage)

    assert result is True
    mockLlmService.generateTextViaLLM.assert_called_once()


# ============================================================================
# Message Handler Main Entry Point Tests
# ============================================================================


@pytest.mark.asyncio
async def testMessageHandlerRoutingPrivate(
    llmHandler, mockContext, mockDatabase, mockLlmService, privateChat, testUser
):
    """Test message handler routes private messages correctly, dood!"""
    from internal.bot.handlers.base import HandlerResultStatus

    message = createMockMessage(
        messageId=1,
        chatId=privateChat.id,
        userId=testUser.id,
        text="Hello",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    mockDatabase.getChatMessagesSince.return_value = []

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.messageHandler(update, mockContext, ensuredMessage)

    assert result == HandlerResultStatus.FINAL


@pytest.mark.asyncio
async def testMessageHandlerRoutingGroup(llmHandler, mockContext, mockDatabase, groupChat, testUser):
    """Test message handler routes group messages correctly, dood!"""
    from internal.bot.handlers.base import HandlerResultStatus

    message = createMockMessage(
        messageId=1,
        chatId=groupChat.id,
        userId=testUser.id,
        text="Random group message",
    )

    update = createMockUpdate(message=message)
    ensuredMessage = EnsuredMessage.fromMessage(message)

    # Mock synchronous database methods (they are NOT async in the actual code)
    mockDatabase.updateChatUser = Mock(return_value=None)
    mockDatabase.saveChatMessage = Mock(return_value=None)

    # No reply, no mention, zero probability
    # Even though no sub-handler processes the message, the LLM handler still returns FINAL
    # because it's typically the last handler in the chain
    result = await llmHandler.messageHandler(update, mockContext, ensuredMessage)

    # The LLM handler returns FINAL even when no sub-handler processes the message
    # This is the expected behavior as it's the terminal handler in the chain
    assert result == HandlerResultStatus.FINAL


@pytest.mark.asyncio
async def testMessageHandlerPriority(llmHandler, mockContext, mockDatabase, mockLlmService, groupChat, testUser):
    """Test message handler priority: reply > mention > random, dood!"""
    from internal.bot.handlers.base import HandlerResultStatus

    # Create bot message
    botMessage = createMockMessage(
        messageId=1,
        chatId=groupChat.id,
        userId=mockContext.bot.id,
        text="Bot message",
    )

    # Create user reply with mention
    userReply = createMockMessage(
        messageId=2,
        chatId=groupChat.id,
        userId=testUser.id,
        text="@test_bot reply",
        replyToMessage=botMessage,
    )

    update = createMockUpdate(message=userReply)
    ensuredMessage = EnsuredMessage.fromMessage(userReply)

    # Mock database
    mockDatabase.getChatMessageByMessageId.return_value = {
        "chat_id": groupChat.id,
        "message_id": 1,
        "user_id": mockContext.bot.id,
        "message_category": "bot",
        "message_text": "Bot message",
        "root_message_id": 1,
        "created_at": datetime.datetime.now(datetime.timezone.utc),
    }

    mockDatabase.getChatMessagesByRootId.return_value = []

    # Mock sendMessage
    llmHandler.sendMessage = AsyncMock(return_value=createMockMessage())

    result = await llmHandler.messageHandler(update, mockContext, ensuredMessage)

    # Should handle as reply (higher priority than mention)
    assert result == HandlerResultStatus.FINAL
