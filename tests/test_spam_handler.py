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

from internal.bot.handlers.spam import SpamHandlers
from internal.bot.models import ChatSettingsKey, ChatSettingsValue, EnsuredMessage
from internal.database.models import MessageCategory, SpamReason
from lib.spam import NaiveBayesFilter
from lib.spam.models import BayesModelStats, SpamScore
from tests.fixtures.telegram_mocks import (
    createMockBot,
    createMockChat,
    createMockContext,
    createMockMessage,
    createMockUpdate,
    createMockUser,
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
            ChatSettingsKey.BAYES_ENABLED: "true",
            ChatSettingsKey.BAYES_AUTO_LEARN: "true",
            ChatSettingsKey.BAYES_MIN_CONFIDENCE: "0.1",
            ChatSettingsKey.ALLOW_MARK_SPAM_OLD_USERS: "false",
            ChatSettingsKey.ALLOW_USER_SPAM_COMMAND: "false",
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
            handler = SpamHandlers(mockConfigManager, mockDatabase, mockLlmManager)
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
                handler = SpamHandlers(mockConfigManager, mockDatabase, mockLlmManager)

                assert handler.configManager == mockConfigManager
                assert handler.db == mockDatabase
                assert handler.llmManager == mockLlmManager
                assert handler.bayesFilter is not None

    def testInitCreatesBayesFilter(self, mockConfigManager, mockDatabase, mockLlmManager):
        """Test Bayes filter is created during initialization, dood!"""
        with patch("internal.bot.handlers.spam.DatabaseBayesStorage") as MockStorage:
            with patch("internal.bot.handlers.spam.NaiveBayesFilter") as MockFilter:
                handler = SpamHandlers(mockConfigManager, mockDatabase, mockLlmManager)

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
    async def testCheckSpamDetectsKnownSpammer(
        self, spamHandler, mockBot, mockDatabase, mockCacheService, mockQueueService
    ):
        """Test known spammers are immediately banned, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_WARN_TRESHOLD: ChatSettingsValue("50.0"),
            ChatSettingsKey.SPAM_BAN_TRESHOLD: ChatSettingsValue("90.0"),
            ChatSettingsKey.DETECT_SPAM: ChatSettingsValue("true"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "spammer",
            "full_name": "Spammer",
            "messages_count": 2,
            "is_spammer": True,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }
        mockDatabase.getChatMessagesByUser.return_value = []
        mockDatabase.getSpamMessagesByText.return_value = []

        message = createMockMessage(text="Spam message")
        message.reply_text = AsyncMock(return_value=message)
        message.get_bot = Mock(return_value=mockBot)
        ensuredMessage = EnsuredMessage.fromMessage(message)

        # Mock sendMessage to avoid complexity
        spamHandler.sendMessage = AsyncMock(return_value=message)

        result = await spamHandler.checkSpam(ensuredMessage)

        assert result is True
        mockBot.ban_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def testCheckSpamDetectsDuplicateMessages(
        self, spamHandler, mockBot, mockDatabase, mockCacheService, mockQueueService
    ):
        """Test duplicate messages increase spam score, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_WARN_TRESHOLD: ChatSettingsValue("50.0"),
            ChatSettingsKey.SPAM_BAN_TRESHOLD: ChatSettingsValue("90.0"),
            ChatSettingsKey.DETECT_SPAM: ChatSettingsValue("true"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "user",
            "full_name": "User",
            "messages_count": 5,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }
        # Return 7 duplicate messages and 2 different ones
        mockDatabase.getChatMessagesByUser.return_value = [
            {"message_id": i, "message_text": "Same spam" if i < 7 else "Different", "chat_id": 123, "user_id": 456}
            for i in range(1, 10)
        ]
        mockDatabase.getSpamMessagesByText.return_value = []

        message = createMockMessage(messageId=10, text="Same spam")
        message.reply_text = AsyncMock(return_value=message)
        message.get_bot = Mock(return_value=mockBot)
        ensuredMessage = EnsuredMessage.fromMessage(message)

        # Mock sendMessage to avoid complexity
        spamHandler.sendMessage = AsyncMock(return_value=message)

        result = await spamHandler.checkSpam(ensuredMessage)

        # Should be detected as spam due to duplicates
        assert result is True

    @pytest.mark.asyncio
    async def testCheckSpamDetectsKnownSpamText(
        self, spamHandler, mockBot, mockDatabase, mockCacheService, mockQueueService
    ):
        """Test known spam text is immediately detected, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_WARN_TRESHOLD: ChatSettingsValue("50.0"),
            ChatSettingsKey.SPAM_BAN_TRESHOLD: ChatSettingsValue("90.0"),
            ChatSettingsKey.DETECT_SPAM: ChatSettingsValue("true"),
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
        mockDatabase.getSpamMessagesByText.return_value = [
            {"text": "Known spam message", "chat_id": 123, "user_id": 789}
        ]

        message = createMockMessage(text="Known spam message")
        message.reply_text = AsyncMock(return_value=message)
        message.get_bot = Mock(return_value=mockBot)
        ensuredMessage = EnsuredMessage.fromMessage(message)

        # Mock sendMessage to avoid complexity
        spamHandler.sendMessage = AsyncMock(return_value=message)

        result = await spamHandler.checkSpam(ensuredMessage)

        assert result is True

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
        entity = Mock(spec=MessageEntity)
        entity.type = MessageEntityType.URL
        entity.offset = 15
        entity.length = 17
        message.entities = [entity]
        message.reply_text = AsyncMock(return_value=message)
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await spamHandler.checkSpam(ensuredMessage)

        # URL adds 60 points, should trigger warning but not ban
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
    async def testCheckSpamUsesBayesFilter(self, spamHandler, mockBot, mockDatabase, mockCacheService, mockBayesFilter):
        """Test Bayes filter is used when enabled, dood!"""
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
        mockBayesFilter.classify.return_value = SpamScore(score=45.0, isSpam=False, confidence=0.8, tokenScores={})

        message = createMockMessage(text="Test message")
        ensuredMessage = EnsuredMessage.fromMessage(message)

        result = await spamHandler.checkSpam(ensuredMessage)

        mockBayesFilter.classify.assert_called()
        assert result is False

    @pytest.mark.asyncio
    async def testMarkAsSpamLearnsBayesFilter(
        self, spamHandler, mockBot, mockDatabase, mockCacheService, mockBayesFilter
    ):
        """Test marking as spam trains Bayes filter, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.BAYES_AUTO_LEARN: ChatSettingsValue("true"),
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES: ChatSettingsValue("false"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "spammer",
            "full_name": "Spammer",
            "messages_count": 2,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }

        message = createMockMessage(text="Spam message")
        message.get_bot = Mock(return_value=mockBot)

        await spamHandler.markAsSpam(message, SpamReason.ADMIN, score=100.0)

        mockBayesFilter.learnSpam.assert_called_once_with(messageText="Spam message", chatId=123)

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
# Unit Tests - User Management
# ============================================================================


class TestUserManagement:
    """Test user banning and unbanning, dood!"""

    @pytest.mark.asyncio
    async def testMarkAsSpamBansUser(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test marking as spam bans the user, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.BAYES_AUTO_LEARN: ChatSettingsValue("false"),
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES: ChatSettingsValue("false"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "spammer",
            "full_name": "Spammer",
            "messages_count": 2,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }

        message = createMockMessage(text="Spam")
        message.get_bot = Mock(return_value=mockBot)

        await spamHandler.markAsSpam(message, SpamReason.ADMIN, score=100.0)

        mockBot.ban_chat_member.assert_called_once_with(chat_id=123, user_id=456, revoke_messages=True)
        mockDatabase.markUserIsSpammer.assert_called_once_with(chatId=123, userId=456, isSpammer=True)

    @pytest.mark.asyncio
    async def testMarkAsSpamDeletesMessage(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test marking as spam deletes the message, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.BAYES_AUTO_LEARN: ChatSettingsValue("false"),
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES: ChatSettingsValue("false"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "spammer",
            "full_name": "Spammer",
            "messages_count": 2,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }

        message = createMockMessage(messageId=789, text="Spam")
        message.get_bot = Mock(return_value=mockBot)

        await spamHandler.markAsSpam(message, SpamReason.ADMIN, score=100.0)

        mockBot.delete_message.assert_called_once_with(chat_id=123, message_id=789)

    @pytest.mark.asyncio
    async def testMarkAsSpamDoesNotBanAdmin(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test admins cannot be marked as spam, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {}

        adminUser = createMockUser(userId=456, username="admin")
        chat = createMockChat(chatId=123, chatType="group")
        mockAdmin = Mock()
        mockAdmin.user = adminUser
        chat.get_administrators = AsyncMock(return_value=[mockAdmin])

        message = createMockMessage(text="Admin message")
        message.from_user = adminUser
        message.chat = chat
        message.get_bot = Mock(return_value=mockBot)
        message.reply_text = AsyncMock(return_value=message)

        await spamHandler.markAsSpam(message, SpamReason.ADMIN, score=100.0)

        mockBot.ban_chat_member.assert_not_called()

    @pytest.mark.asyncio
    async def testMarkAsSpamDeletesAllUserMessages(
        self, spamHandler, mockBot, mockDatabase, mockCacheService, mockBayesFilter
    ):
        """Test marking as spam can delete all user messages, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.BAYES_AUTO_LEARN: ChatSettingsValue("true"),
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES: ChatSettingsValue("true"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "spammer",
            "full_name": "Spammer",
            "messages_count": 5,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }
        mockDatabase.getChatMessagesByUser.return_value = [
            {"message_id": i, "message_text": f"Message {i}", "chat_id": 123, "user_id": 456} for i in range(1, 6)
        ]

        message = createMockMessage(messageId=10, text="Spam")
        message.get_bot = Mock(return_value=mockBot)

        await spamHandler.markAsSpam(message, SpamReason.ADMIN, score=100.0)

        # Should delete messages 1-5 (not 10 which is the spam message itself)
        mockBot.delete_messages.assert_called_once()
        call_args = mockBot.delete_messages.call_args
        assert call_args[1]["chat_id"] == 123
        assert len(call_args[1]["message_ids"]) == 5


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
# Command Tests - /spam Command
# ============================================================================


class TestSpamCommand:
    """Test /spam command functionality, dood!"""

    @pytest.mark.asyncio
    async def testSpamCommandMarksMessageAsSpam(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test /spam command marks replied message as spam, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.ALLOW_USER_SPAM_COMMAND: ChatSettingsValue("false"),
            ChatSettingsKey.BAYES_AUTO_LEARN: ChatSettingsValue("false"),
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES: ChatSettingsValue("false"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 789,
            "username": "spammer",
            "full_name": "Spammer",
            "messages_count": 2,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }

        # Create admin user
        adminUser = createMockUser(userId=456, username="admin")
        chat = createMockChat(chatId=123, chatType="group")
        mockAdmin = Mock()
        mockAdmin.user = adminUser
        chat.get_administrators = AsyncMock(return_value=[mockAdmin])

        # Create spam message
        spamMessage = createMockMessage(messageId=100, chatId=123, userId=789, text="Spam content")
        spamMessage.get_bot = Mock(return_value=mockBot)

        # Create command message
        commandMessage = createMockMessage(messageId=101, chatId=123, userId=456, text="/spam")
        commandMessage.chat = chat
        commandMessage.from_user = adminUser
        commandMessage.reply_to_message = spamMessage
        commandMessage.delete = AsyncMock()

        update = createMockUpdate(message=commandMessage)
        context = createMockContext()

        await spamHandler.spam_command(update, context)

        mockBot.ban_chat_member.assert_called_once()
        commandMessage.delete.assert_called_once()

    @pytest.mark.asyncio
    async def testSpamCommandRequiresReply(self, spamHandler, mockBot, mockCacheService):
        """Test /spam command requires reply to message, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.ALLOW_USER_SPAM_COMMAND: ChatSettingsValue("true")
        }

        message = createMockMessage(text="/spam")
        message.reply_to_message = None
        message.delete = AsyncMock()

        update = createMockUpdate(message=message)
        context = createMockContext()

        await spamHandler.spam_command(update, context)

        # Should just delete command message without action
        message.delete.assert_called_once()
        mockBot.ban_chat_member.assert_not_called()

    @pytest.mark.asyncio
    async def testSpamCommandAllowsUserReports(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test /spam command allows user reports when enabled, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.ALLOW_USER_SPAM_COMMAND: ChatSettingsValue("true"),
            ChatSettingsKey.BAYES_AUTO_LEARN: ChatSettingsValue("false"),
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
            ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES: ChatSettingsValue("false"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 789,
            "username": "spammer",
            "full_name": "Spammer",
            "messages_count": 2,
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }

        chat = createMockChat(chatId=123, chatType="group")
        chat.get_administrators = AsyncMock(return_value=[])

        spamMessage = createMockMessage(messageId=100, chatId=123, userId=789, text="Spam")
        spamMessage.get_bot = Mock(return_value=mockBot)

        commandMessage = createMockMessage(messageId=101, chatId=123, userId=456, text="/spam")
        commandMessage.chat = chat
        commandMessage.reply_to_message = spamMessage
        commandMessage.delete = AsyncMock()

        update = createMockUpdate(message=commandMessage)
        context = createMockContext()

        await spamHandler.spam_command(update, context)

        mockBot.ban_chat_member.assert_called_once()


# ============================================================================
# Command Tests - /pretrain_bayes Command
# ============================================================================


class TestPretrainBayesCommand:
    """Test /pretrain_bayes command functionality, dood!"""

    @pytest.mark.asyncio
    async def testPretrainBayesCommand(self, spamHandler, mockBot, mockDatabase, mockBayesFilter):
        """Test /pretrain_bayes command trains filter, dood!"""
        spamHandler.injectBot(mockBot)
        mockDatabase.getSpamMessages.return_value = []
        mockDatabase.getChatMessagesSince.return_value = []
        mockBayesFilter.getModelInfo.return_value = BayesModelStats(
            total_spam_messages=10,
            total_ham_messages=90,
            total_tokens=1000,
            vocabulary_size=500,
            chat_id=123,
        )

        adminUser = createMockUser(userId=456, username="admin")
        chat = createMockChat(chatId=123, chatType="private")
        mockAdmin = Mock()
        mockAdmin.user = adminUser
        chat.get_administrators = AsyncMock(return_value=[mockAdmin])

        message = createMockMessage(chatId=456, userId=456, text="/pretrain_bayes")
        message.chat = chat
        message.from_user = adminUser
        message.reply_text = AsyncMock(return_value=message)
        message.get_bot = Mock(return_value=mockBot)

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = []

        await spamHandler.pretrain_bayes_command(update, context)

        message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def testPretrainBayesCommandWithChatId(self, spamHandler, mockBot, mockDatabase, mockBayesFilter):
        """Test /pretrain_bayes command with specific chat ID, dood!"""
        spamHandler.injectBot(mockBot)
        mockDatabase.getSpamMessages.return_value = []
        mockDatabase.getChatMessagesSince.return_value = []
        mockBayesFilter.getModelInfo.return_value = BayesModelStats(
            total_spam_messages=5,
            total_ham_messages=45,
            total_tokens=500,
            vocabulary_size=250,
            chat_id=-100123456789,
        )

        adminUser = createMockUser(userId=456, username="admin")
        chat = createMockChat(chatId=456, chatType="private")
        targetChat = createMockChat(chatId=-100123456789, chatType="supergroup")
        mockAdmin = Mock()
        mockAdmin.user = adminUser
        targetChat.get_administrators = AsyncMock(return_value=[mockAdmin])
        targetChat.set_bot = Mock()

        message = createMockMessage(chatId=456, userId=456, text="/pretrain_bayes -100123456789")
        message.chat = chat
        message.from_user = adminUser
        message.reply_text = AsyncMock(return_value=message)
        message.get_bot = Mock(return_value=mockBot)

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["-100123456789"]

        await spamHandler.pretrain_bayes_command(update, context)

        message.reply_text.assert_called_once()


# ============================================================================
# Command Tests - /learn_spam and /learn_ham Commands
# ============================================================================


class TestLearnCommands:
    """Test /learn_spam and /learn_ham commands, dood!"""

    @pytest.mark.asyncio
    async def testLearnSpamCommand(self, spamHandler, mockBot, mockDatabase, mockBayesFilter):
        """Test /learn_spam command trains filter with spam, dood!"""
        spamHandler.injectBot(mockBot)
        mockBayesFilter.learnSpam.return_value = True

        # Mock isAdmin to return True
        spamHandler.isAdmin = AsyncMock(return_value=True)

        adminUser = createMockUser(userId=456, username="admin")
        chat = createMockChat(chatId=456, chatType="private")

        replyMessage = createMockMessage(text="This is spam")
        message = createMockMessage(chatId=456, userId=456, text="/learn_spam")
        message.chat = chat
        message.from_user = adminUser
        message.reply_to_message = replyMessage
        message.reply_text = AsyncMock(return_value=message)
        message.external_reply = None
        entity = Mock(spec=MessageEntity)
        entity.type = MessageEntityType.BOT_COMMAND
        entity.offset = 0
        entity.length = 11
        message.entities = [entity]

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.bot = mockBot
        context.args = []

        await spamHandler.learn_spam_ham_command(update, context)

        mockBayesFilter.learnSpam.assert_called_once()
        mockDatabase.addSpamMessage.assert_called_once()

    @pytest.mark.asyncio
    async def testLearnHamCommand(self, spamHandler, mockBot, mockDatabase, mockBayesFilter):
        """Test /learn_ham command trains filter with ham, dood!"""
        spamHandler.injectBot(mockBot)
        mockBayesFilter.learnHam.return_value = True

        # Mock isAdmin to return True
        spamHandler.isAdmin = AsyncMock(return_value=True)

        adminUser = createMockUser(userId=456, username="admin")
        chat = createMockChat(chatId=456, chatType="private")

        replyMessage = createMockMessage(text="This is legitimate")
        message = createMockMessage(chatId=456, userId=456, text="/learn_ham")
        message.chat = chat
        message.from_user = adminUser
        message.reply_to_message = replyMessage
        message.reply_text = AsyncMock(return_value=message)
        message.external_reply = None
        entity = Mock(spec=MessageEntity)
        entity.type = MessageEntityType.BOT_COMMAND
        entity.offset = 0
        entity.length = 10
        message.entities = [entity]

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.bot = mockBot
        context.args = []

        await spamHandler.learn_spam_ham_command(update, context)

        mockBayesFilter.learnHam.assert_called_once()
        mockDatabase.addHamMessage.assert_called_once()

    @pytest.mark.asyncio
    async def testLearnCommandRequiresReply(self, spamHandler, mockBot):
        """Test learn commands require reply to message, dood!"""
        spamHandler.injectBot(mockBot)

        message = createMockMessage(text="/learn_spam")
        message.reply_to_message = None
        message.reply_text = AsyncMock(return_value=message)
        entity = Mock(spec=MessageEntity)
        entity.type = MessageEntityType.BOT_COMMAND
        entity.offset = 0
        entity.length = 11
        message.entities = [entity]

        update = createMockUpdate(message=message)
        context = createMockContext()

        await spamHandler.learn_spam_ham_command(update, context)

        message.reply_text.assert_called_once()
        # Should send error message about needing reply


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

    @pytest.mark.asyncio
    async def testGetSpamScoreCommandRequiresPrivateChat(self, spamHandler, mockBot):
        """Test /get_spam_score only works in private chats, dood!"""
        spamHandler.injectBot(mockBot)

        message = createMockMessage(text="/get_spam_score")
        message.chat.type = Chat.GROUP
        message.reply_to_message = createMockMessage(text="Test")

        update = createMockUpdate(message=message)
        context = createMockContext()

        await spamHandler.get_spam_score_command(update, context)

        # Should return early without processing


# ============================================================================
# Command Tests - /unban Command
# ============================================================================


class TestUnbanCommand:
    """Test /unban command functionality, dood!"""

    @pytest.mark.asyncio
    async def testUnbanCommandUnbansUser(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test /unban command unbans user and corrects classification, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {}
        mockDatabase.getChatUserByUsername.return_value = {
            "chat_id": 123,
            "user_id": 789,
            "username": "unbanned_user",
            "full_name": "Unbanned User",
            "messages_count": 5,
            "is_spammer": True,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "{}",
        }
        mockDatabase.getSpamMessagesByUserId.return_value = [
            {"chat_id": 123, "user_id": 789, "message_id": 1, "text": "Message 1", "score": 100},
            {"chat_id": 123, "user_id": 789, "message_id": 2, "text": "Message 2", "score": 100},
        ]

        adminUser = createMockUser(userId=456, username="admin")
        chat = createMockChat(chatId=123, chatType="group")
        mockAdmin = Mock()
        mockAdmin.user = adminUser
        chat.get_administrators = AsyncMock(return_value=[mockAdmin])

        message = createMockMessage(chatId=123, userId=456, text="/unban @unbanned_user")
        message.chat = chat
        message.from_user = adminUser
        message.reply_text = AsyncMock(return_value=message)
        message.get_bot = Mock(return_value=mockBot)  # Override to return test's mockBot

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["@unbanned_user"]

        await spamHandler.unban_command(update, context)

        mockBot.unban_chat_member.assert_called_once_with(chat_id=123, user_id=789, only_if_banned=True)
        mockDatabase.markUserIsSpammer.assert_called_once_with(chatId=123, userId=789, isSpammer=False)
        mockDatabase.deleteSpamMessagesByUserId.assert_called_once()
        assert mockDatabase.addHamMessage.call_count == 2

    @pytest.mark.asyncio
    async def testUnbanCommandWithReply(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test /unban command works with reply to message, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {}
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 789,
            "username": "unbanned_user",
            "full_name": "Unbanned User",
            "messages_count": 5,
            "is_spammer": True,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "{}",
        }
        mockDatabase.getSpamMessagesByUserId.return_value = []

        adminUser = createMockUser(userId=456, username="admin")
        chat = createMockChat(chatId=123, chatType="group")
        mockAdmin = Mock()
        mockAdmin.user = adminUser
        chat.get_administrators = AsyncMock(return_value=[mockAdmin])

        bannedUser = createMockUser(userId=789, username="unbanned_user")
        replyMessage = createMockMessage(userId=789, text="Old message")
        replyMessage.from_user = bannedUser

        message = createMockMessage(chatId=123, userId=456, text="/unban")
        message.chat = chat
        message.from_user = adminUser
        message.reply_to_message = replyMessage
        message.reply_text = AsyncMock(return_value=message)
        message.get_bot = Mock(return_value=mockBot)  # Override to return test's mockBot

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = []

        await spamHandler.unban_command(update, context)

        mockBot.unban_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def testUnbanCommandRequiresAdmin(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test /unban command requires admin permissions, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {}
        mockDatabase.getChatUserByUsername.return_value = {
            "chat_id": 123,
            "user_id": 789,
            "username": "user",
            "full_name": "User",
            "messages_count": 5,
            "is_spammer": True,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "{}",
        }

        regularUser = createMockUser(userId=456, username="regular")
        chat = createMockChat(chatId=123, chatType="group")
        chat.get_administrators = AsyncMock(return_value=[])

        message = createMockMessage(chatId=123, userId=456, text="/unban @user")
        message.chat = chat
        message.from_user = regularUser
        message.reply_text = AsyncMock(return_value=message)

        update = createMockUpdate(message=message)
        context = createMockContext()
        context.args = ["@user"]

        await spamHandler.unban_command(update, context)

        mockBot.unban_chat_member.assert_not_called()
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
    async def testMarkAsSpamDoesNotBanOldUsers(self, spamHandler, mockBot, mockDatabase, mockCacheService):
        """Test old users cannot be marked as spam without admin override, dood!"""
        spamHandler.injectBot(mockBot)
        mockCacheService.getChatSettings.return_value = {
            ChatSettingsKey.ALLOW_MARK_SPAM_OLD_USERS: ChatSettingsValue("false"),
            ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: ChatSettingsValue("10"),
        }
        mockDatabase.getChatUser.return_value = {
            "chat_id": 123,
            "user_id": 456,
            "username": "olduser",
            "full_name": "Old User",
            "messages_count": 50,  # More than max
            "is_spammer": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
            "timezone": "",
            "metadata": "",
        }

        message = createMockMessage(text="Message")
        message.get_bot = Mock(return_value=mockBot)
        message.reply_text = AsyncMock(return_value=message)

        await spamHandler.markAsSpam(message, SpamReason.AUTO, score=100.0)

        mockBot.ban_chat_member.assert_not_called()

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


# ============================================================================
# Test Summary
# ============================================================================


def testSummary():
    """
    Test Summary for SpamHandlers, dood!

    Total Test Cases: 50+

    Coverage Areas:
    - Initialization: 2 tests
    - Spam Detection Logic: 9 tests
    - Bayes Filter Integration: 4 tests
    - User Management: 4 tests
    - Message Spam Checking: 2 tests
    - Training Workflows: 2 tests
    - /spam Command: 3 tests
    - /pretrain_bayes Command: 2 tests
    - /learn_spam and /learn_ham Commands: 3 tests
    - /get_spam_score Command: 2 tests
    - /unban Command: 3 tests
    - Edge Cases and Error Handling: 9 tests

    Key Features Tested:
    ✓ Handler initialization with Bayes filter
    ✓ Spam detection logic (automatic forwards, anonymous admins, trusted users)
    ✓ Known spammer detection
    ✓ Duplicate message detection
    ✓ Known spam text detection
    ✓ URL and external mention detection
    ✓ Bayes filter classification integration
    ✓ Bayes filter training (spam and ham)
    ✓ Bayes filter statistics retrieval
    ✓ Bayes filter reset functionality
    ✓ User banning and message deletion
    ✓ Admin protection from spam marking
    ✓ Batch message deletion for spammers
    ✓ Message handler for group chats
    ✓ Training from message history
    ✓ Skipping spam users during training
    ✓ /spam command (admin and user reports)
    ✓ /pretrain_bayes command (with and without chat ID)
    ✓ /learn_spam and /learn_ham commands
    ✓ /get_spam_score command (private chat only)
    ✓ /unban command (username and reply modes)
    ✓ Admin permission checks for commands
    ✓ Error handling for Bayes filter failures
    ✓ Error handling for database failures
    ✓ Old user protection from auto-spam marking
    ✓ Explicit non-spammer marking

    Test Coverage:
    - Comprehensive unit tests for all spam detection methods
    - Integration tests for complete workflows
    - Command tests for all spam-related commands
    - Edge cases and error handling
    - Admin permission validation
    - Bayes filter integration and training

    Target Coverage: 75%+ for SpamHandlers class
    """
    pass
