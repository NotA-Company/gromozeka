"""Per-session mutex registry and global concurrency limiter for sandbox execution.

Provides serialised execution within a session via :class:`SessionLockRegistry`,
a global concurrency cap via :class:`GlobalRunLimiter`, and cross-process
library-pool locking via :func:`acquirePoolLock` / :func:`releasePoolLock`.

Classes:
    SessionLockRegistry: Per-session asyncio.Lock registry with bounded
        waiter count and force-cancel support.
    GlobalRunLimiter: Global asyncio.Semaphore cap with timeout-based rejection.

Functions:
    acquirePoolLock: Acquire an exclusive ``fcntl.flock`` on a runtime pool directory.
    releasePoolLock: Release a previously acquired pool lock.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from .config import ConcurrencyConfig
from .enums import RuntimeName
from .errors import LibraryPoolLocked, SandboxBusy, SessionBusy, SessionDropped

logger = logging.getLogger(__name__)


@dataclass
class _SessionState:
    """Mutable state for a single session's lock.

    Attributes:
        lock: Mutex serialising execution within the session.
        waiters: Number of tasks that have entered ``acquire()`` but not yet
            exited (either via ``release()`` or by raising on cancellation).
        cancelled: Whether the session has been force-cancelled.
    """

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    waiters: int = 0
    cancelled: bool = False


class SessionLockRegistry:
    """Per-session mutex-based concurrency registry for sandbox execution.

    Uses ``asyncio.Lock`` keyed by *sessionId* with a waiter counter to
    enforce "1 active + N queued" semantics.  At most one run executes per
    session at a time; up to ``maxQueuedRunsPerSession`` additional tasks may
    queue.  Provides a force-cancel mechanism that marks the session as
    cancelled and releases the mutex so every waiter can wake, detect
    cancellation, and raise ``SessionDropped``.

    Attributes:
        _config: Concurrency configuration.
        _states: Mapping from sessionId to its :class:`_SessionState`.
    """

    def __init__(self, config: ConcurrencyConfig) -> None:
        """Initialise the lock registry.

        Args:
            config: Concurrency configuration.

        Returns:
            None
        """
        self._config = config
        self._states: dict[str, _SessionState] = {}

    async def acquire(self, sessionId: str) -> None:
        """Acquire the session mutex, waiting if necessary.

        If the session is already force-cancelled, raises
        :class:`SessionDropped` immediately.  If the number of in-flight
        tasks (holder + waiters) has reached ``maxQueuedRunsPerSession``,
        raises :class:`SessionBusy` before blocking.  Otherwise increments
        the waiter counter and blocks on the mutex.  After acquiring, checks
        cancellation again and raises :class:`SessionDropped` if the session
        was cancelled while waiting.

        Args:
            sessionId: The session to acquire the mutex for.

        Returns:
            None

        Raises:
            SessionBusy: If the session queue is already full.
            SessionDropped: If the session was force-cancelled.
        """
        state = self._states.setdefault(sessionId, _SessionState())
        if state.cancelled:
            raise SessionDropped(f"Session {sessionId} has been dropped")
        if state.waiters >= self._config.maxQueuedRunsPerSession:
            raise SessionBusy(
                f"Session {sessionId} queue full "
                f"({self._config.maxQueuedRunsPerSession}/{self._config.maxQueuedRunsPerSession})"
            )
        state.waiters += 1
        try:
            await state.lock.acquire()
            if state.cancelled:
                state.lock.release()
                raise SessionDropped(f"Session {sessionId} was dropped while waiting")
        except BaseException:
            state.waiters -= 1
            raise

    def release(self, sessionId: str) -> None:
        """Release the session mutex, allowing the next waiter to proceed.

        Args:
            sessionId: The session to release the mutex for.

        Returns:
            None
        """
        state = self._states[sessionId]
        if state.waiters <= 0:
            logger.warning(
                "release() called with waiters=%d for session %s — possible unpaired release",
                state.waiters,
                sessionId,
            )
        state.waiters -= 1
        try:
            state.lock.release()
        except RuntimeError:
            pass  # Lock already released (e.g. after forceCancel cascade)

    def forceCancel(self, sessionId: str) -> None:
        """Force-cancel all waiters for a session.

        Marks the session as cancelled and releases the mutex so the current
        holder (or one waiter) wakes up.  Subsequent waiters in
        :meth:`acquire` will see the cancelled flag before acquiring and
        cascade the release, each raising :class:`SessionDropped`.

        Args:
            sessionId: The session to force-cancel.

        Returns:
            None
        """
        state = self._states.setdefault(sessionId, _SessionState())
        state.cancelled = True
        try:
            state.lock.release()
        except RuntimeError:
            pass  # Lock not currently held

    def isCancelled(self, sessionId: str) -> bool:
        """Check whether a session has been force-cancelled.

        Args:
            sessionId: The session to check.

        Returns:
            True if the session has been force-cancelled.
        """
        state = self._states.get(sessionId)
        return state.cancelled if state is not None else False

    def clearCancelled(self, sessionId: str) -> None:
        """Clear the cancelled flag after full cleanup.

        Resets the cancelled flag and removes the session state so a fresh
        one is created on next use.

        Args:
            sessionId: The session to clear.

        Returns:
            None
        """
        state = self._states.get(sessionId)
        if state is not None:
            state.cancelled = False
        self._states.pop(sessionId, None)

    @asynccontextmanager
    async def sessionLock(self, sessionId: str):
        """Async context manager for session mutex acquisition.

        Args:
            sessionId: The session to acquire a lock for.

        Yields:
            None

        Raises:
            SessionBusy: If the session queue is already full.
            SessionDropped: If the session was force-cancelled.
        """
        await self.acquire(sessionId)
        try:
            yield
        finally:
            self.release(sessionId)


class GlobalRunLimiter:
    """Global concurrency cap for all sandbox runs.

    Uses an ``asyncio.Semaphore`` to bound total in-flight runs across all
    sessions.  Raises :class:`SandboxBusy` on timeout.

    Attributes:
        _semaphore: The underlying semaphore bounding concurrency.
        _waitSeconds: Maximum seconds to wait before raising SandboxBusy.
    """

    def __init__(self, maxConcurrent: int, waitSeconds: float) -> None:
        """Initialise the global run limiter.

        Args:
            maxConcurrent: Maximum number of concurrent runs globally.
            waitSeconds: Maximum seconds to wait before raising SandboxBusy.

        Returns:
            None
        """
        self._semaphore = asyncio.Semaphore(maxConcurrent)
        self._waitSeconds: float = waitSeconds

    async def acquire(self) -> None:
        """Acquire the global run semaphore.

        Returns:
            None

        Raises:
            SandboxBusy: If the semaphore cannot be acquired within
                *waitSeconds*.
        """
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self._waitSeconds,
            )
        except asyncio.TimeoutError:
            raise SandboxBusy(f"Global sandbox concurrency cap reached " f"(waited {self._waitSeconds}s)") from None

    def release(self) -> None:
        """Release the global run semaphore.

        Returns:
            None
        """
        self._semaphore.release()

    @asynccontextmanager
    async def runSlot(self):
        """Async context manager for global run slot acquisition.

        Yields:
            None

        Raises:
            SandboxBusy: If the semaphore cannot be acquired within
                *waitSeconds*.
        """
        await self.acquire()
        try:
            yield
        finally:
            self.release()


async def acquirePoolLock(runtime: RuntimeName, poolDir: Path) -> IO[str]:
    """Acquire an exclusive ``fcntl.flock`` on the runtime library pool lock file.

    This protects the library pool from concurrent install/remove operations
    across processes.  Non-blocking — raises :class:`LibraryPoolLocked` if held.

    Args:
        runtime: The runtime whose pool to lock.
        poolDir: The runtime's pool directory.

    Returns:
        An opaque lock handle; pass to :func:`releasePoolLock` to release.

    Raises:
        LibraryPoolLocked: If another process holds the lock.
    """
    poolDir.mkdir(parents=True, exist_ok=True)
    lockPath = poolDir / "pool.lock"

    def _acquire() -> IO[str]:
        lockFile: IO[str] = open(lockPath, "a")  # noqa: SIM115
        try:
            fcntl.flock(lockFile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            lockFile.close()
            raise LibraryPoolLocked(f"Library pool for runtime {runtime.value} is locked by another process")
        return lockFile

    return await asyncio.to_thread(_acquire)


def releasePoolLock(lockHandle: IO[str]) -> None:
    """Release a pool lock acquired by :func:`acquirePoolLock`.

    Args:
        lockHandle: The handle returned by :func:`acquirePoolLock`.

    Returns:
        None
    """
    lockHandle.close()  # closing the file releases the flock


@asynccontextmanager
async def poolLock(runtime: RuntimeName, poolDir: Path):
    """Async context manager for acquiring and releasing a pool lock.

    Args:
        runtime: The runtime whose pool to lock.
        poolDir: The runtime's pool directory.

    Yields:
        The lock handle to be passed to releasePoolLock.

    Raises:
        LibraryPoolLocked: If another process holds the lock.
    """
    lock = await acquirePoolLock(runtime=runtime, poolDir=poolDir)
    try:
        yield lock
    finally:
        releasePoolLock(lock)
