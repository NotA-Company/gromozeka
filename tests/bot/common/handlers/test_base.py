"""Tests for the ``cache.chatUserMetadataLock()`` contract of :meth:`BaseBotHandler.setUserMetadata`.

Covers behaviour area (F): the ``isUpdate=True`` read-merge-write path must acquire
``cache.chatUserMetadataLock()`` exactly once around its read-merge-write, while the
full-replace path must not. Removing that wrapper reintroduces a lost-update race, and
these tests fail if the wrapper is dropped.

:meth:`BaseBotHandler.setUserMetadata` lives on :class:`BaseBotHandler`, which is
abstract / mixin-bound and not instantiated directly. It is exercised here through its
concrete subclass :class:`UserDataHandler`, constructed against a real in-memory database
(``testDatabase`` fixture) with the ``CacheService`` singleton reset per test by the local
autouse fixture. For the ``isUpdate=True`` path the handler reads via
``cache.getUserMetadata``; the autouse singleton reset plus
``cache.injectDatabase(testDatabase)`` in ``_makeHandler`` bind the handler's ``self.cache``
to a fresh :class:`CacheService`, and the cache is then swapped for a mock per-test so the
lock acquisition can be spied on.
"""

import types
from typing import Generator, Optional, cast
from unittest.mock import AsyncMock, Mock

import pytest

from internal.bot.common.handlers.user_data import UserDataHandler
from internal.bot.models import BotProvider, UserMetadataDict
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
    inherited ``setUserMetadata`` helper, so the cached values are unused.

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
        host for the inherited ``setUserMetadata`` helper.
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


class _CountingMetadataLock:
    """Async CM stand-in that counts acquisitions for lock-usage assertions.

    Stands in for the context manager returned by
    :meth:`CacheService.chatUserMetadataLock` so a test can assert that a given
    code path acquired the lock. Every ``__aenter__`` increments
    :attr:`enterCount`; ``__aexit__`` is a no-op that does not suppress
    exceptions. Used to pin down that ``setUserMetadata(isUpdate=True)``
    serializes its read-merge-write inside the lock.
    """

    def __init__(self) -> None:
        self.enterCount: int = 0
        """Number of times the context was entered (incremented on ``__aenter__``)."""

    async def __aenter__(self) -> None:
        """Enter the context: increment :attr:`enterCount`.

        Returns:
            None.
        """
        self.enterCount += 1

    async def __aexit__(
        self,
        excType: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[types.TracebackType],
    ) -> bool:
        """Exit the context.

        Does not suppress exceptions (always returns ``False``).

        Args:
            excType: Exception type raised inside the ``async with`` body, or
                ``None`` when no exception occurred.
            exc: Exception instance, or ``None``.
            tb: Traceback object, or ``None``.

        Returns:
            ``False`` so any raised exception propagates unchanged.
        """
        return False


# ---------------------------------------------------------------------------
# (F) setUserMetadata lock contract
# ---------------------------------------------------------------------------


class TestSetUserMetadataLockContract:
    """Tests pinning the ``cache.chatUserMetadataLock()`` acquisition in ``setUserMetadata``.

    ``BaseBotHandler.setUserMetadata(isUpdate=True)`` performs a read-merge-write
    that must be serialized against concurrent metadata writers; the
    serialization is provided by ``cache.chatUserMetadataLock()``. Removing that
    wrapper reintroduces a lost-update race, and these tests fail if the wrapper
    is dropped, pinning the contract down.
    """

    async def test_setUserMetadata_isUpdate_acquiresMetadataLock(self, testDatabase: Database) -> None:
        """``isUpdate=True`` acquires ``chatUserMetadataLock`` exactly once.

        Builds a handler, swaps its cache for a mock whose
        ``chatUserMetadataLock`` returns a :class:`_CountingMetadataLock`, then
        calls ``setUserMetadata(..., isUpdate=True)``. The lock must be entered
        exactly once, and the recorded ``updateUserMetadata`` payload must be
        the shallow merge of the existing dict with the new one (proving the
        read-merge-write happened inside the lock).

        Args:
            testDatabase: Fresh in-memory database fixture (used to build the
                handler; the cache is swapped for a mock afterwards).
        """
        handler = await _makeHandler(testDatabase)

        countingLock = _CountingMetadataLock()
        mockCache = Mock()
        mockCache.chatUserMetadataLock = Mock(return_value=countingLock)
        mockCache.getUserMetadata = AsyncMock(return_value=cast(UserMetadataDict, {"existingKey": "existingVal"}))
        mockCache.updateUserMetadata = AsyncMock(return_value=None)
        handler.cache = mockCache  # type: ignore[assignment]

        await handler.setUserMetadata(
            chatId=100,
            userId=7,
            metadata=cast(UserMetadataDict, {"newKey": "newVal"}),
            isUpdate=True,
        )

        assert countingLock.enterCount == 1
        mockCache.updateUserMetadata.assert_awaited_once_with(
            chatId=100,
            userId=7,
            metadata={"existingKey": "existingVal", "newKey": "newVal"},
        )

    async def test_setUserMetadata_fullReplace_alsoAcquiresMetadataLock(self, testDatabase: Database) -> None:
        """``isUpdate=False`` also acquires ``chatUserMetadataLock`` exactly once.

        The full-replace path writes ``metadata`` verbatim with no prior read,
        but it still runs inside ``chatUserMetadataLock()`` so it cannot be
        clobbered by a concurrent read-merge-write from another handler. Pins
        the contract that BOTH ``isUpdate`` paths are serialized.

        Args:
            testDatabase: Fresh in-memory database fixture (used to build the
                handler; the cache is swapped for a mock afterwards).
        """
        handler = await _makeHandler(testDatabase)

        countingLock = _CountingMetadataLock()
        mockCache = Mock()
        mockCache.chatUserMetadataLock = Mock(return_value=countingLock)
        mockCache.getUserMetadata = AsyncMock(return_value=cast(UserMetadataDict, {}))
        mockCache.updateUserMetadata = AsyncMock(return_value=None)
        handler.cache = mockCache  # type: ignore[assignment]

        await handler.setUserMetadata(
            chatId=100,
            userId=7,
            metadata=cast(UserMetadataDict, {"newKey": "newVal"}),
            isUpdate=False,
        )

        assert countingLock.enterCount == 1
        mockCache.getUserMetadata.assert_not_called()
        mockCache.updateUserMetadata.assert_awaited_once_with(chatId=100, userId=7, metadata={"newKey": "newVal"})
