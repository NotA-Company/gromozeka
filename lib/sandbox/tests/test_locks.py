"""Tests for sandbox lock registry and concurrency limiter (lib.sandbox.locks).

Covers:
- SessionLockRegistry: concurrent acquire/release, overflow, force-cancel,
  lazy creation, session independence, clearCancelled recovery.
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


async def testSessionLockRegistryConcurrentAcquireRelease() -> None:
    """Verify that multiple workers can acquire and release slots concurrently.

    With maxQueuedRunsPerSession=10 (11 slots), 5 workers should all complete.

    Returns:
        None
    """
    config = ConcurrencyConfig(maxQueuedRunsPerSession=10, maxConcurrentRunsGlobal=10, globalQueueWaitSeconds=60)
    registry = SessionLockRegistry(config)
    completionCount = 0
    sessionId = "session-concurrent"

    async def worker() -> None:
        nonlocal completionCount
        await registry.acquire(sessionId)
        try:
            completionCount += 1
            await asyncio.sleep(0.01)
        finally:
            registry.release(sessionId)

    tasks = [asyncio.create_task(worker()) for _ in range(5)]
    await asyncio.gather(*tasks)

    assert completionCount == 5


# ============================================================================
# SessionLockRegistry — overflow
# ============================================================================


async def testSessionLockRegistryOverflow(concurrencyConfig: ConcurrencyConfig) -> None:
    """Verify that exceeding maxQueuedRunsPerSession raises SessionBusy.

    With maxQueuedRunsPerSession=2, the semaphore has 3 slots.  Fill all 3
    slots, then verify the 4th acquire raises SessionBusy.

    Args:
        concurrencyConfig: Concurrency config with maxQueuedRunsPerSession=2.

    Returns:
        None
    """
    registry = SessionLockRegistry(concurrencyConfig)
    sessionId = "session-overflow"

    # Fill all 3 slots (maxQueuedRunsPerSession=2, so 2+1=3)
    await registry.acquire(sessionId)
    await registry.acquire(sessionId)
    await registry.acquire(sessionId)

    # The 4th should raise SessionBusy
    with pytest.raises(SessionBusy):
        await registry.acquire(sessionId)

    # Clean up
    registry.release(sessionId)
    registry.release(sessionId)
    registry.release(sessionId)


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


async def testSessionLockRegistryForceCancelWakesMultipleWaiters() -> None:
    """Verify that forceCancel causes all subsequent callers to receive SessionDropped.

    After forceCancel, any new acquire() calls should immediately raise
    SessionDropped, regardless of how many callers attempt to acquire.

    Returns:
        None
    """
    config = ConcurrencyConfig(maxQueuedRunsPerSession=10, maxConcurrentRunsGlobal=10, globalQueueWaitSeconds=60)
    registry = SessionLockRegistry(config)
    sessionId = "session-multi-cancel"

    # Acquire a slot
    await registry.acquire(sessionId)

    # Force-cancel the session
    registry.forceCancel(sessionId)

    # Multiple callers should all receive SessionDropped
    for _ in range(3):
        with pytest.raises(SessionDropped):
            await registry.acquire(sessionId)

    # Clean up
    registry.release(sessionId)


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

    # Both should have semaphores without issue
    assert session1 in registry._semaphores
    assert session2 in registry._semaphores

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

    # No semaphore should exist yet
    assert sessionId not in registry._semaphores

    # After acquire, a semaphore should exist
    await registry.acquire(sessionId)
    assert sessionId in registry._semaphores

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
    # After clearCancelled, the semaphore should also be removed
    assert sessionId not in registry._semaphores


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
