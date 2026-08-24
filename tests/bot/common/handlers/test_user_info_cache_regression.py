"""End-to-end regression tests for the write-through ``chat_users`` cache (Phase 5).

Proves the cache actually eliminates redundant ``chat_users`` DB reads/writes on
the message hot path — the headline claim of the feature. The cache-layer unit
tests in ``tests/services/cache/test_user_info.py`` already cover the five
``CacheService`` methods in isolation; these tests drive the same claims through
real handler methods (``saveChatMessage`` + ``cache.getUserMetadata``) wired to a
real in-memory database, so they would break if a handler were ever rewired
back to the raw ``db.chatUsers`` repo.

Test level: **handler-method**. We call ``handler.saveChatMessage(...)`` and
``handler.cache.getUserMetadata(...)`` directly rather than driving a full
``newMessageHandler`` pipeline (which would need a live ``_bot`` for media
processing, chat-info refresh, etc.). ``updateChatInfo`` — the one
``saveChatMessage`` dependency that touches ``self._bot`` — is stubbed at the
instance level. Everything else (the cache, the DB, ``cache.updateChatUser``,
``cache.getUserMetadata``) runs for real.

Spies patch ``ChatUsersRepository`` at the **class** level (the repo declares
``__slots__ = ()``, which forbids instance-level ``patch.object``) using
``AsyncMock(wraps=originalMethod)`` so the real DB still works and every call is
recorded.

Headline assertions:

* **Warm cache + unchanged sender** → ``ChatUsersRepository.updateChatUser``
  call count 0 (skip-when-unchanged) AND ``ChatUsersRepository.getChatUser``
  call count 0 (warm hit) for one inbound message.
* **Warm cache + changed username** → ``updateChatUser`` call count >= 1 (the
  cache does not swallow genuine writes).
* **Cold cache** → ``getChatUser`` call count >= 1 (a cache miss falls through
  to the DB rather than silently returning stale/empty data).
"""

import datetime
from typing import Generator
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.message_preprocessor import MessagePreprocessorHandler
from internal.bot.models import (
    BotProvider,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
    MessageType,
)
from internal.database import Database
from internal.database.models import MessageCategory
from internal.database.repositories.chat_users import ChatUsersRepository
from internal.services.cache import CacheService
from internal.services.queue_service.service import QueueService
from lib.db.utils import DEFAULT_THREAD_ID

# Fixed identifiers used across every test — keeping them constant makes the
# pre-seed / warm / drive steps line up unambiguously.
_CHAT_ID = 100
_USER_ID = 7
_USERNAME = "alice"
_FULL_NAME = "Alice"


# ---------------------------------------------------------------------------
# Singleton hygiene
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _resetSingletons() -> Generator[None, None, None]:
    """Reset the ``CacheService`` and ``QueueService`` singletons around every test.

    ``tests/conftest.py`` resets ``LLMService`` / ``ProxyService`` /
    ``ProxyHelper`` autouse, but not ``CacheService`` or ``QueueService``. The
    cache singleton holds a reference to the injected database, so without a
    reset the closed in-memory database from the previous test would leak into
    the next one.

    Yields:
        None.
    """
    CacheService._instance = None
    QueueService._instance = None
    yield
    CacheService._instance = None
    QueueService._instance = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeConfigManager() -> Mock:
    """Build a minimal ``ConfigManager`` stub for the handler constructor.

    ``BaseBotHandler.__init__`` reads ``getBotConfig()``;
    ``MessagePreprocessorHandler.__init__`` additionally reads
    ``getSearchHistoryConfig()`` to cache ``_searchEnabled``. Returning
    ``{"enabled": False}`` keeps the embedding-dispatch path dormant — these
    tests never reach the post-save embedding block.

    Returns:
        ``Mock`` exposing ``getBotConfig()`` returning a token/owners dict and
        ``getSearchHistoryConfig()`` returning ``{"enabled": False}``.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test_token", "owners": [123456]})
    cm.getSearchHistoryConfig = Mock(return_value={"enabled": False})
    return cm


async def _makeHandler(testDatabase: Database) -> MessagePreprocessorHandler:
    """Construct a :class:`MessagePreprocessorHandler` wired to a real in-memory DB.

    Resets the ``CacheService`` singleton, injects *testDatabase* into it (so
    ``handler.cache.updateChatUser`` / ``getUserMetadata`` round-trip through
    SQLite), then builds the handler. The handler's ``BaseBotHandler.__init__``
    re-fetches the same cache singleton, so ``handler.cache`` is the injected
    instance. ``updateChatInfo`` is stubbed at the instance level because the
    real implementation needs ``self._bot`` (not wired in tests); this isolates
    the ``cache.updateChatUser`` hot-path write that is the subject of these
    tests.

    Args:
        testDatabase: Fresh in-memory :class:`Database` (``testDatabase``
            fixture).

    Returns:
        A fully wired :class:`MessagePreprocessorHandler` whose ``cache`` is
        backed by *testDatabase*, with ``updateChatInfo`` stubbed to a no-op.
    """
    CacheService._instance = None
    cache = CacheService.getInstance()
    await cache.injectDatabase(testDatabase)

    handler = MessagePreprocessorHandler(
        configManager=_makeConfigManager(),
        database=testDatabase,
        botProvider=BotProvider.TELEGRAM,
    )
    # saveChatMessage calls updateChatInfo first; the real implementation needs
    # self._bot (raising ValueError when it is None). Stub it to a no-op so the
    # subsequent cache.updateChatUser + db.chatMessages.saveChatMessage calls —
    # the hot-path writes under test — run for real.
    handler.updateChatInfo = AsyncMock(return_value=None)  # type: ignore[method-assign]
    return handler


async def _seedRow(testDatabase: Database) -> None:
    """Insert the canonical ``chat_users`` row directly via the repository.

    Bypasses the cache so the cache stays cold after seeding. The row carries
    the module-level ``_USERNAME`` / ``_FULL_NAME`` constants so a message whose
    sender matches them triggers the skip-when-unchanged optimisation.

    Args:
        testDatabase: Real in-memory database.
    """
    await testDatabase.chatUsers.updateChatUser(
        chatId=_CHAT_ID, userId=_USER_ID, username=_USERNAME, fullName=_FULL_NAME
    )


def _makeMessage(*, username: str = _USERNAME, fullName: str = _FULL_NAME) -> EnsuredMessage:
    """Build a real :class:`EnsuredMessage` that ``saveChatMessage`` can persist.

    The message is a ``MessageType.TEXT`` from a private chat so
    ``saveChatMessage`` does not early-return on ``UNKNOWN`` and does not need a
    reply parent. ``threadId`` is set to ``DEFAULT_THREAD_ID`` (0) to match the
    DB schema's expectation.

    Args:
        username: Sender username (default ``_USERNAME`` — matches the seed so
            ``cache.updateChatUser`` skips).
        fullName: Sender display name (default ``_FULL_NAME``).

    Returns:
        Fully constructed :class:`EnsuredMessage` ready for ``saveChatMessage``.
    """
    message = EnsuredMessage(
        sender=MessageSender(id=_USER_ID, name=fullName, username=username),
        recipient=MessageRecipient(id=_CHAT_ID, chatType=ChatType.PRIVATE),
        messageId=42,
        date=datetime.datetime(2026, 7, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText="hello world",
        messageType=MessageType.TEXT,
    )
    message.threadId = DEFAULT_THREAD_ID
    return message


# ---------------------------------------------------------------------------
# Warm cache: one inbound message → zero chat_users DB reads
# ---------------------------------------------------------------------------


class TestWarmCacheZeroDbReads:
    """Headline proof: a warm cache eliminates ``chat_users`` DB traffic."""

    async def test_warmCache_unchangedSender_zeroChatUsersDbReadsAndWrites(self, testDatabase: Database) -> None:
        """One inbound message through a warm cache touches ``chat_users`` zero times.

        Pre-seeds the ``(chat, user)`` row, warms the cache, then spies on both
        ``ChatUsersRepository.updateChatUser`` and ``getChatUser`` at the class
        level (``AsyncMock(wraps=original)`` so the real DB still works). Drives
        ``handler.saveChatMessage`` (which calls ``cache.updateChatUser`` with
        the sender's matching username/fullName → skip-when-unchanged) followed
        by ``handler.cache.getUserMetadata`` (which routes through
        ``cache.getChatUser`` → warm hit). Both spies must record **zero** calls
        — the headline regression claim.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        await _seedRow(testDatabase)
        # Warm the cache so userInfo holds the seeded row.
        await handler.cache.getChatUser(chatId=_CHAT_ID, userId=_USER_ID)

        originalUpdate = testDatabase.chatUsers.updateChatUser
        originalGet = testDatabase.chatUsers.getChatUser
        with (
            patch.object(ChatUsersRepository, "updateChatUser", new=AsyncMock(wraps=originalUpdate)) as updateSpy,
            patch.object(ChatUsersRepository, "getChatUser", new=AsyncMock(wraps=originalGet)) as getSpy,
        ):
            message = _makeMessage()  # sender matches the seeded row
            saved = await handler.saveChatMessage(message, messageCategory=MessageCategory.USER)
            assert saved is True

            # getUserMetadata routes through cache.getChatUser. The per-message
            # userSummary extraction that used to ride alongside this call was
            # removed in user-memories Phase 4b (structured <user-memories>
            # system-prompt block is the replacement).
            _ = await handler.cache.getUserMetadata(chatId=_CHAT_ID, userId=_USER_ID)

        # Skip-when-unchanged: no DB write.
        assert updateSpy.call_count == 0
        # Warm hit: no DB read.
        assert getSpy.call_count == 0


# ---------------------------------------------------------------------------
# Counterpoint: changed username → DB write fires
# ---------------------------------------------------------------------------


class TestChangedUsernameTriggersDbWrite:
    """Proves the cache does not swallow genuine writes."""

    async def test_warmCache_changedUsername_triggersChatUsersDbWrite(self, testDatabase: Database) -> None:
        """A changed sender username forces ``updateChatUser`` to hit the DB.

        Same setup as the warm test but the message's sender carries a
        different username (``"alice2"`` vs the seeded ``"alice"``). The
        skip-when-unchanged guard must NOT fire, so
        ``ChatUsersRepository.updateChatUser`` is called at least once.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        await _seedRow(testDatabase)
        await handler.cache.getChatUser(chatId=_CHAT_ID, userId=_USER_ID)  # warm

        originalUpdate = testDatabase.chatUsers.updateChatUser
        with patch.object(ChatUsersRepository, "updateChatUser", new=AsyncMock(wraps=originalUpdate)) as updateSpy:
            message = _makeMessage(username="alice2", fullName="Alice")
            saved = await handler.saveChatMessage(message, messageCategory=MessageCategory.USER)
            assert saved is True

        # Warm row means no re-read on update: exactly one cache.updateChatUser
        # → one db.chatUsers.updateChatUser. A future double-call regression
        # (e.g. a re-read-then-write loop) must fail here.
        assert updateSpy.call_count == 1


# ---------------------------------------------------------------------------
# Counterpoint: cold cache → DB read fires
# ---------------------------------------------------------------------------


class TestColdCacheTriggersDbRead:
    """Proves a cache miss falls through to the DB rather than returning stale data."""

    async def test_coldCache_getUserMetadata_triggersChatUsersDbRead(self, testDatabase: Database) -> None:
        """A cold cache read for ``cache.getUserMetadata`` hits the DB.

        Seeds the row directly via the repo (cache stays cold), then calls
        ``cache.getUserMetadata`` — which routes through ``cache.getChatUser``.
        On a cold cache the miss must fall through to
        ``ChatUsersRepository.getChatUser``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        await _seedRow(testDatabase)
        # Deliberately do NOT warm the cache.

        originalGet = testDatabase.chatUsers.getChatUser
        with patch.object(ChatUsersRepository, "getChatUser", new=AsyncMock(wraps=originalGet)) as getSpy:
            await handler.cache.getUserMetadata(chatId=_CHAT_ID, userId=_USER_ID)

        # Single getUserMetadata call → single cache miss → single
        # db.chatUsers.getChatUser read. A double-read regression must fail here.
        assert getSpy.call_count == 1
