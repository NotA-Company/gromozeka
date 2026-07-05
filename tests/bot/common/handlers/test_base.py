"""Tests for :meth:`BaseBotHandler.getUserMemorySummary` (memory-refinement phase 7a).

Covers behaviour area (E):

* No ``chat_users`` row → ``None``.
* Row exists but ``metadata`` is empty → ``None``.
* Row carries a ``memoryRefinement["<threadId>"].summary`` → returns that
  summary text.
* Row carries a summary for thread ``0`` but thread ``5`` is queried → ``None``.

``getUserMemorySummary`` lives on :class:`BaseBotHandler`, which is abstract /
mixin-bound and not instantiated directly. It is exercised here through its
concrete subclass :class:`UserDataHandler`, constructed against a real in-memory
database (``testDatabase`` fixture) with the ``CacheService`` singleton reset
per test by the local autouse fixture. Since Phase 2 of the write-through
chat_users cache, the method reads via ``cache.getUserMetadata`` (which itself
reads through ``cache.getChatUser`` → the chat_users row). The autouse singleton
reset above plus ``cache.injectDatabase(testDatabase)`` in ``_makeHandler`` bind
the handler's ``self.cache`` to a fresh :class:`CacheService` wired to the test
DB, so the cache miss falls through to SQLite and the assertions stay real.
"""

import json
from typing import Generator
from unittest.mock import Mock

import pytest

from internal.bot.common.handlers.user_data import UserDataHandler
from internal.bot.models import BotProvider
from internal.database import Database
from internal.services.cache import CacheService

# ---------------------------------------------------------------------------
# Singleton hygiene
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _resetCacheServiceSingleton() -> Generator[None, None, None]:
    """Reset the ``CacheService`` singleton around every test in this module.

    Keeps the closed in-memory database from one test from leaking into the
    next via the ``CacheService`` singleton (which is not reset by
    ``tests/conftest.py``).

    Yields:
        None.
    """
    CacheService._instance = None
    yield
    CacheService._instance = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeConfigManager() -> Mock:
    """Build a minimal ``ConfigManager`` stub for the handler constructor.

    ``UserDataHandler.__init__`` reads ``get("user-memory", {})`` to cache the
    refinement config; returning ``{}`` leaves the feature disabled and makes
    thresholds fall back to module constants. These tests only exercise the
    inherited ``getUserMemorySummary`` helper, so the cached values are unused.

    Returns:
        ``Mock`` exposing ``getBotConfig()`` returning a token/owners dict and
        ``get(key, default)`` returning ``{}`` for any key.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test_token", "owners": [123456]})
    cm.get = Mock(return_value={})
    return cm


async def _makeHandler(testDatabase: Database) -> UserDataHandler:
    """Construct a :class:`UserDataHandler` wired to a real in-memory database.

    Args:
        testDatabase: Fresh in-memory :class:`Database`` (``testDatabase``
            fixture).

    Returns:
        A :class:`UserDataHandler` whose ``db`` is *testDatabase*, used as the
        host for the inherited ``getUserMemorySummary`` helper.
    """
    CacheService._instance = None
    cache = CacheService.getInstance()
    await cache.injectDatabase(testDatabase)

    handler = UserDataHandler(
        configManager=_makeConfigManager(),
        database=testDatabase,
        botProvider=BotProvider.TELEGRAM,
    )
    return handler


# ---------------------------------------------------------------------------
# (E) getUserMemorySummary
# ---------------------------------------------------------------------------


class TestGetUserMemorySummary:
    """Tests for :meth:`BaseBotHandler.getUserMemorySummary`."""

    async def test_returnsNoneWhenNoChatUserRow(self, testDatabase: Database) -> None:
        """A missing ``chat_users`` row → ``None``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)

        result = await handler.getUserMemorySummary(chatId=100, userId=7, threadId=0)

        assert result is None

    async def test_returnsNoneWhenMetadataEmpty(self, testDatabase: Database) -> None:
        """An existing row with empty metadata → ``None``.

        ``parseUserMetadata`` treats a falsy ``metadata`` string as ``{}``, so
        there is no ``memoryRefinement`` section to read.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        await _ensureChatUser(testDatabase, chatId=100, userId=7)
        await testDatabase.chatUsers.updateUserMetadata(chatId=100, userId=7, metadata="")

        result = await handler.getUserMemorySummary(chatId=100, userId=7, threadId=0)

        assert result is None

    async def test_returnsSummaryWhenPresent(self, testDatabase: Database) -> None:
        """A stored ``memoryRefinement["0"].summary`` is returned verbatim.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        await _ensureChatUser(testDatabase, chatId=100, userId=7)
        metadata = {
            "memoryRefinement": {
                "0": {
                    "summary": "bio text",
                    "lastProcessedMessageId": "1",
                    "lastProcessedMessageDate": "2026-05-05T12:00:00+00:00",
                }
            }
        }
        await testDatabase.chatUsers.updateUserMetadata(chatId=100, userId=7, metadata=json.dumps(metadata))

        result = await handler.getUserMemorySummary(chatId=100, userId=7, threadId=0)

        assert result == "bio text"

    async def test_returnsNoneWhenThreadAbsent(self, testDatabase: Database) -> None:
        """Querying a thread id with no entry → ``None`` (sibling threads untouched).

        Thread ``0`` has a summary but thread ``5`` is queried; the method must
        return ``None`` rather than falling back to another thread's summary.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        await _ensureChatUser(testDatabase, chatId=100, userId=7)
        metadata = {
            "memoryRefinement": {
                "0": {
                    "summary": "bio text",
                    "lastProcessedMessageId": "1",
                    "lastProcessedMessageDate": "2026-05-05T12:00:00+00:00",
                }
            }
        }
        await testDatabase.chatUsers.updateUserMetadata(chatId=100, userId=7, metadata=json.dumps(metadata))

        result = await handler.getUserMemorySummary(chatId=100, userId=7, threadId=5)

        assert result is None


async def _ensureChatUser(testDatabase: Database, *, chatId: int, userId: int) -> None:
    """Create (or refresh) a ``chat_users`` row so ``updateUserMetadata`` targets it.

    ``updateUserMetadata`` issues a plain ``UPDATE`` (not an upsert), so the row
    must exist beforehand. ``updateChatUser`` performs the upsert that creates
    it.

    Args:
        testDatabase: Database to write to.
        chatId: Chat id of the row to ensure.
        userId: User id of the row to ensure.
    """
    await testDatabase.chatUsers.updateChatUser(
        chatId=chatId,
        userId=userId,
        username=f"@user{userId}",
        fullName="Alice",
    )
