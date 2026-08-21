"""Test graceful degradation and failure backoff in TheBot.getBotId().

Pins the bug fix for the missing stale-value fallback on refresh failure.
Before the fix, getBotId() would raise the platform exception immediately
if refresh failed, even if a cached value was available and within the grace
window. After the fix, cached values are used within (TTL + GRACE) seconds
of caching, providing graceful degradation for transient platform issues.

Test Coverage:
- Failure with NO cached value: raises immediately
- Failure WITH fresh cached value: returns stale value within grace window
- Failure with cached value older than TTL+GRACE: raises immediately
- Telegram path unchanged: property access only, no platform API calls
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
import telegram
import telegram.ext

import lib.max_bot as libMax
from internal.bot.common.bot import TheBot
from internal.bot.constants import BOT_ID_CACHE_TTL_SECONDS, BOT_ID_FAILURE_GRACE_SECONDS
from internal.bot.models import BotProvider
from internal.services.cache import CacheService


class TestGetBotIdFailureGracePeriod:
    """Tests for getBotId() failure grace period and stale-value fallback."""

    @pytest.fixture
    def _resetSingletons(self):
        """Reset CacheService singleton around the test."""
        CacheService._instance = None
        yield
        CacheService._instance = None

    @pytest.fixture
    def mockCacheService(self):
        """Create a mock CacheService."""
        cache = Mock(spec=CacheService)
        return cache

    @pytest.fixture
    def maxBotWithGracePeriod(self, mockCacheService, _resetSingletons):
        """Build a Max TheBot instance with mocked deps for grace period testing."""
        maxBotClient = AsyncMock(spec=libMax.MaxBotClient)

        # Create mock user info
        userInfo = Mock()
        userInfo.user_id = 999888777
        userInfo.username = "grace_test_bot"

        maxBotClient.getMyInfo.return_value = userInfo

        config = {"bot_owners": [123456]}

        bot = TheBot(
            botProvider=BotProvider.MAX,
            config=config,
            maxBot=maxBotClient,
        )

        bot.cache = mockCacheService
        return bot

    async def test_failureWithNoCachedValue_propagatesImmediately(self, maxBotWithGracePeriod: TheBot) -> None:
        """Failure with NO cached value: exception propagates immediately.

        Args:
            maxBotWithGracePeriod: The TheBot instance with Max provider.
        """
        bot = maxBotWithGracePeriod

        # Arrange: getMyInfo raises an exception
        bot.maxBot.getMyInfo.side_effect = Exception("Platform unavailable")  # type: ignore[union-attr]

        # Act/Assert: Should raise immediately (no cache to fall back to)
        with pytest.raises(Exception, match="Platform unavailable"):
            await bot.getBotId()

        # Assert: No cache was set (failures never write to cache)
        assert bot._botId is None

    async def test_failureWithFreshCachedValue_returnsStaleWithinGrace(self, maxBotWithGracePeriod: TheBot) -> None:
        """Failure WITH fresh cached value: returns stale value within grace window.

        Args:
            maxBotWithGracePeriod: The TheBot instance with Max provider.
        """
        bot = maxBotWithGracePeriod

        # Arrange: First call succeeds and caches the value at time 0
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            mock_monotonic.return_value = 0.0
            result1 = await bot.getBotId()
            assert result1 == 999888777

        # Reset call count
        bot.maxBot.getMyInfo.reset_mock()  # type: ignore[union-attr]

        # Simulate time passing within TTL (e.g., 3000 seconds)
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            mock_monotonic.return_value = 3000.0
            # Cache is still within TTL, so this should NOT call getMyInfo
            result2 = await bot.getBotId()
            assert result2 == 999888777
            assert bot.maxBot.getMyInfo.call_count == 0  # type: ignore[union-attr]

        # Arrange: Make refresh fail on next call (cache is fresh)
        bot.maxBot.getMyInfo.side_effect = Exception("Platform unavailable")  # type: ignore[union-attr]

        # Simulate time passing to exactly TTL (cache just expired, but still within grace)
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            mock_monotonic.return_value = BOT_ID_CACHE_TTL_SECONDS

            # Act: Should return stale cached value (within grace window)
            result3 = await bot.getBotId()

            # Assert: Returns stale value, exception NOT raised
            assert result3 == 999888777

    async def test_failureWithCacheOlderThanTtlPlusGrace_raisesImmediately(self, maxBotWithGracePeriod: TheBot) -> None:
        """Failure with cached value older than TTL+GRACE: raises immediately.

        Args:
            maxBotWithGracePeriod: The TheBot instance with Max provider.
        """
        bot = maxBotWithGracePeriod

        # Arrange: First call succeeds and caches the value at time 0
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            mock_monotonic.return_value = 0.0
            result1 = await bot.getBotId()
            assert result1 == 999888777

        # Arrange: Make refresh fail on subsequent calls
        bot.maxBot.getMyInfo.side_effect = Exception("Platform unavailable")  # type: ignore[union-attr]

        # Simulate time passing beyond TTL+GRACE (cache is too old to use)
        with patch("internal.bot.common.bot.time.monotonic") as mock_monotonic:
            mock_monotonic.return_value = BOT_ID_CACHE_TTL_SECONDS + BOT_ID_FAILURE_GRACE_SECONDS + 1.0

            # Act/Assert: Should raise immediately (cache too old, no fallback)
            with pytest.raises(Exception, match="Platform unavailable"):
                await bot.getBotId()

    async def test_telegramPathUnchanged_propertyAccessOnly(self, mockCacheService, _resetSingletons) -> None:
        """Telegram path unchanged: tgBot.id property access only, no platform API calls.

        Args:
            mockCacheService: Mock cache service.
            _resetSingletons: Fixture to reset CacheService singleton.
        """
        # Mock the telegram.ext.ExtBot
        tgBot = AsyncMock(spec=telegram.ext.ExtBot)
        tgBot.id = 123456789
        tgBot.username = "test_bot"

        config = {"bot_owners": [123456]}

        bot = TheBot(botProvider=BotProvider.TELEGRAM, config=config, tgBot=tgBot)
        bot.cache = mockCacheService

        # Act: Call getBotId
        result = await bot.getBotId()

        # Assert: Returns correct bot ID via property access
        assert result == 123456789

        # Verify cache was set
        assert bot._botId == 123456789

        # Second call should return cached value without property access
        result2 = await bot.getBotId()
        assert result2 == 123456789
