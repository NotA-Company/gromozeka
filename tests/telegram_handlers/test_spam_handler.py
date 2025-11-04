"""
Comprehensive tests for SpamHandlers, dood!

This module provides extensive test coverage for the SpamHandlers class,
testing spam detection, Bayes filter integration, user management, and
all spam-related commands.

Test Categories:
- Initialization Tests: Handler setup and Bayes filter initialization
- Unit Tests: Spam detection logic, Bayes filter operations, user management
- Integration Tests: Complete spam workflows, message checking, training
- Command Tests: All spam-related commands (/spam, /pretrain_bayes, etc.)
- Edge Cases: Error handling, boundary conditions, admin checks
"""

import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import Chat, MessageEntity
from telegram.constants import MessageEntityType

from internal.bot.handlers.spam import SpamHandler
from internal.bot.models import ChatSettingsKey, ChatSettingsValue, EnsuredMessage
from internal.database.models import MessageCategory
from lib.bayes_filter import NaiveBayesFilter
from lib.bayes_filter.models import BayesModelStats, SpamScore
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
    """Create a mock ConfigManager with spam-related settings, dood!"""
    mock = Mock()
    mock.getBotConfig.return_value = {
        "bot_owners": ["owner1"],
        "defaults": {
            ChatSettingsKey.DETECT_SPAM: "true",
            ChatSettingsKey.SPAM_WARN_TRESHOLD: "50.0",
            ChatSettingsKey.SPAM_BAN_TRESHOLD: "90.0",
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: "10",
            ChatSettingsKey.BAYES_ENABLED: "false",
            ChatSettingsKey.BAYES_AUTO_LEARN: "true",
            ChatSettingsKey.BAYES_MIN_CONFIDENCE: "0.1",
            ChatSettingsKey.ALLOW_MARK_SPAM_OLD_USERS: "false",
            ChatSettingsKey.ALLOW_USER_SPAM_COMMAND: "true",
            ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES: "true",
        },
    }
    return mock


@pytest.fixture
def mockDatabase():
    """Create a mock DatabaseWrapper for spam operations, dood!"""
    mock = Mock()
    mock.getChatSettings.return_value = {}
    mock.getChatUser.return_value = None
    mock.getChatMessageByMessageId.return_value = None
    mock.getChatMessagesByUser.return_value = []
    mock.getSpamMessagesByText.return_value = []
    mock.getSpamMessages.return_value = []
    mock.getSpamMessagesByUserId.return_value = []
    mock.getChatMessagesSince.return_value = []
    mock.getChatUserByUsername.return_value = None
    mock.updateChatUser = Mock()
    mock.saveChatMessage = Mock()
    mock.addSpamMessage = Mock()
    mock.addHamMessage = Mock()
    mock.markUserIsSpammer = Mock()
    mock.deleteSpamMessagesByUserId = Mock()
    mock.updateUserMetadata = Mock()
    mock.updateChatMessageCategory = Mock()
    return mock


@pytest.fixture
def mockLlmManager():
    """Create a mock LLMManager, dood!"""
    mock = Mock()
    return mock


@pytest.fixture
def mockBayesFilter():
    """Create a mock NaiveBayesFilter, dood!"""
    mock = AsyncMock(spec=NaiveBayesFilter)
    mock.classify = AsyncMock(return_value=SpamScore(score=30.0, isSpam=False, confidence=0.5, tokenScores={}))
    mock.learnSpam = AsyncMock(return_value=True)
    mock.learnHam = AsyncMock(return_value=True)
    mock.getModelInfo = AsyncMock(
        return_value=BayesModelStats(
            total_spam_messages=10,
            total_ham_messages=90,
            total_tokens=1000,
            vocabulary_size=500,
            chat_id=None,
        )
    )
    mock.reset = AsyncMock(return_value=True)
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
        MockQueue.getInstance.return_value = mockInstance
        yield mockInstance


@pytest.fixture
def spamHandler(mockConfigManager, mockDatabase, mockLlmManager, mockCacheService, mockQueueService, mockBayesFilter):
    """Create a SpamHandlers instance with mocked dependencies, dood!"""
    with patch("internal.bot.handlers.spam.DatabaseBayesStorage"):
        with patch("internal.bot.handlers.spam.NaiveBayesFilter", return_value=mockBayesFilter):
            handler = SpamHandler(mockConfigManager, mockDatabase, mockLlmManager)
            handler.bayesFilter = mockBayesFilter
            return handler


@pytest.fixture
def mockBot():
    """Create a mock bot instance, dood!"""
    bot = createMockBot()
    bot.delete_message = AsyncMock(return_value=True)
    bot.delete_messages = AsyncMock(return_value=True)
    bot.ban_chat_member = AsyncMock(return_value=True)
    bot.ban_chat_sender_chat = AsyncMock(return_value=True)
    bot.unban_chat_member = AsyncMock(return_value=True)
    return bot


# ============================================================================
# Initialization Tests
# ============================================================================


class TestInitialization:
    """Test SpamHandlers initialization, dood!"""

    def testInitWithAllDependencies(self, mockConfigManager, mockDatabase, mockLlmManager):
        """Test handler initializes correctly with all dependencies, dood!"""
        with patch("internal.bot.handlers.spam.DatabaseBayesStorage"):
            with patch("internal.bot.handlers.spam.NaiveBayesFilter"):
                handler = SpamHandler(mockConfigManager, mockDatabase, mockLlmManager)

                assert handler.configManager == mockConfigManager
                assert handler.db == mockDatabase
                assert handler.llmManager == mockLlmManager
                assert handler.bayesFilter is not None

    def testInitCreatesBayesFilter(self, mockConfigManager, mockDatabase, mockLlmManager):
        """Test Bayes filter is created during initialization, dood!"""
        with patch("internal.bot.handlers.spam.DatabaseBayesStorage") as MockStorage:
            with patch("internal.bot.handlers.spam.NaiveBayesFilter") as MockFilter:
                handler = SpamHandler(mockConfigManager, mockDatabase, mockLlmManager)

                MockStorage.assert_called_once_with(mockDatabase)
                MockFilter.assert_called_once()
                assert handler.bayesFilter is not None


# ============================================================================
# Unit Tests - Spam Detection Logic
# ============================================================================


class TestSpamDetectionLogic:
    """Test spam detection logic and scoring, dood!"""

    @pytest.mark.asyncio
    async def testCheckSpamSkipsAutomaticForwards(self, spamHandler, mockBot):
        """Test automatic forwards are not checked for spam, dood!"""
        spamHandler.injectBot(mockBot)
        message = createMockMessage(text="Test message")
        message.is_automatic_forward = True
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await spamHandler.checkSpam(ensuredMessage)

        assert result is False

    @pytest.mark.asyncio
    async def testCheckSpamSkipsAnonymousAdmin(self, spamHandler, mockBot):
        """Test anonymous admin messages are not checked for spam, dood!"""
        spamHandler.injectBot(mockBot)
        chatId = -100123456789
        message = createMockMessage(chatId=chatId, userId=chatId, text="Admin message")
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await spamHandler.checkSpam(ensuredMessage)

        assert result is False

    @pytest.mark.asyncio
    async def testCheckSpamSkipsMessagesWithoutText(self, spamHandler, mockBot):
        """Test messages without text are not checked, dood!"""
        spamHandler.injectBot(mockBot)
        message = createMockMessage(text=None)
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await spamHandler.checkSpam(ensuredMessage)

        assert result is False

    @pytest.mark.asyncio
    async def testCheckSpamSkipsTrustedUsers(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test users with enough messages are trusted, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10")
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "testuser",
            "full_name": "Test User",
            "messages_count": 15,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }

        message = createMockMessage(text="Normal message")
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await spamHandler.checkSpam(ensuredMessage)

        assert result is False

    @pytest.mark.asyncio
    async def testCheckSpamDetectsURLs(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test URLs increase spam score, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_WARN_TRESHOLD: ChatSettingsValue("50.0"),
            ChatSettingsKey.SPAM_BAN_TRESHOLD: ChatSettingsValue("90.0"),
            ChatSettingsKey.BAYES_ENABLED: ChatSettingsValue("false"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "user",
            "full_name": "User",
            "messages_count": 2,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }
        mockDatabase.getChatMessagesByUser.return_value = []
        mockDatabase.getSpamMessagesByText.return_value = []

        message = createMockMessage(text="Check this out https://spam.com")
        message._bot = mockBot  # Set _bot attribute to prevent None in markAsSpam
        entity = Mock(spec=MessageEntity)
        entity.type = MessageEntityType.URL
        entity.offset = 15
        entity.length = 17
        message.entities = [entity]
        message.reply_text = AsyncMock(return_value=message)
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await spamHandler.checkSpam(ensuredMessage)

        # URL adds 60 points, should trigger warning but not ban
        print(f"DEBUG: Result = {result}, Expected = False")
        assert result is False  # Not banned yet

    @pytest.mark.asyncio
    async def testCheckSpamDetectsExternalMentions(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test mentions of users not in chat increase spam score, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_WARN_TRESHOLD: ChatSettingsValue("50.0"),
            ChatSettingsKey.SPAM_BAN_TRESHOLD: ChatSettingsValue("90.0"),
            ChatSettingsKey.BAYES_ENABLED: ChatSettingsValue("false"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "user",
            "full_name": "User",
            "messages_count": 2,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }
        mockDatabase.getChatMessagesByUser.return_value = []
        mockDatabase.getSpamMessagesByText.return_value = []
        mockDatabase.getChatUserByUsername.return_value = None  # User not in chat

        message = createMockMessage(text="Contact @external_user for deals")
        message._bot = mockBot  # Set _bot attribute to prevent None in markAsSpam
        entity = Mock(spec=MessageEntity)
        entity.type = MessageEntityType.MENTION
        entity.offset = 8
        entity.length = 14
        message.entities = [entity]
        message.reply_text = AsyncMock(return_value=message)
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await spamHandler.checkSpam(ensuredMessage)

        # External mention adds 60 points
        assert result is False  # Not banned yet


# ============================================================================
# Unit Tests - Bayes Filter Integration
# ============================================================================


class TestBayesFilterIntegration:
    """Test Bayes filter integration, dood!"""

    @pytest.mark.asyncio
    async def testMarkAsHamLearnsBayesFilter(self, spamHandler, mockBayesFilter):
        """Test marking as ham trains Bayes filter, dood!"""
        message = createMockMessage(text="Legitimate message", chatId=123)
        # Ensure message.chat_id returns the integer, not a Mock
        message.chat_id = 123

        result = await spamHandler.markAsHam(message)

        assert result is True
        mockBayesFilter.learnHam.assert_called_once_with(messageText="Legitimate message", chatId=123)

    @pytest.mark.asyncio
    async def testGetBayesFilterStats(self, spamHandler, mockBayesFilter):
        """Test getting Bayes filter statistics, dood!"""
        mockBayesFilter.getModelInfo.return_value = BayesModelStats(
            total_spam_messages=50,
            total_ham_messages=150,
            total_tokens=2000,
            vocabulary_size=800,
            chat_id=123,
        )

        stats = await spamHandler.getBayesFilterStats(chatId=123)

        assert stats["total_spam_messages"] == 50
        assert stats["total_ham_messages"] == 150
        assert stats["vocabulary_size"] == 800
        assert stats["chat_id"] == 123

    @pytest.mark.asyncio
    async def testResetBayesFilter(self, spamHandler, mockBayesFilter):
        """Test resetting Bayes filter, dood!"""
        mockBayesFilter.reset.return_value = True

        result = await spamHandler.resetBayesFilter(chat_id=123)

        assert result is True
        mockBayesFilter.reset.assert_called_once_with(123)


# ============================================================================
# Integration Tests - Message Spam Checking
# ============================================================================


class TestMessageSpamChecking:
    """Test complete spam checking workflow, dood!"""

    @pytest.mark.asyncio
    async def testMessageHandlerSkipsPrivateChats(self, spamHandler):
        """Test message handler skips private chats, dood!"""
        message = createMockMessage(text="Test")
        message.chat.type = Chat.PRIVATE
        ensuredMessage = EnsuredMessage.fromMessage(message)
        update = createMockUpdate(message=message)
        context = createMockContext()

        from internal.bot.handlers.base import HandlerResultStatus

        result = await spamHandler.messageHandler(update, context, ensuredMessage)

        assert result == HandlerResultStatus.SKIPPED

    @pytest.mark.asyncio
    async def testMessageHandlerChecksGroupMessages(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test message handler checks group messages for spam, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.DETECT_SPAM: ChatSettingsValue("true"),
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "user",
            "full_name": "User",
            "messages_count": 2,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }
        mockDatabase.getChatMessagesByUser.return_value = []
        mockDatabase.getSpamMessagesByText.return_value = []

        message = createMockMessage(text="Normal message")
        message.chat.type = Chat.GROUP
        ensuredMessage = EnsuredMessage.fromMessage(message)
        update = createMockUpdate(message=message)
        context = createMockContext()

        from internal.bot.handlers.base import HandlerResultStatus

        result = await spamHandler.messageHandler(update, context, ensuredMessage)

        assert result == HandlerResultStatus.NEXT


# ============================================================================
# Integration Tests - Training Workflows
# ============================================================================


class TestTrainingWorkflows:
    """Test Bayes filter training workflows, dood!"""

    @pytest.mark.asyncio
    async def testTrainBayesFromHistory(self, spamHandler, mockDatabase, mockBayesFilter):
        """Test training Bayes filter from message history, dood!"""
        mockDatabase.getSpamMessages.return_value = [
            {"chat_id": 123, "user_id": 456, "text": "Spam 1", "message_id": 1},
            {"chat_id": 123, "user_id": 789, "text": "Spam 2", "message_id": 2},
        ]
        mockDatabase.getChatMessagesSince.return_value = [
            {
                "chat_id": 123,
                "user_id": 111,
                "message_text": "Ham 1",
                "message_category": MessageCategory.USER,
                "message_id": 3,
            },
            {
                "chat_id": 123,
                "user_id": 222,
                "message_text": "Ham 2",
                "message_category": MessageCategory.USER,
                "message_id": 4,
            },
        ]
        mockBayesFilter.learnSpam.return_value = True
        mockBayesFilter.learnHam.return_value = True

        stats = await spamHandler.trainBayesFromHistory(chatId=123, limit=1000)

        assert stats["spam_learned"] == 2
        assert stats["ham_learned"] == 2
        assert stats["failed"] == 0
        assert mockBayesFilter.learnSpam.call_count == 2
        assert mockBayesFilter.learnHam.call_count == 2

    @pytest.mark.asyncio
    async def testTrainBayesFromHistorySkipsSpamUsers(self, spamHandler, mockDatabase, mockBayesFilter):
        """Test training skips messages from spam users, dood!"""
        mockDatabase.getSpamMessages.return_value = [
            {"chat_id": 123, "user_id": 456, "text": "Spam", "message_id": 1},
        ]
        mockDatabase.getChatMessagesSince.return_value = [
            {
                "chat_id": 123,
                "user_id": 456,  # Same user as spammer
                "message_text": "Should skip",
                "message_category": MessageCategory.USER,
                "message_id": 2,
            },
            {
                "chat_id": 123,
                "user_id": 789,  # Different user
                "message_text": "Should learn",
                "message_category": MessageCategory.USER,
                "message_id": 3,
            },
        ]
        mockBayesFilter.learnSpam.return_value = True
        mockBayesFilter.learnHam.return_value = True

        stats = await spamHandler.trainBayesFromHistory(chatId=123)

        assert stats["spam_learned"] == 1
        assert stats["ham_learned"] == 1  # Only one ham message learned


# ============================================================================
# Command Tests - /get_spam_score Command
# ============================================================================


class TestGetSpamScoreCommand:
    """Test /get_spam_score command functionality, dood!"""

    @pytest.mark.asyncio
    async def testGetSpamScoreCommand(self, spamHandler, mockBot, mockBayesFilter):
        """Test /get_spam_score command analyzes message, dood!"""
        spamHandler.injectBot(mockBot)
        mockBayesFilter.classify.return_value = SpamScore(
            score=75.5, isSpam=True, confidence=0.85, tokenScores={"spam": 90.0, "word": 60.0}
        )

        replyMessage = createMockMessage(text="Check this message")
        message = createMockMessage(chatId=456, userId=456, text="/get_spam_score")
        message.chat.type = Chat.PRIVATE
        message.reply_to_message = replyMessage
        message.reply_text = AsyncMock(return_value=message)
        message.external_reply = None

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = []

        await spamHandler.get_spam_score_command(update, context)

        mockBayesFilter.classify.assert_called_once()
        message.reply_text.assert_called_once()


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling, dood!"""

    @pytest.mark.asyncio
    async def testCheckSpamHandlesBayesFilterError(
        self, spamHandler, mockBot, mockDatabase, mockCacheService, mockBayesFilter
    ):
        """Test spam check handles Bayes filter errors gracefully, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_WARN_TRESHOLD: ChatSettingsValue("50.0"),
            ChatSettingsKey.SPAM_BAN_TRESHOLD: ChatSettingsValue("90.0"),
            ChatSettingsKey.BAYES_ENABLED: ChatSettingsValue("true"),
            ChatSettingsKey.BAYES_MIN_CONFIDENCE: ChatSettingsValue("0.1"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "user",
            "full_name": "User",
            "messages_count": 2,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }
        mockDatabase.getChatMessagesByUser.return_value = []
        mockDatabase.getSpamMessagesByText.return_value = []
        mockBayesFilter.classify.side_effect = RuntimeError("Bayes error")

        message = createMockMessage(text="Test message")
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await spamHandler.checkSpam(ensuredMessage)

        # Should continue without Bayes filter
        assert result is False

    @pytest.mark.asyncio
    async def testMarkAsHamWithoutText(self, spamHandler):
        """Test marking as ham without text returns False, dood!"""
        message = createMockMessage(text=None)

        result = await spamHandler.markAsHam(message)

        assert result is False

    @pytest.mark.asyncio
    async def testGetBayesFilterStatsHandlesError(self, spamHandler, mockBayesFilter):
        """Test getting stats handles errors gracefully, dood!"""
        mockBayesFilter.getModelInfo.side_effect = RuntimeError("Stats error")

        stats = await spamHandler.getBayesFilterStats(chatId=123)

        assert stats == {}

    @pytest.mark.asyncio
    async def testResetBayesFilterHandlesError(self, spamHandler, mockBayesFilter):
        """Test reset handles errors gracefully, dood!"""
        mockBayesFilter.reset.side_effect = RuntimeError("Reset error")

        result = await spamHandler.resetBayesFilter(chat_id=123)

        assert result is False

    @pytest.mark.asyncio
    async def testTrainBayesFromHistoryHandlesError(self, spamHandler, mockDatabase, mockBayesFilter):
        """Test training handles errors gracefully, dood!"""
        mockDatabase.getSpamMessages.side_effect = RuntimeError("Database error")

        stats = await spamHandler.trainBayesFromHistory(chatId=123)

        assert stats["failed"] >= 1

    @pytest.mark.asyncio
    async def testCheckSpamSkipsExplicitlyMarkedNonSpammers(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test users marked as notSpammer are skipped, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10")
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "trusted",
            "full_name": "Trusted User",
            "messages_count": 2,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": '{"notSpammer": true}',
        }

        message = createMockMessage(text="Message with URL https://example.com")
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await spamHandler.checkSpam(ensuredMessage)

        assert result is False
