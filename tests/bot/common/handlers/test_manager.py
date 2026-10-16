"""Tests for HandlersManager shutdown and cleanup methods.

Covers:
    - _dumpAllState skips empty chat queues and logs non-empty ones
    - _dumpAllState snapshots chatStates.values() under stateLock
    - _dumpAllState logs each rate limiter stats entry as JSON
    - shutdown() calls _dumpAllState() before draining queues
    - _cleanupOldData orchestrates cache, delayed-task, and bayes token cleanup
    - _visionGcCronJob TTL garbage collection (disabled/gate/sweep semantics)

HandlersManager.__init__ instantiates the entire handler pipeline, so these
tests build a minimal manager via ``HandlersManager.__new__`` and set only the
attributes the methods under test touch. This isolates the dump logic from
handler-construction concerns.
"""

import asyncio
import datetime
import hashlib
import logging
import time
from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Dict, List, Optional, Set, Tuple
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from PIL import Image

from internal.bot.common.handlers.base import BaseBotHandler, visionStorageLock
from internal.bot.common.handlers.manager import (
    AGGRESSIVE_CLEANUP_CACHE_TYPES,
    BAYES_TOKEN_CLEANUP_RULES,
    CACHE_CLEANUP_AGGRESSIVE_TTL_SECS,
    CACHE_CLEANUP_DEFAULT_TTL_SECS,
    DELAYED_TASKS_CLEANUP_TTL_SECS,
    CacheType,
    ChatProcessingState,
    HandlersManager,
)
from internal.database import Database
from internal.database.models import MediaAttachmentDict
from internal.database.repositories.media_attachments import MediaAttachmentsRepository
from internal.models import MessageType
from internal.services.queue_service import DelayedTask, DelayedTaskFunction
from internal.services.storage import StorageScope, StorageService
from lib.ai.imaging import AlphaBackground, VisionOutputImageFormat, normalizeVisionImageStrict


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


class _ObservedVisionLock:
    """Transparent shared-lock wrapper recording task-specific acquire/release events.

    Delegates every acquire/release to the REAL module-level
    ``visionStorageLock`` instance, so production mutual-exclusion semantics
    stay fully in force while the wrapper is patched in; each COMPLETED
    acquisition and each release is appended to a shared event log tagged
    with the acquiring task's ``name``. A contended acquisition is recorded
    only once it actually holds the lock, so the event log doubles as a
    serialization proof: a test can assert both that production code still
    enters its critical sections and the exact ordering of those sections
    against concurrent lock holders.
    """

    def __init__(self, realLock: asyncio.Lock, events: List[str]) -> None:
        """Wrap the real lock and share the event log.

        Args:
            realLock: The real ``visionStorageLock`` every operation delegates to.
            events: Shared list the acquire/release events are appended to.
        """
        self._realLock = realLock
        self._events = events

    async def __aenter__(self) -> "_ObservedVisionLock":
        """Acquire the real lock, then record the acquisition for the current task.

        Returns:
            This wrapper, as the ``async with`` context value.
        """
        await self._realLock.acquire()
        self._events.append(f"acquire:{self._currentTaskName()}")
        return self

    async def __aexit__(
        self,
        excType: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        """Release the real lock, then record the release for the current task.

        Args:
            excType: Exception class propagating out of the block, if any.
            exc: Exception instance propagating out of the block, if any.
            tb: Traceback propagating out of the block, if any.

        Returns:
            None
        """
        self._realLock.release()
        self._events.append(f"release:{self._currentTaskName()}")
        return None

    def _currentTaskName(self) -> str:
        """Return the running task's name used to tag lock events.

        Returns:
            The current task's name, or a placeholder when no task is active.
        """
        task = asyncio.current_task()
        return task.get_name() if task is not None else "no-task"


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
            whose ``delayedTasks.cleanupOldCompletedDelayedTasks`` is an AsyncMock.
            The mockDb is returned separately so callers get Mock-typed access
            for assertions (HandlersManager.db is declared as Database, which
            would shadow the mock type from pyright's perspective).
        """
        mgr = HandlersManager.__new__(HandlersManager)
        mockDb = Mock()
        mockDb.delayedTasks.cleanupOldCompletedDelayedTasks = AsyncMock(return_value=True)
        mgr.db = mockDb
        return mgr, mockDb

    async def testDefaultTtlAllNamespaceSweep(self) -> None:
        """_cleanupOldData calls clearOld for all CacheType members once with conditional TTL.

        Each CacheType namespace is swept once: aggressive types get the 7-day TTL,
        all others get the 365-day default floor. Total of len(CacheType) calls.
        """
        manager, mockDb = self._buildManager()

        with (
            patch("internal.bot.common.handlers.manager.GenericDatabaseCache") as MockCacheClass,
            patch("internal.bot.common.handlers.manager.DatabaseBayesStorage", return_value=AsyncMock()),
        ):
            mockCacheInstance = AsyncMock()
            MockCacheClass.return_value = mockCacheInstance

            await manager._cleanupOldData()

            # Verify GenericDatabaseCache was constructed len(CacheType) times (once per namespace)
            expectedConstructCalls = len(list(CacheType))
            assert MockCacheClass.call_count == expectedConstructCalls

            # Verify clearOld was called len(CacheType) times (once per namespace)
            expectedClearOldCalls = len(list(CacheType))
            assert mockCacheInstance.clearOld.call_count == expectedClearOldCalls

            # Verify each call has the correct TTL for its namespace
            callArgsList = mockCacheInstance.clearOld.call_args_list

            for i, cacheType in enumerate(CacheType):
                args, _ = callArgsList[i]
                expectedTtl = (
                    CACHE_CLEANUP_AGGRESSIVE_TTL_SECS
                    if cacheType in AGGRESSIVE_CLEANUP_CACHE_TYPES
                    else CACHE_CLEANUP_DEFAULT_TTL_SECS
                )
                assert args[0] == expectedTtl
                # Verify namespace identity (single sweep, all CacheType members)
                assert MockCacheClass.call_args_list[i].kwargs["namespace"] is cacheType

            # Verify manager identity (first iteration sufficient if pattern is uniform)
            assert MockCacheClass.call_args_list[0].args[0] is mockDb.manager

    async def testAggressivePerNamespaceSweeps(self) -> None:
        """_cleanupOldData applies aggressive TTL to aggressive namespaces in the single pass.

        Asserts:
        - Total calls = len(CacheType) (one sweep per namespace)
        - Aggressive types (4 namespaces) receive AGGRESSIVE_TTL (7 days)
        - Non-aggressive types (4 namespaces) receive DEFAULT_TTL (365 days)
        """
        manager, mockDb = self._buildManager()

        with (
            patch("internal.bot.common.handlers.manager.GenericDatabaseCache") as MockCacheClass,
            patch("internal.bot.common.handlers.manager.DatabaseBayesStorage", return_value=AsyncMock()),
        ):
            mockCacheInstance = AsyncMock()
            MockCacheClass.return_value = mockCacheInstance

            await manager._cleanupOldData()

            # Total calls = len(CacheType) (single sweep)
            expectedTotalCalls = len(list(CacheType))
            assert mockCacheInstance.clearOld.call_count == expectedTotalCalls

            # Verify aggressive types get aggressive TTL in the single sweep
            aggressiveCalls = []
            defaultCalls = []

            for i, cacheType in enumerate(CacheType):
                call = mockCacheInstance.clearOld.call_args_list[i]
                args, _ = call
                ttl = args[0]
                expectedTtl = (
                    CACHE_CLEANUP_AGGRESSIVE_TTL_SECS
                    if cacheType in AGGRESSIVE_CLEANUP_CACHE_TYPES
                    else CACHE_CLEANUP_DEFAULT_TTL_SECS
                )
                assert ttl == expectedTtl, f"CacheType {cacheType} got TTL {ttl}, expected {expectedTtl}"

                if ttl == CACHE_CLEANUP_AGGRESSIVE_TTL_SECS:
                    aggressiveCalls.append(call)
                elif ttl == CACHE_CLEANUP_DEFAULT_TTL_SECS:
                    defaultCalls.append(call)

            # Should have exactly len(AGGRESSIVE_CLEANUP_CACHE_TYPES) aggressive calls
            assert len(aggressiveCalls) == len(AGGRESSIVE_CLEANUP_CACHE_TYPES)

            # Should have len(CacheType) - len(AGGRESSIVE_CLEANUP_CACHE_TYPES) default calls
            assert len(defaultCalls) == len(list(CacheType)) - len(AGGRESSIVE_CLEANUP_CACHE_TYPES)

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


class TestVisionGc:
    """Tests for HandlersManager._visionGcCronJob (vision TTL garbage collection).

    Uses the ``HandlersManager.__new__`` bypass pattern from
    ``TestCleanupOldData``: only the attributes the GC touches are set — a real
    ``Database`` (``testDatabase`` fixture, so the repo methods run
    against real in-memory SQLite) plus the two init-cached GC attributes.
    ``StorageService.getInstance`` is class-patched (so no ``StorageService``
    singleton reset is needed) everywhere EXCEPT the real-fs-store regression
    test, which clears ``StorageService._instances`` itself. Rows are seeded
    through the real repo API and backdated with the canonical raw-SQL pattern
    from ``tests/database/repositories/test_media_attachments.py``. Repo spy
    patches are applied at CLASS level — the repositories use ``__slots__``,
    so instance attributes are read-only.
    """

    _OLD_TS = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    """Timestamp guaranteed older than any sane cutoff (TTL is 1 day in these tests)."""

    @staticmethod
    def _buildManager(testDatabase: Database, *, visionTtlDays: int, lastGcTime: float = 0.0) -> HandlersManager:
        """Build a minimal HandlersManager wired for the vision GC.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
            visionTtlDays: Value for the init-cached ``_visionTtlDays`` attribute.
            lastGcTime: Value for the init-cached ``_lastVisionGcTime`` attribute.

        Returns:
            A minimally-initialized HandlersManager suitable for GC tests.
        """
        mgr = HandlersManager.__new__(HandlersManager)
        mgr.db = testDatabase
        mgr._visionTtlDays = visionTtlDays
        mgr._lastVisionGcTime = lastGcTime
        return mgr

    @staticmethod
    def _makeTask() -> DelayedTask:
        """Build the DelayedTask the cron dispatcher would pass to the GC.

        Returns:
            A DelayedTask tagged as CRON_JOB (the GC ignores its payload).
        """
        return DelayedTask(taskId="test-vision-gc", delayedUntil=0.0, function=DelayedTaskFunction.CRON_JOB, kwargs={})

    @staticmethod
    def _makeStorageMock(deleteReturnValue: bool = True) -> Mock:
        """Build a StorageService stand-in with a controllable ``delete``.

        Args:
            deleteReturnValue: Value ``delete`` returns by default.

        Returns:
            A Mock whose ``delete`` is a Mock returning *deleteReturnValue*.
        """
        storageMock = Mock()
        storageMock.delete = Mock(return_value=deleteReturnValue)
        return storageMock

    @staticmethod
    async def _seedAttachmentWithVisionUrl(testDatabase: Database, mediaId: str, visionUrl: Optional[str]) -> None:
        """Seed one media row (with an optional vision_url) through the repo API.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
            mediaId: Media attachment unique identifier to seed.
            visionUrl: Vision storage key to set, or None to leave it NULL.

        Returns:
            None
        """
        repo = testDatabase.mediaAttachments
        assert await repo.addMediaAttachment(fileUniqueId=mediaId, fileId=f"fid-{mediaId}") is True
        if visionUrl is not None:
            assert await repo.updateMediaAttachment(mediaId, visionUrl=visionUrl) is True

    @staticmethod
    async def _backdateUpdatedAt(testDatabase: Database, mediaId: str, ts: datetime.datetime) -> None:
        """Backdate a row's ``updated_at`` via the canonical raw-SQL test pattern.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
            mediaId: Media attachment unique identifier to backdate.
            ts: Timestamp (aware UTC) to write.

        Returns:
            None
        """
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "UPDATE media_attachments SET updated_at = :ts WHERE file_unique_id = :id",
            {"ts": ts.isoformat(), "id": mediaId},
        )

    async def testDisabledTtl_skipsRepoQueries(self, testDatabase: Database) -> None:
        """ttl-days = 0 disables the GC before any work: the repo is never queried.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
        """
        manager = self._buildManager(testDatabase, visionTtlDays=0)

        with (
            patch.object(StorageService, "getInstance", return_value=Mock()),
            patch.object(
                MediaAttachmentsRepository,
                "getExpiredVisionAttachmentsWithRetention",
                new_callable=AsyncMock,
            ) as mockExpired,
        ):
            await manager._visionGcCronJob(self._makeTask())

        mockExpired.assert_not_called()

    async def testElapsedGateNotReached_skipsQueries(self, testDatabase: Database) -> None:
        """A GC pass within the interval is skipped: no queries, gate timestamp unchanged.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
        """
        lastRun = time.time()
        manager = self._buildManager(testDatabase, visionTtlDays=1, lastGcTime=lastRun)

        with (
            patch.object(StorageService, "getInstance", return_value=Mock()),
            patch.object(
                MediaAttachmentsRepository,
                "getExpiredVisionAttachmentsWithRetention",
                new_callable=AsyncMock,
            ) as mockExpired,
        ):
            await manager._visionGcCronJob(self._makeTask())

        mockExpired.assert_not_called()
        assert manager._lastVisionGcTime == lastRun

    async def testNothingExpired_noDeleteNoClear(self, testDatabase: Database) -> None:
        """No expired rows → early return: no file deletion, no vision_url clear.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
        """
        manager = self._buildManager(testDatabase, visionTtlDays=1)
        repo = testDatabase.mediaAttachments
        # Seeded fresh (updated_at = now) → still live, nothing expired.
        await self._seedAttachmentWithVisionUrl(testDatabase, "fresh-row", "fresh.jpeg")

        storageMock = self._makeStorageMock()
        realClear = repo.clearVisionUrl
        with (
            patch.object(StorageService, "getInstance", return_value=storageMock),
            patch.object(MediaAttachmentsRepository, "clearVisionUrl", side_effect=realClear) as mockClear,
        ):
            await manager._visionGcCronJob(self._makeTask())

        storageMock.delete.assert_not_called()
        mockClear.assert_not_awaited()

    async def testColdKey_deletesFileAndClearsRow(self, testDatabase: Database) -> None:
        """Expired row whose key nothing live references: file deleted, row cleared.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
        """
        manager = self._buildManager(testDatabase, visionTtlDays=1)
        repo = testDatabase.mediaAttachments
        await self._seedAttachmentWithVisionUrl(testDatabase, "cold-row", "cold.jpeg")
        await self._backdateUpdatedAt(testDatabase, "cold-row", self._OLD_TS)

        storageMock = self._makeStorageMock()
        realClear = repo.clearVisionUrl
        with (
            patch.object(StorageService, "getInstance", return_value=storageMock),
            patch.object(MediaAttachmentsRepository, "clearVisionUrl", side_effect=realClear) as mockClear,
        ):
            await manager._visionGcCronJob(self._makeTask())

        storageMock.delete.assert_called_once_with("cold.jpeg")
        mockClear.assert_awaited_once_with("cold-row")

        row = await repo.getMediaAttachment("cold-row")
        assert row is not None
        assert row["vision_url"] is None

    async def testHotKey_sharedUrl_fileKeptRowCleared(self, testDatabase: Database) -> None:
        """Expired row sharing its vision_url with a live row: file kept, row cleared.

        The dedup guard must prevent deleting a file a fresh row still
        references; only the expired row's reference is dropped.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
        """
        manager = self._buildManager(testDatabase, visionTtlDays=1)
        repo = testDatabase.mediaAttachments
        await self._seedAttachmentWithVisionUrl(testDatabase, "expired-row", "shared.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "fresh-row", "shared.jpeg")
        await self._backdateUpdatedAt(testDatabase, "expired-row", self._OLD_TS)

        storageMock = self._makeStorageMock()
        realClear = repo.clearVisionUrl
        with (
            patch.object(StorageService, "getInstance", return_value=storageMock),
            patch.object(MediaAttachmentsRepository, "clearVisionUrl", side_effect=realClear) as mockClear,
        ):
            await manager._visionGcCronJob(self._makeTask())

        storageMock.delete.assert_not_called()
        mockClear.assert_awaited_once_with("expired-row")

        expiredAfter = await repo.getMediaAttachment("expired-row")
        freshAfter = await repo.getMediaAttachment("fresh-row")
        assert expiredAfter is not None
        assert expiredAfter["vision_url"] is None
        assert freshAfter is not None
        assert freshAfter["vision_url"] == "shared.jpeg"

    async def testDeleteRaises_clearSkippedLoopContinues(
        self, testDatabase: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A raising delete skips that row's clear (retryable) and the loop continues.

        First row's delete raises a backend error: no clear for it (its row
        still matches next hour's expired query), a warning is logged, and the
        second row is fully processed.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
            caplog: pytest log-capture fixture.
        """
        manager = self._buildManager(testDatabase, visionTtlDays=1)
        repo = testDatabase.mediaAttachments
        await self._seedAttachmentWithVisionUrl(testDatabase, "boom-row", "boom.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "ok-row", "ok.jpeg")
        await self._backdateUpdatedAt(testDatabase, "boom-row", self._OLD_TS)
        await self._backdateUpdatedAt(testDatabase, "ok-row", self._OLD_TS)

        storageMock = self._makeStorageMock()
        storageMock.delete = Mock(side_effect=[Exception("backend io error"), True])
        realClear = repo.clearVisionUrl
        with (
            patch.object(StorageService, "getInstance", return_value=storageMock),
            patch.object(MediaAttachmentsRepository, "clearVisionUrl", side_effect=realClear) as mockClear,
            caplog.at_level(logging.WARNING),
        ):
            await manager._visionGcCronJob(self._makeTask())

        # Loop continued past the failure to the second row.
        assert storageMock.delete.call_args_list == [call("boom.jpeg"), call("ok.jpeg")]

        # boom-row: clear skipped, row untouched → retried next hour.
        boomRow = await repo.getMediaAttachment("boom-row")
        assert boomRow is not None
        assert boomRow["vision_url"] == "boom.jpeg"

        # ok-row: fully processed.
        mockClear.assert_awaited_once_with("ok-row")
        okRow = await repo.getMediaAttachment("ok-row")
        assert okRow is not None
        assert okRow["vision_url"] is None

        # Warning logged for the failed row.
        assert "boom-row" in caplog.text

    async def testGatePasses_updatesLastRunTime(self, testDatabase: Database) -> None:
        """A GC pass that gets past the elapsed gate advances _lastVisionGcTime.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
        """
        manager = self._buildManager(testDatabase, visionTtlDays=1, lastGcTime=0.0)
        assert manager._lastVisionGcTime == 0.0

        with patch.object(StorageService, "getInstance", return_value=Mock()):
            await manager._visionGcCronJob(self._makeTask())

        assert manager._lastVisionGcTime > 0.0

    async def testRetainedKeysLookupFailed_abortsSweep(
        self, testDatabase: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``getExpiredVisionAttachmentsWithRetention`` returning None (query FAILED) aborts the sweep.

        Regression for the fail-destructive sentinel: None must never be
        treated as "nothing is expired" (or as emptiness at all). With the
        combined snapshot query failing, NO file is deleted, NO row is
        cleared (rows keep their ``vision_url`` for the next tick's retry),
        and a single WARNING explains the abort.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
            caplog: pytest log-capture fixture.
        """
        manager = self._buildManager(testDatabase, visionTtlDays=1)
        repo = testDatabase.mediaAttachments
        await self._seedAttachmentWithVisionUrl(testDatabase, "expired-row", "cold.jpeg")
        await self._backdateUpdatedAt(testDatabase, "expired-row", self._OLD_TS)

        storageMock = self._makeStorageMock()
        realClear = repo.clearVisionUrl
        with (
            patch.object(StorageService, "getInstance", return_value=storageMock),
            patch.object(
                MediaAttachmentsRepository,
                "getExpiredVisionAttachmentsWithRetention",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(MediaAttachmentsRepository, "clearVisionUrl", side_effect=realClear) as mockClear,
            caplog.at_level(logging.WARNING),
        ):
            await manager._visionGcCronJob(self._makeTask())

        storageMock.delete.assert_not_called()
        mockClear.assert_not_awaited()

        row = await repo.getMediaAttachment("expired-row")
        assert row is not None
        assert row["vision_url"] == "cold.jpeg"

        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "aborting sweep" in warnings[0].getMessage()

    async def testMidSweepRefreshOfExpiredRow_keepsSharedObjectAndLiveRow(
        self, testDatabase: Database, tmp_path: Path
    ) -> None:
        """A mid-sweep refresh of an expired row cannot strip a shared key's protection.

        Regression pinning the residual post-snapshot window of the combined
        retention query: expired row A and live row B share key K. The spy
        wraps the real combined ``getExpiredVisionAttachmentsWithRetention``,
        then refreshes A via the real ``updateMediaAttachment`` (lock-blind
        receipt-path write) before the sweep uses it — safe because retention
        was decided atomically with expired-ness. K stays retained (row B was
        live at statement time): the object survives, B's reference is
        intact, and A is merely cleared (self-heals on next receipt).

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
            tmp_path: pytest tmp dir for the real fs vision store.
        """
        StorageService._instances.clear()
        try:
            configManager = Mock()
            configManager.getStorageConfig = Mock(
                return_value={
                    "type": "null",
                    "storages": {"vision": {"type": "fs", "fs": {"base-dir": str(tmp_path / "vision")}}},
                }
            )
            visionStorage = StorageService.getInstance(StorageScope.VISION)
            visionStorage.injectConfig(configManager, scope=StorageScope.VISION)

            manager = self._buildManager(testDatabase, visionTtlDays=1)
            repo = testDatabase.mediaAttachments
            await self._seedAttachmentWithVisionUrl(testDatabase, "row-A", "shared.jpeg")
            await self._seedAttachmentWithVisionUrl(testDatabase, "row-B", "shared.jpeg")
            await self._backdateUpdatedAt(testDatabase, "row-A", self._OLD_TS)

            # The shared object exists in the real fs vision store.
            visionStorage.store("shared.jpeg", b"normalized-bytes")
            assert visionStorage.exists("shared.jpeg")

            realLookup = repo.getExpiredVisionAttachmentsWithRetention
            realUpdate = repo.updateMediaAttachment

            async def refreshAfterSnapshot(
                cutoff: datetime.datetime,
            ) -> Optional[Tuple[List[MediaAttachmentDict], Set[str]]]:
                """Delegate the combined snapshot, then flip row A live.

                Args:
                    cutoff: Expiration boundary the GC passes through.

                Returns:
                    The real combined (expiredRows, retainedKeys) result.
                """
                result = await realLookup(cutoff)
                # The exact production interleaving: an ordinary (lock-blind)
                # receipt-path refresh lands AFTER the combined snapshot
                # returns and BEFORE the sweep uses it.
                await realUpdate("row-A")
                return result

            with patch.object(
                MediaAttachmentsRepository,
                "getExpiredVisionAttachmentsWithRetention",
                side_effect=refreshAfterSnapshot,
            ):
                await manager._visionGcCronJob(self._makeTask())

            # The shared object survived: row B's live reference was honored.
            assert visionStorage.exists("shared.jpeg")
            rowB = await repo.getMediaAttachment("row-B")
            assert rowB is not None
            assert rowB["vision_url"] == "shared.jpeg"

            # Row A was in the expired snapshot → cleared by the sweep
            # (acceptable outcome; self-heals on its next receipt).
            rowA = await repo.getMediaAttachment("row-A")
            assert rowA is not None
            assert rowA["vision_url"] is None
        finally:
            StorageService._instances.clear()

    async def testConcurrentPublishDuringSweep_objectRestoredByReceipt(self, testDatabase: Database) -> None:
        """A receipt publishing mid-sweep cannot end up with a dangling row.

        Regression for the snapshot TOCTOU race: rows A(key1) and B(key2)
        are expired and cold at snapshot time, but a concurrent receipt
        publishes key2 on fresh row C while the sweep is running. Under
        the shared ``visionStorageLock`` the receipt's critical section
        cannot run mid-sweep: it blocks on the lock the GC holds, so the
        GC deletes key2 BEFORE the receipt re-stores and publishes it —
        row C ends consistent (``vision_url`` set AND object present).
        Without the lock the publish lands mid-sweep and the GC then
        deletes key2 out from under row C, leaving it dangling.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
        """
        manager = self._buildManager(testDatabase, visionTtlDays=1)
        repo = testDatabase.mediaAttachments
        await self._seedAttachmentWithVisionUrl(testDatabase, "row-A", "key1.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "row-B", "key2.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "row-C", None)
        await self._backdateUpdatedAt(testDatabase, "row-A", self._OLD_TS)
        await self._backdateUpdatedAt(testDatabase, "row-B", self._OLD_TS)

        # Dict-backed storage mock so object presence is observable.
        files: Dict[str, bytes] = {}
        storageMock = Mock()
        storageMock.store = Mock(side_effect=lambda key, data: files.__setitem__(key, data))
        storageMock.delete = Mock(side_effect=lambda key: files.pop(key, None) is not None)

        realClear = repo.clearVisionUrl
        realUpdate = repo.updateMediaAttachment
        receiptTasks: List[asyncio.Task] = []
        spawned = {"done": False}

        async def concurrentReceipt() -> None:
            """Simulate the receipt-side store-and-publish critical section.

            Mirrors ``_storeVisionImage``'s second critical section (store
            BEFORE the ``vision_url`` write) under the shared lock.

            Returns:
                None
            """
            async with visionStorageLock:
                storageMock.store("key2.jpeg", b"re-normalized-bytes")
                assert await realUpdate("row-C", visionUrl="key2.jpeg") is True

        async def clearDuringSweep(mediaId: str) -> bool:
            """Spawn the concurrent receipt once, at the sweep's first clear.

            Args:
                mediaId: Media attachment unique identifier to clear.

            Returns:
                The real ``clearVisionUrl`` result.
            """
            if not spawned["done"]:
                spawned["done"] = True
                receiptTasks.append(asyncio.create_task(concurrentReceipt()))
                # Let the receipt task run up to its lock acquisition: with
                # the lock it blocks until the sweep finishes; without it the
                # publish lands mid-sweep.
                await asyncio.sleep(0)
            return await realClear(mediaId)

        with (
            patch.object(StorageService, "getInstance", return_value=storageMock),
            patch.object(MediaAttachmentsRepository, "clearVisionUrl", side_effect=clearDuringSweep),
        ):
            await manager._visionGcCronJob(self._makeTask())
        for receiptTask in receiptTasks:
            await receiptTask

        # Row C was published by the receipt AND its object is present:
        # the sweep deleted key2 first, the receipt's store re-created it.
        rowC = await repo.getMediaAttachment("row-C")
        assert rowC is not None
        assert rowC["vision_url"] == "key2.jpeg"
        assert files.get("key2.jpeg") == b"re-normalized-bytes"

        # The sweep itself completed normally: A and B cleared, key1 gone
        # (deleted and never re-stored).
        rowA = await repo.getMediaAttachment("row-A")
        rowB = await repo.getMediaAttachment("row-B")
        assert rowA is not None
        assert rowA["vision_url"] is None
        assert rowB is not None
        assert rowB["vision_url"] is None
        assert "key1.jpeg" not in files

    async def testProductionReceiptPath_objectRestoredByRealReceipt(
        self, testDatabase: Database, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The REAL ``_storeVisionImage`` receipt restores a key the sweep deleted.

        Companion to ``testConcurrentPublishDuringSweep_objectRestoredByReceipt``
        (which hand-rolls the receipt's critical section to prove the GC-side
        lock protocol in isolation); this test runs the REAL production receipt
        path against a live sweep. Rows A(key1) and B(K) are expired and cold;
        the receipt for fresh row C carries the same source bytes, so strict
        normalization re-derives exactly K (deterministic content addressing).
        The receipt is started first: it takes ``visionStorageLock`` for its
        reuse-check section, so the sweep cannot begin until the receipt has
        stepped out to normalization — and the receipt's store-and-publish
        section can only run AFTER the sweep releases the lock. By then the
        sweep has already deleted K (it was cold at snapshot time), so the
        receipt re-stores K and publishes it on row C: no dangling row, and
        the sweep's own outcome is intact.

        Receipt-first ordering alone cannot force normalization to finish
        while the sweep is active, so final states alone cannot detect a
        production regression that drops the lock: a late store-and-publish
        would re-store the deleted object and still look consistent. This
        test therefore also swaps in a transparent wrapper
        ([`_ObservedVisionLock`]) that delegates to the real lock while
        recording task-specific acquire/release events, and asserts the
        receipt performs BOTH critical-section acquisitions with its
        store-and-publish acquisition following the sweep's release — the
        test fails deterministically if ``_storeVisionImage`` stops
        acquiring ``visionStorageLock``, regardless of scheduling.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
            tmp_path: pytest tmp dir for the real fs vision store.
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        StorageService._instances.clear()
        # Python 3.14 checks asyncio.Lock loop-affinity only on the CONTENDED
        # acquire path, so a binding left by an earlier test's loop would fail
        # this test's contended GC acquire with "bound to a different event
        # loop". Clear the stale binding so the lock (re)binds to THIS test's
        # loop, and clear it again afterwards to leave a pristine lock.
        visionStorageLock._loop = None  # type: ignore[attr-defined]
        try:
            configManager = Mock()
            configManager.getStorageConfig = Mock(
                return_value={
                    "type": "null",
                    "storages": {"vision": {"type": "fs", "fs": {"base-dir": str(tmp_path / "vision")}}},
                }
            )
            visionStorage = StorageService.getInstance(StorageScope.VISION)
            visionStorage.injectConfig(configManager, scope=StorageScope.VISION)

            # A real decodable PNG so the receipt's libmagic guard and the
            # strict normalization (asyncio.to_thread thread hop) run for real.
            pngBuf = BytesIO()
            Image.new("RGB", (8, 8), (200, 10, 10)).save(pngBuf, format="PNG")
            pngBytes = pngBuf.getvalue()

            # Pre-derive the receipt's content key with the SAME normalizer and
            # parameters the handler below is configured with — byte-identical
            # output means the receipt re-derives exactly expired row B's key.
            normalized = normalizeVisionImageStrict(
                imageBytes=pngBytes,
                maxDimension=2048,
                outputFormat=VisionOutputImageFormat.JPEG,
                quality=85,
            )
            assert normalized is not None
            normalizedBytes, normalizedMime = normalized
            receiptKey = f"{hashlib.sha512(normalizedBytes).hexdigest()}.{normalizedMime.split('/')[-1]}"

            manager = self._buildManager(testDatabase, visionTtlDays=1)
            repo = testDatabase.mediaAttachments
            await self._seedAttachmentWithVisionUrl(testDatabase, "row-A", "key1.jpeg")
            await self._seedAttachmentWithVisionUrl(testDatabase, "row-B", receiptKey)
            await self._seedAttachmentWithVisionUrl(testDatabase, "row-C", None)
            await self._backdateUpdatedAt(testDatabase, "row-A", self._OLD_TS)
            await self._backdateUpdatedAt(testDatabase, "row-B", self._OLD_TS)

            visionStorage.store("key1.jpeg", b"old-bytes-1")
            visionStorage.store(receiptKey, b"old-normalized")

            # Minimal real BaseBotHandler carrying exactly what
            # _storeVisionImage touches (the file's __new__ bypass pattern).
            handler = BaseBotHandler.__new__(BaseBotHandler)
            handler.db = testDatabase
            handler.visionStorage = visionStorage
            handler._bot = None
            handler._visionMaxImageDimension = 2048
            handler._visionImageFormat = VisionOutputImageFormat.JPEG
            handler._visionImageQuality = 85
            handler._visionAlphaBackground = AlphaBackground.ADAPTIVE

            # Transparent lock observation: delegate to the REAL lock (the
            # module-level instance imported above — patching does not touch
            # this binding) while recording task-specific acquire/release
            # events. It must be patched into BOTH consumer modules: base.py
            # resolves its global at call time, but manager.py holds its own
            # ``from .base import`` binding, so patching base alone would
            # leave the sweep's hold unobserved.
            lockEvents: List[str] = []
            observedLock = _ObservedVisionLock(visionStorageLock, lockEvents)

            with (
                caplog.at_level(logging.INFO),
                patch("internal.bot.common.handlers.base.visionStorageLock", observedLock),
                patch("internal.bot.common.handlers.manager.visionStorageLock", observedLock),
            ):
                # Receipt first: its uncontended lock acquisition happens
                # before any await, so the sweep below deterministically
                # starts AFTER the receipt's reuse-check section released
                # the lock — the production receipt-in-flight interleaving.
                # Named tasks so the observed lock can tag events per role.
                receiptTask = asyncio.create_task(
                    handler._storeVisionImage(
                        chatId=100,
                        mediaId="row-C",
                        mediaType=MessageType.IMAGE,
                        fileId="fid-row-C",
                        mediaData=pngBytes,
                    ),
                    name="receipt",
                )
                gcTask = asyncio.create_task(manager._visionGcCronJob(self._makeTask()), name="gc-sweep")
                receiptResult, _ = await asyncio.gather(receiptTask, gcTask)

            # Deterministic lock-observation gate: the REAL receipt performed
            # BOTH production critical sections through the real lock,
            # serialized against the sweep's single hold — the reuse-check
            # pair (before the sweep could start), then the sweep's pair,
            # then the store-and-publish pair (a contended acquire is
            # recorded only once it holds the lock, i.e. after the sweep's
            # release; no receipt acquisition can be recorded between the
            # sweep's acquire and release). If _storeVisionImage stopped
            # acquiring ``visionStorageLock``, no receipt events would be
            # recorded and this fails even though every final-state
            # assertion below could still pass.
            assert lockEvents == [
                "acquire:receipt",
                "release:receipt",
                "acquire:gc-sweep",
                "release:gc-sweep",
                "acquire:receipt",
                "release:receipt",
            ]

            # The receipt republished exactly row B's deleted key with the
            # freshly normalized bytes.
            assert receiptResult == (receiptKey, pngBytes)

            # Row C ends consistent: published DB reference AND stored object.
            rowC = await repo.getMediaAttachment("row-C")
            assert rowC is not None
            assert rowC["vision_url"] == receiptKey
            assert visionStorage.get(receiptKey) == normalizedBytes

            # The sweep completed normally: both expired rows cleared, and the
            # summary proves BOTH keys were deleted (including the receipt's
            # key — cold at snapshot time, before the post-sweep re-store).
            rowA = await repo.getMediaAttachment("row-A")
            rowB = await repo.getMediaAttachment("row-B")
            assert rowA is not None
            assert rowA["vision_url"] is None
            assert rowB is not None
            assert rowB["vision_url"] is None
            assert visionStorage.get("key1.jpeg") is None

            summary = next(record for record in caplog.records if "Vision GC:" in record.getMessage())
            message = summary.getMessage()
            assert "cleared 2/2 expired row(s)" in message
            assert "deleted 2 distinct file(s)" in message
        finally:
            StorageService._instances.clear()
            visionStorageLock._loop = None  # type: ignore[attr-defined]

    async def testSummaryCounts_outcomesAndDistinctKeys(
        self, testDatabase: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Summary counters report outcomes, not attempts, and DISTINCT files.

        Five expired rows: one file deleted (True); one delete hits an
        already-missing file (False — must count as missing, not deleted);
        two rows share one key (deleted once, the idempotent second delete
        misses); one row's file is held by a live row (cleared with the
        file retained, never deleted). Expected summary: 5/5 cleared,
        2 distinct files deleted, 2 already-missing deletes, 1 retained.

        Args:
            testDatabase: Fresh in-memory Database with migrations applied.
            caplog: pytest log-capture fixture.
        """
        manager = self._buildManager(testDatabase, visionTtlDays=1)
        repo = testDatabase.mediaAttachments
        await self._seedAttachmentWithVisionUrl(testDatabase, "row-del", "del.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "row-gone", "gone.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "row-shared-1", "shared.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "row-shared-2", "shared.jpeg")
        await self._seedAttachmentWithVisionUrl(testDatabase, "row-hot", "hot.jpeg")
        # Fresh row holding the same key as row-hot → that key stays live.
        await self._seedAttachmentWithVisionUrl(testDatabase, "live-holder", "hot.jpeg")
        for expiredRow in ("row-del", "row-gone", "row-shared-1", "row-shared-2", "row-hot"):
            await self._backdateUpdatedAt(testDatabase, expiredRow, self._OLD_TS)

        storageMock = self._makeStorageMock()
        # Per-call outcomes in expired-row order: del(True), gone(False),
        # shared #1(True), shared #2(already gone → False). row-hot is
        # live-referenced and never reaches delete.
        storageMock.delete = Mock(side_effect=[True, False, True, False])
        realClear = repo.clearVisionUrl
        with (
            patch.object(StorageService, "getInstance", return_value=storageMock),
            patch.object(MediaAttachmentsRepository, "clearVisionUrl", side_effect=realClear),
            caplog.at_level(logging.INFO),
        ):
            await manager._visionGcCronJob(self._makeTask())

        assert storageMock.delete.call_args_list == [
            call("del.jpeg"),
            call("gone.jpeg"),
            call("shared.jpeg"),
            call("shared.jpeg"),
        ]

        summary = next(
            record
            for record in caplog.records
            if record.levelno == logging.INFO and "Vision GC:" in record.getMessage()
        )
        message = summary.getMessage()
        assert "cleared 5/5 expired row(s)" in message
        assert "deleted 2 distinct file(s)" in message
        assert "2 delete(s) hit an already-missing file" in message
        assert "1 row(s) cleared with file retained (shared key still live)" in message
