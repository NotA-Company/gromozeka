"""Tests for HandlersManager shutdown and cleanup methods.

Covers:
    - _dumpAllState skips empty chat queues and logs non-empty ones
    - _dumpAllState snapshots chatStates.values() under stateLock
    - _dumpAllState logs each rate limiter stats entry as JSON
    - shutdown() calls _dumpAllState() before draining queues
    - _cleanupOldData orchestrates cache, delayed-task, and bayes token cleanup

HandlersManager.__init__ instantiates the entire handler pipeline, so these
tests build a minimal manager via ``HandlersManager.__new__`` and set only the
attributes the methods under test touch. This isolates the dump logic from
handler-construction concerns.
"""

import asyncio
from typing import Tuple
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.manager import (
    AGGRESSIVE_CLEANUP_CACHE_TYPES,
    BAYES_TOKEN_CLEANUP_RULES,
    CACHE_CLEANUP_AGGRESSIVE_TTL_SECS,
    CACHE_CLEANUP_DEFAULT_TTL_SECS,
    DELAYED_TASKS_CLEANUP_TTL_SECS,
    ChatProcessingState,
    HandlersManager,
)


def _mockRateLimiterManager(statsList: list) -> Mock:
    """Build a mock RateLimiterManager instance whose dumpAllStats returns statsList.

    Args:
        statsList: The list of stats entries dumpAllStats should return.

    Returns:
        A Mock configured as a RateLimiterManager with dumpAllStats returning statsList.
    """
    mockInstance = Mock()
    mockInstance.dumpAllStats = Mock(return_value=statsList)
    return mockInstance


@pytest.fixture
def minimalManager() -> HandlersManager:
    """Build a HandlersManager without running the heavy __init__.

    Sets up just the attributes referenced by shutdown and _dumpAllState:
    chat-state map, stateLock, shutdown event, and the handler-tasks set.

    Returns:
        A minimally-initialized HandlersManager suitable for dump tests.
    """
    mgr = HandlersManager.__new__(HandlersManager)
    mgr.chatStates = {}
    mgr.stateLock = asyncio.Lock()
    mgr._shutdownEvent = asyncio.Event()
    mgr.handlerTasks = set()
    return mgr


class TestDumpAllStateChatQueues:
    """Tests for the chat-state queue-size logging inside _dumpAllState."""

    async def testSkipsEmptyQueues(self, minimalManager: HandlersManager) -> None:
        """Chat states with empty queues produce no logger.info calls.

        Args:
            minimalManager: Minimal HandlersManager fixture.
        """
        state1 = ChatProcessingState(chatId=100, threadId=0)
        state2 = ChatProcessingState(chatId=200, threadId=0)
        minimalManager.chatStates = {"100:0": state1, "200:0": state2}

        with (
            patch(
                "internal.bot.common.handlers.manager.RateLimiterManager.getInstance",
                return_value=_mockRateLimiterManager([]),
            ),
            patch("internal.bot.common.handlers.manager.logger") as mockLogger,
        ):
            await minimalManager._dumpAllState()

        mockLogger.info.assert_not_called()

    async def testLogsNonEmptyQueues(self, minimalManager: HandlersManager) -> None:
        """Non-empty queues are logged with chatId, threadId, and queue size.

        Args:
            minimalManager: Minimal HandlersManager fixture.
        """
        state = ChatProcessingState(chatId=123, threadId=0)
        state.queue.append(Mock())  # make the queue non-empty
        minimalManager.chatStates = {"123:0": state}

        with (
            patch(
                "internal.bot.common.handlers.manager.RateLimiterManager.getInstance",
                return_value=_mockRateLimiterManager([]),
            ),
            patch("internal.bot.common.handlers.manager.logger") as mockLogger,
        ):
            await minimalManager._dumpAllState()

        mockLogger.info.assert_called_once()
        callArgs = mockLogger.info.call_args.args
        assert callArgs[1] == 123  # chatId
        assert callArgs[2] == 0  # threadId
        assert callArgs[3] == 1  # queueSize

    async def testSnapshotsUnderStateLock(self, minimalManager: HandlersManager) -> None:
        """_dumpAllState acquires stateLock while snapshotting chat states.

        Replaces stateLock with an AsyncMock and verifies the async context
        manager is entered (i.e. the snapshot is guarded by the lock).

        Args:
            minimalManager: Minimal HandlersManager fixture.
        """
        mockLock = AsyncMock()
        minimalManager.stateLock = mockLock
        state = ChatProcessingState(chatId=456, threadId=0)
        minimalManager.chatStates = {"456:0": state}

        with patch(
            "internal.bot.common.handlers.manager.RateLimiterManager.getInstance",
            return_value=_mockRateLimiterManager([]),
        ):
            await minimalManager._dumpAllState()

        mockLock.__aenter__.assert_awaited()
        mockLock.__aexit__.assert_awaited()


class TestDumpAllState:
    """Tests for _dumpAllState, which combines chat-state and rate-limiter dumps."""

    async def testLogsChatQueuesAndRateLimiters(self, minimalManager: HandlersManager) -> None:
        """_dumpAllState logs both non-empty chat queues and rate limiter stats.

        Sets up a non-empty chat state, mocks dumpAllStats to return [], and
        verifies that the chat-state dump produces a logger.info call (the
        non-empty queue) and that dumpAllStats was invoked exactly once.

        Args:
            minimalManager: Minimal HandlersManager fixture.
        """
        state = ChatProcessingState(chatId=123, threadId=0)
        state.queue.append(Mock())
        minimalManager.chatStates = {"123:0": state}

        mockManagerInstance = _mockRateLimiterManager([])

        with (
            patch(
                "internal.bot.common.handlers.manager.RateLimiterManager.getInstance",
                return_value=mockManagerInstance,
            ),
            patch("internal.bot.common.handlers.manager.logger") as mockLogger,
        ):
            await minimalManager._dumpAllState()

        # Chat-state dump produced a log (non-empty queue)
        mockLogger.info.assert_called()
        # dumpAllStats was invoked
        mockManagerInstance.dumpAllStats.assert_called_once()

    async def testLogsRateLimiterResultsAsJson(self, minimalManager: HandlersManager) -> None:
        """_dumpAllState logs each rate limiter stats entry as JSON via logger.info.

        Mocks dumpAllStats to return two entries and verifies logger.info is
        called exactly twice (chat states are empty so no chat-state logs),
        with each call's single argument being a JSON string containing the
        expected limiter and queue values.

        Args:
            minimalManager: Minimal HandlersManager fixture.
        """
        entries = [
            {
                "limiter": "api",
                "queue": "yandex",
                "requestsInWindow": 5,
                "maxRequests": 10,
                "windowSeconds": 60,
                "utilizationPercent": 50.0,
            },
            {
                "limiter": "db",
                "queue": "pg",
                "requestsInWindow": 1,
                "maxRequests": 20,
                "windowSeconds": 30,
                "utilizationPercent": 5.0,
            },
        ]

        mockManagerInstance = _mockRateLimiterManager(entries)

        with (
            patch(
                "internal.bot.common.handlers.manager.RateLimiterManager.getInstance",
                return_value=mockManagerInstance,
            ),
            patch("internal.bot.common.handlers.manager.logger") as mockLogger,
        ):
            await minimalManager._dumpAllState()

        infoCalls = mockLogger.info.call_args_list
        assert len(infoCalls) == 2

        # Each call's single arg is a JSON string containing the entry fields
        loggedStrings = [call.args[0] for call in infoCalls]
        assert any('"limiter": "api"' in s for s in loggedStrings)
        assert any('"queue": "yandex"' in s for s in loggedStrings)
        assert any('"limiter": "db"' in s for s in loggedStrings)
        assert any('"queue": "pg"' in s for s in loggedStrings)

    async def testShutdownCallsDumpAllState(self, minimalManager: HandlersManager) -> None:
        """shutdown() calls _dumpAllState() before draining queues.

        Replaces _dumpAllState with an AsyncMock and verifies it is awaited
        exactly once during shutdown.

        Args:
            minimalManager: Minimal HandlersManager fixture.
        """
        minimalManager._dumpAllState = AsyncMock()

        await minimalManager.shutdown()

        minimalManager._dumpAllState.assert_awaited_once()


class TestCleanupOldData:
    """Tests for HandlersManager._cleanupOldData call orchestration.

    _cleanupOldData wires together cache sweeps, delayed-task cleanup, and bayes
    token cleanup. These tests verify the correct methods are called with the
    correct TTL constants and cache types, without touching a real database.
    """

    @staticmethod
    def _buildManager() -> Tuple[HandlersManager, Mock]:
        """Build a minimal HandlersManager with a mocked db for _cleanupOldData.

        Returns:
            A ``(manager, mockDb)`` tuple. ``manager.db`` is set to ``mockDb``
            whose ``cache.clearOldCacheEntries`` and
            ``delayedTasks.cleanupOldCompletedDelayedTasks`` are AsyncMocks.
            The mockDb is returned separately so callers get Mock-typed access
            for assertions (HandlersManager.db is declared as Database, which
            would shadow the mock type from pyright's perspective).
        """
        mgr = HandlersManager.__new__(HandlersManager)
        mockDb = Mock()
        mockDb.cache.clearOldCacheEntries = AsyncMock(return_value=True)
        mockDb.delayedTasks.cleanupOldCompletedDelayedTasks = AsyncMock(return_value=True)
        mgr.db = mockDb
        return mgr, mockDb

    async def testDefaultTtlAllNamespaceSweep(self) -> None:
        """_cleanupOldData calls clearOldCacheEntries once with the 365-day default TTL."""
        manager, mockDb = self._buildManager()

        with patch("internal.bot.common.handlers.manager.DatabaseBayesStorage", return_value=AsyncMock()):
            await manager._cleanupOldData()

        mockDb.cache.clearOldCacheEntries.assert_any_call(ttl=CACHE_CLEANUP_DEFAULT_TTL_SECS)

    async def testAggressivePerNamespaceSweeps(self) -> None:
        """_cleanupOldData calls clearOldCacheEntries for each aggressive cache type.

        Asserts one aggressive-TTL call per entry in AGGRESSIVE_CLEANUP_CACHE_TYPES,
        plus the single default-TTL call, totalling 1 + len(types) calls.
        """
        manager, mockDb = self._buildManager()

        with patch("internal.bot.common.handlers.manager.DatabaseBayesStorage", return_value=AsyncMock()):
            await manager._cleanupOldData()

        # One aggressive call per aggressive type
        for cacheType in AGGRESSIVE_CLEANUP_CACHE_TYPES:
            mockDb.cache.clearOldCacheEntries.assert_any_call(
                ttl=CACHE_CLEANUP_AGGRESSIVE_TTL_SECS, cacheType=cacheType
            )
        # Total = 1 default + len(aggressive types)
        expectedCallCount = 1 + len(AGGRESSIVE_CLEANUP_CACHE_TYPES)
        assert mockDb.cache.clearOldCacheEntries.await_count == expectedCallCount

    async def testDelayedTasksCleanup(self) -> None:
        """_cleanupOldData calls delayedTasks.cleanupOldCompletedDelayedTasks with 30-day TTL."""
        manager, mockDb = self._buildManager()

        with patch("internal.bot.common.handlers.manager.DatabaseBayesStorage", return_value=AsyncMock()):
            await manager._cleanupOldData()

        mockDb.delayedTasks.cleanupOldCompletedDelayedTasks.assert_called_once_with(ttl=DELAYED_TASKS_CLEANUP_TTL_SECS)

    async def testBayesTokenCleanup(self) -> None:
        """_cleanupOldData constructs DatabaseBayesStorage and calls cleanupOldTokens with rules."""
        manager, mockDb = self._buildManager()

        with patch("internal.bot.common.handlers.manager.DatabaseBayesStorage") as mockBayesClass:
            mockBayesInstance = AsyncMock()
            mockBayesClass.return_value = mockBayesInstance

            await manager._cleanupOldData()

            mockBayesClass.assert_called_once_with(mockDb)
            mockBayesInstance.cleanupOldTokens.assert_called_once_with(BAYES_TOKEN_CLEANUP_RULES)
