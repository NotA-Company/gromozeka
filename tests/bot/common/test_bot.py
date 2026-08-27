"""Regression tests for TheBot.getChatAdmins graceful degradation.

Pins the fix for the bug where getChatAdmins would crash when the bot was
kicked from a chat or no longer had access. Before the fix, the method would
raise telegram.error.Forbidden or lib.max_bot.exceptions.NotFoundError and
propagate up through isAdmin and chatConfiguration_Init, crashing the entire
/configure command. After the fix, it logs a warning and returns an empty dict,
which the caller (isAdmin) treats as "no admins in this chat".
"""

from datetime import datetime, timedelta, timezone
from typing import Generator
from unittest.mock import AsyncMock, Mock, patch

import pytest
import telegram
import telegram.error
import telegram.ext
from telegram.warnings import PTBDeprecationWarning

import lib.max_bot as libMax
import lib.max_bot.exceptions as maxExceptions
from internal.bot.common.bot import TheBot
from internal.bot.models import BotProvider, ChatType, EnsuredMessage, MessageRecipient, MessageSender
from internal.models import MessageId
from internal.services.cache import CacheService
from tests.utils import createMockMessage


@pytest.fixture
def _resetSingletons() -> Generator[None, None, None]:
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
def mockCacheService() -> Mock:
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
def telegramBot(mockCacheService: Mock, _resetSingletons: None) -> TheBot:
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


class TestGetChatAdminsRegression:
    """Pins getChatAdmins graceful degradation for access-denied errors."""

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


class TestTelegramSendRetry:
    """Tests for Telegram send retry logic in _retryTelegramSend.

    The int-form ``retry_after`` is deliberately exercised for forward-compat: while
    ``PTB_TIMEDELTA`` is unset, PTB emits a ``PTBDeprecationWarning`` on every
    ``retry_after`` property access, so the RetryAfter tests wrap their bodies in
    ``pytest.warns(PTBDeprecationWarning)`` to assert that expectation instead of
    filtering it — a tripwire that fails when PTB flips the default.
    """

    @pytest.fixture
    def replyToMessage(self) -> EnsuredMessage:
        """Create a test EnsuredMessage for use as replyToMessage.

        Returns:
            EnsuredMessage for a user message.
        """
        return EnsuredMessage(
            sender=MessageSender(id=456, name="Test User", username="@testuser"),
            recipient=MessageRecipient(id=123, chatType=ChatType.PRIVATE),
            messageId=MessageId(789),
            date=datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc),
            messageText="test message",
        )

    # A. Direct unit tests for _retryTelegramSend

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryTelegramSend_timedOutThenSuccess_retriesAndReturns(
        self, mockSleep: AsyncMock, telegramBot: TheBot
    ) -> None:
        """TimedOut exceptions trigger retry with exponential backoff + jitter.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
        """
        # Arrange: Callable fails twice with TimedOut, then succeeds
        mockCallable = AsyncMock(
            side_effect=[
                telegram.error.TimedOut("Timed out"),
                telegram.error.TimedOut("Timed out"),
                "ok",
            ]
        )

        # Act: Call _retryTelegramSend
        result = await telegramBot._retryTelegramSend(mockCallable)

        # Assert: Returns result, called 3 times, slept twice
        assert result == "ok"
        assert mockCallable.call_count == 3
        assert mockSleep.call_count == 2

        # Check first delay: base=0.5 * 2**0 + jitter[0,0.5] = [0.5, 1.0]
        firstDelay = mockSleep.call_args_list[0].args[0]
        assert 0.5 <= firstDelay <= 1.0

        # Check second delay: base=0.5 * 2**1 + jitter[0,0.5] = [1.0, 1.5]
        secondDelay = mockSleep.call_args_list[1].args[0]
        assert 1.0 <= secondDelay <= 1.5

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryTelegramSend_timedOutExhausted_raisesAfterMaxAttempts(
        self, mockSleep: AsyncMock, telegramBot: TheBot
    ) -> None:
        """Exhausted retries raise the last TimedOut exception.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
        """
        # Arrange: Callable always fails with TimedOut
        mockCallable = AsyncMock(
            side_effect=[
                telegram.error.TimedOut("Timed out"),
                telegram.error.TimedOut("Timed out"),
                telegram.error.TimedOut("Timed out"),
            ]
        )

        # Act/Assert: Raises TimedOut after max attempts
        with pytest.raises(telegram.error.TimedOut):
            await telegramBot._retryTelegramSend(mockCallable)

        # Assert: Called 3 times (max), slept twice (no sleep after last attempt)
        assert mockCallable.call_count == 3
        assert mockSleep.call_count == 2

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryTelegramSend_badRequest_notRetried(self, mockSleep: AsyncMock, telegramBot: TheBot) -> None:
        """BadRequest is a client error and never retried.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
        """
        # Arrange: Callable fails with BadRequest
        mockCallable = AsyncMock(side_effect=[telegram.error.BadRequest("message is too long")])

        # Act/Assert: Raises BadRequest immediately
        with pytest.raises(telegram.error.BadRequest):
            await telegramBot._retryTelegramSend(mockCallable)

        # Assert: Called once, never slept
        assert mockCallable.call_count == 1
        mockSleep.assert_not_called()

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryTelegramSend_forbidden_notRetried(self, mockSleep: AsyncMock, telegramBot: TheBot) -> None:
        """Forbidden is a non-retryable error and never retried.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
        """
        # Arrange: Callable fails with Forbidden
        mockCallable = AsyncMock(side_effect=[telegram.error.Forbidden("bot was blocked")])

        # Act/Assert: Raises Forbidden immediately
        with pytest.raises(telegram.error.Forbidden):
            await telegramBot._retryTelegramSend(mockCallable)

        # Assert: Called once, never slept
        assert mockCallable.call_count == 1
        mockSleep.assert_not_called()

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryTelegramSend_retryAfterThenSuccess_honorsRetryAfter(
        self, mockSleep: AsyncMock, telegramBot: TheBot
    ) -> None:
        """RetryAfter exception honors the retry_after delay.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
        """
        with pytest.warns(PTBDeprecationWarning):
            # Arrange: Callable fails with RetryAfter, then succeeds
            mockCallable = AsyncMock(
                side_effect=[
                    telegram.error.RetryAfter(retry_after=2),
                    "ok",
                ]
            )

            # Act: Call _retryTelegramSend
            result = await telegramBot._retryTelegramSend(mockCallable)

            # Assert: Returns result, called twice, slept once with exact delay
            assert result == "ok"
            assert mockCallable.call_count == 2
            assert mockSleep.call_count == 1
            assert mockSleep.call_args.args[0] == 2.0

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryTelegramSend_retryAfterOverCap_cappedAt60(
        self, mockSleep: AsyncMock, telegramBot: TheBot
    ) -> None:
        """RetryAfter delay is capped at 60 seconds.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
        """
        with pytest.warns(PTBDeprecationWarning):
            # Arrange: Callable fails with RetryAfter(999) twice, then succeeds
            mockCallable = AsyncMock(
                side_effect=[
                    telegram.error.RetryAfter(retry_after=999),
                    telegram.error.RetryAfter(retry_after=999),
                    "ok",
                ]
            )

            # Act: Call _retryTelegramSend
            result = await telegramBot._retryTelegramSend(mockCallable)

            # Assert: Returns result, called 3 times, slept twice with capped delay
            assert result == "ok"
            assert mockCallable.call_count == 3
            assert mockSleep.call_count == 2
            assert mockSleep.call_args_list[0].args[0] == 60.0
            assert mockSleep.call_args_list[1].args[0] == 60.0

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryTelegramSend_retryAfterAsTimedelta_honored(
        self, mockSleep: AsyncMock, telegramBot: TheBot
    ) -> None:
        """RetryAfter with timedelta is converted to float seconds.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
        """
        with pytest.warns(PTBDeprecationWarning):
            # Arrange: Callable fails with RetryAfter(timedelta), then succeeds
            mockCallable = AsyncMock(
                side_effect=[
                    telegram.error.RetryAfter(retry_after=timedelta(seconds=3)),
                    "ok",
                ]
            )

            # Act: Call _retryTelegramSend
            result = await telegramBot._retryTelegramSend(mockCallable)

            # Assert: Returns result, slept with converted delay
            assert result == "ok"
            assert mockCallable.call_count == 2
            assert mockSleep.call_count == 1
            assert mockSleep.call_args.args[0] == 3.0

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryTelegramSend_networkErrorThenSuccess_retries(
        self, mockSleep: AsyncMock, telegramBot: TheBot
    ) -> None:
        """NetworkError triggers retry with exponential backoff + jitter.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
        """
        # Arrange: Callable fails with NetworkError, then succeeds
        mockCallable = AsyncMock(
            side_effect=[
                telegram.error.NetworkError("connection reset"),
                "ok",
            ]
        )

        # Act: Call _retryTelegramSend
        result = await telegramBot._retryTelegramSend(mockCallable)

        # Assert: Returns result, called twice, slept once with backoff
        assert result == "ok"
        assert mockCallable.call_count == 2
        assert mockSleep.call_count == 1
        delay = mockSleep.call_args.args[0]
        assert 0.5 <= delay <= 1.0

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryTelegramSend_successOnFirstAttempt_noRetry(
        self, mockSleep: AsyncMock, telegramBot: TheBot
    ) -> None:
        """Successful call on first attempt does not retry.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
        """
        # Arrange: Callable succeeds on first try
        mockCallable = AsyncMock(side_effect=["ok"])

        # Act: Call _retryTelegramSend
        result = await telegramBot._retryTelegramSend(mockCallable)

        # Assert: Returns result, called once, never slept
        assert result == "ok"
        assert mockCallable.call_count == 1
        mockSleep.assert_not_called()

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryTelegramSend_retryAfterExhausted_raisesAfterMaxAttempts(
        self, mockSleep: AsyncMock, telegramBot: TheBot
    ) -> None:
        """Exhausted RetryAfter exceptions raise after max attempts.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
        """
        with pytest.warns(PTBDeprecationWarning):
            # Arrange: Callable always fails with RetryAfter(retry_after=1)
            mockCallable = AsyncMock(
                side_effect=[
                    telegram.error.RetryAfter(retry_after=1),
                    telegram.error.RetryAfter(retry_after=1),
                    telegram.error.RetryAfter(retry_after=1),
                ]
            )

            # Act/Assert: Raises RetryAfter after max attempts
            with pytest.raises(telegram.error.RetryAfter):
                await telegramBot._retryTelegramSend(mockCallable)

            # Assert: Called 3 times (max), slept twice (no sleep after last attempt)
            assert mockCallable.call_count == 3
            assert mockSleep.call_count == 2

            # Verify both sleeps honored retry_after=1.0 (under cap)
            assert mockSleep.call_args_list[0].args[0] == 1.0
            assert mockSleep.call_args_list[1].args[0] == 1.0

    # B. Integration tests via TheBot.sendMessage

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_sendMessage_timedOutInMarkdownPath_doesNotTriggerPlaintextFallback(
        self, mockSleep: AsyncMock, telegramBot: TheBot, replyToMessage: EnsuredMessage
    ) -> None:
        """TimedOut in markdown path bubbles past narrowed except; plaintext fallback NOT triggered.

        This is the KEY regression test for the narrowed except clause. Before the fix,
        TimedOut would be caught by the broad `except Exception` and incorrectly trigger
        the plaintext fallback. After the fix, TimedOut bubbles past the narrowed except
        and exhausts retries, returning an empty list (partial results).

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
            replyToMessage: The EnsuredMessage to reply to.
        """
        # Arrange: send_message always fails with TimedOut (exhausts retries)
        telegramBot.tgBot.send_message.side_effect = [  # type: ignore[union-attr]
            telegram.error.TimedOut("Timed out"),
            telegram.error.TimedOut("Timed out"),
            telegram.error.TimedOut("Timed out"),
        ]

        # Act: Send message with markdown (error message send disabled to avoid call_count noise)
        result = await telegramBot.sendMessage(
            replyToMessage=replyToMessage,
            messageText="hello",
            tryMarkdownV2=True,
            sendErrorIfAny=False,
        )

        # Assert: send_message called 3 times (only markdown path, NO plaintext fallback)
        assert telegramBot.tgBot.send_message.call_count == 3  # type: ignore[union-attr]
        assert result == []

        # Verify sleep was called for retries
        assert mockSleep.call_count == 2

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_sendMessage_badRequestInMarkdownPath_triggersPlaintextFallback(
        self, mockSleep: AsyncMock, telegramBot: TheBot, replyToMessage: EnsuredMessage
    ) -> None:
        """BadRequest in markdown path triggers plaintext fallback.

        This verifies the preserved markdown-fallback behavior after the narrowed except fix.
        BadRequest is caught by the narrowed except, triggering the plaintext attempt.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
            replyToMessage: The EnsuredMessage to reply to.
        """
        # Arrange: send_message fails with BadRequest first, then succeeds
        successMessage = createMockMessage(text="hello")
        telegramBot.tgBot.send_message.side_effect = [  # type: ignore[union-attr]
            telegram.error.BadRequest("can't parse entities"),
            successMessage,
        ]

        # Act: Send message with markdown
        result = await telegramBot.sendMessage(
            replyToMessage=replyToMessage,
            messageText="hello",
            tryMarkdownV2=True,
            sendErrorIfAny=False,
        )

        # Assert: send_message called twice (markdown failed, plaintext succeeded)
        assert telegramBot.tgBot.send_message.call_count == 2  # type: ignore[union-attr]

        # Verify first call had parse_mode (markdown attempt)
        firstKwargs = telegramBot.tgBot.send_message.call_args_list[0].kwargs  # type: ignore[union-attr]
        assert "parse_mode" in firstKwargs

        # Verify second call did NOT have parse_mode (plaintext fallback)
        secondKwargs = telegramBot.tgBot.send_message.call_args_list[1].kwargs  # type: ignore[union-attr]
        assert "parse_mode" not in secondKwargs

        # Verify no retry sleeps (BadRequest is non-retryable)
        mockSleep.assert_not_called()

        # Assert: Returns list with one EnsuredMessage
        assert len(result) == 1
        assert result[0].messageId.asInt() == successMessage.message_id

    # C. Integration test for editMessage

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_editMessage_timedOutThenSuccess_retries(self, mockSleep: AsyncMock, telegramBot: TheBot) -> None:
        """editMessage retries on TimedOut using _retryTelegramSend.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
        """
        # Arrange: edit_message_text fails with TimedOut, then succeeds
        successMock = Mock()
        telegramBot.tgBot.edit_message_text.side_effect = [  # type: ignore[union-attr]
            telegram.error.TimedOut("Timed out"),
            successMock,
        ]

        # Act: Edit message (useMarkdown=False to skip markdownToMarkdownV2 path)
        result = await telegramBot.editMessage(
            messageId=MessageId(1),
            chatId=123,
            text="edited",
            useMarkdown=False,
        )

        # Assert: edit_message_text called twice, slept once, result is truthy
        assert telegramBot.tgBot.edit_message_text.call_count == 2  # type: ignore[union-attr]
        assert mockSleep.call_count == 1
        assert result

    @patch("internal.bot.common.bot.asyncio.sleep", new_callable=AsyncMock)
    async def test_sendMessage_photoTimedOutThenSuccess_retries(
        self, mockSleep: AsyncMock, telegramBot: TheBot, replyToMessage: EnsuredMessage
    ) -> None:
        """send_photo retries on TimedOut using _retryTelegramSend.

        Args:
            mockSleep: Mocked asyncio.sleep for delay verification.
            telegramBot: The TheBot instance with Telegram provider.
            replyToMessage: The EnsuredMessage to reply to.
        """
        # Arrange: send_photo fails with TimedOut, then succeeds
        successMessage = createMockMessage(text="photo")
        telegramBot.tgBot.send_photo.side_effect = [  # type: ignore[union-attr]
            telegram.error.TimedOut("Timed out"),
            successMessage,
        ]

        # Act: Send photo with tryMarkdownV2=False to isolate the photo retry from markdown path
        result = await telegramBot.sendMessage(
            replyToMessage=replyToMessage,
            messageText="caption",
            photoData=b"fakeimg",
            tryMarkdownV2=False,
            sendErrorIfAny=False,
        )

        # Assert: send_photo called twice, slept once, result is non-empty list
        assert telegramBot.tgBot.send_photo.call_count == 2  # type: ignore[union-attr]
        assert mockSleep.call_count == 1
        assert len(result) == 1
        assert result[0].messageId.asInt() == successMessage.message_id


class TestGetBotIdMemoization:
    """Tests for TheBot.getBotId() memoization to avoid repeated platform API calls."""

    @pytest.fixture
    def maxBotWithMemoization(self, mockCacheService: Mock, _resetSingletons: None) -> TheBot:
        """Build a Max TheBot instance with mocked deps for memoization testing.

        Args:
            mockCacheService: Mock cache service.
            _resetSingletons: Fixture to reset CacheService singleton (requested explicitly by bot fixtures).

        Returns:
            A configured TheBot with Max provider.
        """
        # Mock the MaxBotClient with getMyInfo that tracks call count
        maxBotClient = AsyncMock(spec=libMax.MaxBotClient)

        # Create mock user info
        userInfo = Mock()
        userInfo.user_id = 999888777
        userInfo.username = "memo_test_bot"

        maxBotClient.getMyInfo.return_value = userInfo

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

    async def test_getBotId_max_resolvesOnceThenReturnsCached(self, maxBotWithMemoization: TheBot) -> None:
        """getBotId() resolves from API on first call, then returns cached value.

        First call invokes getMyInfo() and caches the result. Subsequent calls
        within the TTL window return the cached value without re-invoking getMyInfo().

        Args:
            maxBotWithMemoization: The TheBot instance with Max provider.
        """
        # Arrange
        bot = maxBotWithMemoization
        expectedBotId = 999888777

        # Act: First call should invoke getMyInfo()
        result1 = await bot.getBotId()

        # Assert: Returns correct bot ID, getMyInfo called once
        assert result1 == expectedBotId
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]

        # Act: Second call should return cached value
        result2 = await bot.getBotId()

        # Assert: Returns same bot ID, getMyInfo still called once (not called again)
        assert result2 == expectedBotId
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]

        # Act: Third call (extra verification)
        result3 = await bot.getBotId()

        # Assert: Returns same bot ID, getMyInfo still called once
        assert result3 == expectedBotId
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]

    async def test_getBotId_max_cacheExpiredReResolves(self, maxBotWithMemoization: TheBot) -> None:
        """getBotId() re-resolves from API after TTL expires.

        First call invokes getMyInfo() and caches the result with a timestamp.
        After advancing time.monotonic() past the TTL window, a subsequent call
        re-invokes getMyInfo() with useCache=False and updates the cached value.

        Args:
            maxBotWithMemoization: The TheBot instance with Max provider.
        """
        # Arrange
        bot = maxBotWithMemoization
        expectedBotId1 = 999888777

        # First, reset the cached values to ensure we control the initial state
        bot._botId = None
        bot._botIdCachedAt = 0.0

        # Act: First call should invoke getMyInfo() and cache the timestamp
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            # First call sets _botIdCachedAt to 100.0 (non-zero for hasCachedValue check)
            mock_monotonic.return_value = 100.0
            result1 = await bot.getBotId()

        # Assert: Returns correct bot ID, getMyInfo called once with useCache=False
        assert result1 == expectedBotId1
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]
        assert bot._botIdCachedAt == 100.0  # Was set to our mocked value
        bot.maxBot.getMyInfo.assert_called_once_with(useCache=False)  # type: ignore[union-attr]

        # Update the mock to return a different bot ID on second resolution
        newUserInfo = Mock()
        newUserInfo.user_id = 111222333
        newUserInfo.username = "memo_test_bot_updated"
        bot.maxBot.getMyInfo.return_value = newUserInfo  # type: ignore[union-attr]

        # Act: Advance time past TTL (3600 seconds) by patching the module's reference
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            # Return a time > TTL (3600) to force re-resolution
            mock_monotonic.return_value = 7300.0  # 100 + 7200 (past TTL)

            # Act: Second call after TTL expired should re-resolve
            result2 = await bot.getBotId()

            # Assert: Returns new bot ID, getMyInfo called twice, both with useCache=False
            assert result2 == 111222333
            assert bot.maxBot.getMyInfo.call_count == 2  # type: ignore[union-attr]
            # Verify both calls had useCache=False
            for call in bot.maxBot.getMyInfo.call_args_list:  # type: ignore[union-attr]
                assert call.kwargs == {"useCache": False}

    async def test_getBotId_max_cacheWithinTtlNoReResolve(self, maxBotWithMemoization: TheBot) -> None:
        """getBotId() does not re-resolve when called within TTL window.

        Verifies that time.monotonic() is used correctly and the cached value is
        returned as long as the time since caching is less than BOT_ID_CACHE_TTL_SECONDS.

        Args:
            maxBotWithMemoization: The TheBot instance with Max provider.
        """
        # Arrange
        bot = maxBotWithMemoization
        expectedBotId = 999888777

        # Reset the cached values to ensure we control the initial state
        bot._botId = None
        bot._botIdCachedAt = 0.0

        # Act: First call should invoke getMyInfo() and cache the timestamp
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            # First call sets _botIdCachedAt to 100.0 (non-zero for hasCachedValue check)
            mock_monotonic.return_value = 100.0
            result1 = await bot.getBotId()

        # Assert: Returns correct bot ID, getMyInfo called once
        assert result1 == expectedBotId
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]
        assert bot._botIdCachedAt == 100.0  # Was set to our mocked value

        # Act: Advance time within TTL (less than 3600 seconds)
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            # Return a time < TTL (3600) to ensure cache is still valid
            mock_monotonic.return_value = 3100.0  # 100 + 3000, still within TTL

            # Act: Second call should return cached value
            result2 = await bot.getBotId()

            # Assert: Returns same bot ID, getMyInfo still called once (not called again)
            assert result2 == expectedBotId
            assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]

    async def test_getBotId_telegram_returnsCachedWithoutRepeatedAccess(self, telegramBot: TheBot) -> None:
        """getBotId() on Telegram returns cached value; tgBot.id accessed once.

        For Telegram, the bot ID comes from tgBot.id which is a property, so
        we verify the method is memoized correctly.

        Args:
            telegramBot: The TheBot instance with Telegram provider.
        """
        # Arrange
        expectedBotId = 123456789

        # Act: First call
        result1 = await telegramBot.getBotId()

        # Assert: Returns correct bot ID
        assert result1 == expectedBotId

        # Act: Second call should return cached value
        result2 = await telegramBot.getBotId()

        # Assert: Returns same bot ID (cached)
        assert result2 == expectedBotId
        # For Telegram, we just verify the values are identical
        assert result1 == result2

    async def test_getBotId_max_cachePersistsAcrossMultipleCalls(self, maxBotWithMemoization: TheBot) -> None:
        """getBotId() cache persists across many calls without re-resolving.

        This stress test verifies that no matter how many times we call getBotId()
        within the TTL window, getMyInfo() is only ever called once.

        Args:
            maxBotWithMemoization: The TheBot instance with Max provider.
        """
        # Arrange
        bot = maxBotWithMemoization
        expectedBotId = 999888777

        # Act: Call getBotId() 10 times
        results = []
        for _ in range(10):
            result = await bot.getBotId()
            results.append(result)

        # Assert: All results are identical
        assert all(result == expectedBotId for result in results)

        # Assert: getMyInfo() was called exactly once
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]


class TestGetBotUserNameMemoization:
    """Tests for TheBot.getBotUserName() memoization to avoid repeated platform API calls."""

    @pytest.fixture
    def maxBotWithMemoization(self, mockCacheService: Mock, _resetSingletons: None) -> TheBot:
        """Build a Max TheBot instance with mocked deps for memoization testing.

        Args:
            mockCacheService: Mock cache service.
            _resetSingletons: Fixture to reset CacheService singleton (requested explicitly by bot fixtures).

        Returns:
            A configured TheBot with Max provider.
        """
        # Mock the MaxBotClient with getMyInfo that tracks call count
        maxBotClient = AsyncMock(spec=libMax.MaxBotClient)

        # Create mock user info
        userInfo = Mock()
        userInfo.user_id = 999888777
        userInfo.username = "memo_test_bot"

        maxBotClient.getMyInfo.return_value = userInfo

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

    async def test_getBotUserName_max_resolvesOnceThenReturnsCached(self, maxBotWithMemoization: TheBot) -> None:
        """getBotUserName() resolves from API on first call, then returns cached value.

        First call invokes getMyInfo() and caches the result. Subsequent calls
        within the TTL window return the cached value without re-invoking getMyInfo().

        Args:
            maxBotWithMemoization: The TheBot instance with Max provider.
        """
        # Arrange
        bot = maxBotWithMemoization
        expectedUserName = "memo_test_bot"

        # Act: First call should invoke getMyInfo()
        result1 = await bot.getBotUserName()

        # Assert: Returns correct username, getMyInfo called once
        assert result1 == expectedUserName
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]

        # Act: Second call should return cached value
        result2 = await bot.getBotUserName()

        # Assert: Returns same username, getMyInfo still called once (not called again)
        assert result2 == expectedUserName
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]

        # Act: Third call (extra verification)
        result3 = await bot.getBotUserName()

        # Assert: Returns same username, getMyInfo still called once
        assert result3 == expectedUserName
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]

    async def test_getBotUserName_max_cacheExpiredReResolves(self, maxBotWithMemoization: TheBot) -> None:
        """getBotUserName() re-resolves from API after TTL expires.

        First call invokes getMyInfo() and caches the result with a timestamp.
        After advancing time.monotonic() past the TTL window, a subsequent call
        re-invokes getMyInfo() with useCache=False and updates the cached value.

        Args:
            maxBotWithMemoization: The TheBot instance with Max provider.
        """
        # Arrange
        bot = maxBotWithMemoization
        expectedUserName1 = "memo_test_bot"

        # First, reset the cached values to ensure we control the initial state
        bot._botUserName = None
        bot._botUserNameCachedAt = 0.0

        # Act: First call should invoke getMyInfo() and cache the timestamp
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            # First call sets _botUserNameCachedAt to 100.0 (non-zero for hasCachedValue check)
            mock_monotonic.return_value = 100.0
            result1 = await bot.getBotUserName()

        # Assert: Returns correct username, getMyInfo called once with useCache=False
        assert result1 == expectedUserName1
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]
        assert bot._botUserNameCachedAt == 100.0  # Was set to our mocked value
        bot.maxBot.getMyInfo.assert_called_once_with(useCache=False)  # type: ignore[union-attr]

        # Update the mock to return a different username on second resolution
        newUserInfo = Mock()
        newUserInfo.user_id = 999888777
        newUserInfo.username = "memo_test_bot_updated"
        bot.maxBot.getMyInfo.return_value = newUserInfo  # type: ignore[union-attr]

        # Act: Advance time past TTL (3600 seconds) by patching the module's reference
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            # Return a time > TTL (3600) to force re-resolution
            mock_monotonic.return_value = 7300.0  # 100 + 7200 (past TTL)

            # Act: Second call after TTL expired should re-resolve
            result2 = await bot.getBotUserName()

            # Assert: Returns new username, getMyInfo called twice, both with useCache=False
            assert result2 == "memo_test_bot_updated"
            assert bot.maxBot.getMyInfo.call_count == 2  # type: ignore[union-attr]
            # Verify both calls had useCache=False
            for call in bot.maxBot.getMyInfo.call_args_list:  # type: ignore[union-attr]
                assert call.kwargs == {"useCache": False}

    async def test_getBotUserName_max_cacheWithinTtlNoReResolve(self, maxBotWithMemoization: TheBot) -> None:
        """getBotUserName() does not re-resolve when called within TTL window.

        Verifies that time.monotonic() is used correctly and the cached value is
        returned as long as the time since caching is less than BOT_USERNAME_CACHE_TTL_SECONDS.

        Args:
            maxBotWithMemoization: The TheBot instance with Max provider.
        """
        # Arrange
        bot = maxBotWithMemoization
        expectedUserName = "memo_test_bot"

        # Reset the cached values to ensure we control the initial state
        bot._botUserName = None
        bot._botUserNameCachedAt = 0.0

        # Act: First call should invoke getMyInfo() and cache the timestamp
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            # First call sets _botUserNameCachedAt to 100.0 (non-zero for hasCachedValue check)
            mock_monotonic.return_value = 100.0
            result1 = await bot.getBotUserName()

        # Assert: Returns correct username, getMyInfo called once
        assert result1 == expectedUserName
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]
        assert bot._botUserNameCachedAt == 100.0  # Was set to our mocked value

        # Act: Advance time within TTL (less than 3600 seconds)
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            # Return a time < TTL (3600) to ensure cache is still valid
            mock_monotonic.return_value = 3100.0  # 100 + 3000, still within TTL

            # Act: Second call should return cached value
            result2 = await bot.getBotUserName()

            # Assert: Returns same username, getMyInfo still called once (not called again)
            assert result2 == expectedUserName
            assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]

    async def test_getBotUserName_telegram_returnsCachedWithoutRepeatedAccess(self, telegramBot: TheBot) -> None:
        """getBotUserName() on Telegram returns cached value; tgBot.username accessed once.

        For Telegram, the bot username comes from tgBot.username which is a property, so
        we verify the method is memoized correctly.

        Args:
            telegramBot: The TheBot instance with Telegram provider.
        """
        # Arrange
        expectedUserName = "test_bot"

        # Act: First call
        result1 = await telegramBot.getBotUserName()

        # Assert: Returns correct username
        assert result1 == expectedUserName

        # Act: Second call should return cached value
        result2 = await telegramBot.getBotUserName()

        # Assert: Returns same username (cached)
        assert result2 == expectedUserName
        # For Telegram, we just verify the values are identical
        assert result1 == result2

    async def test_getBotUserName_max_noneUsername_cachesCorrectly(self, maxBotWithMemoization: TheBot) -> None:
        """getBotUserName() correctly caches None username (legitimate platform value).

        Regression test for the sentinel collision bug: the cache gates were checking
        `self._botUserName is not None`, which caused the cache to never hit when
        the platform legitimately returned username=None. This resulted in an uncached
        HTTP call on every getBotUserName() invocation.

        After the fix, the cache gates on `self._botUserNameCachedAt > 0` instead,
        which distinguishes "never resolved" from "resolved to None".

        Args:
            maxBotWithMemoization: The TheBot instance with Max provider.
        """
        # Arrange: Mock getMyInfo to return None username (legitimate platform value)
        bot = maxBotWithMemoization
        userInfo = Mock()
        userInfo.user_id = 999888777
        userInfo.username = None  # Legitimate None value

        bot.maxBot.getMyInfo.return_value = userInfo  # type: ignore[union-attr]

        # Act: First call should invoke getMyInfo()
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            mock_monotonic.return_value = 100.0
            result1 = await bot.getBotUserName()

        # Assert: Returns None (correct), getMyInfo called once
        assert result1 is None
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]
        assert bot._botUserNameCachedAt == 100.0  # Timestamp was set on success

        # Act: Second call should return cached None without re-invoking getMyInfo()
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            mock_monotonic.return_value = 3100.0  # 100 + 3000, still within TTL
            result2 = await bot.getBotUserName()

        # Assert: Returns None (cached), getMyInfo still called once total
        assert result2 is None
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]

    async def test_getBotUserName_max_cachePersistsAcrossMultipleCalls(self, maxBotWithMemoization: TheBot) -> None:
        """getBotUserName() cache persists across many calls without re-resolving.

        This stress test verifies that no matter how many times we call getBotUserName()
        within the TTL window, getMyInfo() is only ever called once.

        Args:
            maxBotWithMemoization: The TheBot instance with Max provider.
        """
        # Arrange
        bot = maxBotWithMemoization
        expectedUserName = "memo_test_bot"

        # Act: Call getBotUserName() 10 times
        results = []
        for _ in range(10):
            result = await bot.getBotUserName()
            results.append(result)

        # Assert: All results are identical
        assert all(result == expectedUserName for result in results)

        # Assert: getMyInfo() was called exactly once
        assert bot.maxBot.getMyInfo.call_count == 1  # type: ignore[union-attr]
