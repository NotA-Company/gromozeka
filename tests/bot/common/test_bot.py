"""Regression tests for TheBot.getChatAdmins graceful degradation.

Pins the fix for the bug where getChatAdmins would crash when the bot was
kicked from a chat or no longer had access. Before the fix, the method would
raise telegram.error.Forbidden or lib.max_bot.exceptions.NotFoundError and
propagate up through isAdmin and chatConfiguration_Init, crashing the entire
/configure command. After the fix, it logs a warning and returns an empty dict,
which the caller (isAdmin) treats as "no admins in this chat".
"""

from typing import Generator
from unittest.mock import AsyncMock, Mock

import pytest
import telegram
import telegram.error
import telegram.ext

import lib.max_bot as libMax
import lib.max_bot.exceptions as maxExceptions
from internal.bot.common.bot import TheBot
from internal.bot.models import BotProvider, ChatType, MessageRecipient
from internal.services.cache import CacheService


class TestGetChatAdminsRegression:
    """Pins getChatAdmins graceful degradation for access-denied errors."""

    @pytest.fixture
    def _resetSingletons(self) -> Generator[None, None, None]:
        """Reset CacheService singleton around the test.

        The code path reaches self.cache, which leaks state across tests.
        This fixture is requested explicitly by the bot fixtures.

        Yields:
            None.
        """
        CacheService._instance = None
        yield
        CacheService._instance = None

    @pytest.fixture
    def mockCacheService(self) -> Mock:
        """Create a mock CacheService.

        Returns:
            Mock: Mocked CacheService with getChatAdmins/setChatAdmins and new accessibility methods.
        """
        cache = Mock(spec=CacheService)
        cache.getChatAdmins = Mock(return_value=None)
        cache.setChatAdmins = Mock()
        cache.isChatInaccessible = AsyncMock(return_value=False)
        cache.markChatInaccessible = AsyncMock()
        return cache

    @pytest.fixture
    def telegramBot(self, mockCacheService: Mock, _resetSingletons: None) -> TheBot:
        """Build a Telegram TheBot instance with mocked deps.

        Args:
            mockCacheService: Mock cache service.
            _resetSingletons: Fixture to reset CacheService singleton (requested explicitly by bot fixtures).

        Returns:
            A configured TheBot for the regression path.
        """
        # Mock the telegram.ext.ExtBot
        tgBot = AsyncMock(spec=telegram.ext.ExtBot)
        tgBot.id = 123456789
        tgBot.username = "test_bot"

        # Config dict with bot_owners (what TheBot expects)
        config = {"bot_owners": [123456]}

        # Create TheBot with Telegram provider
        bot = TheBot(
            botProvider=BotProvider.TELEGRAM,
            config=config,
            tgBot=tgBot,
        )

        # Inject the mock cache (replacing the singleton)
        bot.cache = mockCacheService

        return bot

    @pytest.fixture
    def maxBot(self, mockCacheService: Mock, _resetSingletons: None) -> TheBot:
        """Build a Max TheBot instance with mocked deps.

        Args:
            mockCacheService: Mock cache service.
            _resetSingletons: Fixture to reset CacheService singleton (requested explicitly by bot fixtures).

        Returns:
            A configured TheBot for the regression path.
        """
        # Mock the MaxBotClient
        maxBotClient = AsyncMock(spec=libMax.MaxBotClient)

        # Config dict with bot_owners (what TheBot expects)
        config = {"bot_owners": [123456]}

        # Create TheBot with Max provider
        bot = TheBot(
            botProvider=BotProvider.MAX,
            config=config,
            maxBot=maxBotClient,
        )

        # Inject the mock cache (replacing the singleton)
        bot.cache = mockCacheService

        return bot

    @pytest.fixture
    def groupChat(self) -> MessageRecipient:
        """Create a test group chat recipient.

        Returns:
            MessageRecipient for a group chat.
        """
        return MessageRecipient(id=-1001234567890, chatType=ChatType.GROUP)

    async def test_getChatAdmins_telegramForbidden_returnsEmptyDict(
        self, telegramBot: TheBot, groupChat: MessageRecipient, mockCacheService: Mock
    ) -> None:
        """Telegram Forbidden error (bot kicked/blocked) returns empty dict.

        Args:
            telegramBot: The TheBot instance with Telegram provider.
            groupChat: Test group chat.
            mockCacheService: Mock cache service for verification.
        """
        # Arrange: Telegram API raises Forbidden when bot is kicked
        telegramBot.tgBot.get_chat_administrators.side_effect = (  # type: ignore[union-attr]
            telegram.error.Forbidden("Forbidden: bot was kicked from the supergroup chat")
        )

        # Act: Call getChatAdmins - should NOT raise
        result = await telegramBot.getChatAdmins(groupChat)

        # Assert: Returns empty dict, cache NOT populated
        assert result == {}
        mockCacheService.getChatAdmins.assert_called_once_with(groupChat.id)
        mockCacheService.setChatAdmins.assert_not_called()

    async def test_getChatAdmins_telegramBadRequest_returnsEmptyDict(
        self, telegramBot: TheBot, groupChat: MessageRecipient, mockCacheService: Mock
    ) -> None:
        """Telegram BadRequest error (chat not found) returns empty dict.

        This is conservative - only catch BadRequest when it clearly means
        the chat is inaccessible (e.g., "Chat not found"). We're NOT catching
        all BadRequest errors globally, just the one for inaccessible chats.

        Args:
            telegramBot: The TheBot instance with Telegram provider.
            groupChat: Test group chat.
            mockCacheService: Mock cache service for verification.
        """
        # Arrange: Telegram API raises BadRequest for inaccessible chat
        telegramBot.tgBot.get_chat_administrators.side_effect = (  # type: ignore[union-attr]
            telegram.error.BadRequest("Bad Request: chat not found")
        )

        # Act: Call getChatAdmins - should NOT raise
        result = await telegramBot.getChatAdmins(groupChat)

        # Assert: Returns empty dict, cache NOT populated
        assert result == {}
        mockCacheService.getChatAdmins.assert_called_once_with(groupChat.id)
        mockCacheService.setChatAdmins.assert_not_called()

    async def test_getChatAdmins_maxNotFound_returnsEmptyDict(
        self, maxBot: TheBot, groupChat: MessageRecipient, mockCacheService: Mock
    ) -> None:
        """Max NotFoundError (bot not in chat) returns empty dict.

        Args:
            maxBot: The TheBot instance with Max provider.
            groupChat: Test group chat.
            mockCacheService: Mock cache service for verification.
        """
        # Arrange: Max API raises NotFoundError when bot not in chat
        maxBot.maxBot.getAdmins.side_effect = (  # type: ignore[union-attr]
            maxExceptions.NotFoundError("Resource not found.")
        )

        # Act: Call getChatAdmins - should NOT raise
        result = await maxBot.getChatAdmins(groupChat)

        # Assert: Returns empty dict, cache NOT populated
        assert result == {}
        mockCacheService.getChatAdmins.assert_called_once_with(groupChat.id)
        mockCacheService.setChatAdmins.assert_not_called()

    async def test_getChatAdmins_telegramSuccess_returnsAdminsAndCaches(
        self, telegramBot: TheBot, groupChat: MessageRecipient, mockCacheService: Mock
    ) -> None:
        """Successful Telegram fetch returns admins and caches them.

        Args:
            telegramBot: The TheBot instance with Telegram provider.
            groupChat: Test group chat.
            mockCacheService: Mock cache service for verification.
        """
        # Arrange: Telegram API returns admins
        admin1 = Mock()
        admin1.user.id = 123
        admin1.user.username = "admin1"
        admin1.user.full_name = "Admin One"

        admin2 = Mock()
        admin2.user.id = 456
        admin2.user.username = None
        admin2.user.full_name = "Admin Two"

        telegramBot.tgBot.get_chat_administrators.side_effect = [[admin1, admin2]]  # type: ignore[union-attr]

        # Act: Call getChatAdmins
        result = await telegramBot.getChatAdmins(groupChat)

        # Assert: Returns admins dict, cache populated
        assert result == {
            123: ("@admin1", "Admin One"),
            456: ("", "Admin Two"),
        }
        mockCacheService.getChatAdmins.assert_called_once_with(groupChat.id)
        mockCacheService.setChatAdmins.assert_called_once_with(groupChat.id, result)

    async def test_getChatAdmins_maxSuccess_returnsAdminsAndCaches(
        self, maxBot: TheBot, groupChat: MessageRecipient, mockCacheService: Mock
    ) -> None:
        """Successful Max fetch returns admins and caches them.

        Args:
            maxBot: The TheBot instance with Max provider.
            groupChat: Test group chat.
            mockCacheService: Mock cache service for verification.
        """
        # Arrange: Max API returns admins
        admin1 = Mock()
        admin1.user_id = 123
        admin1.username = "admin1"
        admin1.first_name = "Admin"
        admin1.last_name = "One"

        admin2 = Mock()
        admin2.user_id = 456
        admin2.username = None
        admin2.first_name = "Admin"
        admin2.last_name = "Two"

        adminResponse = Mock()
        adminResponse.members = [admin1, admin2]

        maxBot.maxBot.getAdmins.side_effect = [adminResponse]  # type: ignore[union-attr]

        # Act: Call getChatAdmins
        result = await maxBot.getChatAdmins(groupChat)

        # Assert: Returns admins dict, cache populated
        assert result == {
            123: ("@admin1", "Admin One"),
            456: ("", "Admin Two"),
        }
        mockCacheService.getChatAdmins.assert_called_once_with(groupChat.id)
        mockCacheService.setChatAdmins.assert_called_once_with(groupChat.id, result)

    async def test_getChatAdmins_cachedValue_returnsWithoutApiCall(
        self, telegramBot: TheBot, groupChat: MessageRecipient, mockCacheService: Mock
    ) -> None:
        """Cached value is returned without API call.

        Args:
            telegramBot: The TheBot instance with Telegram provider.
            groupChat: Test group chat.
            mockCacheService: Mock cache service for verification.
        """
        # Arrange: Cache returns a value
        cachedAdmins = {123: ("@admin1", "Admin One")}
        mockCacheService.getChatAdmins.return_value = cachedAdmins

        # Act: Call getChatAdmins
        result = await telegramBot.getChatAdmins(groupChat)

        # Assert: Returns cached value, no API call, no cache set
        assert result is cachedAdmins
        mockCacheService.getChatAdmins.assert_called_once_with(groupChat.id)
        mockCacheService.setChatAdmins.assert_not_called()
        telegramBot.tgBot.get_chat_administrators.assert_not_called()  # type: ignore[union-attr]

    async def test_getChatAdmins_shortCircuitWhenInaccessible(
        self, telegramBot: TheBot, groupChat: MessageRecipient, mockCacheService: Mock
    ) -> None:
        """Short-circuit to {} for known-inaccessible chats (zero API/DB cost).

        Args:
            telegramBot: The TheBot instance with Telegram provider.
            groupChat: Test group chat.
            mockCacheService: Mock cache service for verification.
        """
        # Arrange: Cache reports chat as inaccessible
        mockCacheService.isChatInaccessible.return_value = True

        # Act: Call getChatAdmins
        result = await telegramBot.getChatAdmins(groupChat)

        # Assert: Returns empty dict, no API call, no cache read/write
        assert result == {}
        mockCacheService.isChatInaccessible.assert_awaited_once_with(groupChat.id)
        mockCacheService.getChatAdmins.assert_not_called()
        mockCacheService.setChatAdmins.assert_not_called()
        telegramBot.tgBot.get_chat_administrators.assert_not_called()  # type: ignore[union-attr]

    async def test_getChatAdmins_telegramForbidden_marksInaccessible(
        self, telegramBot: TheBot, groupChat: MessageRecipient, mockCacheService: Mock
    ) -> None:
        """Telegram Forbidden marks chat inaccessible (memory + DB) and returns {}.

        Args:
            telegramBot: The TheBot instance with Telegram provider.
            groupChat: Test group chat.
            mockCacheService: Mock cache service for verification.
        """
        # Arrange: Telegram API raises Forbidden when bot is kicked
        telegramBot.tgBot.get_chat_administrators.side_effect = (  # type: ignore[union-attr]
            telegram.error.Forbidden("Forbidden: bot was kicked from the supergroup chat")
        )

        # Act: Call getChatAdmins - should NOT raise
        result = await telegramBot.getChatAdmins(groupChat)

        # Assert: Returns empty dict, marks inaccessible, cache NOT populated
        assert result == {}
        mockCacheService.getChatAdmins.assert_called_once_with(groupChat.id)
        mockCacheService.markChatInaccessible.assert_awaited_once_with(groupChat.id)
        mockCacheService.setChatAdmins.assert_not_called()

    async def test_getChatAdmins_telegramBadRequestChatNotFound_marksInaccessible(
        self, telegramBot: TheBot, groupChat: MessageRecipient, mockCacheService: Mock
    ) -> None:
        """Telegram BadRequest "chat not found" marks chat inaccessible and returns {}.

        Args:
            telegramBot: The TheBot instance with Telegram provider.
            groupChat: Test group chat.
            mockCacheService: Mock cache service for verification.
        """
        # Arrange: Telegram API raises BadRequest for inaccessible chat
        telegramBot.tgBot.get_chat_administrators.side_effect = (  # type: ignore[union-attr]
            telegram.error.BadRequest("Bad Request: chat not found")
        )

        # Act: Call getChatAdmins - should NOT raise
        result = await telegramBot.getChatAdmins(groupChat)

        # Assert: Returns empty dict, marks inaccessible, cache NOT populated
        assert result == {}
        mockCacheService.getChatAdmins.assert_called_once_with(groupChat.id)
        mockCacheService.markChatInaccessible.assert_awaited_once_with(groupChat.id)
        mockCacheService.setChatAdmins.assert_not_called()

    async def test_getChatAdmins_maxNotFound_marksInaccessible(
        self, maxBot: TheBot, groupChat: MessageRecipient, mockCacheService: Mock
    ) -> None:
        """Max NotFoundError marks chat inaccessible (memory + DB) and returns {}.

        Args:
            maxBot: The TheBot instance with Max provider.
            groupChat: Test group chat.
            mockCacheService: Mock cache service for verification.
        """
        # Arrange: Max API raises NotFoundError when bot not in chat
        maxBot.maxBot.getAdmins.side_effect = (  # type: ignore[union-attr]
            maxExceptions.NotFoundError("Resource not found.")
        )

        # Act: Call getChatAdmins - should NOT raise
        result = await maxBot.getChatAdmins(groupChat)

        # Assert: Returns empty dict, marks inaccessible, cache NOT populated
        assert result == {}
        mockCacheService.getChatAdmins.assert_called_once_with(groupChat.id)
        mockCacheService.markChatInaccessible.assert_awaited_once_with(groupChat.id)
        mockCacheService.setChatAdmins.assert_not_called()

    async def test_getChatAdmins_telegramSuccess_stillCachesAndDoesNotMarkInaccessible(
        self, telegramBot: TheBot, groupChat: MessageRecipient, mockCacheService: Mock
    ) -> None:
        """Successful fetch still caches admins and does NOT mark inaccessible.

        Args:
            telegramBot: The TheBot instance with Telegram provider.
            groupChat: Test group chat.
            mockCacheService: Mock cache service for verification.
        """
        # Arrange: Telegram API returns admins
        admin1 = Mock()
        admin1.user.id = 123
        admin1.user.username = "admin1"
        admin1.user.full_name = "Admin One"

        telegramBot.tgBot.get_chat_administrators.side_effect = [[admin1]]  # type: ignore[union-attr]

        # Act: Call getChatAdmins
        result = await telegramBot.getChatAdmins(groupChat)

        # Assert: Returns admins dict, cache populated, NOT marked inaccessible
        assert result == {
            123: ("@admin1", "Admin One"),
        }
        mockCacheService.getChatAdmins.assert_called_once_with(groupChat.id)
        mockCacheService.setChatAdmins.assert_called_once_with(groupChat.id, result)
        mockCacheService.markChatInaccessible.assert_not_called()
