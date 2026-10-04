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
import logging
import time
from typing import Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, Mock, call, patch

import pytest

from internal.bot.common.handlers.base import visionStorageLock
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
from internal.database.repositories.media_attachments import MediaAttachmentsRepository
from internal.services.queue_service import DelayedTask, DelayedTaskFunction
from internal.services.storage import StorageService


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
    ``Database`` (``testDatabase`` fixture, so the Phase-A repo methods run
    against real in-memory SQLite) plus the two init-cached GC attributes.
    ``StorageService.getInstance`` is class-patched, so no ``StorageService``
    singleton reset is needed here. Rows are seeded through the real repo API
    and backdated with the canonical raw-SQL pattern from
    ``tests/database/repositories/test_media_attachments.py``. Repo spy patches
    are applied at CLASS level — the repositories use ``__slots__``, so
    instance attributes are read-only.
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
                MediaAttachmentsRepository, "getExpiredVisionAttachments", new_callable=AsyncMock
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
                MediaAttachmentsRepository, "getExpiredVisionAttachments", new_callable=AsyncMock
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

    async def testLiveKeysLookupFailed_abortsSweep(
        self, testDatabase: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``getLiveVisionUrls`` returning None (lookup FAILED) aborts the sweep.

        Regression for the fail-destructive sentinel: None must never be
        treated as "nothing is live". With expired rows present and the
        live-lookup failing, NO file is deleted, NO row is cleared (rows
        keep their ``vision_url`` for the next tick's retry), and a single
        WARNING explains the abort.

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
            patch.object(MediaAttachmentsRepository, "getLiveVisionUrls", new_callable=AsyncMock, return_value=None),
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
