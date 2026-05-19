"""Tests for sandbox lock registry and concurrency limiter (lib.sandbox.locks).

Covers:
- SessionLockRegistry: serial acquire/release, overflow, force-cancel,
  force-cancel wakes blocked waiters, lazy creation, session independence,
  clearCancelled recovery.
- GlobalRunLimiter: acquire/release, SandboxBusy on timeout, release frees slot.
- acquirePoolLock / releasePoolLock: basic acquisition, LibraryPoolLocked on
  contention.
"""

import asyncio
from pathlib import Path

import pytest

from lib.sandbox.config import ConcurrencyConfig
from lib.sandbox.enums import RuntimeName
from lib.sandbox.errors import LibraryPoolLocked, SandboxBusy, SessionBusy, SessionDropped
from lib.sandbox.locks import GlobalRunLimiter, SessionLockRegistry, acquirePoolLock, releasePoolLock

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def concurrencyConfig() -> ConcurrencyConfig:
    """Provide a ConcurrencyConfig with small limits suitable for testing.

    Returns:
        A ConcurrencyConfig with maxQueuedRunsPerSession=2.
    """
    return ConcurrencyConfig(maxQueuedRunsPerSession=2, maxConcurrentRunsGlobal=4, globalQueueWaitSeconds=1)


@pytest.fixture
def registry(concurrencyConfig: ConcurrencyConfig) -> SessionLockRegistry:
    """Provide a fresh SessionLockRegistry for each test.

    Args:
        concurrencyConfig: The concurrency config fixture.

    Returns:
        A new SessionLockRegistry instance.
    """
    return SessionLockRegistry(concurrencyConfig)


# ============================================================================
# SessionLockRegistry — concurrent acquire/release
# ============================================================================


async def testSessionLockRegistrySerialAcquireRelease() -> None:
    """Verify that workers execute serially (one active holder at a time).

    With maxQueuedRunsPerSession=3, 3 workers should all complete serially.

    Returns:
        None
    """
    config = ConcurrencyConfig(maxQueuedRunsPerSession=3, maxConcurrentRunsGlobal=10, globalQueueWaitSeconds=60)
    registry = SessionLockRegistry(config)
    completionCount = 0
    sessionId = "session-serial"

    async def worker() -> None:
        nonlocal completionCount
        await registry.acquire(sessionId)
        try:
            completionCount += 1
            await asyncio.sleep(0.01)
        finally:
            registry.release(sessionId)

    tasks = [asyncio.create_task(worker()) for _ in range(3)]
    await asyncio.gather(*tasks)

    assert completionCount == 3


# ============================================================================
# SessionLockRegistry — overflow
# ============================================================================


async def testSessionLockRegistryOverflow(concurrencyConfig: ConcurrencyConfig) -> None:
    """Verify that exceeding maxQueuedRunsPerSession raises SessionBusy.

    With maxQueuedRunsPerSession=2, the system supports 1 active + 1 queued
    (2 total in-flight).  Start 1 active holder + 1 queued waiter, then
    verify the 3rd acquire raises SessionBusy.

    Args:
        concurrencyConfig: Concurrency config with maxQueuedRunsPerSession=2.

    Returns:
        None
    """
    registry = SessionLockRegistry(concurrencyConfig)
    sessionId = "session-overflow"
    overflowDetected = False

    async def holder() -> None:
        """Hold the lock to block queue waiters."""
        await registry.acquire(sessionId)
        try:
            await asyncio.sleep(0.2)
        finally:
            registry.release(sessionId)

    async def queuedWorker() -> None:
        """Queue a waiter that will block behind the holder."""
        await registry.acquire(sessionId)
        try:
            pass
        finally:
            registry.release(sessionId)

    async def overflowWorker() -> None:
        """This should get SessionBusy because queue is full."""
        nonlocal overflowDetected
        try:
            await registry.acquire(sessionId)
        except SessionBusy:
            overflowDetected = True

    # Start holder first so it takes the lock
    holderTask = asyncio.create_task(holder())
    await asyncio.sleep(0.01)  # Let holder acquire

    # Queue 1 waiter (fills the queue: 1 holder + 1 queued = 2 total)
    queuedTask = asyncio.create_task(queuedWorker())
    await asyncio.sleep(0.01)  # Let it queue up

    # 3rd attempt should raise SessionBusy
    overflowTask = asyncio.create_task(overflowWorker())
    await asyncio.sleep(0.01)
    await holderTask  # Let holder finish, releasing the waiter
    await queuedTask
    await overflowTask

    assert overflowDetected


# ============================================================================
# SessionLockRegistry — force-cancel
# ============================================================================


async def testSessionLockRegistryForceCancel(registry: SessionLockRegistry) -> None:
    """Verify that forceCancel causes subsequent callers to receive SessionDropped.

    Args:
        registry: Fresh SessionLockRegistry fixture.

    Returns:
        None
    """
    sessionId = "session-cancel"

    # Acquire a slot
    await registry.acquire(sessionId)

    # Force-cancel the session
    registry.forceCancel(sessionId)

    # New callers should receive SessionDropped
    with pytest.raises(SessionDropped):
        await registry.acquire(sessionId)

    # Holder can still release
    registry.release(sessionId)


# ============================================================================
# SessionLockRegistry — force-cancel rejects multiple callers
# ============================================================================


async def testSessionLockRegistryForceCancelWakesBlockedWaiters() -> None:
    """Verify that forceCancel wakes waiters blocked on the lock.

    Holder takes the lock, waiters queue up.  forceCancel should cause ALL
    queued waiters to receive SessionDropped.

    Returns:
        None
    """
    config = ConcurrencyConfig(maxQueuedRunsPerSession=10, maxConcurrentRunsGlobal=10, globalQueueWaitSeconds=60)
    registry = SessionLockRegistry(config)
    sessionId = "session-wake"
    cancelledCount = 0

    async def holder() -> None:
        await registry.acquire(sessionId)
        try:
            await asyncio.sleep(0.2)  # Hold lock while waiters queue
        finally:
            registry.release(sessionId)

    async def queuedWorker() -> None:
        nonlocal cancelledCount
        try:
            await registry.acquire(sessionId)
        except SessionDropped:
            cancelledCount += 1

    # Start holder
    holderTask = asyncio.create_task(holder())
    await asyncio.sleep(0.01)

    # Queue 3 waiters
    waiterTasks = [asyncio.create_task(queuedWorker()) for _ in range(3)]
    await asyncio.sleep(0.01)

    # Force cancel while waiters are blocked
    registry.forceCancel(sessionId)

    # Wait for all tasks
    await holderTask
    await asyncio.gather(*waiterTasks)

    assert cancelledCount == 3, f"Expected 3 cancelled waiters, got {cancelledCount}"


# ============================================================================
# SessionLockRegistry — different sessions independent
# ============================================================================


async def testSessionLockRegistryDifferentSessionsIndependent(registry: SessionLockRegistry) -> None:
    """Verify that locks for different sessionIds do not interfere.

    Two sessions should be able to acquire their slots concurrently
    without blocking each other.

    Args:
        registry: Fresh SessionLockRegistry fixture.

    Returns:
        None
    """
    session1 = "session-alpha"
    session2 = "session-beta"

    # Acquire both sessions concurrently — should not block
    await registry.acquire(session1)
    await registry.acquire(session2)

    # Both should have states without issue
    assert session1 in registry._states
    assert session2 in registry._states

    registry.release(session1)
    registry.release(session2)


# ============================================================================
# SessionLockRegistry — lazy creation
# ============================================================================


async def testSessionLockRegistryLazyCreation(registry: SessionLockRegistry) -> None:
    """Verify that no semaphore exists for a session until first acquire.

    Args:
        registry: Fresh SessionLockRegistry fixture.

    Returns:
        None
    """
    sessionId = "session-lazy"

    # No state should exist yet
    assert sessionId not in registry._states

    # After acquire, a state should exist
    await registry.acquire(sessionId)
    assert sessionId in registry._states

    registry.release(sessionId)


# ============================================================================
# SessionLockRegistry — isCancelled and clearCancelled
# ============================================================================


async def testSessionLockRegistryIsCancelledAndClear(registry: SessionLockRegistry) -> None:
    """Verify isCancelled returns True after forceCancel and False after clearCancelled.

    Args:
        registry: Fresh SessionLockRegistry fixture.

    Returns:
        None
    """
    sessionId = "session-state"

    assert not registry.isCancelled(sessionId)

    registry.forceCancel(sessionId)
    assert registry.isCancelled(sessionId)

    registry.clearCancelled(sessionId)
    assert not registry.isCancelled(sessionId)
    # After clearCancelled, the state should also be removed
    assert sessionId not in registry._states


# ============================================================================
# SessionLockRegistry — acquire on cancelled session raises immediately
# ============================================================================


async def testSessionLockRegistryAcquireOnCancelledSession(registry: SessionLockRegistry) -> None:
    """Verify that acquiring a cancelled session raises SessionDropped immediately.

    Args:
        registry: Fresh SessionLockRegistry fixture.

    Returns:
        None
    """
    sessionId = "session-already-cancelled"

    registry.forceCancel(sessionId)

    with pytest.raises(SessionDropped):
        await registry.acquire(sessionId)


# ============================================================================
# SessionLockRegistry — clearCancelled allows fresh acquire
# ============================================================================


async def testSessionLockRegistryClearCancelledAllowsFreshAcquire(registry: SessionLockRegistry) -> None:
    """Verify that after clearCancelled, a new acquire works with a fresh semaphore.

    Args:
        registry: Fresh SessionLockRegistry fixture.

    Returns:
        None
    """
    sessionId = "session-fresh"

    # Acquire and release normally
    await registry.acquire(sessionId)
    registry.release(sessionId)

    # Force-cancel, then clear
    registry.forceCancel(sessionId)
    registry.clearCancelled(sessionId)

    # Should be able to acquire again with a fresh semaphore
    await registry.acquire(sessionId)
    registry.release(sessionId)


# ============================================================================
# SessionLockRegistry — forceCancel followed by release is safe
# ============================================================================


async def testSessionLockRegistryForceCancelReleaseSafe(registry: SessionLockRegistry) -> None:
    """Verify that release after forceCancel does not raise or corrupt state.

    forceCancel releases all semaphore slots; a subsequent release by the
    original holder should be silently absorbed.

    Args:
        registry: Fresh SessionLockRegistry fixture.

    Returns:
        None
    """
    sessionId = "session-safe"

    # Acquire a slot
    await registry.acquire(sessionId)

    # Force-cancel releases all slots
    registry.forceCancel(sessionId)

    # The holder's release should not raise
    registry.release(sessionId)


# ============================================================================
# GlobalRunLimiter — acquire/release
# ============================================================================


async def testGlobalRunLimiterAcquireRelease() -> None:
    """Verify basic acquire and release works on GlobalRunLimiter.

    Returns:
        None
    """
    limiter = GlobalRunLimiter(maxConcurrent=2, waitSeconds=5)
    await limiter.acquire()
    limiter.release()
    # Should be able to acquire again after release
    await limiter.acquire()
    limiter.release()


# ============================================================================
# GlobalRunLimiter — SandboxBusy on timeout
# ============================================================================


async def testGlobalRunLimiterSandboxBusyOnTimeout() -> None:
    """Verify that GlobalRunLimiter raises SandboxBusy when the semaphore is exhausted.

    Create a limiter with maxConcurrent=1 and waitSeconds=0.1.  Acquire once,
    then try again — should get SandboxBusy after the timeout.

    Returns:
        None
    """
    limiter = GlobalRunLimiter(maxConcurrent=1, waitSeconds=0.1)

    # Acquire the only slot — should succeed immediately
    await limiter.acquire()

    # Second acquire should time out and raise SandboxBusy
    with pytest.raises(SandboxBusy):
        await limiter.acquire()

    # Clean up
    limiter.release()


# ============================================================================
# GlobalRunLimiter — release frees slot
# ============================================================================


async def testGlobalRunLimiterReleaseFreesSlot() -> None:
    """Verify that after releasing, the next acquire succeeds.

    Returns:
        None
    """
    limiter = GlobalRunLimiter(maxConcurrent=1, waitSeconds=1)

    # Acquire the only slot
    await limiter.acquire()

    # Release it
    limiter.release()

    # Should be able to acquire again
    await limiter.acquire()
    limiter.release()


# ============================================================================
# GlobalRunLimiter — multiple concurrent acquires
# ============================================================================


async def testGlobalRunLimiterMultipleConcurrent() -> None:
    """Verify that the limiter allows up to maxConcurrent concurrent acquires.

    Returns:
        None
    """
    limiter = GlobalRunLimiter(maxConcurrent=3, waitSeconds=2)
    acquired: list[int] = []

    async def worker(index: int) -> None:
        await limiter.acquire()
        acquired.append(index)
        await asyncio.sleep(0.05)
        limiter.release()

    tasks = [asyncio.create_task(worker(i)) for i in range(6)]
    await asyncio.gather(*tasks)

    # All 6 should have completed (3 at a time)
    assert len(acquired) == 6


# ============================================================================
# acquirePoolLock — basic
# ============================================================================


async def testAcquirePoolLockBasic(tmp_path: Path) -> None:
    """Verify that acquirePoolLock acquires a lock and releasePoolLock releases it.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        None
    """
    poolDir = tmp_path / "python-pool"
    handle = await acquirePoolLock(RuntimeName.PYTHON, poolDir)
    assert handle is not None
    # The pool directory should have been created
    assert poolDir.exists()
    # Release should succeed
    releasePoolLock(handle)


# ============================================================================
# acquirePoolLock — LibraryPoolLocked on contention
# ============================================================================


async def testAcquirePoolLockContention(tmp_path: Path) -> None:
    """Verify that acquiring a pool lock twice raises LibraryPoolLocked.

    Acquire once, then try to acquire again — should raise LibraryPoolLocked
    since the lock is exclusive and non-blocking.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        None
    """
    poolDir = tmp_path / "python-pool-contended"
    handle = await acquirePoolLock(RuntimeName.PYTHON, poolDir)

    try:
        # Second acquire should fail because the lock is held
        with pytest.raises(LibraryPoolLocked):
            await acquirePoolLock(RuntimeName.PYTHON, poolDir)
    finally:
        releasePoolLock(handle)


# ============================================================================
# acquirePoolLock — creates pool directory
# ============================================================================


async def testAcquirePoolLockCreatesDirectory(tmp_path: Path) -> None:
    """Verify that acquirePoolLock creates the pool directory if it doesn't exist.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        None
    """
    poolDir = tmp_path / "new-nested" / "python-pool"
    assert not poolDir.exists()

    handle = await acquirePoolLock(RuntimeName.PYTHON, poolDir)
    try:
        assert poolDir.exists()
    finally:
        releasePoolLock(handle)


# ============================================================================
# SessionLockRegistry — forceCancel + acquire + release + clearCancelled sequence
# ============================================================================


async def testSessionLockRegistryForceCancelAcquireReleaseClearSequence() -> None:
    """Verify waiter counter integrity across forceCancel + acquire + release.

    Simulates the dropSession(force=True) lock interaction:
    1. Acquire the lock
    2. forceCancel (sets cancelled=True, releases lock)
    3. acquire raises SessionDropped (before incrementing waiters)
    4. release should NOT decrement waiters (lock was never acquired)
    5. clearCancelled resets state
    6. Next acquire should succeed with waiters=1

    Returns:
        None
    """
    config = ConcurrencyConfig(maxQueuedRunsPerSession=2, maxConcurrentRunsGlobal=10, globalQueueWaitSeconds=60)
    registry = SessionLockRegistry(config)
    sessionId = "session-drop-seq"

    # 1. Acquire the lock (waiters=1)
    await registry.acquire(sessionId)

    # Verify waiters is 1 (holder)
    state = registry._states[sessionId]
    assert state.waiters == 1

    # 2. forceCancel — sets cancelled and releases lock
    registry.forceCancel(sessionId)
    assert state.cancelled
    # Lock was released, so holder's release will catch RuntimeError

    # 3. Release the original holder (RuntimeError expected, suppressed in release())
    registry.release(sessionId)
    # waiters should be 0 now (was 1, decremented to 0)
    assert state.waiters == 0

    # 4. acquire should raise SessionDropped WITHOUT incrementing waiters
    with pytest.raises(SessionDropped):
        await registry.acquire(sessionId)
    # waiters should still be 0
    assert state.waiters == 0

    # 5. clearCancelled resets state
    registry.clearCancelled(sessionId)
    assert sessionId not in registry._states
    assert not registry.isCancelled(sessionId)

    # 6. Next acquire should work normally (fresh state, waiters=1 after acquire)
    await registry.acquire(sessionId)
    newState = registry._states[sessionId]
    assert newState.waiters == 1
    assert not newState.cancelled

    registry.release(sessionId)
    assert newState.waiters == 0
