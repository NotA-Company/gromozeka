"""Per-session semaphore registry and global concurrency limiter for sandbox execution.

Provides bounded concurrency within a session via :class:`SessionLockRegistry`,
a global concurrency cap via :class:`GlobalRunLimiter`, and cross-process
library-pool locking via :func:`acquirePoolLock` / :func:`releasePoolLock`.

Classes:
    SessionLockRegistry: Per-session asyncio.Semaphore registry with bounded
        slots and force-cancel support.
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
from pathlib import Path
from typing import IO

from .config import ConcurrencyConfig
from .enums import RuntimeName
from .errors import LibraryPoolLocked, SandboxBusy, SessionBusy, SessionDropped

logger = logging.getLogger(__name__)


class SessionLockRegistry:
    """Per-session semaphore-based concurrency registry for sandbox execution.

    Uses ``asyncio.Semaphore`` keyed by *sessionId* with
    ``maxQueuedRunsPerSession + 1`` slots (1 for the executing holder + N for
    queued waiters).  Provides a force-cancel mechanism that releases all
    semaphore slots so every waiter can proceed, detect cancellation, and
    raise ``SessionDropped``.

    Attributes:
        _config: Concurrency configuration.
        _semaphores: Mapping from sessionId to its ``asyncio.Semaphore``.
        _cancelled: Set of sessionIds that have been force-cancelled.
    """

    def __init__(self, config: ConcurrencyConfig) -> None:
        """Initialise the lock registry.

        Args:
            config: Concurrency configuration.
        """
        self._config = config
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._cancelled: set[str] = set()

    async def acquire(self, sessionId: str) -> None:
        """Acquire a session slot, waiting if necessary.

        Uses an ``asyncio.Semaphore`` with ``maxQueuedRunsPerSession + 1``
        slots per session.  If all slots are taken, raises :class:`SessionBusy`
        before blocking.  If the session was force-cancelled, raises
        :class:`SessionDropped`.

        Args:
            sessionId: The session to acquire a slot for.

        Raises:
            SessionBusy: If all semaphore slots are already taken.
            SessionDropped: If the session was force-cancelled.
        """
        if sessionId in self._cancelled:
            raise SessionDropped(f"Session {sessionId} has been dropped")

        if sessionId not in self._semaphores:
            self._semaphores[sessionId] = asyncio.Semaphore(self._config.maxQueuedRunsPerSession + 1)

        sem = self._semaphores[sessionId]
        # Check if queue is full BEFORE blocking.
        # asyncio.Semaphore._value is the internal counter; <= 0 means all slots taken.
        if sem._value <= 0:  # noqa: SLF001
            raise SessionBusy(
                f"Session {sessionId} queue full "
                f"({self._config.maxQueuedRunsPerSession}/{self._config.maxQueuedRunsPerSession})"
            )

        # Acquire a slot (atomic, FIFO-ordered)
        await sem.acquire()

        # Check for force-cancel after acquiring
        if sessionId in self._cancelled:
            sem.release()
            raise SessionDropped(f"Session {sessionId} was dropped while waiting")

    def release(self, sessionId: str) -> None:
        """Release a session slot, allowing the next waiter to proceed.

        Args:
            sessionId: The session to release a slot for.
        """
        if sessionId in self._semaphores:
            try:
                self._semaphores[sessionId].release()
            except ValueError:
                pass  # Already at max

    def forceCancel(self, sessionId: str) -> None:
        """Force-cancel all waiters for a session.

        Marks the session as cancelled and releases all semaphore slots so
        every waiter can wake up, check cancellation, and raise
        :class:`SessionDropped`.  Called by ``dropSession(force=True)``.

        Args:
            sessionId: The session to force-cancel.
        """
        self._cancelled.add(sessionId)
        if sessionId in self._semaphores:
            sem = self._semaphores[sessionId]
            # Release all slots so ALL waiters can wake up, check cancellation,
            # and raise SessionDropped
            for _ in range(self._config.maxQueuedRunsPerSession + 1):
                try:
                    sem.release()
                except ValueError:
                    break  # Released all possible slots

    def isCancelled(self, sessionId: str) -> bool:
        """Check whether a session has been force-cancelled.

        Args:
            sessionId: The session to check.

        Returns:
            True if the session has been force-cancelled.
        """
        return sessionId in self._cancelled

    def clearCancelled(self, sessionId: str) -> None:
        """Clear the cancelled flag after full cleanup.

        Removes the cancelled flag and the semaphore so a fresh one is created
        on next use.

        Args:
            sessionId: The session to clear.
        """
        self._cancelled.discard(sessionId)
        # Remove semaphore so a fresh one is created on next use
        self._semaphores.pop(sessionId, None)

    @asynccontextmanager
    async def sessionLock(self, sessionId: str):
        """Async context manager for session lock acquisition.

        Args:
            sessionId: The session to acquire a lock for.

        Yields:
            None

        Raises:
            SessionBusy: If all semaphore slots are already taken.
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
        """
        self._semaphore = asyncio.Semaphore(maxConcurrent)
        self._waitSeconds: float = waitSeconds

    async def acquire(self) -> None:
        """Acquire the global run semaphore.

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
        """Release the global run semaphore."""
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
    """
    lockHandle.close()  # closing the file releases the flock
