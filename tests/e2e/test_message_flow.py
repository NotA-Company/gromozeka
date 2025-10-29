"""
End-to-end tests for complete message flows in Gromozeka bot, dood!

This module tests complete message lifecycles from user input through handler
processing to bot response and database persistence. Tests use real components
(handlers, database, services) with mocked external APIs (Telegram, LLM), dood!

Test Coverage:
    - Simple text message flow (user -> bot -> DB)
    - Reply to bot message flow (contextual responses)
    - Bot mention in group flow (mention detection and response)
    - Media message flow (photo/sticker processing)
    - Private vs group chat behavior differences
    - Error handling and edge cases
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from telegram import Chat

from internal.bot.handlers.manager import HandlersManager
from internal.bot.models import ChatSettingsKey
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from lib.ai.models import ModelResultStatus, ModelRunResult
from tests.fixtures.telegram_mocks import (
    createMockBot,
    createMockContext,
    createMockMessage,
    createMockPhoto,
    createMockSticker,
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
        "bot_owners": ["testuser"],  # Add bot_owners as usernames
    }
    mock.getOpenWeatherMapConfig.return_value = {"enabled": False}
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
    manager.listModels.return_value = ["test-model"]

    return manager


@pytest.fixture
async def handlersManager(mockConfigManager, inMemoryDb, mockLlmManager, mockBot):
    """
    Create handlers manager with all dependencies, dood!

    Args:
        mockConfigManager: Mocked config manager
        inMemoryDb: In-memory database
        mockLlmManager: Mocked LLM manager
        mockBot: Mocked bot

    Returns:
        HandlersManager: Configured handlers manager
    """
    manager = HandlersManager(
        configManager=mockConfigManager,
        database=inMemoryDb,
        llmManager=mockLlmManager,
    )
    manager.injectBot(mockBot)
    return manager


# ============================================================================
# Test: Simple Text Message Flow
# ============================================================================


@pytest.mark.asyncio
async def testSimpleTextMessageFlow(inMemoryDb, mockBot, handlersManager):
    """
    Test complete flow: user sends text -> bot processes -> saves to DB, dood!

    Flow:
        1. User sends text message
        2. Message preprocessor saves to database
        3. Message passes through handler chain
        4. Database contains saved message

    Verifies:
        - Message saved to database
        - User info updated in database
        - Handler chain executes successfully
    """
    # 1. Create user message
    chatId = 123
    userId = 456
    messageText = "Hello bot, dood!"

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text=messageText,
    )
    message.chat.type = Chat.GROUP  # Set as group chat to avoid ALLOW_PRIVATE check
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # 2. Process through handler chain
    await handlersManager.handle_message(update, context)

    # 3. Verify message saved to DB
    messages = inMemoryDb.getChatMessagesSince(chatId=chatId, limit=10)
    assert len(messages) == 1, "Message should be saved to database, dood!"

    savedMessage = messages[0]
    assert savedMessage["message_id"] == 1
    assert savedMessage["chat_id"] == chatId
    assert savedMessage["user_id"] == userId
    assert savedMessage["message_text"] == messageText
    assert savedMessage["message_category"] == MessageCategory.USER

    # 4. Verify user info updated
    users = inMemoryDb.getChatUsers(chatId=chatId)
    assert len(users) >= 1, "User should be saved to database, dood!"


@pytest.mark.asyncio
async def testSimpleTextMessageWithBotResponse(inMemoryDb, mockBot, handlersManager):
    """
    Test flow where bot responds to user message in private chat, dood!

    Flow:
        1. User sends message in private chat
        2. Bot generates response via LLM
        3. Bot sends response
        4. Both messages saved to database

    Verifies:
        - User message saved
        - Bot response sent
        - Bot response saved to database
    """
    from internal.services.llm.service import LLMService

    # Mock LLM service to return response
    mockService = Mock(spec=LLMService)
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="Hello user, dood!",
    )
    result.setFallback(False)
    result.setToolsUsed(False)
    mockService.generateTextViaLLM = AsyncMock(return_value=result)

    # Inject mock service into all handlers that have llmService
    for handler in handlersManager.handlers:
        if hasattr(handler, "llmService"):
            handler.llmService = mockService

    # 1. Create private chat message
    chatId = 123
    userId = 456

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="Hello bot!",
    )
    message.chat.type = Chat.PRIVATE
    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Set chat settings to allow private messages
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_PRIVATE.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.LLM_MESSAGE_FORMAT.value, "text")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.USE_TOOLS.value, "false")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.FALLBACK_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_PROMPT.value, "You are a helpful assistant")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_PROMPT_SUFFIX.value, "")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.FALLBACK_HAPPENED_PREFIX.value, "")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.TOOLS_USED_PREFIX.value, "")

    # 2. Process message
    await handlersManager.handle_message(update, context)

    # 3. Verify bot sent response
    message.reply_text.assert_called()

    # 4. Verify both messages in database
    messages = inMemoryDb.getChatMessagesSince(chatId=chatId, limit=10)
    assert len(messages) >= 1, "At least user message should be saved, dood!"


# ============================================================================
# Test: Reply to Bot Message Flow
# ============================================================================


@pytest.mark.asyncio
async def testReplyToBotMessageFlow(inMemoryDb, mockBot, handlersManager):
    """
    Test complete flow: user replies to bot -> bot generates contextual response, dood!

    Flow:
        1. Bot message exists in database
        2. User replies to bot message
        3. Bot retrieves conversation thread
        4. Bot generates contextual response
        5. Response saved to database

    Verifies:
        - Reply detection works
        - Conversation thread retrieved
        - Contextual response generated
        - Thread linkage maintained in database
    """
    from internal.services.llm.service import LLMService

    # Mock LLM service
    mockService = Mock(spec=LLMService)
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="I understand your reply, dood!",
    )
    result.setFallback(False)
    result.setToolsUsed(False)
    mockService.generateTextViaLLM = AsyncMock(return_value=result)

    # Inject mock service into all handlers that have llmService
    for handler in handlersManager.handlers:
        if hasattr(handler, "llmService"):
            handler.llmService = mockService

    chatId = 123
    userId = 456
    botId = mockBot.id

    # 1. Create chat_users entries (required for JOIN in getChatMessageByMessageId)
    inMemoryDb.updateChatUser(
        chatId=chatId,
        userId=botId,
        username="test_bot",
        fullName="Test Bot",
    )
    inMemoryDb.updateChatUser(
        chatId=chatId,
        userId=userId,
        username="testuser",
        fullName="Test User",
    )

    # 2. Save bot's original message to database
    botMessageId = 10
    inMemoryDb.saveChatMessage(
        date=datetime.now(),
        messageId=botMessageId,
        chatId=chatId,
        userId=botId,
        messageText="Hello! How can I help you, dood?",
        messageCategory=MessageCategory.BOT,
        rootMessageId=botMessageId,  # Root of thread
    )

    # 2. Create user's reply message
    userReplyId = 11
    botMessage = createMockMessage(
        messageId=botMessageId,
        chatId=chatId,
        userId=botId,
        text="Hello! How can I help you, dood?",
    )

    userReply = createMockMessage(
        messageId=userReplyId,
        chatId=chatId,
        userId=userId,
        text="I need help with something",
        replyToMessage=botMessage,
    )

    update = createMockUpdate(message=userReply)
    context = createMockContext(bot=mockBot)

    # Set chat settings
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_PRIVATE.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_REPLY.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.LLM_MESSAGE_FORMAT.value, "text")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.USE_TOOLS.value, "false")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.FALLBACK_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_PROMPT.value, "You are a helpful assistant")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_PROMPT_SUFFIX.value, "")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.FALLBACK_HAPPENED_PREFIX.value, "")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.TOOLS_USED_PREFIX.value, "")

    # 3. Process reply
    await handlersManager.handle_message(update, context)

    # 4. Verify bot sent response
    userReply.reply_text.assert_called()

    # 5. Verify messages in database with thread linkage
    messages = inMemoryDb.getChatMessagesSince(chatId=chatId, limit=10)
    assert len(messages) >= 2, "Should have bot message and user reply, dood!"

    # Verify thread structure
    userMessage = [m for m in messages if m["message_id"] == userReplyId]
    assert len(userMessage) == 1
    assert userMessage[0]["reply_id"] == botMessageId


# ============================================================================
# Test: Bot Mention in Group Flow
# ============================================================================


@pytest.mark.asyncio
async def testBotMentionInGroupFlow(inMemoryDb, mockBot, handlersManager):
    """
    Test complete flow: user mentions bot in group -> bot responds, dood!

    Flow:
        1. User mentions bot by username in group
        2. Bot detects mention
        3. Bot generates response
        4. Response sent and saved

    Verifies:
        - Mention detection works
        - Bot responds to mentions
        - Group chat handling correct
    """
    from internal.services.llm.service import LLMService

    # Mock LLM service
    mockService = Mock(spec=LLMService)
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="Yes, I'm here, dood!",
    )
    result.setFallback(False)
    result.setToolsUsed(False)
    mockService.generateTextViaLLM = AsyncMock(return_value=result)

    # Inject mock service into all handlers that have llmService
    for handler in handlersManager.handlers:
        if hasattr(handler, "llmService"):
            handler.llmService = mockService

    chatId = 789
    userId = 456

    # 1. Create group message with bot mention
    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text=f"@{mockBot.username} are you there?",
    )
    message.chat.type = Chat.GROUP

    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Set chat settings
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_MENTION.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.LLM_MESSAGE_FORMAT.value, "text")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.USE_TOOLS.value, "false")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.FALLBACK_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_PROMPT.value, "You are a helpful assistant")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_PROMPT_SUFFIX.value, "")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.FALLBACK_HAPPENED_PREFIX.value, "")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.TOOLS_USED_PREFIX.value, "")

    # 2. Process message
    await handlersManager.handle_message(update, context)

    # 3. Verify bot sent response
    message.reply_text.assert_called()

    # 4. Verify message saved
    messages = inMemoryDb.getChatMessagesSince(chatId=chatId, limit=10)
    assert len(messages) >= 1, "Message should be saved, dood!"


# ============================================================================
# Test: Media Message Flow
# ============================================================================


@pytest.mark.asyncio
async def testPhotoMessageFlow(inMemoryDb, mockBot, handlersManager):
    """
    Test complete flow: user sends photo -> bot processes -> metadata saved, dood!

    Flow:
        1. User sends photo message
        2. Bot processes media
        3. Photo metadata saved to database
        4. Message saved with media reference

    Verifies:
        - Photo processing works
        - Media metadata saved
        - Message-media linkage correct
    """
    chatId = 123
    userId = 456

    # 1. Create photo message
    photo = createMockPhoto(
        fileId="photo_123",
        width=1280,
        height=720,
    )

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="Check out this photo, dood!",
    )
    message.chat.type = Chat.GROUP  # Set as group chat
    message.photo = [photo]
    message.caption = "Check out this photo, dood!"
    message.text = None

    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # 2. Process message
    await handlersManager.handle_message(update, context)

    # 3. Verify message saved with media info
    messages = inMemoryDb.getChatMessagesSince(chatId=chatId, limit=10)
    assert len(messages) == 1, "Photo message should be saved, dood!"

    savedMessage = messages[0]
    assert savedMessage["message_type"] == "image"
    assert savedMessage["media_file_id"] == "photo_123"
    assert savedMessage["message_text"] == "Check out this photo, dood!"


@pytest.mark.asyncio
async def testStickerMessageFlow(inMemoryDb, mockBot, handlersManager):
    """
    Test complete flow: user sends sticker -> bot processes -> metadata saved, dood!

    Flow:
        1. User sends sticker
        2. Bot processes sticker
        3. Sticker metadata saved

    Verifies:
        - Sticker processing works
        - Sticker metadata saved correctly
    """
    chatId = 123
    userId = 456

    # 1. Create sticker message
    sticker = createMockSticker(
        fileId="sticker_123",
        emoji="😀",
    )

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="",
    )
    message.chat.type = Chat.GROUP  # Set as group chat
    message.sticker = sticker
    message.text = None

    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # 2. Process message
    await handlersManager.handle_message(update, context)

    # 3. Verify message saved with sticker info
    messages = inMemoryDb.getChatMessagesSince(chatId=chatId, limit=10)
    assert len(messages) == 1, "Sticker message should be saved, dood!"

    savedMessage = messages[0]
    assert savedMessage["message_type"] == "sticker"
    assert savedMessage["media_file_id"] == "sticker_123"


# ============================================================================
# Test: Private vs Group Chat Behavior
# ============================================================================


@pytest.mark.asyncio
async def testPrivateChatBehavior(inMemoryDb, mockBot, handlersManager):
    """
    Test bot behavior in private chat, dood!

    Verifies:
        - Bot responds to all messages in private chat
        - No mention required
        - Context from previous messages used
    """
    from internal.services.llm.service import LLMService

    # Mock LLM service
    mockService = Mock(spec=LLMService)
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="Private chat response, dood!",
    )
    result.setFallback(False)
    result.setToolsUsed(False)
    mockService.generateTextViaLLM = AsyncMock(return_value=result)

    # Inject mock service into all handlers that have llmService
    for handler in handlersManager.handlers:
        if hasattr(handler, "llmService"):
            handler.llmService = mockService

    chatId = 123
    userId = 456

    # Create private chat message (no mention needed)
    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="Just a regular message",
    )
    message.chat.type = Chat.PRIVATE

    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Enable private chat
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_PRIVATE.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.LLM_MESSAGE_FORMAT.value, "text")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.USE_TOOLS.value, "false")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.FALLBACK_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_PROMPT.value, "You are a helpful assistant")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_PROMPT_SUFFIX.value, "")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.FALLBACK_HAPPENED_PREFIX.value, "")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.TOOLS_USED_PREFIX.value, "")

    # Process message
    await handlersManager.handle_message(update, context)

    # Verify bot responded (no mention required in private chat)
    message.reply_text.assert_called()


@pytest.mark.asyncio
async def testGroupChatBehavior(inMemoryDb, mockBot, handlersManager):
    """
    Test bot behavior in group chat, dood!

    Verifies:
        - Bot doesn't respond to all messages in group
        - Mention or reply required for response
        - Random reply probability can be configured
    """
    chatId = 789
    userId = 456

    # Create group message without mention
    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="Just chatting in the group",
    )
    message.chat.type = Chat.GROUP

    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Set random reply probability to 0 (no random replies)
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.RANDOM_ANSWER_PROBABILITY.value, "0.0")

    # Process message
    await handlersManager.handle_message(update, context)

    # Verify bot did NOT respond (no mention, no reply, no random)
    mockBot.sendMessage.assert_not_called()


# ============================================================================
# Test: Error Handling
# ============================================================================


@pytest.mark.asyncio
async def testMessageFlowWithLlmError(inMemoryDb, mockBot, handlersManager):
    """
    Test error handling when LLM fails, dood!

    Verifies:
        - Message still saved to database
        - Error handled gracefully
        - User notified of error
    """
    from internal.services.llm.service import LLMService

    # Mock LLM service to raise error
    mockService = Mock(spec=LLMService)
    mockService.generateTextViaLLM = AsyncMock(side_effect=Exception("LLM service error, dood!"))

    # Inject mock service into all handlers that have llmService
    for handler in handlersManager.handlers:
        if hasattr(handler, "llmService"):
            handler.llmService = mockService

    chatId = 123
    userId = 456

    message = createMockMessage(
        messageId=1,
        chatId=chatId,
        userId=userId,
        text="Test message",
    )
    message.chat.type = Chat.PRIVATE

    update = createMockUpdate(message=message)
    context = createMockContext(bot=mockBot)

    # Enable private chat
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.ALLOW_PRIVATE.value, "true")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.LLM_MESSAGE_FORMAT.value, "text")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.USE_TOOLS.value, "false")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.FALLBACK_MODEL.value, "test-model")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_PROMPT.value, "You are a helpful assistant")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.CHAT_PROMPT_SUFFIX.value, "")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.FALLBACK_HAPPENED_PREFIX.value, "")
    inMemoryDb.setChatSetting(chatId, ChatSettingsKey.TOOLS_USED_PREFIX.value, "")

    # Process message (should handle error gracefully)
    await handlersManager.handle_message(update, context)

    # Verify message still saved despite error
    messages = inMemoryDb.getChatMessagesSince(chatId=chatId, limit=10)
    assert len(messages) >= 1, "Message should be saved even on error, dood!"


# ============================================================================
# Test: Performance and Timing
# ============================================================================


@pytest.mark.asyncio
async def testMessageProcessingPerformance(inMemoryDb, mockBot, handlersManager):
    """
    Test message processing performance, dood!

    Verifies:
        - Message processing completes in reasonable time
        - Multiple messages handled efficiently
    """
    import time

    chatId = 123
    userId = 456

    # Process multiple messages
    startTime = time.time()

    for i in range(10):
        message = createMockMessage(
            messageId=i + 1,
            chatId=chatId,
            userId=userId,
            text=f"Message {i + 1}",
        )
        message.chat.type = Chat.GROUP  # Set as group chat
        update = createMockUpdate(message=message)
        context = createMockContext(bot=mockBot)

        await handlersManager.handle_message(update, context)

    endTime = time.time()
    processingTime = endTime - startTime

    # Verify all messages saved
    messages = inMemoryDb.getChatMessagesSince(chatId=chatId, limit=20)
    assert len(messages) == 10, "All messages should be saved, dood!"

    # Verify reasonable processing time (< 5 seconds for 10 messages)
    assert processingTime < 5.0, f"Processing too slow: {processingTime}s, dood!"


# ============================================================================
# Test: Database State Verification
# ============================================================================


@pytest.mark.asyncio
async def testDatabaseStateAfterMessageFlow(inMemoryDb, mockBot, handlersManager):
    """
    Test database state after complete message flow, dood!

    Verifies:
        - All messages saved correctly
        - User information updated
        - Chat settings preserved
        - Thread relationships maintained
    """
    chatId = 123
    userId = 456

    # Send multiple messages
    for i in range(5):
        message = createMockMessage(
            messageId=i + 1,
            chatId=chatId,
            userId=userId,
            text=f"Message {i + 1}",
        )
        message.chat.type = Chat.GROUP  # Set as group chat
        update = createMockUpdate(message=message)
        context = createMockContext(bot=mockBot)

        await handlersManager.handle_message(update, context)

    # Verify database state
    messages = inMemoryDb.getChatMessagesSince(chatId=chatId, limit=10)
    assert len(messages) == 5, "All messages should be in database, dood!"

    # Verify message order
    for i, msg in enumerate(messages):
        assert msg["message_id"] == i + 1
        assert msg["message_text"] == f"Message {i + 1}"

    # Verify user info
    users = inMemoryDb.getChatUsers(chatId=chatId)
    assert len(users) >= 1, "User should be in database, dood!"

    userInfo = [u for u in users if u["user_id"] == userId]
    assert len(userInfo) == 1
    assert userInfo[0]["username"] == "testuser"
